"""Explicit transport selection; no database, preference lookup or fallback."""

from typing import Literal

from app.core.errors import AppError
from app.integrations import codex_exec, responses
from app.integrations.call_control import CallControl

CallMode = Literal["RESPONSES_API", "CODEX_EXEC"]


def analyze(*args, call_mode: CallMode = "RESPONSES_API", **kwargs) -> str:
    control = CallControl(kwargs.pop("on_progress", None))
    if call_mode == "RESPONSES_API":
        return control.run(responses.analyze, *args, **kwargs)
    if call_mode == "CODEX_EXEC":
        return control.run(codex_exec.analyze, *args, **kwargs)
    raise AppError(422, "ai_call_mode_invalid")


def converse(*args, call_mode: CallMode = "RESPONSES_API", **kwargs) -> str:
    control = CallControl(kwargs.pop("on_progress", None))
    if call_mode == "RESPONSES_API":
        return control.run(responses.converse, *args, **kwargs)
    if call_mode == "CODEX_EXEC":
        return control.run(codex_exec.converse, *args, **kwargs)
    raise AppError(422, "ai_call_mode_invalid")


def probe_model(*args, call_mode: CallMode = "RESPONSES_API") -> None:
    if call_mode == "RESPONSES_API":
        responses.probe_model(*args)
    elif call_mode == "CODEX_EXEC":
        codex_exec.probe_model(*args)
    else:
        raise AppError(422, "ai_call_mode_invalid")
