from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import DB, Actor, check_origin
from app.modules.candidate_results.schemas import CandidateReviewInput
from app.modules.case_analysis import apply, candidate_review, schemas, service
from app.modules.projects import record_deletion

router = APIRouter(prefix="/api/projects/{project_id}/case-analysis", tags=["case-analysis"])


@router.get("")
def listing(project_id: int, actor: Actor, db: DB, page: int = Query(1, ge=1)):
    return service.listing(project_id, actor, db, page)


@router.post("/prepare", dependencies=[Depends(check_origin)], status_code=201)
def prepare(project_id: int, payload: schemas.Prepare, actor: Actor, db: DB):
    return service.prepare(project_id, payload, actor, db)


@router.post("/import", dependencies=[Depends(check_origin)])
def import_report(project_id: int, payload: schemas.Import, actor: Actor, db: DB):
    return service.import_report(project_id, payload, actor, db)


@router.get("/{run_id}")
def detail(project_id: int, run_id: int, actor: Actor, db: DB, summary: bool = False):
    return (
        service.summary(project_id, run_id, actor, db)
        if summary
        else service.detail(project_id, run_id, actor, db)
    )


@router.post("/{run_id}/start", dependencies=[Depends(check_origin)], status_code=202)
def start(project_id: int, run_id: int, payload: schemas.Confirm, actor: Actor, db: DB):
    return service.start(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/cancel", dependencies=[Depends(check_origin)])
def cancel(project_id: int, run_id: int, actor: Actor, db: DB):
    return service.cancel(project_id, run_id, actor, db)


@router.post("/{run_id}/retry", dependencies=[Depends(check_origin)])
def retry(project_id: int, run_id: int, request_id: UUID, actor: Actor, db: DB):
    return service.retry(project_id, run_id, request_id, actor, db)


@router.post("/{run_id}/handling", dependencies=[Depends(check_origin)])
def handling(project_id: int, run_id: int, payload: schemas.Handling, actor: Actor, db: DB):
    return service.handling(project_id, run_id, payload, actor, db)


@router.get("/{run_id}/preview")
def preview(project_id: int, run_id: int, actor: Actor, db: DB):
    return apply.preview(project_id, run_id, actor, db)


@router.post("/{run_id}/apply", dependencies=[Depends(check_origin)], status_code=202)
def application(project_id: int, run_id: int, payload: schemas.Application, actor: Actor, db: DB):
    return apply.submit(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/chat", dependencies=[Depends(check_origin)], status_code=202)
def chat(project_id: int, run_id: int, payload: schemas.Chat, actor: Actor, db: DB):
    return service.chat(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/from-chat", dependencies=[Depends(check_origin)])
def from_chat(project_id: int, run_id: int, payload: schemas.FromChat, actor: Actor, db: DB):
    return service.from_chat(project_id, run_id, payload, actor, db)


@router.get("/{run_id}/deletion")
def deletion_coverage(project_id: int, run_id: int, actor: Actor, db: DB):
    return record_deletion.info(project_id, "coverage", run_id, actor, db)


@router.post("/{run_id}/delete", dependencies=[Depends(check_origin)])
def delete_coverage(
    project_id: int, run_id: int, payload: record_deletion.DeleteRequest, actor: Actor, db: DB
):
    return record_deletion.remove(project_id, "coverage", run_id, payload, actor, db)


@router.get("/{run_id}/candidate-review")
def candidate_review_get(project_id: int, run_id: int, actor: Actor, db: DB):
    return candidate_review.review(project_id, run_id, actor, db)


@router.post("/{run_id}/candidate-review", dependencies=[Depends(check_origin)])
def candidate_review_save(
    project_id: int, run_id: int, payload: CandidateReviewInput, actor: Actor, db: DB
):
    return candidate_review.review(project_id, run_id, actor, db, payload)
