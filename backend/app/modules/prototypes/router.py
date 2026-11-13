from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from app.api.dependencies import DB, Actor, check_origin
from app.modules.documents import service as documents
from app.modules.documents.schemas import DeleteInput, GroupInput, MoveInput, ReorderInput
from app.modules.prototypes import directories, service
from app.modules.prototypes.schemas import CheckInput, GitScope, ImageUpload, LiveInput

router = APIRouter(prefix="/api/projects/{project_id}/prototypes", tags=["prototypes"])


@router.post("/directories", dependencies=[Depends(check_origin)], status_code=201)
async def upload_directory(
    project_id: int, request: Request, actor: Actor, db: DB, payload: ImageUpload = Query()
) -> dict:
    await directories.upload(project_id, None, payload, request.stream(), actor, db)
    return service.state(project_id, actor, db)


@router.post(
    "/directories/{source_id}/versions", dependencies=[Depends(check_origin)], status_code=201
)
async def directory_version(
    project_id: int,
    source_id: int,
    request: Request,
    actor: Actor,
    db: DB,
    payload: ImageUpload = Query(),
) -> dict:
    await directories.upload(project_id, source_id, payload, request.stream(), actor, db)
    return service.state(project_id, actor, db)


@router.get("/directories/{source_id}/versions/{version_id}/files")
def directory_files(project_id: int, source_id: int, version_id: int, actor: Actor, db: DB) -> dict:
    return directories.catalog(project_id, source_id, version_id, actor, db)


@router.get("/directories/{source_id}/versions/{version_id}/archive")
def directory_archive(
    project_id: int, source_id: int, version_id: int, actor: Actor, db: DB
) -> StreamingResponse:
    return StreamingResponse(
        directories.download(project_id, source_id, version_id, actor, db),
        media_type="application/x-tar",
        headers={
            "Content-Disposition": f'attachment; filename="prototype-directory-v{version_id}.tar"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/directories/{source_id}/versions/{version_id}/file")
def directory_file(
    project_id: int,
    source_id: int,
    version_id: int,
    path: str,
    actor: Actor,
    db: DB,
    inline: bool = False,
) -> FileResponse:
    stored, entry = directories.get_file(project_id, source_id, version_id, path, actor, db)
    return FileResponse(
        stored,
        filename=entry["path"].rsplit("/", 1)[-1],
        media_type="image/"
        + ("jpeg" if entry["extension"] in {"jpg", "jpeg"} else entry["extension"])
        if entry["extension"] in directories.IMAGES
        else "text/plain",
        content_disposition_type="inline"
        if inline and entry["extension"] in directories.IMAGES
        else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/directories/{source_id}/versions/{version_id}/preview")
def directory_preview(
    project_id: int, source_id: int, version_id: int, path: str, actor: Actor, db: DB
) -> dict:
    return directories.preview(project_id, source_id, version_id, path, actor, db)


@router.get("/directories/{source_id}/versions/{version_id}/browser", response_class=HTMLResponse)
def directory_browser(
    project_id: int, source_id: int, version_id: int, path: str, actor: Actor, db: DB
) -> HTMLResponse:
    return HTMLResponse(
        directories.html_preview(project_id, source_id, version_id, path, actor, db),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline' data:; "
                "style-src 'unsafe-inline' data:; img-src data: blob:; font-src data:; "
                "base-uri 'none'; form-action 'none'"
            ),
        },
    )


@router.get("")
def state(project_id: int, actor: Actor, db: DB) -> dict:
    return service.state(project_id, actor, db)


@router.get("/options")
def options(project_id: int, actor: Actor, db: DB) -> list[dict]:
    return service.options(project_id, actor, db)


@router.post("/groups", dependencies=[Depends(check_origin)], status_code=201)
def group(project_id: int, payload: GroupInput, actor: Actor, db: DB) -> dict:
    documents.create_group(project_id, payload, actor, db, "PROTOTYPE")
    return service.state(project_id, actor, db)


@router.patch("/groups/{group_id}", dependencies=[Depends(check_origin)])
def rename(project_id: int, group_id: int, payload: GroupInput, actor: Actor, db: DB) -> dict:
    documents.rename_group(project_id, group_id, payload, actor, db, "PROTOTYPE")
    return service.state(project_id, actor, db)


@router.post("/move", dependencies=[Depends(check_origin)])
def move(project_id: int, payload: MoveInput, actor: Actor, db: DB) -> dict:
    documents.move(project_id, payload, actor, db, "PROTOTYPE")
    return service.state(project_id, actor, db)


@router.post("/reorder", dependencies=[Depends(check_origin)])
def reorder(project_id: int, payload: ReorderInput, actor: Actor, db: DB) -> dict:
    documents.reorder(project_id, payload, actor, db, "PROTOTYPE")
    return service.state(project_id, actor, db)


@router.post("/upload", dependencies=[Depends(check_origin)], status_code=201)
async def upload(
    project_id: int, request: Request, actor: Actor, db: DB, payload: ImageUpload = Query()
) -> dict:
    await documents.upload(
        project_id,
        payload,
        request.stream(),
        actor,
        db,
        "PROTOTYPE",
        payload.name,
        payload.description,
    )
    return service.state(project_id, actor, db)


@router.post("/scope", dependencies=[Depends(check_origin)])
def scope(project_id: int, payload: GitScope, actor: Actor, db: DB) -> dict:
    return service.read_scope(project_id, payload, actor, db)


@router.post("", dependencies=[Depends(check_origin)], status_code=201)
def create(project_id: int, payload: LiveInput, actor: Actor, db: DB) -> dict:
    return service.save_live(project_id, None, payload, actor, db)


@router.patch("/{source_id}", dependencies=[Depends(check_origin)])
def edit(project_id: int, source_id: int, payload: LiveInput, actor: Actor, db: DB) -> dict:
    return service.save_live(project_id, source_id, payload, actor, db)


@router.post("/{source_id}/check", dependencies=[Depends(check_origin)])
def check(project_id: int, source_id: int, payload: CheckInput, actor: Actor, db: DB) -> dict:
    return service.check(project_id, source_id, payload.connection_id, actor, db)


@router.get("/{source_id}/pages")
def pages(project_id: int, source_id: int, actor: Actor, db: DB) -> dict:
    return service.link_catalog(project_id, source_id, actor, db)


@router.get("/{document_id}/deletion")
def deletion_info(project_id: int, document_id: int, actor: Actor, db: DB) -> dict:
    return documents.deletion_info(project_id, document_id, actor, db, "PROTOTYPE")


@router.post("/{document_id}/delete", dependencies=[Depends(check_origin)])
def delete_document(
    project_id: int, document_id: int, payload: DeleteInput, actor: Actor, db: DB
) -> dict:
    return documents.delete_document(project_id, document_id, payload, actor, db, "PROTOTYPE")
