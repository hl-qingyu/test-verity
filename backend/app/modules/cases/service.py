import hashlib
import io
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import ValidationError
from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    CaseCategory,
    CaseImport,
    CaseLibrary,
    CaseLifecycleRecord,
    CaseRecord,
    CaseVersion,
    ManagedCase,
    UserAccount,
)
from app.modules.cases.files import read_import
from app.modules.cases.schemas import (
    COLUMNS,
    DESIGN_FIELDS,
    AssignCategory,
    BatchEdit,
    CaseDesign,
    CaseInput,
    CaseValues,
    CategoryInput,
    DeleteCase,
    DeleteCategory,
    EditScope,
    ImportConfirm,
    ImportReview,
    ImportUpload,
    LifecycleInput,
    Search,
)
from app.modules.documents.service import access


def lock(
    project_id: int, actor: UserAccount, db: Session, revision: int | None = None
) -> CaseLibrary:
    access(project_id, actor, db, lock=True)
    db.execute(insert(CaseLibrary).values(project_id=project_id).on_conflict_do_nothing())
    library = db.get(CaseLibrary, project_id, with_for_update=True, populate_existing=True)
    if revision is not None and revision != library.revision:
        raise AppError(409, "cases_changed")
    return library


def category(project_id: int, category_id: int | None, db: Session) -> CaseCategory | None:
    if category_id is None:
        return None
    row = db.scalar(
        select(CaseCategory).where(
            CaseCategory.project_id == project_id, CaseCategory.id == category_id
        )
    )
    if row is None:
        raise AppError(404, "case_category_not_found")
    return row


def metadata(project_id: int, actor: UserAccount, db: Session) -> dict:
    library = lock(project_id, actor, db)
    counts = dict(
        db.execute(
            select(ManagedCase.category_id, func.count())
            .where(ManagedCase.project_id == project_id, ManagedCase.deleted_at.is_(None))
            .group_by(ManagedCase.category_id)
        ).all()
    )
    return {
        "revision": library.revision,
        "next_number": library.next_number,
        "categories": [
            {"id": c.id, "name": c.name, "count": counts.get(c.id, 0)}
            for c in db.scalars(
                select(CaseCategory)
                .where(CaseCategory.project_id == project_id)
                .order_by(CaseCategory.id)
            )
        ],
    }


def save_category(
    project_id: int,
    category_id: int | None,
    payload: CategoryInput,
    actor: UserAccount,
    db: Session,
) -> dict:
    library = lock(project_id, actor, db, payload.revision)
    old = category(project_id, category_id, db)
    query = select(CaseCategory.id).where(
        CaseCategory.project_id == project_id, CaseCategory.name == payload.name
    )
    if old:
        query = query.where(CaseCategory.id != old.id)
    if db.scalar(query):
        raise AppError(409, "case_category_duplicate")
    if old:
        old.name = payload.name
        old.updated_by = actor.id
    else:
        db.add(CaseCategory(project_id=project_id, name=payload.name, updated_by=actor.id))
    library.revision += 1
    db.commit()
    return metadata(project_id, actor, db)


def delete_category(
    project_id: int, category_id: int, payload: DeleteCategory, actor: UserAccount, db: Session
) -> dict:
    library = lock(project_id, actor, db, payload.revision)
    old = category(project_id, category_id, db)
    rows = list(
        db.scalars(
            select(ManagedCase).where(
                ManagedCase.project_id == project_id, ManagedCase.category_id == category_id
            )
        )
    )
    active_rows = [row for row in rows if row.deleted_at is None]
    if active_rows:
        if payload.target_id is None or payload.target_id == category_id:
            raise AppError(422, "case_category_target_required")
        category(project_id, payload.target_id, db)
        for row in active_rows:
            row.category_id = payload.target_id
            row.updated_by = actor.id
        db.flush()
    for row in rows:
        if row.deleted_at is not None:
            row.category_id = None
    db.flush()
    db.delete(old)
    library.revision += 1
    db.commit()
    return metadata(project_id, actor, db)


def assign_category(
    project_id: int, payload: AssignCategory, actor: UserAccount, db: Session
) -> dict:
    library = lock(project_id, actor, db, payload.revision)
    category(project_id, payload.category_id, db)
    rows = list(
        db.scalars(
            select(ManagedCase).where(
                ManagedCase.project_id == project_id,
                ManagedCase.deleted_at.is_(None),
                ManagedCase.id.in_(payload.case_ids),
            )
        )
    )
    if len(rows) != len(set(payload.case_ids)):
        raise AppError(404, "case_not_found")
    for row in rows:
        row.category_id = payload.category_id
        row.updated_by = actor.id
    library.revision += 1
    db.commit()
    return metadata(project_id, actor, db)


def record_value(field: str, kind: str, default: str = ""):
    return func.coalesce(
        select(getattr(CaseRecord, field))
        .where(CaseRecord.version_id == CaseVersion.id, CaseRecord.kind == kind)
        .order_by(CaseRecord.id.desc())
        .limit(1)
        .correlate(CaseVersion)
        .scalar_subquery(),
        default,
    )


def case_query(project_id: int):
    return (
        select(
            ManagedCase.id,
            func.coalesce(ManagedCase.imported_number, cast(ManagedCase.number, String)).label(
                "number"
            ),
            ManagedCase.number.label("sort_number"),
            ManagedCase.category_id,
            ManagedCase.lifecycle,
            CaseVersion.id.label("version_id"),
            CaseVersion.number.label("version"),
            *[getattr(CaseVersion, f) for f in DESIGN_FIELDS],
            CaseVersion.source_kind,
            record_value("result", "TEST").label("result"),
            record_value("tester", "TEST").label("tester"),
            record_value("review_status", "REVIEW", "待审核").label("review_status"),
            record_value("source_kind", "TEST").label("result_origin"),
            func.row_number().over(order_by=ManagedCase.number).label("serial"),
        )
        .join(
            CaseVersion,
            (CaseVersion.case_id == ManagedCase.id)
            & (CaseVersion.number == ManagedCase.current_version),
        )
        .where(ManagedCase.project_id == project_id, ManagedCase.deleted_at.is_(None))
    )


def filtered(project_id: int, payload: Search):
    base = case_query(project_id).subquery()
    query = select(base)
    if payload.lifecycle != "ALL":
        query = query.where(base.c.lifecycle == payload.lifecycle)
    if payload.category_id is not None:
        query = query.where(base.c.category_id == (payload.category_id or None))
    for condition in payload.conditions:
        if not condition.value.strip():
            continue
        value = condition.value.strip()
        column = cast(base.c[condition.field], String)
        if condition.operator == "equals":
            query = query.where(func.lower(column) == value.lower())
        elif condition.operator == "contains":
            query = query.where(column.icontains(value, autoescape=True))
        else:
            query = query.where(~column.icontains(value, autoescape=True))
    return query.order_by(base.c.sort_number)


def list_cases(project_id: int, payload: Search, actor: UserAccount, db: Session) -> dict:
    meta = metadata(project_id, actor, db)
    query = filtered(project_id, payload)
    count = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    page = min(payload.page, max(1, (count + payload.page_size - 1) // payload.page_size))
    offset = (page - 1) * payload.page_size
    items = [
        dict(row) for row in db.execute(query.offset(offset).limit(payload.page_size)).mappings()
    ]
    for i, row in enumerate(items):
        row["serial"] = offset + i + 1
    return {**meta, "items": items, "total": count, "page": page, "page_size": payload.page_size}


def own_case(project_id: int, case_id: int, db: Session) -> ManagedCase:
    row = db.scalar(
        select(ManagedCase).where(
            ManagedCase.project_id == project_id,
            ManagedCase.id == case_id,
            ManagedCase.deleted_at.is_(None),
        )
    )
    if row is None:
        raise AppError(404, "case_not_found")
    return row


def set_case_lifecycle(project_id, row, state, reason, actor, db, basis):
    if row.project_id != project_id or state not in {"ACTIVE", "RETIRED"} or not reason.strip():
        raise AppError(422, "case_lifecycle_invalid")
    if row.lifecycle != state:
        row.lifecycle, row.updated_by = state, actor.id
        db.add(
            CaseLifecycleRecord(
                project_id=project_id,
                case_id=row.id,
                actor_id=actor.id,
                lifecycle=state,
                reason=reason,
                basis=basis,
            )
        )


def change_lifecycle(project_id, case_id, payload: LifecycleInput, actor, db):
    library = lock(project_id, actor, db, payload.revision)
    row = own_case(project_id, case_id, db)
    set_case_lifecycle(
        project_id, row, payload.lifecycle, payload.reason, actor, db, {"origin": "MANUAL"}
    )
    library.revision += 1
    db.commit()
    return detail(project_id, case_id, actor, db)


def version_view(version: CaseVersion, db: Session) -> dict:
    records = []
    for record in db.scalars(
        select(CaseRecord).where(CaseRecord.version_id == version.id).order_by(CaseRecord.id.desc())
    ):
        account = db.get(UserAccount, record.recorded_by)
        records.append(
            {
                "id": record.id,
                "kind": record.kind,
                "result": record.result,
                "tester": record.tester,
                "review_status": record.review_status,
                "source_kind": record.source_kind,
                "recorded_by": account.display_name,
                "recorded_at": record.recorded_at.isoformat(),
            }
        )
    actor = db.get(UserAccount, version.created_by)
    return {
        "id": version.id,
        "number": version.number,
        **{f: getattr(version, f) for f in DESIGN_FIELDS},
        "source_kind": version.source_kind,
        "source": version.source,
        "import_id": version.import_id,
        "created_by": actor.display_name,
        "created_at": version.created_at.isoformat(),
        "records": records,
    }


def detail(project_id: int, case_id: int, actor: UserAccount, db: Session) -> dict:
    meta = metadata(project_id, actor, db)
    row = own_case(project_id, case_id, db)
    versions = [
        version_view(v, db)
        for v in db.scalars(
            select(CaseVersion)
            .where(CaseVersion.case_id == case_id)
            .order_by(CaseVersion.number.desc())
        )
    ]
    return {
        **meta,
        "id": row.id,
        "number": row.imported_number if row.imported_number is not None else str(row.number),
        "category_id": row.category_id,
        "lifecycle": row.lifecycle,
        "lifecycle_history": [
            {
                "lifecycle": h.lifecycle,
                "reason": h.reason,
                "actor_id": h.actor_id,
                "at": h.created_at.isoformat(),
                "basis": h.basis,
            }
            for h in db.scalars(
                select(CaseLifecycleRecord)
                .where(
                    CaseLifecycleRecord.project_id == project_id,
                    CaseLifecycleRecord.case_id == case_id,
                )
                .order_by(CaseLifecycleRecord.id)
            )
        ],
        "versions": versions,
    }


def add_records(
    version: CaseVersion,
    actor: UserAccount,
    db: Session,
    result: str,
    tester: str,
    review_status: str,
    source_kind: str,
    review_at: datetime | None = None,
) -> None:
    db.add(
        CaseRecord(
            project_id=version.project_id,
            version_id=version.id,
            kind="TEST",
            result=result,
            tester=tester,
            source_kind=source_kind,
            recorded_by=actor.id,
        )
    )
    db.add(
        CaseRecord(
            project_id=version.project_id,
            version_id=version.id,
            kind="REVIEW",
            review_status=review_status,
            source_kind=source_kind,
            recorded_by=actor.id,
            **({"recorded_at": review_at} if review_at is not None else {}),
        )
    )


def insert_case(
    project_id: int,
    library: CaseLibrary,
    payload: CaseDesign,
    actor: UserAccount,
    db: Session,
    *,
    category_id: int | None,
    request_id: str,
    result: str,
    tester: str,
    review_status: str = "待审核",
    import_id: int | None = None,
    source: dict | None = None,
    source_kind: str | None = None,
    review_at: datetime | None = None,
) -> ManagedCase:
    row = ManagedCase(
        project_id=project_id,
        number=library.next_number,
        imported_number=(source or {}).get("original_number")
        if str((source or {}).get("original_number", "")).strip()
        else None,
        category_id=category_id,
        current_version=1,
        request_id=request_id,
        created_by=actor.id,
        updated_by=actor.id,
    )
    library.next_number += 1
    db.add(row)
    db.flush()
    kind = source_kind or ("IMPORT" if import_id else "MANUAL")
    version = CaseVersion(
        project_id=project_id,
        case_id=row.id,
        number=1,
        **{f: getattr(payload, f) for f in DESIGN_FIELDS},
        source_kind=kind,
        import_id=import_id,
        source=source or {},
        created_by=actor.id,
    )
    db.add(version)
    db.flush()
    add_records(version, actor, db, result, tester, review_status, kind, review_at=review_at)
    return row


def apply_case_update(
    project_id: int,
    row: ManagedCase,
    payload: CaseValues,
    actor: UserAccount,
    db: Session,
    *,
    source_kind: str = "MANUAL",
    source: dict | None = None,
    design_review: str = "待审核",
    review_at: datetime | None = None,
) -> None:
    current = db.scalar(
        select(CaseVersion).where(
            CaseVersion.case_id == row.id, CaseVersion.number == row.current_version
        )
    )
    if row.lifecycle == "RETIRED":
        latest_test = db.scalar(
            select(CaseRecord)
            .where(CaseRecord.version_id == current.id, CaseRecord.kind == "TEST")
            .order_by(CaseRecord.id.desc())
            .limit(1)
        )
        if not latest_test or (payload.result, payload.tester) != (
            latest_test.result,
            latest_test.tester,
        ):
            raise AppError(422, "case_retired_test_forbidden")
    if any(getattr(current, f) != getattr(payload, f) for f in DESIGN_FIELDS):
        row.current_version += 1
        version = CaseVersion(
            project_id=project_id,
            case_id=row.id,
            number=row.current_version,
            **{f: getattr(payload, f) for f in DESIGN_FIELDS},
            source_kind=source_kind,
            source=source or {},
            created_by=actor.id,
        )
        db.add(version)
        db.flush()
        add_records(version, actor, db, "未测", "", design_review, source_kind, review_at=review_at)
    else:
        test = db.scalar(
            select(CaseRecord)
            .where(CaseRecord.version_id == current.id, CaseRecord.kind == "TEST")
            .order_by(CaseRecord.id.desc())
            .limit(1)
        )
        review = db.scalar(
            select(CaseRecord)
            .where(CaseRecord.version_id == current.id, CaseRecord.kind == "REVIEW")
            .order_by(CaseRecord.id.desc())
            .limit(1)
        )
        if not test or test.result != payload.result or test.tester != payload.tester:
            db.add(
                CaseRecord(
                    project_id=project_id,
                    version_id=current.id,
                    kind="TEST",
                    result=payload.result,
                    tester=payload.tester,
                    source_kind="MANUAL",
                    recorded_by=actor.id,
                )
            )
        if not review or review.review_status != payload.review_status:
            db.add(
                CaseRecord(
                    project_id=project_id,
                    version_id=current.id,
                    kind="REVIEW",
                    review_status=payload.review_status,
                    source_kind="MANUAL",
                    recorded_by=actor.id,
                )
            )
    row.category_id = payload.category_id
    row.updated_by = actor.id


def save_case(
    project_id: int, case_id: int | None, payload: CaseInput, actor: UserAccount, db: Session
) -> dict:
    library = lock(project_id, actor, db)
    if case_id is None:
        previous = db.scalar(
            select(ManagedCase).where(
                ManagedCase.project_id == project_id,
                ManagedCase.request_id == str(payload.request_id),
            )
        )
        if previous:
            initial = db.scalar(
                select(CaseVersion).where(
                    CaseVersion.case_id == previous.id, CaseVersion.number == 1
                )
            )
            if previous.category_id != payload.category_id or any(
                getattr(initial, f) != getattr(payload, f) for f in DESIGN_FIELDS
            ):
                raise AppError(409, "case_create_conflict")
            first_test = db.scalar(
                select(CaseRecord)
                .where(CaseRecord.version_id == initial.id, CaseRecord.kind == "TEST")
                .order_by(CaseRecord.id)
                .limit(1)
            )
            if first_test and (
                first_test.result != payload.result or first_test.tester != payload.tester
            ):
                raise AppError(409, "case_create_conflict")
            return detail(project_id, previous.id, actor, db)
    if payload.revision != library.revision:
        raise AppError(409, "cases_changed")
    category(project_id, payload.category_id, db)
    if case_id is None:
        row = insert_case(
            project_id,
            library,
            payload,
            actor,
            db,
            category_id=payload.category_id,
            request_id=str(payload.request_id),
            result=payload.result,
            tester=payload.tester,
            review_status=payload.review_status,
        )
    else:
        row = own_case(project_id, case_id, db)
        apply_case_update(project_id, row, payload, actor, db)
    library.revision += 1
    db.commit()
    return detail(project_id, row.id, actor, db)


def edit_scope(project_id: int, payload: EditScope, actor: UserAccount, db: Session) -> dict:
    meta = metadata(project_id, actor, db)
    query = filtered(project_id, payload)
    if payload.case_ids is not None:
        scoped = query.subquery()
        query = (
            select(scoped).where(scoped.c.id.in_(payload.case_ids)).order_by(scoped.c.sort_number)
        )
    rows = [dict(r) for r in db.execute(query.limit(20001)).mappings()]
    if payload.case_ids is not None and len(rows) != len(payload.case_ids):
        raise AppError(409, "case_selection_changed")
    # ponytail: bounded in-memory edit snapshot; use server-side drafts for larger libraries.
    if len(rows) > 20000 or len(json.dumps(rows, ensure_ascii=False).encode()) > 50_000_000:
        raise AppError(422, "case_edit_limit")
    for i, row in enumerate(rows):
        row["serial"] = i + 1
    return {**meta, "items": rows, "total": len(rows), "page": 1, "page_size": 100}


def batch_edit(project_id: int, payload: BatchEdit, actor: UserAccount, db: Session) -> dict:
    library = lock(project_id, actor, db, payload.revision)
    snapshot = edit_scope(project_id, payload.search, actor, db)
    existing = {r["id"]: r for r in snapshot["items"]}
    patches = (
        {r.id: r.changes for r in payload.rows}
        if payload.mode == "rows"
        else {case_id: payload.changes for case_id in existing}
    )
    if not patches or not set(patches).issubset(existing):
        raise AppError(404, "case_not_found")
    updates = []
    for case_id, changes in patches.items():
        old = existing[case_id]
        values = {f: old[f] for f in CaseValues.model_fields}
        values.update(changes.model_dump(exclude_unset=True))
        validated = CaseValues.model_validate(values)
        category(project_id, validated.category_id, db)
        if any(old[f] != getattr(validated, f) for f in CaseValues.model_fields):
            updates.append((own_case(project_id, case_id, db), validated))
    for row, values in updates:
        apply_case_update(project_id, row, values, actor, db)
    if updates:
        library.revision += 1
    db.commit()
    return {**metadata(project_id, actor, db), "updated": len(updates)}


def delete_case(
    project_id: int, case_id: int, payload: DeleteCase, actor: UserAccount, db: Session
) -> dict:
    library = lock(project_id, actor, db, payload.revision)
    row = own_case(project_id, case_id, db)
    row.deleted_at = datetime.now(UTC)
    row.deleted_by = actor.id
    row.updated_by = actor.id
    library.revision += 1
    db.commit()
    return metadata(project_id, actor, db)


def export_cases(project_id: int, payload: Search, actor: UserAccount, db: Session) -> bytes:
    lock(project_id, actor, db)
    rows = list(db.execute(filtered(project_id, payload)).mappings())
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "测试用例"
    sheet.append([name for _, name in COLUMNS])
    sheet.freeze_panes = "C2"
    for i, row in enumerate(rows, 1):
        sheet.append([i if key == "serial" else row[key] for key, _ in COLUMNS])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="EAF2E3")
    for i in range(1, 15):
        sheet.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 12 if i < 3 else 28
    sheet.auto_filter.ref = sheet.dimensions
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def import_path(batch: CaseImport) -> Path:
    root = Settings().document_storage_path.resolve() / "case-imports"
    path = (root / batch.storage_key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError(503, "document_storage_unavailable")
    return path


def own_import(project_id: int, batch_id: int, db: Session) -> CaseImport:
    batch = db.scalar(
        select(CaseImport).where(CaseImport.project_id == project_id, CaseImport.id == batch_id)
    )
    if batch is None:
        raise AppError(404, "case_import_not_found")
    return batch


def import_info(project_id: int, batch_id: int, actor: UserAccount, db: Session) -> dict:
    access(project_id, actor, db, lock=True)
    batch = own_import(project_id, batch_id, db)
    return {
        "id": batch.id,
        "filename": batch.filename,
        "preview_revision": batch.preview_revision,
        "committed": batch.committed,
    }


async def upload_import(
    project_id: int,
    payload: ImportUpload,
    chunks: AsyncIterator[bytes],
    actor: UserAccount,
    db: Session,
) -> dict:
    access(project_id, actor, db)
    actor_id = actor.id
    db.rollback()
    extension = payload.filename.rsplit(".", 1)[-1].lower()
    if extension not in ("xlsx", "xls", "csv"):
        raise AppError(422, "case_import_format")
    root = Settings().document_storage_path.resolve() / "case-imports"
    key = uuid4().hex
    staging = root / (key + ".part")
    target = root / key
    try:
        root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with staging.open("xb") as stream:
            async for chunk in chunks:
                size += len(chunk)
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if not size:
            raise AppError(422, "document_empty")
        raw = read_import(staging, extension)
        if not raw["sheets"]:
            raise AppError(422, "case_import_empty")
        actor = db.get(UserAccount, actor_id, populate_existing=True)
        if actor is None:
            raise AppError(401, "not_authenticated")
        lock(project_id, actor, db)
        old = db.scalar(
            select(CaseImport).where(
                CaseImport.project_id == project_id,
                CaseImport.request_id == str(payload.request_id),
            )
        )
        if old:
            if old.sha256 != digest.hexdigest() or old.filename != payload.filename:
                raise AppError(409, "case_import_conflict")
            return import_info(project_id, old.id, actor, db)
        batch = CaseImport(
            project_id=project_id,
            filename=payload.filename,
            storage_key=key,
            sha256=digest.hexdigest(),
            request_id=str(payload.request_id),
            raw_data=raw,
            created_by=actor.id,
        )
        db.add(batch)
        db.flush()
        os.replace(staging, target)
        db.commit()
        return import_info(project_id, batch.id, actor, db)
    except OSError:
        db.rollback()
        raise AppError(503, "document_storage_unavailable") from None
    finally:
        staging.unlink(missing_ok=True)


def signature(values: dict) -> tuple:
    return tuple(values.get(f, "") for f in DESIGN_FIELDS)


def review_import(
    project_id: int, batch_id: int, payload: ImportReview, actor: UserAccount, db: Session
) -> dict:
    library = lock(project_id, actor, db)
    batch = own_import(project_id, batch_id, db)
    if batch.committed:
        raise AppError(409, "case_import_committed")
    if batch.preview_revision != payload.preview_revision:
        raise AppError(409, "case_preview_changed")
    if batch.raw_data.get("parser_version") != 2:
        # Repair old parsed snapshots on explicit recheck; keep the uploaded original unchanged.
        batch.raw_data = read_import(import_path(batch), batch.filename.rsplit(".", 1)[-1].lower())
    category(project_id, payload.category_id, db)
    existing = {}
    for row in db.execute(case_query(project_id)).mappings():
        value = dict(row)
        existing.setdefault(signature(value), []).append(value)
    seen, items, errors, warnings, summaries = {}, [], [], [], []
    skipped = 0
    for sheet_index, sheet in enumerate(batch.raw_data["sheets"]):
        raw = sheet["rows"]
        nonempty = [i for i, row in enumerate(raw) if any(v.strip() for v in row)]
        if not nonempty:
            continue
        header_index = nonempty[0]
        headers = [v.strip() for v in raw[header_index]]
        mapped = {}
        for key, name in COLUMNS:
            positions = [i for i, value in enumerate(headers) if value == name]
            if len(positions) > 1:
                errors.append(
                    {
                        "sheet": sheet["name"],
                        "row": header_index + 1,
                        "field": key,
                        "message": "表头重复，请修改原文件",
                    }
                )
            if positions:
                mapped[key] = positions[0]
        if not set(mapped) - {"serial", "number"}:
            errors.append(
                {
                    "sheet": sheet["name"],
                    "row": header_index + 1,
                    "field": "header",
                    "message": "未识别到用例业务表头，请使用标准列名",
                }
            )
            continue
        summaries.append({"name": sheet["name"], "header_row": header_index + 1})
        formulas = {tuple(c) for c in sheet["formulas"]}
        for row_index, row in enumerate(raw[header_index + 1 :], header_index + 1):
            if not any(v.strip() for v in row):
                continue
            values = {key: row[col] if col < len(row) else "" for key, col in mapped.items()}
            if not any(v.strip() for key, v in values.items() if key not in ("serial", "number")):
                skipped += 1
                continue
            row_key = f"{sheet_index}:{row_index + 1}"
            location = {"sheet": sheet["name"], "row": row_index + 1}
            row_errors = []
            for field, col in mapped.items():
                if field == "serial":
                    continue
                if (row_index, col) in formulas:
                    row_errors.append({**location, "field": field, "message": "公式需先转换为值"})
                if any(
                    r1 <= row_index < r2 and c1 <= col < c2 for r1, c1, r2, c2 in sheet["merges"]
                ):
                    row_errors.append(
                        {**location, "field": field, "message": "合并单元格需拆开填写"}
                    )
            try:
                parsed = CaseInput(
                    **{k: v for k, v in values.items() if k not in ("serial", "number")},
                    revision=0,
                    request_id=uuid4(),
                )
            except ValidationError as exc:
                for err in exc.errors(include_input=False):
                    field = str(err["loc"][0])
                    row_errors.append(
                        {
                            **location,
                            "field": field,
                            "message": f"非法值：{values.get(field, '')[:100]}，请修改原文件",
                        }
                    )
                errors.extend(row_errors)
                continue
            errors.extend(row_errors)
            content = {f: getattr(parsed, f) for f in DESIGN_FIELDS}
            key = signature(content)
            matches = existing.get(key, [])
            prior = seen.get(key)
            if prior and not matches:
                errors.append(
                    {
                        **location,
                        "field": "title",
                        "message": f"文件内重复：{prior['sheet']} 第{prior['row']}行，请修改原文件",
                    }
                )
            seen.setdefault(key, location)
            if parsed.result not in ("", "未测") and not parsed.tester:
                warnings.append(
                    {**location, "field": "tester", "message": "未填写测试人员，保留为空"}
                )
            items.append(
                {
                    "key": row_key,
                    **location,
                    "values": {**content, "result": parsed.result, "tester": parsed.tester},
                    "matches": matches[:20],
                    "match_count": len(matches),
                    "source": {
                        **location,
                        "original_serial": values.get("serial", ""),
                        "original_number": values.get("number", ""),
                        "original_result": values.get("result", ""),
                    },
                }
            )
    if not items and not errors:
        errors.append(
            {"sheet": "", "row": 0, "field": "file", "message": "文件中没有可导入的用例内容"}
        )
    batch.preview = {
        "mode": "automatic-v3",
        "items": items,
        "errors": errors,
        "warnings": warnings,
        "skipped": skipped,
        "category_id": payload.category_id,
        "sheets": summaries,
        "total": len(items),
        "duplicate_count": sum(bool(i["matches"]) for i in items),
    }
    batch.preview_revision += 1
    batch.library_revision = library.revision
    db.commit()
    return preview_response(batch)


def preview_response(batch: CaseImport) -> dict:
    return {
        **batch.preview,
        "preview_revision": batch.preview_revision,
        "revision": batch.library_revision,
        "committed": batch.committed,
    }


def confirm_import(
    project_id: int, batch_id: int, payload: ImportConfirm, actor: UserAccount, db: Session
) -> dict:
    library = lock(project_id, actor, db)
    batch = own_import(project_id, batch_id, db)
    if batch.committed:
        return {"count": batch.preview.get("imported_count", 0), "already_committed": True}
    if payload.preview_revision != batch.preview_revision:
        raise AppError(409, "case_preview_changed")
    if payload.revision != library.revision or batch.library_revision != library.revision:
        raise AppError(409, "cases_changed")
    data = batch.preview
    if not data or data.get("mode") != "automatic-v3":
        raise AppError(409, "case_preview_changed")
    if data["errors"]:
        raise AppError(422, "case_import_has_errors")
    duplicates = {item["key"] for item in data["items"] if item["matches"]}
    if set(payload.duplicate_decisions) != duplicates:
        raise AppError(422, "case_import_duplicate_decisions")
    category(project_id, data["category_id"], db)
    count = 0
    for item in data["items"]:
        if payload.duplicate_decisions.get(item["key"]) == "skip":
            continue
        values = item["values"]
        design = CaseDesign(**{f: values[f] for f in DESIGN_FIELDS})
        insert_case(
            project_id,
            library,
            design,
            actor,
            db,
            category_id=data["category_id"],
            request_id=str(uuid4()),
            result=values["result"],
            tester=values["tester"],
            import_id=batch.id,
            source=item["source"],
        )
        count += 1
    batch.preview = {
        **data,
        "imported_count": count,
        "duplicate_decisions": payload.duplicate_decisions,
    }
    batch.committed = True
    batch.confirmed_by = actor.id
    library.revision += 1
    db.commit()
    return {"count": count, "already_committed": False}
