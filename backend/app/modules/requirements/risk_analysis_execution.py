"""Worker execution for versioned requirement-risk analysis."""

import copy
import logging
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB

from app.core.errors import AppError
from app.db.models import (
    GitHubConnection,
    GitHubRepository,
    ProjectRepository,
    RequirementRiskAnalysis,
    SourceDocument,
    UserAccount,
)
from app.integrations import ai_client as responses
from app.integrations import github
from app.integrations.response_diagnostics import safe_snapshot
from app.modules.ai import native_terminal, task_lifecycle
from app.modules.ai.recovery import propagate_database_outage
from app.modules.ai.service import analysis_configuration
from app.modules.documents import service as documents
from app.modules.documents.files import decode_text
from app.modules.github.service import saved_token
from app.modules.prototypes import directories
from app.modules.prototypes import service as prototypes
from app.modules.requirements import (
    analysis_materials,
    artifacts,
    risk_analysis_service,
    risk_schemas,
    risk_service,
)

logger = logging.getLogger(__name__)


def recover(db):
    task_lifecycle.mark_interrupted(
        db, (RequirementRiskAnalysis,), "risk_analysis_worker_interrupted"
    )
    db.commit()


def github_access(source, actor, db):
    repo = db.get(ProjectRepository, source.repository_id)
    if repo is None or repo.project_id != source.project_id:
        raise AppError(422, "risk_source_unavailable")
    connection = db.scalar(
        select(GitHubConnection)
        .join(GitHubRepository, GitHubRepository.connection_id == GitHubConnection.id)
        .where(
            GitHubConnection.owner_id == actor.id,
            GitHubRepository.github_id == repo.github_id,
        )
        .order_by(GitHubConnection.id)
    )
    if connection is None:
        raise AppError(422, "github_connection_required")
    return repo.full_name, saved_token(connection)


def prepare(task, actor, db, *, contract_version=3):
    input_data = {
        "contract_version": contract_version,
        "request_id": task.request_id,
        "project_id": task.project_id,
        "revision": task.id,
        "focus": task.focus,
        "materials": [],
    }
    bindings, binaries, git_jobs = [], [], []
    for number, selection in enumerate(task.selections, 1):
        source = db.scalar(
            select(SourceDocument).where(
                SourceDocument.id == selection["document_id"],
                SourceDocument.project_id == task.project_id,
                SourceDocument.deleted_at.is_(None),
            )
        )
        if source is None:
            raise AppError(422, "risk_source_unavailable")
        if source.kind == "LINK" and selection.get("url") and selection["url"] != source.url:
            raise AppError(409, "prototype_link_changed")
        source_id = f"D{number}"
        version = None
        if source.kind == "FILE":
            path, row = documents.stored_version(
                task.project_id, selection["version_id"], actor, db
            )
            if row.document_id != source.id:
                raise AppError(422, "risk_source_unavailable")
            version = documents.version_view(row, db)
            material = analysis_materials.file_material(
                path, row.extension, source_id, row.filename
            )
            material.update(name=source.name or row.filename, origin=source.purpose)
            material.pop("role", None)
            if row.extension in ("png", "jpg", "jpeg", "webp", "pdf"):
                binaries.append((path, row.extension, source_id, row.filename))
        elif source.kind == "DIRECTORY":
            material, attached = directories.material(
                task.project_id,
                source.id,
                selection["version_id"],
                selection["paths"],
                source_id,
                actor,
                db,
            )
            _, row = documents.stored_version(task.project_id, selection["version_id"], actor, db)
            version = documents.version_view(row, db)
            material.update(name=source.name, origin=source.purpose)
            binaries.extend(attached)
        elif source.kind == "GITHUB":
            full_name, token = github_access(source, actor, db)
            material = {
                "source_id": source_id,
                "name": source.name,
                "origin": source.purpose,
                "kind": "PROTOTYPE_CODE",
                "snapshot_ref": source.latest_commit or "",
                "read_state": "READABLE",
                "read_note": "",
                "segments": [],
            }
            if not source.latest_commit or not source.file_manifest:
                material.update(
                    read_state="NOT_LOADED", read_note="尚未固定可读取的GitHub文件", snapshot_ref=""
                )
            else:
                git_jobs.append((material, full_name, token, copy.deepcopy(source.file_manifest)))
        else:
            files = selection.get("paths", [])
            if files:
                captured = prototypes.link_pages(
                    task.project_id, source.id, files, selection["snapshot"], actor, db
                )
                material = {
                    "source_id": source_id,
                    "name": source.name,
                    "origin": source.purpose,
                    "kind": "LINK",
                    "snapshot_ref": captured["snapshot_ref"],
                    "read_state": "PARTIAL",
                    "read_note": (
                        "已固定页面HTML、原型说明及批注引用Markdown全文；不执行脚本或读取其他资源"
                    ),
                    "segments": [
                        {
                            "segment_id": f"p{i}",
                            "location": item["location"],
                            "text": item["text"],
                            "image_ref": "",
                        }
                        for i, item in enumerate(captured["segments"], 1)
                    ],
                }
            else:
                material = {
                    "source_id": source_id,
                    "name": source.name,
                    "origin": source.purpose,
                    "kind": "LINK",
                    "snapshot_ref": "",
                    "read_state": "NOT_LOADED",
                    "read_note": "历史任务仅保存链接，未采集页面",
                    "segments": [],
                }
        input_data["materials"].append(material)
        bindings.append(
            {
                "source_id": source_id,
                "document_id": source.id,
                "name": material["name"],
                "kind": source.kind,
                "purpose": source.purpose,
                "version": version,
                "url": source.url,
                "branch": source.branch,
                "commit": source.latest_commit,
                "deleted": False,
            }
        )
    db.rollback()
    for material, full_name, token, manifest in git_jobs:
        for file_number, entry in enumerate(manifest, 1):
            content = decode_text(github.prototype_content(token, full_name, entry["sha"]))
            for segment in analysis_materials.text_segments(content, entry["path"]):
                segment["segment_id"] = f"f{file_number}-{segment['segment_id']}"
                material["segments"].append(segment)
    return input_data, bindings, binaries


def validate_result(answer, input_data, project_id):
    return risk_service.validate_candidate(answer, input_data, project_id)


def execute(task_id, session_factory):
    diagnostics = {}
    try:
        with session_factory() as db:
            task = db.get(RequirementRiskAnalysis, task_id)
            if task is None or task.status != "RUNNING":
                return
            actor = db.get(UserAccount, task.actor_id)
            if actor is None:
                raise AppError(403, "risk_analysis_access_lost")
            documents.access(task.project_id, actor, db)
            config, key = analysis_configuration(actor, db, task.ai_config)
            terminal_options = native_terminal.analysis_options(task.ai_config)
            base_url = config["base_url"]
            effort = config["reasoning_effort"]
            project_id, actor_id = task.project_id, task.actor_id
            title = task.title
            skill = task.context.get("skill")
            if not isinstance(skill, dict) or not isinstance(skill.get("instructions"), str):
                raise AppError(409, "skill_snapshot_missing")
            if risk_analysis_service.has_mislabeled_skill(skill):
                raise AppError(409, "risk_analysis_contract_mismatch")
            if "input" in task.context:
                binaries = risk_analysis_service.frozen_materials(task.project_id, task, actor, db)
                input_data = copy.deepcopy(task.context["input"])
                input_data.update(request_id=task.request_id, revision=task.id)
                risk_schemas.AnalysisInput.model_validate(input_data)
                bindings = copy.deepcopy(task.context["bindings"])
                db.rollback()
            else:
                input_data, bindings, binaries = prepare(
                    task, actor, db, contract_version=skill.get("contract_version", 3)
                )
        with session_factory() as db:
            task = db.get(RequirementRiskAnalysis, task_id, with_for_update=True)
            if task is None or task.status != "RUNNING":
                return
            task.context = {"input": input_data, "bindings": bindings, "skill": skill}
            task.updated_at = datetime.now(UTC)
            db.commit()
        instructions = skill["instructions"]
        last_check = 0.0

        def check():
            nonlocal last_check
            if monotonic() - last_check < 1:
                return
            last_check = monotonic()
            with session_factory() as db:
                current = db.get(RequirementRiskAnalysis, task_id)
                actor = db.get(UserAccount, actor_id)
                if current is None or current.status != "RUNNING":
                    raise AppError(409, "risk_analysis_cancelled")
                if actor is None:
                    raise AppError(403, "risk_analysis_access_lost")
                documents.access(project_id, actor, db)
                analysis_configuration(actor, db, config)

        answer = responses.analyze(
            base_url,
            config["model"],
            key,
            effort,
            instructions,
            analysis_materials.model_content(input_data, binaries),
            diagnostics=diagnostics,
            output_profile="requirement_analysis",
            on_progress=check,
            call_mode=config.get("call_mode", "RESPONSES_API"),
            **terminal_options,
            **analysis_materials.structured_reading_options(
                config.get("call_mode"), input_data, binaries
            ),
        )
        artifacts.save_candidate(task_id, answer)
        check()
        output, corrections, comparison_corrections, review_warnings = validate_result(
            answer, input_data, project_id
        )
        with session_factory() as db:
            actor = db.get(UserAccount, actor_id)
            if actor is None:
                raise AppError(403, "risk_analysis_access_lost")
            documents.access(project_id, actor, db, lock=True)
            task = db.get(RequirementRiskAnalysis, task_id, with_for_update=True)
            if task.status != "RUNNING":
                return
            analysis_configuration(actor, db, config)
            result = risk_service.store_report(
                project_id,
                title,
                "input.json",
                "risk-report.json",
                input_data,
                output,
                bindings,
                actor,
                db,
                commit=False,
            )
            task = db.get(RequirementRiskAnalysis, task_id, with_for_update=True)
            task.report_id = result["id"]
            task.context = {
                **task.context,
                "function_risk_corrections": corrections,
                "comparison_text_corrections": comparison_corrections,
                "review_warnings": review_warnings,
                "ai_diagnostics": safe_snapshot(diagnostics),
            }
            task.status, task.updated_at = "COMPLETED", datetime.now(UTC)
            db.commit()
    except Exception as exc:
        propagate_database_outage(exc)
        code = exc.detail if isinstance(exc, AppError) else "risk_analysis_internal_error"
        logger.warning("risk_analysis_failed id=%s type=%s", task_id, type(exc).__name__)
        values = {"status": "FAILED", "error_code": code, "updated_at": datetime.now(UTC)}
        if diagnostics:
            values["context"] = RequirementRiskAnalysis.context.op("||")(
                cast({"ai_diagnostics": safe_snapshot(diagnostics)}, JSONB)
            )
        with session_factory() as db:
            db.execute(
                update(RequirementRiskAnalysis)
                .where(
                    RequirementRiskAnalysis.id == task_id,
                    RequirementRiskAnalysis.status == "RUNNING",
                )
                .values(**values)
            )
            db.commit()
