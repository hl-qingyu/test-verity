"""Private encrypted CLI event journal; display projections never expose tool payloads."""

import json
from datetime import UTC, datetime
from uuid import UUID

from cryptography.fernet import InvalidToken

from app.core.config import Settings
from app.core.errors import AppError
from app.security.secrets import credential_cipher

MAX_TEXT = 16000


def project_event(event):
    kind = event.get("type", "")
    item = event.get("item") or {}
    text = ""
    if kind == "error":
        text = event.get("message", "")
    elif kind == "turn.failed":
        error = event.get("error") or {}
        text = error.get("message", "") if isinstance(error, dict) else str(error)
    elif kind in ("item.started", "item.updated", "item.completed"):
        if not isinstance(item, dict):
            return None
        item_kind = item.get("type")
        if item_kind == "reasoning":
            text = "模型处理中"
        elif item_kind == "agent_message":
            text = item.get("text", "")
        elif item_kind == "mcp_tool_call":
            arguments = item.get("arguments") or {}
            text = f"{item.get('tool', '工具')} · {item.get('status', kind)}"
            if isinstance(arguments, dict):
                for key in ("offset_bytes", "max_bytes"):
                    value = arguments.get(key)
                    if type(value) is int:
                        text += f" · {key}={value}"
            error = item.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                text += "\n" + error["message"]
        else:
            return None
    elif kind not in ("thread.started", "turn.started", "turn.completed"):
        return None
    text = text if isinstance(text, str) else ""
    return {"type": kind, "text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT}


class EventJournal:
    def __init__(self, directory, cipher, secrets=()):
        self.path = directory / "timeline.enc.jsonl"
        self.cipher = cipher
        self.secrets = tuple(s for s in secrets if s)
        self.sequence = 0

    def append(self, event, elapsed):
        # Mask before projection so slicing cannot leave a partially exposed key.
        raw = json.dumps(event, ensure_ascii=False)
        for secret in self.secrets:
            raw = raw.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED_API_KEY]")
        projected = project_event(json.loads(raw))
        if projected is None:
            return
        sequence = self.sequence + 1
        record = {
            **projected,
            "sequence": sequence,
            "at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(elapsed, 3),
        }
        token = self.cipher.encrypt(json.dumps(record, ensure_ascii=False).encode())
        # One flushed encrypted line per event is readable while the process is still running.
        with self.path.open("ab") as output:
            output.write(token + b"\n")
        self.sequence = sequence


def read_events(attempt_id, cursor=0, limit=100):
    try:
        identity = str(UUID(attempt_id))
    except (ValueError, TypeError, AttributeError):
        raise AppError(409, "generation_cli_log_unavailable") from None
    directory = Settings().ai_cli_work_path.resolve() / identity
    journal, archive = directory / "timeline.enc.jsonl", directory / "events.enc"
    cipher = credential_cipher("ai_key_storage_unavailable")
    items, has_more, available = [], False, False
    try:
        if journal.is_file():
            available = True
            with journal.open("rb") as source:
                for index, line in enumerate(source):
                    if index < cursor:
                        continue
                    if not line.endswith(b"\n"):
                        break  # An in-progress append is retried at the same cursor.
                    if len(items) >= limit:
                        has_more = True
                        break
                    items.append(json.loads(cipher.decrypt(line.strip())))
        elif archive.is_file():
            available = True
            raw = cipher.decrypt(archive.read_bytes()).partition(b"\n---stderr---\n")[0]
            sequence = 0
            for line in raw.decode().splitlines():
                if not line.strip():
                    continue
                projected = project_event(json.loads(line))
                if projected is None:
                    continue
                sequence += 1
                if sequence <= cursor:
                    continue
                if len(items) >= limit:
                    has_more = True
                    break
                items.append(
                    {**projected, "sequence": sequence, "at": None, "elapsed_seconds": None}
                )
    except (OSError, InvalidToken, ValueError, UnicodeError):
        raise AppError(503, "generation_cli_log_unavailable") from None
    return {
        "items": items,
        "next_cursor": cursor + len(items),
        "has_more": has_more,
        "available": available,
    }
