from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from app.api.dependencies import DB, Actor, check_origin
from app.modules.cases import service
from app.modules.cases.schemas import (
    AssignCategory,
    BatchEdit,
    CaseInput,
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

router = APIRouter(prefix="/api/projects/{project_id}/cases", tags=["cases"])


@router.get("/metadata")
def metadata(project_id: int, actor: Actor, db: DB) -> dict:
    return service.metadata(project_id, actor, db)


@router.post("/search")
def search(project_id: int, payload: Search, actor: Actor, db: DB) -> dict:
    return service.list_cases(project_id, payload, actor, db)


@router.post("/edit-scope")
def edit_scope(project_id: int, payload: EditScope, actor: Actor, db: DB) -> dict:
    return service.edit_scope(project_id, payload, actor, db)


@router.post("/batch-edit", dependencies=[Depends(check_origin)])
def batch_edit(project_id: int, payload: BatchEdit, actor: Actor, db: DB) -> dict:
    return service.batch_edit(project_id, payload, actor, db)


@router.post("/{case_id}/delete", dependencies=[Depends(check_origin)])
def delete_case(project_id: int, case_id: int, payload: DeleteCase, actor: Actor, db: DB) -> dict:
    return service.delete_case(project_id, case_id, payload, actor, db)


@router.post("/{case_id}/lifecycle", dependencies=[Depends(check_origin)])
def lifecycle(project_id: int, case_id: int, payload: LifecycleInput, actor: Actor, db: DB):
    return service.change_lifecycle(project_id, case_id, payload, actor, db)


@router.post("/categories", dependencies=[Depends(check_origin)], status_code=201)
def create_category(project_id: int, payload: CategoryInput, actor: Actor, db: DB) -> dict:
    return service.save_category(project_id, None, payload, actor, db)


@router.patch("/categories/{category_id}", dependencies=[Depends(check_origin)])
def edit_category(
    project_id: int, category_id: int, payload: CategoryInput, actor: Actor, db: DB
) -> dict:
    return service.save_category(project_id, category_id, payload, actor, db)


@router.post("/categories/{category_id}/delete", dependencies=[Depends(check_origin)])
def delete_category(
    project_id: int, category_id: int, payload: DeleteCategory, actor: Actor, db: DB
) -> dict:
    return service.delete_category(project_id, category_id, payload, actor, db)


@router.post("/assign-category", dependencies=[Depends(check_origin)])
def assign_category(project_id: int, payload: AssignCategory, actor: Actor, db: DB) -> dict:
    return service.assign_category(project_id, payload, actor, db)


@router.post("", dependencies=[Depends(check_origin)], status_code=201)
def create_case(project_id: int, payload: CaseInput, actor: Actor, db: DB) -> dict:
    return service.save_case(project_id, None, payload, actor, db)


@router.get("/{case_id}")
def detail(project_id: int, case_id: int, actor: Actor, db: DB) -> dict:
    return service.detail(project_id, case_id, actor, db)


@router.patch("/{case_id}", dependencies=[Depends(check_origin)])
def update_case(project_id: int, case_id: int, payload: CaseInput, actor: Actor, db: DB) -> dict:
    return service.save_case(project_id, case_id, payload, actor, db)


@router.post("/export", dependencies=[Depends(check_origin)])
def export_cases(project_id: int, payload: Search, actor: Actor, db: DB) -> Response:
    return Response(
        service.export_cases(project_id, payload, actor, db),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="test-cases.xlsx"'},
    )


@router.post("/imports", dependencies=[Depends(check_origin)], status_code=201)
async def upload_import(
    project_id: int, request: Request, actor: Actor, db: DB, payload: ImportUpload = Query()
) -> dict:
    return await service.upload_import(project_id, payload, request.stream(), actor, db)


@router.get("/imports/{batch_id}/source")
def import_source(project_id: int, batch_id: int, actor: Actor, db: DB) -> FileResponse:
    service.access(project_id, actor, db)
    batch = service.own_import(project_id, batch_id, db)
    return FileResponse(
        service.import_path(batch),
        filename=batch.filename,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/imports/{batch_id}")
def import_info(project_id: int, batch_id: int, actor: Actor, db: DB) -> dict:
    return service.import_info(project_id, batch_id, actor, db)


@router.post("/imports/{batch_id}/review", dependencies=[Depends(check_origin)])
def review_import(
    project_id: int, batch_id: int, payload: ImportReview, actor: Actor, db: DB
) -> dict:
    return service.review_import(project_id, batch_id, payload, actor, db)


@router.post("/imports/{batch_id}/confirm", dependencies=[Depends(check_origin)])
def confirm_import(
    project_id: int, batch_id: int, payload: ImportConfirm, actor: Actor, db: DB
) -> dict:
    return service.confirm_import(project_id, batch_id, payload, actor, db)
