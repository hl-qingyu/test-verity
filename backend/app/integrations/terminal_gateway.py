"""Authenticated loopback proxy between native TUI and its private stdio app-server."""

import codecs
import hmac
import json
import secrets
import subprocess
from datetime import UTC, datetime
from threading import Event, Lock, Thread

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response
from websockets.sync.server import serve

from app.integrations.terminal_policy import PolicyDenied


class TerminalGateway:
    def __init__(
        self,
        args,
        environment,
        work,
        policy,
        job,
        cipher,
        diagnostics,
        redact,
        capture=None,
        redact_event=None,
    ):
        self.token = secrets.token_urlsafe(32)
        self.policy = policy
        self.failed = Event()
        self.write_lock = Lock()
        self.client_lock = Lock()
        self.client = None
        self.used = Event()
        self.blocked_command = False
        self.capture = capture
        self.event_lock = Lock()
        self.event_path = diagnostics.with_name(diagnostics.name.split(".")[0] + ".rpc.enc.jsonl")
        self.redact_event = redact_event or redact
        self.process = subprocess.Popen(
            args,
            cwd=work,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=0x00000004 | subprocess.CREATE_NO_WINDOW,
        )
        try:
            job.assign_and_resume(self.process)
            self.cipher, self.diagnostics, self.redact = cipher, diagnostics, redact
            self.server = serve(
                self.handle,
                "127.0.0.1",
                0,
                process_request=self.authenticate,
                max_size=32 * 1024 * 1024,
                compression=None,
            )
            self.port = self.server.socket.getsockname()[1]
            self.thread = Thread(
                target=self.server.serve_forever, name="cli-policy-gateway", daemon=True
            )
            self.stderr_thread = Thread(
                target=self.capture_errors, name="cli-server-errors", daemon=True
            )
            self.thread.start()
            self.stderr_thread.start()
        except BaseException:
            self.process.kill()
            self.process.wait()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()
            raise

    def authenticate(self, connection, request):
        if not hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), ("Bearer " + self.token).encode()
        ):
            return Response(401, "Unauthorized", Headers(), b"Unauthorized")

    def write(self, message):
        with self.write_lock:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
            self.process.stdin.flush()

    def capture_errors(self):
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            with self.diagnostics.open("ab") as target:
                while data := self.process.stderr.read1(8192):
                    text = self.redact(decoder.decode(data))
                    if text:
                        target.write(self.cipher.encrypt(text.encode()) + b"\n")
                        target.flush()
        except OSError:
            self.failed.set()

    def record_event(self, event):
        # Keep failure evidence, never the user prompt or arbitrary RPC arguments.
        data = self.redact_event(
            json.dumps({**event, "at": datetime.now(UTC).isoformat()}, ensure_ascii=False)
        ).encode()
        try:
            with self.event_lock, self.event_path.open("ab") as target:
                target.write(self.cipher.encrypt(data) + b"\n")
        except OSError:
            self.failed.set()

    def handle(self, connection):
        if self.used.is_set() or not self.client_lock.acquire(blocking=False):
            connection.close(code=1008)
            return
        self.used.set()
        self.client = connection
        pending_user_inputs = set()
        pending_lock = Lock()

        def responses():
            try:
                while line := self.process.stdout.readline():
                    message = json.loads(line)
                    params = message.get("params") or {}
                    if message.get("method") in ("turn/started", "turn/completed"):
                        turn = params.get("turn") or {}
                        self.record_event(
                            {
                                "method": message["method"],
                                "thread_id": params.get("threadId"),
                                "turn_id": turn.get("id"),
                                "status": "running"
                                if message["method"] == "turn/started"
                                else turn.get("status"),
                                "error": turn.get("error"),
                            }
                        )
                    elif "error" in message or message.get("method") == "error":
                        self.record_event(
                            {
                                "method": "error",
                                "id": message.get("id"),
                                "error": message.get("error") or params.get("error"),
                            }
                        )
                    if "method" in message and "id" in message:
                        # No UI response can grant filesystem, command, or network privileges.
                        if message["method"] != "item/tool/requestUserInput":
                            self.write(self.policy.denial(message["id"]))
                            continue
                        with pending_lock:
                            pending_user_inputs.add(message["id"])
                    connection.send(line.decode().rstrip("\r\n"))
                    if self.capture:
                        self.capture.receive(message)
            except (OSError, ValueError, ConnectionClosed):
                pass
            finally:
                connection.close()

        reader = Thread(target=responses, name="cli-policy-responses", daemon=True)
        reader.start()
        try:
            for raw in connection:
                message = json.loads(raw)
                if not isinstance(message, dict) or (
                    "id" in message and type(message["id"]) not in (str, int)
                ):
                    connection.close(code=1008)
                    break
                if "method" not in message:
                    with pending_lock:
                        allowed = message.get("id") in pending_user_inputs
                        pending_user_inputs.discard(message.get("id"))
                    if allowed:
                        self.write(message)
                    continue
                try:
                    checked = self.policy.request(message)
                    if self.capture:
                        if self.capture.done.is_set() and message.get("method") == "turn/start":
                            raise PolicyDenied("generation_complete")
                        self.capture.request(checked)
                    self.write(checked)
                    if message.get("method") == "turn/interrupt":
                        self.record_event({"method": "turn/interrupt"})
                except PolicyDenied as exc:
                    self.record_event(
                        {
                            "method": "policy_denied",
                            "rpc_method": message.get("method"),
                            "reason": str(exc),
                        }
                    )
                    if message.get("method") in (
                        "thread/shellCommand",
                        "command/exec",
                        "process/spawn",
                    ):
                        self.blocked_command = True
                    if "id" in message:
                        connection.send(
                            json.dumps(self.policy.denial(message["id"]), ensure_ascii=False)
                        )
        except (OSError, ValueError, ConnectionClosed):
            pass
        finally:
            self.client = None
            self.failed.set()
            self.client_lock.release()

    def close(self):
        if self.client:
            self.client.close()
        self.server.shutdown()
        self.thread.join()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.stderr_thread.join()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
