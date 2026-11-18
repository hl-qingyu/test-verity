"""Real pinned CLI against a loopback fake provider; no paid requests or real user keys."""

import json
import os
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from time import monotonic
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.core.errors import AppError
from app.integrations import codex_exec, codex_probe


class FakeProvider:
    def __init__(self, mode="ok", text="OK", tool_program=None):
        self.requests = []
        self.release = Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, self.headers.get("Authorization"), payload))
                if mode == "gated":
                    owner.release.wait(15)
                if mode == "silent":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.flush()
                    owner.release.wait(10)
                    return
                if mode in ("auth", "server", "redirect") or (
                    mode == "native_retry" and len(owner.requests) == 1
                ):
                    self.send_response({"auth": 401, "server": 500, "redirect": 307}.get(mode, 500))
                    self.send_header("Location", owner.url + "/unapproved")
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"synthetic provider error"}}')
                    return
                if mode == "invalid":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b"synthetic invalid JSON UPSTREAM-FAKE-KEY")
                    return
                message = {
                    "id": "msg_fake",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                }
                output = [message]
                if tool_program and len(owner.requests) == 1:
                    output = [
                        {
                            "id": "call_reading",
                            "type": "custom_tool_call",
                            "call_id": "call_reading",
                            "name": "exec",
                            "namespace": "functions",
                            "input": tool_program,
                            "status": "completed",
                        }
                    ]
                elif mode == "tool" or (
                    mode in ("native_round", "native_file") and len(owner.requests) == 1
                ):
                    output = [
                        {
                            "id": "call_fake",
                            "type": "function_call",
                            "call_id": "call_fake",
                            "name": "not_available",
                            "arguments": "{}",
                            "status": "completed",
                        }
                    ]
                    if mode == "native_file":
                        output[0] = {
                            "id": "call_fake",
                            "type": "custom_tool_call",
                            "call_id": "call_fake",
                            "name": "exec",
                            "namespace": "functions",
                            "input": "const r=await tools.mcp__filesystem__read_text_file("
                            "{path:'input.json'});"
                            "let data=r.structuredContent?.content;"
                            "if(typeof data!=='string'){"
                            "let p=r.content[0].text;"
                            "try{const o=JSON.parse(p);data=o.structuredContent?.content"
                            "??o.content?.[0]?.text??p;}catch{data=p;}}"
                            "text({tools:ALL_TOOLS.map(x=>x.name),characters:data.length,"
                            "head:data.slice(0,150),tail:data.slice(-150)})",
                            "status": "completed",
                        }
                response = {
                    "id": "resp_fake",
                    "object": "response",
                    "status": "completed",
                    "model": payload["model"],
                    "output": output,
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                }
                events = [
                    {
                        "type": "response.created",
                        "response": {**response, "status": "in_progress", "output": []},
                    },
                    {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {**output[0], "status": "in_progress"},
                    },
                    {"type": "response.output_item.done", "output_index": 0, "item": output[0]},
                    {"type": "response.completed", "response": response},
                ]
                if mode == "broken":
                    events = events[:1]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for event in events:
                    self.wfile.write(
                        (
                            "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
                        ).encode()
                    )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@unittest.skipUnless(os.name == "nt", "Windows CLI probe integration")
class RealCLIProbeTests(unittest.TestCase):
    def setUp(self):
        runtime = codex_exec.runtime_status()
        if not runtime["probe_available"]:
            self.skipTest("requires installed CLI exe")

    def run_probe(self, mode):
        with (
            FakeProvider(mode) as provider,
            patch.object(codex_probe.responses, "normalize_base_url", return_value=provider.url),
        ):
            if mode == "ok":
                original = codex_exec.subprocess.Popen
                with patch.object(codex_exec.subprocess, "Popen", wraps=original) as process:
                    codex_exec.probe_model(
                        "https://example.com", "gpt-6.1-sol", "UPSTREAM-FAKE-KEY", "low"
                    )
                environment = process.call_args.kwargs["env"]
                self.assertNotEqual(environment["VERITY_CODEX_KEY"], "UPSTREAM-FAKE-KEY")
                self.assertNotIn("AI_ENCRYPTION_KEY", environment)
                self.assertNotIn("DATABASE_URL", environment)
                self.assertNotIn("UPSTREAM-FAKE-KEY", " ".join(process.call_args.args[0]))
            else:
                with self.assertRaises(AppError) as caught:
                    codex_exec.probe_model(
                        "https://example.com", "gpt-6.1-sol", "UPSTREAM-FAKE-KEY", "low"
                    )
                self.assertEqual(
                    caught.exception.detail,
                    {
                        "tool": "ai_cli_tools_forbidden",
                        "broken": "ai_incomplete_response",
                        "auth": "ai_auth_failed",
                        "server": "ai_upstream_error",
                        "redirect": "ai_upstream_error",
                        "invalid": "ai_cli_invalid_response",
                    }[mode],
                )
            self.assertEqual(len(provider.requests), 1)
            path, authorization, payload = provider.requests[0]
            self.assertEqual(path, "/responses")
            self.assertEqual(authorization, "Bearer UPSTREAM-FAKE-KEY")
            self.assertFalse(payload.get("tools"))
            self.assertFalse(payload["store"])
            self.assertEqual(payload["reasoning"]["effort"], "low")
            content = json.dumps(payload, ensure_ascii=False)
            self.assertIn(codex_probe.PROMPT, content)
            self.assertNotIn("UPSTREAM-FAKE-KEY", content)
            self.assertNotIn("平台 Git 集成", content)

    def test_real_cli_ok_uses_fixed_prompt_no_tools_and_one_request(self):
        self.run_probe("ok")

    def test_real_cli_rejects_tool_output_without_second_request(self):
        self.run_probe("tool")

    def test_real_cli_does_not_retry_http_failure_or_broken_stream(self):
        for mode in ("auth", "server", "broken", "redirect", "invalid"):
            with self.subTest(mode=mode):
                self.run_probe(mode)

    def test_silent_probe_times_out_and_closes_owned_cli(self):
        with (
            FakeProvider("silent") as provider,
            patch.object(codex_probe.responses, "normalize_base_url", return_value=provider.url),
            patch.object(codex_probe, "TIMEOUT", 2),
        ):
            started = monotonic()
            with self.assertRaises(AppError) as caught:
                codex_exec.probe_model("https://example.com", "gpt-6.1-sol", "FAKE-KEY", "low")
            self.assertEqual(caught.exception.detail, "ai_timeout")
            self.assertLess(monotonic() - started, 6)
            self.assertLessEqual(len(provider.requests), 1)


class ProbeGateTests(unittest.TestCase):
    def test_second_request_is_blocked_locally_and_only_first_reaches_provider(self):
        with (
            FakeProvider() as provider,
            patch.object(codex_probe.responses, "normalize_base_url", return_value=provider.url),
            codex_probe.ProbeGate("https://example.com", "synthetic", "FAKE-UPSTREAM") as gate,
        ):
            body = json.dumps(
                {"model": "synthetic", "store": False, "stream": True, "input": codex_probe.PROMPT}
            ).encode()
            request = Request(
                gate.url + "/responses",
                data=body,
                headers={
                    "Authorization": "Bearer " + gate.token,
                    "Content-Type": "application/json",
                },
            )
            with urlopen(request, timeout=5) as response:
                self.assertIn(b"response.completed", response.read())
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=5)
            caught.exception.close()
            self.assertEqual(len(provider.requests), 1)
            self.assertEqual(gate.error.detail, "ai_cli_call_limit")

    def test_untrusted_local_requests_cannot_choose_url_model_or_tools(self):
        with (
            FakeProvider() as provider,
            patch.object(codex_probe.responses, "normalize_base_url", return_value=provider.url),
            codex_probe.ProbeGate("https://example.com", "synthetic", "FAKE-UPSTREAM") as gate,
        ):
            request = Request(
                gate.url + "/responses", data=b"{}", headers={"Authorization": "Bearer wrong"}
            )
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=5)
            caught.exception.close()
            request = Request(
                gate.url + "/responses",
                data=json.dumps(
                    {
                        "model": "other",
                        "store": False,
                        "input": codex_probe.PROMPT,
                        "tools": [{"name": "anything"}],
                    }
                ).encode(),
                headers={"Authorization": "Bearer " + gate.token},
            )
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=5)
            caught.exception.close()
            self.assertEqual(provider.requests, [])
