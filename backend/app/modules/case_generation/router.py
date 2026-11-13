import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response

from app.api.dependencies import DB, Actor, check_origin
from app.modules.case_generation import (
    apply,
    candidate_review,
    chat,
    execution,
    imports,
    schemas,
    service,
)
from app.modules.projects import record_deletion

router = APIRouter(prefix="/api/projects/{project_id}/case-generation", tags=["case-generation"])


@router.get("")
def listing(
    project_id: int,
    actor: Actor,
    db: DB,
    page: int = Query(1, ge=1),
    summary: bool = False,
    run_id: int | None = Query(None, ge=1),
):
    if summary and run_id is not None:
        return service.read_summary(project_id, run_id, actor, db)
    return service.listing(project_id, actor, db, page, summary)


@router.post("/prepare", dependencies=[Depends(check_origin)], status_code=201)
def prepare(project_id: int, payload: schemas.Prepare, actor: Actor, db: DB):
    return service.prepare(project_id, payload, actor, db)


@router.post("/import", dependencies=[Depends(check_origin)], status_code=201)
async def import_report(project_id: int, request: Request, actor: Actor, db: DB):
    payload = await service.read_payload(request.stream(), schemas.Import)
    return imports.import_report(project_id, payload, actor, db)


@router.get("/{run_id}")
def detail(project_id: int, run_id: int, actor: Actor, db: DB):
    return service.detail(project_id, run_id, actor, db)


@router.post("/{run_id}/start", dependencies=[Depends(check_origin)], status_code=202)
def start(project_id: int, run_id: int, payload: schemas.Confirm, actor: Actor, db: DB):
    return service.start(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/cancel", dependencies=[Depends(check_origin)])
def cancel(project_id: int, run_id: int, actor: Actor, db: DB):
    return service.cancel(project_id, run_id, actor, db)


@router.post(
    "/{run_id}/batches/{batch_id}/retry", dependencies=[Depends(check_origin)], status_code=202
)
def retry(
    project_id: int, run_id: int, batch_id: int, payload: schemas.Retry, actor: Actor, db: DB
):
    return service.retry(project_id, run_id, batch_id, payload, actor, db)


@router.post("/{run_id}/batches/{batch_id}/revalidate", dependencies=[Depends(check_origin)])
def revalidate(project_id: int, run_id: int, batch_id: int, actor: Actor, db: DB):
    return execution.revalidate(project_id, run_id, batch_id, actor, db)


@router.get("/{run_id}/batches/{batch_id}/candidate")
def candidate(project_id: int, run_id: int, batch_id: int, actor: Actor, db: DB):
    return FileResponse(
        execution.candidate(project_id, run_id, batch_id, actor, db),
        filename=f"generation-batch-{batch_id}.txt",
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{run_id}/handling", dependencies=[Depends(check_origin)])
def handling(project_id: int, run_id: int, payload: schemas.Handling, actor: Actor, db: DB):
    return service.handle(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/decisions", dependencies=[Depends(check_origin)])
def decision(project_id: int, run_id: int, payload: schemas.Decision, actor: Actor, db: DB):
    return service.decide(project_id, run_id, payload, actor, db)


@router.post(
    "/{run_id}/batches/{batch_id}/candidate-issues/{issue_id}/resolve",
    dependencies=[Depends(check_origin)],
)
def resolve_candidate_issue(
    project_id: int,
    run_id: int,
    batch_id: int,
    issue_id: str,
    payload: schemas.CandidateResolution,
    actor: Actor,
    db: DB,
):
    return candidate_review.resolve(project_id, run_id, batch_id, issue_id, payload, actor, db)


@router.post("/{run_id}/supplement", dependencies=[Depends(check_origin)], status_code=201)
def supplement(project_id: int, run_id: int, payload: schemas.Supplement, actor: Actor, db: DB):
    return service.supplement(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/apply-preview", dependencies=[Depends(check_origin)])
def preview(project_id: int, run_id: int, payload: schemas.Preview, actor: Actor, db: DB):
    return apply.preview(project_id, run_id, payload.keys, actor, db)


@router.post("/{run_id}/applications", dependencies=[Depends(check_origin)])
def application(project_id: int, run_id: int, payload: schemas.Application, actor: Actor, db: DB):
    return apply.submit(project_id, run_id, payload, actor, db)


@router.get("/{run_id}/export")
def export(
    project_id: int,
    run_id: int,
    actor: Actor,
    db: DB,
    kind: str = Query("report", pattern="^(input|report|audit)$"),
):
    row = service.own(project_id, run_id, actor, db)
    value = (
        {
            "handling": row.handling,
            "metadata": row.metadata_snapshot,
            "batches": [
                {
                    "batch_ref": b.batch_ref,
                    "input": b.input_snapshot,
                    "report": b.report,
                    "attempts": b.attempts,
                    "ai": b.ai_config,
                }
                for b in service.batches(row, db)
            ],
        }
        if kind == "audit"
        else row.metadata_snapshot.get("original_" + kind) or service.bundle(row, db, kind)
    )
    return Response(
        json.dumps(value, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="generation-{run_id}-{kind}.json"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{run_id}/chat")
def chat_list(
    project_id: int,
    run_id: int,
    actor: Actor,
    db: DB,
    function_key: str = Query("", max_length=200),
    before: int | None = Query(None, gt=0),
):
    return chat.listing(project_id, run_id, function_key, actor, db, before)


@router.post("/{run_id}/chat", dependencies=[Depends(check_origin)], status_code=202)
def chat_send(project_id: int, run_id: int, payload: schemas.Chat, actor: Actor, db: DB):
    return chat.enqueue(project_id, run_id, payload, actor, db)


@router.post("/{run_id}/chat/{turn_id}/cancel", dependencies=[Depends(check_origin)])
def chat_cancel(project_id: int, run_id: int, turn_id: int, actor: Actor, db: DB):
    return chat.cancel(project_id, run_id, turn_id, actor, db)


@router.post(
    "/{run_id}/chat/{turn_id}/draft", dependencies=[Depends(check_origin)], status_code=201
)
def chat_draft(
    project_id: int, run_id: int, turn_id: int, payload: schemas.ChatDraft, actor: Actor, db: DB
):
    return chat.create_draft(project_id, run_id, turn_id, payload, actor, db)


@router.get("/{run_id}/deletion")
def deletion_generate(project_id: int, run_id: int, actor: Actor, db: DB):
    return record_deletion.info(project_id, "generate", run_id, actor, db)


@router.post("/{run_id}/delete", dependencies=[Depends(check_origin)])
def delete_generate(
    project_id: int, run_id: int, payload: record_deletion.DeleteRequest, actor: Actor, db: DB
):
    return record_deletion.remove(project_id, "generate", run_id, payload, actor, db)
