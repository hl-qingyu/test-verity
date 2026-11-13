from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.api.dependencies import DB, Actor, check_origin
from app.modules.documents import service
from app.modules.documents.schemas import (
    DeleteInput,
    GroupInput,
    LinkBindingInput,
    MoveInput,
    ReorderInput,
    UploadInput,
)

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["documents"])


@router.get("")
def list_documents(project_id: int, actor: Actor, db: DB, include_prototypes: bool = False) -> dict:
    return service.list_documents(
        project_id, actor, db, None if include_prototypes else "REQUIREMENT"
    )


@router.post("/groups", dependencies=[Depends(check_origin)], status_code=201)
def create_group(project_id: int, payload: GroupInput, actor: Actor, db: DB) -> dict:
    return service.create_group(project_id, payload, actor, db)


@router.post("/upload", dependencies=[Depends(check_origin)], status_code=201)
async def upload(
    project_id: int, request: Request, actor: Actor, db: DB, payload: UploadInput = Query()
) -> dict:
    return await service.upload(project_id, payload, request.stream(), actor, db)


@router.patch("/groups/{group_id}", dependencies=[Depends(check_origin)])
def rename_group(project_id: int, group_id: int, payload: GroupInput, actor: Actor, db: DB) -> dict:
    return service.rename_group(project_id, group_id, payload, actor, db)


@router.post("/move", dependencies=[Depends(check_origin)])
def move(project_id: int, payload: MoveInput, actor: Actor, db: DB) -> dict:
    return service.move(project_id, payload, actor, db)


@router.post("/reorder", dependencies=[Depends(check_origin)])
def reorder(project_id: int, payload: ReorderInput, actor: Actor, db: DB) -> dict:
    return service.reorder(project_id, payload, actor, db)


@router.get("/{document_id}/versions")
def versions(project_id: int, document_id: int, actor: Actor, db: DB) -> list[dict]:
    return service.versions(project_id, document_id, actor, db)


@router.get("/versions/{version_id}/preview")
def preview(project_id: int, version_id: int, actor: Actor, db: DB) -> dict:
    return service.preview(project_id, version_id, actor, db)


@router.get("/versions/{version_id}/file")
def download(
    project_id: int, version_id: int, actor: Actor, db: DB, inline: bool = False
) -> FileResponse:
    path, row = service.stored_version(project_id, version_id, actor, db)
    return FileResponse(
        path,
        media_type=row.media_type,
        filename=row.filename,
        content_disposition_type="inline"
        if inline and (row.media_type.startswith("image/") or row.extension == "pdf")
        else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/versions/{version_id}/browser", response_class=HTMLResponse)
def browser_preview(project_id: int, version_id: int, actor: Actor, db: DB) -> HTMLResponse:
    return HTMLResponse(
        service.html_preview(project_id, version_id, actor, db),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
                "base-uri 'none'; form-action 'none'"
            ),
        },
    )


@router.get("/versions/{version_id}/links")
def list_links(project_id: int, version_id: int, actor: Actor, db: DB) -> dict:
    return service.list_links(project_id, version_id, actor, db)


@router.post("/versions/{version_id}/links", dependencies=[Depends(check_origin)])
def bind_link(
    project_id: int, version_id: int, payload: LinkBindingInput, actor: Actor, db: DB
) -> dict:
    return service.bind_link(project_id, version_id, payload, actor, db)


@router.get("/{document_id}/deletion")
def deletion_info(project_id: int, document_id: int, actor: Actor, db: DB) -> dict:
    return service.deletion_info(project_id, document_id, actor, db, "REQUIREMENT")


@router.post("/{document_id}/delete", dependencies=[Depends(check_origin)])
def delete_document(
    project_id: int, document_id: int, payload: DeleteInput, actor: Actor, db: DB
) -> dict:
    return service.delete_document(project_id, document_id, payload, actor, db, "REQUIREMENT")
