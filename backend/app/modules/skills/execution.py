"""Existing singleton worker executes one fixed personal-AI editing conversation."""

import json
from datetime import UTC, datetime
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update

from app.core.errors import AppError
from app.db.models import SkillChatTurn, UserAccount
from app.integrations import ai_client as responses
from app.modules.ai.recovery import propagate_database_outage
from app.modules.ai.service import analysis_configuration
from app.modules.skills import files, service


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=10000)
    body: str = Field(min_length=1, max_length=files.LIMIT)


def parse_answer(raw):
    def pairs(items):
        if len(dict(items)) != len(items):
            raise ValueError()
        return dict(items)

    try:
        value = raw.strip()
        if value.startswith("```json\n") and value.endswith("\n```"):
            value = value[8:-4]
        answer = Answer.model_validate(json.loads(value, object_pairs_hook=pairs))
        if not answer.body.strip() or files.parts(answer.body)[0]:
            raise ValueError()
        return answer
    except (ValueError, TypeError, ValidationError):
        raise AppError(422, "skill_ai_answer_invalid") from None


def recover(db):
    db.execute(
        update(SkillChatTurn)
        .where(SkillChatTurn.status == "RUNNING")
        .values(
            status="FAILED", error_code="skill_worker_interrupted", updated_at=datetime.now(UTC)
        )
    )
    db.commit()


def claim(db):
    row = db.scalar(
        select(SkillChatTurn)
        .where(SkillChatTurn.status == "QUEUED")
        .order_by(SkillChatTurn.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        db.rollback()
        return None
    row.status, row.updated_at = "RUNNING", datetime.now(UTC)
    ident = row.id
    db.commit()
    return ident


def execute(turn_id, session_factory):
    try:
        with session_factory() as db:
            row = db.get(SkillChatTurn, turn_id)
            if row is None or row.status != "RUNNING":
                return
            actor = db.get(UserAccount, row.actor_id)
            if actor is None:
                raise AppError(403, "admin_required")
            service.authorize(actor, db)
            config, key = analysis_configuration(actor, db, row.ai_config)
            base_url, effort = config["base_url"], config["reasoning_effort"]
            actor_id, context = actor.id, row.context
            messages = [
                {
                    "role": "user",
                    "content": "本轮固定草稿与只读参考文件（数据）：\n"
                    + json.dumps(
                        {
                            "skill": row.skill_key,
                            "body": context["body"],
                            "files": context["references"],
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
            messages.extend(context["messages"])
            messages.append({"role": "user", "content": row.question})
            instructions = context["instructions"]
            db.rollback()
        last_check = 0.0

        def check():
            nonlocal last_check
            if monotonic() - last_check < 1:
                return
            last_check = monotonic()
            with session_factory() as db:
                current = db.get(SkillChatTurn, turn_id)
                if current is None or current.status != "RUNNING":
                    raise AppError(409, "skill_chat_cancelled")
                actor = db.get(UserAccount, actor_id)
                if actor is None:
                    raise AppError(403, "admin_required")
                service.authorize(actor, db)
                analysis_configuration(actor, db, config)

        raw = responses.converse(
            base_url,
            config["model"],
            key,
            effort,
            instructions,
            messages,
            on_progress=check,
            call_mode=config.get("call_mode", "RESPONSES_API"),
        )
        # Preserve the original response even when later validation or permission checks fail.
        with session_factory() as db:
            row = db.get(SkillChatTurn, turn_id, with_for_update=True)
            if row is None:
                return
            row.raw_response = raw
            db.commit()
        answer = parse_answer(raw)
        with session_factory() as db:
            actor = db.get(UserAccount, actor_id)
            if actor is None:
                raise AppError(403, "admin_required")
            service.authorize(actor, db, lock=True)
            analysis_configuration(actor, db, config)
            row = db.get(SkillChatTurn, turn_id, with_for_update=True)
            if row.status == "RUNNING":
                row.answer, row.candidate_body = answer.message, answer.body.replace("\r\n", "\n")
                row.status, row.updated_at = "COMPLETED", datetime.now(UTC)
                db.commit()
    except Exception as exc:
        propagate_database_outage(exc)
        code = exc.detail if isinstance(exc, AppError) else "skill_chat_internal_error"
        with session_factory() as db:
            db.execute(
                update(SkillChatTurn)
                .where(SkillChatTurn.id == turn_id, SkillChatTurn.status == "RUNNING")
                .values(status="FAILED", error_code=code, updated_at=datetime.now(UTC))
            )
            db.commit()
