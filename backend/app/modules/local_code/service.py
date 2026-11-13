from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import LocalCodeSource, UserAccount
from app.modules.local_code.schemas import SourceInput, SourceView
from app.modules.projects.service import access_project


def list_sources(project_id: int, actor: UserAccount, db: Session) -> list[SourceView]:
    access_project(project_id, actor, db)
    return [
        SourceView.model_validate(row)
        for row in db.scalars(
            select(LocalCodeSource)
            .where(LocalCodeSource.project_id == project_id)
            .order_by(LocalCodeSource.id)
        )
    ]


def save_source(
    project_id: int, payload: SourceInput, actor: UserAccount, db: Session
) -> SourceView:
    access_project(project_id, actor, db, write=True, lock=True)
    row = db.scalar(
        select(LocalCodeSource).where(
            LocalCodeSource.project_id == project_id,
            LocalCodeSource.owner_id == actor.id,
            LocalCodeSource.client_id == str(payload.client_id),
        )
    )
    if row is None:
        if payload.version != 0:
            raise AppError(409, "local_code_changed")
        row = LocalCodeSource(
            project_id=project_id, owner_id=actor.id, client_id=str(payload.client_id)
        )
        db.add(row)
    else:
        identical = all(
            getattr(row, key) == getattr(payload, key) for key in ("name", "directory_name", "kind")
        )
        if payload.version == 0 and identical:
            return SourceView.model_validate(row)
        if row.version != payload.version:
            raise AppError(409, "local_code_changed")
        # A binding identifies one directory; reauthorizing another requires a new source.
        if row.directory_name != payload.directory_name:
            raise AppError(409, "local_code_directory_changed")
        row.version += 1
    row.name, row.directory_name, row.kind = payload.name, payload.directory_name, payload.kind
    db.commit()
    return SourceView.model_validate(row)
