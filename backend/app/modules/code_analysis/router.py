from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response

from app.api.dependencies import DB, Actor, check_origin
from app.modules.candidate_results.schemas import CandidateReviewInput
from app.modules.code_analysis import candidate_review, chat, export, schemas, service
from app.modules.projects import record_deletion

router = APIRouter(prefix="/api/projects/{project_id}/code-analysis", tags=["code-analysis"])


@router.get("")
def listing(project_id: int, actor: Actor, db: DB, page: int = Query(1, ge=1)):
    return service.listing(project_id, actor, db, page)


@router.get("/options")
def options(project_id: int, actor: Actor, db: DB):
    return service.options(project_id, actor, db)


@router.get("/github-scope")
def github_scope(
    project_id: int, repository_id: int, connection_id: int, branch: str, actor: Actor, db: DB
):
    return service.github_scope(project_id, repository_id, connection_id, branch, actor, db)


@router.post("", dependencies=[Depends(check_origin)], status_code=202)
async def enqueue(project_id: int, request: Request, actor: Actor, db: DB):
    payload = await service.read_payload(request.stream(), schemas.CodeAnalysisRequest)
    return service.enqueue(project_id, payload, actor, db)


@router.get("/github-file")
def github_file(
    project_id: int,
    repository_id: int,
    connection_id: int,
    commit: str,
    path: str,
    actor: Actor,
    db: DB,
):
    return service.github_file(project_id, repository_id, connection_id, commit, path, actor, db)


@router.post("/import", dependencies=[Depends(check_origin)], status_code=201)
async def import_report(project_id: int, request: Request, actor: Actor, db: DB):
    return await service.import_report(project_id, request.stream(), actor, db)


@router.get("/{task_id}/candidate")
def candidate(project_id: int, task_id: int, actor: Actor, db: DB):
    path = export.candidate(project_id, task_id, actor, db)
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=f"code-analysis-{task_id}-ai-candidate.txt",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{task_id}")
def detail(project_id: int, task_id: int, actor: Actor, db: DB):
    return service.detail(project_id, task_id, actor, db)


@router.post("/{task_id}/cancel", dependencies=[Depends(check_origin)])
def cancel(project_id: int, task_id: int, actor: Actor, db: DB):
    return service.cancel(project_id, task_id, actor, db)


@router.post("/{task_id}/retry", dependencies=[Depends(check_origin)], status_code=202)
def retry(project_id: int, task_id: int, payload: schemas.RetryRequest, actor: Actor, db: DB):
    return service.retry(project_id, task_id, payload, actor, db)


@router.post("/{task_id}/revalidate", dependencies=[Depends(check_origin)])
def revalidate(project_id: int, task_id: int, actor: Actor, db: DB):
    return service.revalidate_candidate(project_id, task_id, actor, db)


@router.post("/{task_id}/handling", dependencies=[Depends(check_origin)])
def handling(project_id: int, task_id: int, payload: schemas.HandlingRequest, actor: Actor, db: DB):
    return service.handle_finding(project_id, task_id, payload, actor, db)


@router.get("/{task_id}/export")
def export_report(
    project_id: int,
    task_id: int,
    actor: Actor,
    db: DB,
    format: str = Query("markdown", pattern="^(markdown|input|report)$"),
):
    body, media, extension = export.download(project_id, task_id, format, actor, db)
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": (
                f'attachment; filename="code-analysis-{task_id}-{format}.{extension}"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/{task_id}/chat")
def chat_list(
    project_id: int, task_id: int, actor: Actor, db: DB, before: int | None = Query(None, gt=0)
):
    return chat.listing(project_id, task_id, actor, db, before)


@router.post("/{task_id}/chat", dependencies=[Depends(check_origin)], status_code=202)
def chat_enqueue(project_id: int, task_id: int, payload: schemas.ChatRequest, actor: Actor, db: DB):
    return chat.enqueue(project_id, task_id, payload, actor, db)


@router.post("/{task_id}/chat/{turn_id}/cancel", dependencies=[Depends(check_origin)])
def chat_cancel(project_id: int, task_id: int, turn_id: int, actor: Actor, db: DB):
    return chat.cancel(project_id, task_id, turn_id, actor, db)


@router.get("/{task_id}/deletion")
def deletion_code(project_id: int, task_id: int, actor: Actor, db: DB):
    return record_deletion.info(project_id, "code", task_id, actor, db)


@router.post("/{task_id}/delete", dependencies=[Depends(check_origin)])
def delete_code(
    project_id: int, task_id: int, payload: record_deletion.DeleteRequest, actor: Actor, db: DB
):
    return record_deletion.remove(project_id, "code", task_id, payload, actor, db)


@router.get("/{task_id}/candidate-review")
def candidate_review_get(project_id: int, task_id: int, actor: Actor, db: DB):
    return candidate_review.review(project_id, task_id, actor, db)


@router.post("/{task_id}/candidate-review", dependencies=[Depends(check_origin)])
def candidate_review_save(
    project_id: int, task_id: int, payload: CandidateReviewInput, actor: Actor, db: DB
):
    return candidate_review.review(project_id, task_id, actor, db, payload)
