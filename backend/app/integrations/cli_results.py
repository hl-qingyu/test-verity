"""Durable CLI outcome receipts. Database recovery never repeats a model call."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.call_control import receipt_id
from app.integrations.response_diagnostics import safe_snapshot
from app.security.secrets import credential_cipher


def path(identity):
    return Settings().ai_cli_work_path.resolve() / "results" / f"{UUID(identity)}.enc"


def pending(identity):
    target = path(identity)
    return target.is_file() and not target.with_suffix(".delivered").exists()


def acknowledge(identity):
    target = path(identity)
    if target.is_file():
        target.with_suffix(".delivered").touch(exist_ok=True)


def write(target, value):
    cipher = credential_cipher("ai_key_storage_unavailable")
    data = cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def run(function, *args, **kwargs):
    identity = receipt_id()
    if identity is None:
        return function(*args, **kwargs)
    target = path(identity)
    signature = hashlib.sha256(
        repr(
            (
                function.__module__,
                function.__name__,
                args,
                {k: v for k, v in kwargs.items() if k not in ("on_progress", "diagnostics")},
            )
        ).encode()
    ).hexdigest()
    stats = kwargs.get("diagnostics")
    if target.exists():
        value = json.loads(
            credential_cipher("ai_key_storage_unavailable").decrypt(target.read_bytes())
        )
        # The receipt UUID is the scheduler's immutable call reservation. Once
        # a response exists, recovery must deliver it, never rerun the CLI. The
        # frozen request has already been checked by the business executor.
        if value["signature"] != signature:
            raise AppError(409, "ai_cli_saved_result_mismatch")
        if stats is not None:
            stats.update(value.get("diagnostics", {}))
        if value["state"] == "completed":
            return value["answer"]
        raise AppError(502, value.get("error", "ai_cli_result_incomplete"))
    write(target, {"signature": signature, "state": "started"})
    try:
        answer = function(*args, **kwargs)
    except Exception as exc:
        write(
            target,
            {
                "signature": signature,
                "state": "failed",
                "error": exc.detail if isinstance(exc, AppError) else "ai_cli_execution_failed",
                "diagnostics": safe_snapshot(stats or {}),
            },
        )
        raise
    write(
        target,
        {
            "signature": signature,
            "state": "completed",
            "answer": answer,
            "diagnostics": safe_snapshot(stats or {}),
        },
    )
    return answer
