from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    DocumentVersion,
    SourceDocument,
    UserAccount,
)
from app.db.models import (
    RequirementCategory as Category,
)
from app.db.models import (
    RequirementClassification as Classification,
)
from app.db.models import (
    RequirementHistory as History,
)
from app.db.models import (
    RequirementLibrary as Library,
)
from app.db.models import (
    RequirementRule as Rule,
)
from app.db.models import (
    RequirementSource as Source,
)
from app.modules.documents.service import access, version_view
from app.modules.requirements.schemas import Assign, CategoryInput, DeleteCategory, Move, RuleInput

FIELDS = (
    "title",
    "role",
    "preconditions",
    "action",
    "expected",
    "question",
    "resolution",
    "status",
)


def lock(project_id: int, actor: UserAccount, db: Session, revision: int | None = None) -> Library:
    access(project_id, actor, db, lock=True)
    db.execute(insert(Library).values(project_id=project_id).on_conflict_do_nothing())
    lib = db.get(Library, project_id, with_for_update=True, populate_existing=True)
    if revision is not None and revision != lib.revision:
        raise AppError(409, "requirements_changed")
    return lib


def own[Row: (Category, Rule, DocumentVersion, Classification)](
    model: type[Row], project_id: int, identity: int, db: Session
) -> Row:
    row = db.scalar(select(model).where(model.project_id == project_id, model.id == identity))
    if row is None or (isinstance(row, Rule) and row.deleted_at is not None):
        raise AppError(404, "requirement_not_found")
    return row


def categories(project_id: int, db: Session) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .where(Category.project_id == project_id)
            .order_by(Category.position, Category.id)
        )
    )


def category_view(row: Category) -> dict:
    return {k: getattr(row, k) for k in ("id", "name", "parent_id", "position")}


def source_views(rule_id: int, db: Session) -> list[dict]:
    return [
        {
            "document_version_id": s.document_version_id,
            "role": s.role,
            "location": s.location,
            "excerpt": s.excerpt,
            "document": version_view(v, db),
        }
        for s, v in db.execute(
            select(Source, DocumentVersion)
            .join(DocumentVersion, Source.document_version_id == DocumentVersion.id)
            .where(Source.rule_id == rule_id)
        )
    ]


def rule_view(row: Rule, db: Session) -> dict:
    return {
        **{k: getattr(row, k) for k in FIELDS},
        "id": row.id,
        "number": row.number,
        "category_id": row.category_id,
        "version": row.version,
        "request_id": row.request_id,
        "updated_at": row.updated_at.isoformat(),
        "updated_by": db.get(UserAccount, row.updated_by).display_name,
        "sources": source_views(row.id, db),
        "analysis_id": row.analysis_id,
        "analysis_candidate_key": row.analysis_candidate_key,
    }


def state(project_id: int, actor: UserAccount, db: Session) -> dict:
    lib = lock(project_id, actor, db)
    # ponytail: list-sized page; batch source hydration when large projects need pagination.
    result = {
        "revision": lib.revision,
        "categories": [category_view(c) for c in categories(project_id, db)],
        "rules": [
            rule_view(r, db)
            for r in db.scalars(
                select(Rule)
                .where(Rule.project_id == project_id, Rule.deleted_at.is_(None))
                .order_by(Rule.number)
            )
        ],
    }
    db.commit()
    return result


def detail(project_id: int, rule_id: int, actor: UserAccount, db: Session) -> dict:
    lock(project_id, actor, db)
    result = rule_view(own(Rule, project_id, rule_id, db), db)
    result["history"] = [
        {"version": h.version, "snapshot": h.snapshot, "created_at": h.created_at.isoformat()}
        for h in db.scalars(
            select(History).where(History.rule_id == rule_id).order_by(History.version.desc())
        )
    ]
    db.commit()
    return result


def classification_history(project_id: int, actor: UserAccount, db: Session) -> list[dict]:
    access(project_id, actor, db)
    result = []
    for entry in db.scalars(
        select(Classification)
        .where(Classification.project_id == project_id)
        .order_by(Classification.id.desc())
        .limit(50)
    ):
        result.append(
            {
                "id": entry.id,
                "actor": db.get(UserAccount, entry.actor_id).display_name,
                "created_at": entry.created_at.isoformat(),
                "undone": entry.undone,
                "before": entry.before,
                "after": entry.after,
            }
        )
    return result


def check_parent(project_id: int, parent_id: int | None, db: Session) -> None:
    if parent_id is not None and own(Category, project_id, parent_id, db).parent_id is not None:
        raise AppError(422, "requirement_parent_invalid")


def check_name(
    project_id: int, parent_id: int | None, name: str, db: Session, exclude: int | None = None
) -> None:
    if db.scalar(
        select(Category.id).where(
            Category.project_id == project_id,
            Category.parent_id == parent_id,
            Category.name == name,
            Category.id != exclude if exclude else True,
        )
    ):
        raise AppError(409, "requirement_category_duplicate")


def record(
    project_id: int, actor: UserAccount, before: dict, after: dict, lib: Library, db: Session
) -> dict:
    event = Classification(project_id=project_id, actor_id=actor.id, before=before, after=after)
    db.add(event)
    lib.revision += 1
    db.flush()
    event_id = event.id
    db.commit()
    return {"revision": lib.revision, "event_id": event_id}


def save_category(
    project_id: int,
    category_id: int | None,
    payload: CategoryInput,
    actor: UserAccount,
    db: Session,
) -> dict:
    lib = lock(project_id, actor, db, payload.revision)
    check_parent(project_id, payload.parent_id, db)
    check_name(project_id, payload.parent_id, payload.name, db, category_id)
    before = {"categories": [], "rules": []}
    if category_id:
        row = own(Category, project_id, category_id, db)
        if (row.parent_id is None) != (payload.parent_id is None):
            raise AppError(422, "requirement_parent_invalid")
        before["categories"] = [category_view(row)]
        row.name, row.parent_id = payload.name, payload.parent_id
    else:
        row = Category(
            project_id=project_id,
            name=payload.name,
            parent_id=payload.parent_id,
            position=max(
                [
                    c.position
                    for c in categories(project_id, db)
                    if c.parent_id == payload.parent_id
                ],
                default=-1,
            )
            + 1,
        )
        db.add(row)
        db.flush()
    return record(
        project_id, actor, before, {"categories": [category_view(row)], "rules": []}, lib, db
    )


def move(project_id: int, payload: Move, actor: UserAccount, db: Session) -> dict:
    lib = lock(project_id, actor, db, payload.revision)
    row = own(Category, project_id, payload.category_id, db)
    if row.parent_id is None:
        raise AppError(422, "requirement_parent_invalid")
    check_parent(project_id, payload.parent_id, db)
    check_name(project_id, payload.parent_id, row.name, db, row.id)
    all_rows = categories(project_id, db)
    affected = [c for c in all_rows if c.parent_id in (row.parent_id, payload.parent_id)]
    before = {"categories": [category_view(c) for c in affected], "rules": []}
    target = [c for c in all_rows if c.parent_id == payload.parent_id and c.id != row.id]
    if payload.before_id is not None:
        before_row = own(Category, project_id, payload.before_id, db)
        if before_row.parent_id != payload.parent_id or before_row.id == row.id:
            raise AppError(422, "requirement_target_invalid")
        target.insert(target.index(before_row), row)
    else:
        target.append(row)
    row.parent_id = payload.parent_id
    for i, c in enumerate(target):
        c.position = i
    return record(
        project_id,
        actor,
        before,
        {"categories": [category_view(c) for c in affected], "rules": []},
        lib,
        db,
    )


def assign(project_id: int, payload: Assign, actor: UserAccount, db: Session) -> dict:
    lib = lock(project_id, actor, db, payload.revision)
    row = own(Rule, project_id, payload.rule_id, db)
    if payload.category_id is not None:
        own(Category, project_id, payload.category_id, db)
    before = {"categories": [], "rules": [{"id": row.id, "category_id": row.category_id}]}
    row.category_id = payload.category_id
    return record(
        project_id,
        actor,
        before,
        {"categories": [], "rules": [{"id": row.id, "category_id": row.category_id}]},
        lib,
        db,
    )


def undo(project_id: int, event_id: int, revision: int, actor: UserAccount, db: Session) -> dict:
    lib = lock(project_id, actor, db, revision)
    event = own(Classification, project_id, event_id, db)
    if event.undone:
        raise AppError(409, "requirement_undo_conflict")
    for c in event.after["categories"]:
        if category_view(own(Category, project_id, c["id"], db)) != c:
            raise AppError(409, "requirement_undo_conflict")
    for r in event.after["rules"]:
        if own(Rule, project_id, r["id"], db).category_id != r["category_id"]:
            raise AppError(409, "requirement_undo_conflict")
    for c in event.before["categories"]:
        check_name(project_id, c["parent_id"], c["name"], db, c["id"])
        row = own(Category, project_id, c["id"], db)
        row.name, row.parent_id, row.position = c["name"], c["parent_id"], c["position"]
    old_ids = {c["id"] for c in event.before["categories"]}
    for c in event.after["categories"]:
        if c["id"] not in old_ids:
            if db.scalar(select(Rule.id).where(Rule.category_id == c["id"])) or db.scalar(
                select(Category.id).where(Category.parent_id == c["id"])
            ):
                raise AppError(409, "requirement_undo_conflict")
            db.delete(own(Category, project_id, c["id"], db))
    for r in event.before["rules"]:
        if r["category_id"] is not None:
            own(Category, project_id, r["category_id"], db)
        own(Rule, project_id, r["id"], db).category_id = r["category_id"]
    event.undone = True
    return record(project_id, actor, event.after, event.before, lib, db) | {"event_id": None}


def save_rule(
    project_id: int,
    rule_id: int | None,
    payload: RuleInput,
    actor: UserAccount,
    db: Session,
    *,
    commit: bool = True,
    analysis_id: int | None = None,
    analysis_candidate_key: str | None = None,
) -> dict:
    lib = lock(project_id, actor, db, payload.revision)
    if rule_id is None:
        existing = db.scalar(
            select(Rule).where(
                Rule.project_id == project_id, Rule.request_id == str(payload.request_id)
            )
        )
        if existing:
            raise AppError(409, "requirement_request_exists")
    if payload.category_id is not None:
        own(Category, project_id, payload.category_id, db)
    existing_source_ids = (
        set(db.scalars(select(Source.document_version_id).where(Source.rule_id == rule_id)))
        if rule_id
        else set()
    )
    for source in payload.sources:
        version = own(DocumentVersion, project_id, source.document_version_id, db)
        if (
            db.get(SourceDocument, version.document_id).deleted_at is not None
            and version.id not in existing_source_ids
        ):
            raise AppError(409, "document_deleted")
    row = (
        own(Rule, project_id, rule_id, db)
        if rule_id
        else Rule(
            project_id=project_id,
            number=lib.next_number,
            request_id=str(payload.request_id),
            version=0,
            category_id=payload.category_id,
            analysis_id=analysis_id,
            analysis_candidate_key=analysis_candidate_key,
        )
    )
    if rule_id and payload.category_id != row.category_id:
        raise AppError(409, "requirements_changed")
    if rule_id and payload.request_id != UUID(row.request_id):
        raise AppError(422, "invalid_request")
    if rule_id and all(getattr(row, k) == getattr(payload, k) for k in FIELDS):
        old_sources = [
            {k: s[k] for k in ("document_version_id", "role", "location", "excerpt")}
            for s in source_views(row.id, db)
        ]
        if old_sources == [s.model_dump() for s in payload.sources]:
            if commit:
                db.commit()
            return {"revision": lib.revision}
    if rule_id and row.status == "CONFIRMED" and payload.status == "CONFIRMED":
        raise AppError(422, "requirement_re_review")
    for key in FIELDS:
        setattr(row, key, getattr(payload, key))
    row.updated_by, row.updated_at = actor.id, datetime.now(UTC)
    row.version += 1
    db.add(row)
    db.flush()
    db.execute(delete(Source).where(Source.rule_id == row.id))
    for source in payload.sources:
        db.add(Source(project_id=project_id, rule_id=row.id, **source.model_dump()))
    db.flush()
    db.add(
        History(
            project_id=project_id,
            rule_id=row.id,
            version=row.version,
            snapshot=rule_view(row, db),
            actor_id=actor.id,
        )
    )
    if not rule_id:
        lib.next_number += 1
    lib.revision += 1
    if commit:
        db.commit()
    return {"revision": lib.revision, "rule_id": row.id}


def delete_category(
    project_id: int, category_id: int, payload: DeleteCategory, actor: UserAccount, db: Session
) -> dict:
    lib = lock(project_id, actor, db, payload.revision)
    row = own(Category, project_id, category_id, db)
    children = list(
        db.scalars(
            select(Category).where(Category.project_id == project_id, Category.parent_id == row.id)
        )
    )
    affected_ids = [row.id, *[c.id for c in children]]
    rules = list(
        db.scalars(
            select(Rule).where(
                Rule.project_id == project_id,
                Rule.category_id.in_(affected_ids),
                Rule.deleted_at.is_(None),
            )
        )
    )
    target = None
    if payload.mode == "MOVE":
        if payload.target_id is not None:
            target = own(Category, project_id, payload.target_id, db)
            if target.id in affected_ids or (target.parent_id is None) != (row.parent_id is None):
                raise AppError(422, "requirement_delete_target")
        if (children or rules) and target is None:
            raise AppError(422, "requirement_delete_target")
        if target:
            for child in children:
                check_name(project_id, target.id, child.name, db, child.id)
    before = {
        "categories": [category_view(row), *[category_view(c) for c in children]],
        "rules": [{"id": r.id, "category_id": r.category_id, "deleted_at": None} for r in rules],
    }
    if payload.mode == "MOVE" and target:
        position = (
            max(
                [c.position for c in categories(project_id, db) if c.parent_id == target.id],
                default=-1,
            )
            + 1
        )
        for i, child in enumerate(sorted(children, key=lambda c: (c.position, c.id))):
            child.parent_id, child.position = target.id, position + i
        for rule in rules:
            if rule.category_id == row.id:
                rule.category_id = target.id
    elif payload.mode in ("UNCLASSIFIED", "DELETE"):
        deleted_at = datetime.now(UTC) if payload.mode == "DELETE" else None
        for rule in rules:
            rule.category_id = None
            rule.deleted_at = deleted_at
    after = {
        "categories": [category_view(c) for c in children] if payload.mode == "MOVE" else [],
        "rules": [
            {
                "id": r.id,
                "category_id": r.category_id,
                "deleted_at": r.deleted_at.isoformat() if r.deleted_at else None,
            }
            for r in rules
        ],
        "delete_mode": payload.mode,
    }
    db.flush()
    if payload.mode != "MOVE":
        for child in children:
            db.delete(child)
        db.flush()
    db.delete(row)
    return record(project_id, actor, before, after, lib, db) | {"event_id": None}
