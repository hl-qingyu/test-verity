"""Explicit transport selection; no database, preference lookup or fallback."""

from typing import Literal

from app.core.errors import AppError
from app.integrations import cli_results, codex_exec, responses
from app.integrations.call_control import CallControl

CallMode = Literal["RESPONSES_API", "CODEX_EXEC"]


def analyze(*args, call_mode: CallMode = "RESPONSES_API", **kwargs) -> str:
    control = CallControl(
        kwargs.pop("on_progress", None), keep_cli_on_outage=call_mode == "CODEX_EXEC"
    )
    if call_mode == "RESPONSES_API":
        return control.run(responses.analyze, *args, **kwargs)
    if call_mode == "CODEX_EXEC":
        terminal_spec = kwargs.pop("terminal_spec", None)
        if terminal_spec is not None:
            from app.integrations import codex_terminal

            return control.run(
                cli_results.run,
                codex_terminal.analyze,
                *args,
                terminal_spec=terminal_spec,
                **kwargs,
            )
        return control.run(cli_results.run, codex_exec.analyze, *args, **kwargs)
    raise AppError(422, "ai_call_mode_invalid")


def converse(*args, call_mode: CallMode = "RESPONSES_API", **kwargs) -> str:
    control = CallControl(
        kwargs.pop("on_progress", None), keep_cli_on_outage=call_mode == "CODEX_EXEC"
    )
    if call_mode == "RESPONSES_API":
        return control.run(responses.converse, *args, **kwargs)
    if call_mode == "CODEX_EXEC":
        return control.run(cli_results.run, codex_exec.converse, *args, **kwargs)
    raise AppError(422, "ai_call_mode_invalid")


def probe_model(*args, call_mode: CallMode = "RESPONSES_API") -> None:
    if call_mode == "RESPONSES_API":
        responses.probe_model(*args)
    elif call_mode == "CODEX_EXEC":
        codex_exec.probe_model(*args)
    else:
        raise AppError(422, "ai_call_mode_invalid")


def terminal(*args, **kwargs):
    from app.integrations import codex_terminal

    control = CallControl(kwargs.pop("on_progress", None), keep_cli_on_outage=True)
    return control.run(cli_results.run, codex_terminal.run, *args, **kwargs)
