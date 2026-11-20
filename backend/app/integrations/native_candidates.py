"""Read completed native assistant messages from one server-bound CLI workspace."""

import hashlib
import json

from app.core.errors import AppError
from app.integrations.codex_terminal import directory


def completed_messages(identity, *, turns=None):
    root = directory(identity) / "state" / "sessions"
    result = []
    if not root.is_dir() or root.is_symlink():
        return result
    try:
        for path in sorted(root.rglob("*.jsonl")):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("invalid session path")
            thread, turn, pending = "", "", []
            with path.open(encoding="utf-8") as source:
                for line in source:
                    if not line.endswith("\n"):
                        break
                    row = json.loads(line)
                    if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                        raise ValueError("invalid native record")
                    payload = row.get("payload") or {}
                    kind = payload.get("type")
                    if row.get("type") == "session_meta":
                        thread = payload.get("id", "")
                    if kind == "task_started":
                        turn, pending = payload.get("turn_id", ""), []
                    elif kind == "turn_aborted":
                        pending = []
                    elif (
                        row.get("type") == "response_item"
                        and kind == "message"
                        and payload.get("role") == "assistant"
                        and payload.get("phase") in (None, "final_answer")
                    ):
                        text = "".join(
                            c.get("text", "")
                            for c in payload.get("content", [])
                            if isinstance(c, dict)
                        )
                        if text.strip():
                            pending.append((row.get("timestamp", ""), text))
                    elif kind == "task_complete":
                        if (
                            thread
                            and turn
                            and (turns is None or (thread, turn) in turns)
                            and payload.get("turn_id") == turn
                            and not payload.get("error")
                        ):
                            for timestamp, text in pending:
                                raw_hash = hashlib.sha256(text.encode()).hexdigest()
                                key = hashlib.sha256(
                                    json.dumps([thread, turn, timestamp, raw_hash]).encode()
                                ).hexdigest()
                                result.append(
                                    {
                                        "id": key,
                                        "thread_id": thread,
                                        "turn_id": turn,
                                        "timestamp": timestamp,
                                        "sha256": raw_hash,
                                        "text": text,
                                    }
                                )
                        pending = []
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError(503, "generation_native_results_unavailable") from None
    return sorted(result, key=lambda item: item["timestamp"], reverse=True)
