"""Capture the completed generation turn without parsing or modifying terminal output."""

from threading import Event
from time import monotonic

from app.core.errors import AppError
from app.integrations.terminal_policy import PolicyDenied


class TerminalResult:
    def __init__(self):
        self.done = Event()
        self.thread_id = None
        self.turn_id = None
        self.request_id = None
        self.messages = {}
        self.status = None
        self.completed_at = None

    def request(self, message):
        if (
            message.get("method") == "turn/start"
            and self.thread_id
            and message.get("params", {}).get("threadId") != self.thread_id
        ):
            raise PolicyDenied("bound_generation_thread")
        if message.get("method") == "turn/start" and self.request_id is None:
            self.request_id = message.get("id")
            self.thread_id = message.get("params", {}).get("threadId")

    def receive(self, message):
        if (
            self.request_id is not None
            and message.get("id") == self.request_id
            and "error" in message
        ):
            self.status = "failed"
            self.completed_at = monotonic()
            self.done.set()
            return
        params = message.get("params") or {}
        if (
            not isinstance(params, dict)
            or not self.thread_id
            or params.get("threadId") != self.thread_id
        ):
            return
        method = message.get("method")
        turn = params.get("turn") or {}
        if method == "turn/started" and self.turn_id is None:
            self.turn_id = turn.get("id")
        if method == "item/completed" and params.get("turnId") == self.turn_id:
            item = params.get("item") or {}
            if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                self.messages[item.get("id")] = item["text"]
        if method == "turn/completed" and turn.get("id") == self.turn_id:
            self.status = turn.get("status")
            self.completed_at = monotonic()
            self.done.set()

    def answer(self):
        if self.status in ("failed", "interrupted"):
            raise AppError(502, "generation_terminal_turn_" + self.status)
        if self.status != "completed" or not self.messages:
            raise AppError(502, "generation_terminal_response_incomplete")
        answer = next(reversed(self.messages.values()))
        if not answer.strip():
            raise AppError(502, "generation_terminal_response_incomplete")
        return answer
