"""Private encrypted upstream errors; plaintext never enters application logs."""

import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.response_diagnostics import safe_snapshot
from app.security.secrets import credential_cipher

MAX_ERROR_BYTES = 1024 * 1024


def directory() -> Path:
    return Settings().ai_response_error_path.resolve()


def capture(body: bytes, stats: dict, secret: str) -> None:
    """Capturing an error must never mask the original failure or trigger another request."""
    temporary = None
    try:
        ref = str(uuid4())
        stats.setdefault("error_body_truncated", len(body) > MAX_ERROR_BYTES)
        masked = body[:MAX_ERROR_BYTES]
        if secret:
            masked = masked.replace(secret.encode(), b"[REDACTED_API_KEY]")
        record = {
            "version": 1,
            "captured_at": datetime.now(UTC).isoformat(),
            "diagnostics": safe_snapshot(stats),
            "body_base64": base64.b64encode(masked).decode(),
        }
        encrypted = credential_cipher("ai_key_storage_unavailable").encrypt(
            json.dumps(record, ensure_ascii=True).encode()
        )
        folder = directory()
        folder.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=folder, prefix=".error-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
        os.replace(temporary, folder / f"{ref}.enc")
        stats["error_ref"] = ref
    except (OSError, AppError, ValueError, UnicodeError):
        stats["error_capture_failed"] = True
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def read(ref: str) -> dict:
    """Local diagnostic access only; no API route or public download exposes this store."""
    if str(UUID(ref)) != ref:
        raise ValueError("invalid error reference")
    with (directory() / f"{ref}.enc").open("rb") as stream:
        encrypted = stream.read(MAX_ERROR_BYTES * 3)
    return json.loads(credential_cipher("ai_key_storage_unavailable").decrypt(encrypted))
