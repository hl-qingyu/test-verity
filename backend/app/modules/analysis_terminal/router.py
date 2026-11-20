from fastapi import APIRouter, Depends, WebSocket

from app.api.dependencies import DB, Actor
from app.api.terminal_transport import check_terminal_origin, serve
from app.modules.ai import native_terminal
from app.modules.ai.terminal_schemas import TerminalInput, TerminalStart
from app.modules.analysis_terminal import results, service
from app.modules.analysis_terminal.service import RecordKind

router = APIRouter(
    prefix="/api/projects/{project_id}/analysis-terminal/{kind}/{record_id}",
    tags=["analysis-terminal"],
)


@router.get("")
def current(project_id: int, kind: RecordKind, record_id: int, actor: Actor, db: DB):
    return service.current(project_id, kind, record_id, actor, db)


@router.post("", dependencies=[Depends(check_terminal_origin)], status_code=202)
def start(
    project_id: int, kind: RecordKind, record_id: int, payload: TerminalStart, actor: Actor, db: DB
):
    return service.start(project_id, kind, record_id, payload, actor, db)


@router.post("/{execution_id}/cancel", dependencies=[Depends(check_terminal_origin)])
def cancel(
    project_id: int, kind: RecordKind, record_id: int, execution_id: int, actor: Actor, db: DB
):
    return service.cancel(project_id, kind, record_id, execution_id, actor, db)


@router.get("/results")
def candidate_rounds(project_id: int, kind: RecordKind, record_id: int, actor: Actor, db: DB):
    return results.listing(project_id, kind, record_id, actor, db)


@router.get("/results/{result_id}")
def candidate_round(
    project_id: int, kind: RecordKind, record_id: int, result_id: str, actor: Actor, db: DB
):
    return results.preview(project_id, kind, record_id, result_id, actor, db)


@router.websocket("/generation/{execution_id}/socket")
async def initial_socket(
    ws: WebSocket, project_id: int, kind: RecordKind, record_id: int, execution_id: int
):
    await serve(
        ws,
        lambda actor, db: service.binding(
            project_id, kind, record_id, execution_id, actor, db, initial=True
        ),
        native_terminal.bound_output,
        native_terminal.bound_input,
        TerminalInput,
    )


@router.websocket("/{execution_id}/socket")
async def resume_socket(
    ws: WebSocket, project_id: int, kind: RecordKind, record_id: int, execution_id: int
):
    await serve(
        ws,
        lambda actor, db: service.binding(project_id, kind, record_id, execution_id, actor, db),
        native_terminal.bound_output,
        native_terminal.bound_input,
        TerminalInput,
    )
