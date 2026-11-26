"""Common binding and transport operations for analysis-owned Codex terminals."""

from uuid import uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import ai_client, codex_terminal

TERMINAL_KEY = "analysis_terminal"


def new_binding(execution: int = -1) -> dict:
    return {"identity": str(uuid4()), "execution": execution, "version": 1}


def bind_snapshot(config: dict) -> dict:
    if config.get("call_mode") == "CODEX_EXEC":
        return {**config, TERMINAL_KEY: new_binding()}
    return config


def public_snapshot(config: dict) -> dict:
    return {key: value for key, value in config.items() if key != TERMINAL_KEY}


def available(config: dict, owner_id: int, viewer_id: int) -> bool:
    return owner_id == viewer_id and bool(config.get(TERMINAL_KEY))


def analysis_options(config: dict) -> dict:
    spec = config.get(TERMINAL_KEY)
    return {"terminal_spec": spec} if spec else {}


def enabled_for(owner_id: int) -> bool:
    users = Settings().ai_cli_terminal_user_ids
    return users is None or owner_id in users


def session_view(row: dict, *, kind: str) -> dict:
    terminal = row["terminal"]
    return {
        "id": row["id"],
        "status": row["status"],
        "error_code": row["error_code"],
        "kind": kind,
        "epoch": row.get("request_id", str(row["id"])),
        "replay_rows": terminal.get("rows", 30),
        "replay_cols": terminal.get("cols", 110),
        **codex_terminal.turn_state(terminal["identity"], terminal.get("execution", row["id"])),
    }


def resume_session(config, secret, binding, check, *, legacy_context=None, legacy_instructions=""):
    """Resume the bound thread and run the caller's final permission/result check."""
    options = {}
    if binding.get("thread_id"):
        options["resume_thread"] = binding["thread_id"]
    if legacy_context is not None:
        options.update(fixed_input=legacy_context, instructions=legacy_instructions)
    result = ai_client.terminal(
        config["base_url"],
        config["model"],
        secret,
        config["reasoning_effort"],
        identity=binding["identity"],
        execution=binding["execution"],
        resume=True,
        rows=binding["rows"],
        cols=binding["cols"],
        on_progress=check,
        **options,
    )
    check(force=True)
    return result


def bound_output(bound: dict, cursor: int) -> dict:
    return codex_terminal.output(bound["identity"], bound["execution"], cursor)


def write_command(bound: dict, payload, *, enabled: bool) -> None:
    if not enabled:
        raise AppError(403, "generation_terminal_permission_required")
    if bound.get("readonly"):
        raise AppError(409, "generation_terminal_not_started")
    codex_terminal.put_command(
        bound["identity"], bound["execution"], payload.model_dump(exclude_none=True)
    )


def bound_input(bound: dict, payload) -> None:
    write_command(bound, payload, enabled=enabled_for(bound["owner_id"]))
