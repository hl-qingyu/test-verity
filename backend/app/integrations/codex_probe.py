"""One fixed-text CLI probe. A loopback gate permits one provider request and no tools."""

import hmac
import json
import secrets
import socket
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from time import monotonic
from urllib.error import HTTPError, URLError

from app.core.errors import AppError
from app.integrations import response_errors, responses
from app.integrations.response_diagnostics import error_metadata

PROMPT = "请只回复 OK"
INSTRUCTIONS = "这是固定文字连接测试。请只回复 OK。不得调用工具、读取文件或继续执行其他任务。"
LIMIT = 262144
TIMEOUT = 120


class CapturedStream:
    def __init__(self, source):
        self.source, self.body = source, bytearray()

    def readline(self, size):
        line = self.source.readline(size)
        self.body.extend(line)
        return line


def validate_response(result, body, stream):
    values = [result]
    if stream:
        values.extend(
            json.loads(line[5:].strip())
            for line in body.splitlines()
            if line.startswith(b"data:") and line[5:].strip() != b"[DONE]"
        )
    for value in values:
        if not isinstance(value, dict):
            raise AppError(502, "ai_cli_invalid_response")
        item = value.get("item")
        response = value.get("response", value)
        if not isinstance(response, dict):
            raise AppError(502, "ai_cli_invalid_response")
        outputs = response.get("output", [])
        if not isinstance(outputs, list):
            raise AppError(502, "ai_cli_invalid_response")
        for entry in ([item] if item is not None else []) + outputs:
            if not isinstance(entry, dict) or entry.get("type") not in ("message", "reasoning"):
                raise AppError(502, "ai_cli_tools_forbidden")
    if responses.output_text(result).strip() != "OK":
        raise AppError(502, "ai_cli_invalid_response")


class ProbeGate:
    def __init__(self, base_url, model, key):
        self.base_url = responses.normalize_base_url(base_url)
        self.model, self.key = model, key
        self.token = secrets.token_urlsafe(32)
        self.started = monotonic()
        self.calls = 0
        self.error = None
        self.response = None
        self.lock = Lock()
        gate = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_error(404)

            def do_POST(self):
                try:
                    if self.path != "/responses" or not hmac.compare_digest(
                        self.headers.get("Authorization", ""), "Bearer " + gate.token
                    ):
                        self.send_error(403)
                        return
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= LIMIT:
                        raise AppError(422, "ai_cli_probe_invalid_request")
                    payload = json.loads(self.rfile.read(length))
                    if (
                        not isinstance(payload, dict)
                        or payload.get("model") != gate.model
                        or payload.get("tools")
                        or payload.get("store") is not False
                        or PROMPT not in json.dumps(payload.get("input"), ensure_ascii=False)
                    ):
                        raise AppError(422, "ai_cli_probe_invalid_request")
                    with gate.lock:
                        if gate.calls:
                            raise AppError(409, "ai_cli_call_limit")
                        gate.check()
                        gate.calls = 1
                    body, content_type = gate.forward(payload)
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (ValueError, UnicodeError):
                    gate.fail(AppError(502, "ai_cli_invalid_response"))
                    self.reject()
                except AppError as error:
                    gate.fail(error)
                    self.reject()
                except (OSError, HTTPException):
                    gate.fail(AppError(502, "ai_connection_failed"))

            def reject(self):
                body = b'{"error":{"message":"CLI connection probe rejected"}}'
                try:
                    self.send_response(400)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # Non-daemon request threads are joined before the reservation can be released.
        self.server.daemon_threads = False
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def fail(self, error):
        if self.error is None:
            self.error = error

    def check(self):
        if self.error:
            raise self.error
        if monotonic() - self.started >= TIMEOUT:
            raise AppError(504, "ai_timeout")

    def forward(self, payload):
        captured = None
        body = b""
        stats = {}
        try:
            request = responses.model_request(self.base_url, self.key, payload)
            remaining = max(0.1, TIMEOUT - (monotonic() - self.started))
            with responses.open_model_response(request, remaining) as response:
                self.response = response
                self.check()
                content_type = response.headers.get("Content-Type", "application/json")
                stream = content_type.split(";")[0].strip().lower() == "text/event-stream"
                if stream:
                    captured = CapturedStream(response)
                    result = responses.read_stream(
                        captured,
                        LIMIT,
                        self.started,
                        on_progress=self.check,
                        secret=self.key,
                        diagnostics=stats,
                    )
                    body = bytes(captured.body)
                else:
                    body = response.read(LIMIT + 1)
                    if len(body) > LIMIT:
                        raise AppError(502, "ai_cli_output_too_large")
                    result = json.loads(body)
                validate_response(result, body, stream)
                return body, content_type
        except HTTPError as error:
            self.response = error
            body = error.read(response_errors.MAX_ERROR_BYTES + 1)
            stats.update(error_metadata(body.decode("utf-8", errors="replace")))
            response_errors.capture(body, stats, self.key)
            code = responses.response_error_code(error.code, stats)
            error.close()
            raise AppError(502, code) from None
        except TimeoutError:
            raise AppError(504, "ai_timeout") from None
        except URLError as error:
            code = (
                "ai_timeout" if isinstance(error.reason, TimeoutError) else "ai_connection_failed"
            )
            raise AppError(502, code) from None
        except (ValueError, UnicodeError):
            if body:
                response_errors.capture(body, stats, self.key)
            raise AppError(502, "ai_cli_invalid_response") from None
        except AppError:
            raw = bytes(captured.body) if captured else body
            if raw:
                response_errors.capture(raw, stats, self.key)
            raise

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        response = self.response
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                descriptor = sock.detach()
                if descriptor != -1:
                    socket.close(descriptor)
            except OSError:
                pass
        self.server.server_close()
        self.thread.join()
