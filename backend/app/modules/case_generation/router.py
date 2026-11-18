import json

from fastapi import APIRouter, Depends, Query, Request, WebSocket
from fastapi.responses import FileResponse, Response

from app.api.dependencies import DB, Actor, check_origin
from app.api.terminal_transport import check_terminal_origin
from app.api.terminal_transport import serve as serve_terminal
from app.modules.case_generation import (
    apply,
    candidate_review,
    chat,
    cli,
    execution,
    imports,
    native_results,
    native_terminal,
    schemas,
    service,
)
from app.modules.projects import record_deletion

router = APIRouter(prefix="/api/projects/{project_id}/case-generation", tags=["case-generation"])


@router.get("/{run_id}/terminal/results")
def native_results_list(project_id: int, run_id: int, actor: Actor, db: DB):
    return native_results.listing(project_id, run_id, actor, db)


@router.get("/{run_id}/terminal/results/{result_id}")
def native_result_preview(project_id: int, run_id: int, result_id: str, actor: Actor, db: DB):
    return native_results.preview(project_id, run_id, result_id, actor, db)


@router.post("/{run_id}/terminal/results/{result_id}/save", dependencies=[Depends(check_origin)])
def native_result_save(
    project_id: int,
    run_id: int,
    result_id: str,
    payload: schemas.TerminalResultSave,
    actor: Actor,
    db: DB,
):
    return native_results.save(project_id, run_id, result_id, payload, actor, db)


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


@router.get("/{run_id}/terminal")
def terminal_current(project_id: int, run_id: int, actor: Actor, db: DB):
    return native_terminal.current(project_id, run_id, actor, db)


@router.post("/{run_id}/terminal", dependencies=[Depends(check_terminal_origin)], status_code=202)
def terminal_start(
    project_id: int, run_id: int, payload: schemas.TerminalStart, actor: Actor, db: DB
):
    return native_terminal.start(project_id, run_id, payload, actor, db)


@router.get("/{run_id}/terminal/{turn_id}")
def terminal_read(
    project_id: int,
    run_id: int,
    turn_id: int,
    actor: Actor,
    db: DB,
    cursor: int = Query(0, ge=0, le=10000000),
):
    return native_terminal.read(project_id, run_id, turn_id, cursor, actor, db)


@router.websocket("/{run_id}/terminal/generation/{batch_id}/socket")
async def generation_terminal_socket(
    websocket: WebSocket, project_id: int, run_id: int, batch_id: int
):
    await serve_terminal(
        websocket,
        lambda actor, db: native_terminal.generation_binding(
            project_id, run_id, batch_id, actor, db
        ),
        native_terminal.bound_output,
        native_terminal.bound_input,
        schemas.TerminalInput,
    )


@router.websocket("/{run_id}/terminal/{turn_id}/socket")
async def terminal_socket(websocket: WebSocket, project_id: int, run_id: int, turn_id: int):
    await serve_terminal(
        websocket,
        lambda actor, db: native_terminal.binding(project_id, run_id, turn_id, actor, db),
        native_terminal.bound_output,
        native_terminal.bound_input,
        schemas.TerminalInput,
    )


@router.post("/{run_id}/terminal/{turn_id}/input", dependencies=[Depends(check_terminal_origin)])
def terminal_input(
    project_id: int, run_id: int, turn_id: int, payload: schemas.TerminalInput, actor: Actor, db: DB
):
    return native_terminal.write(project_id, run_id, turn_id, payload, actor, db)


@router.get("/{run_id}/batches/{batch_id}/cli-events")
def batch_cli_events(
    project_id: int,
    run_id: int,
    batch_id: int,
    actor: Actor,
    db: DB,
    cursor: int = Query(0, ge=0, le=1000000),
    attempt: int | None = Query(None, ge=0),
):
    return Response(
        content=json.dumps(
            cli.events(project_id, run_id, "batch", batch_id, actor, db, cursor, attempt)
        ),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{run_id}/chat/{turn_id}/cli-events")
def chat_cli_events(
    project_id: int,
    run_id: int,
    turn_id: int,
    actor: Actor,
    db: DB,
    cursor: int = Query(0, ge=0, le=1000000),
):
    return Response(
        content=json.dumps(cli.events(project_id, run_id, "chat", turn_id, actor, db, cursor)),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


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
