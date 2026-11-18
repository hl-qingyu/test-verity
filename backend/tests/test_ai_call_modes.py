"""Real PostgreSQL rollback checks; every model/process response is simulated."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import test_auth
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from test_ai_service import PAYLOAD, AIDatabaseTests

from app.core.errors import AppError
from app.db.models import (
    AICallPreference,
    AICallReservation,
    AICLIConnection,
    AIConnection,
    SkillChatTurn,
)
from app.integrations import ai_client, codex_exec
from app.integrations.call_control import CallControl, execution_scope
from app.modules.ai import reservations, scheduling, service


class CLIProtocolTests(unittest.TestCase):
    def test_full_text_and_roles_preserved_and_attachments_rejected(self):
        text = "完整输入原文\n" * 200000
        messages = [
            {"role": "developer", "content": "固定Skill"},
            {"role": "user", "content": [{"type": "input_text", "text": text}]},
        ]
        self.assertEqual(
            json.loads(codex_exec.text_input("规则", messages)),
            {"instructions": "规则", "messages": messages},
        )
        with self.assertRaises(AppError) as caught:
            codex_exec.text_input("规则", [{"role": "user", "content": [{"type": "input_file"}]}])
        self.assertEqual(caught.exception.detail, "ai_cli_attachment_unsupported")

    def test_exit_zero_requires_one_final_nonempty_message_and_completed_turn(self):
        answer = {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}}
        done = {"type": "turn.completed"}
        self.assertEqual(codex_exec.final_message([answer, done], 0), "{}")
        for events, code in [
            ([], 0),
            ([done], 0),
            ([answer], 0),
            ([answer, done], 1),
            ([answer, answer, done], 0),
            ([{"type": "turn.failed"}, done], 0),
            ([{"type": "item.completed", "item": {"type": "command_execution"}}, answer, done], 0),
        ]:
            with self.subTest(events=events), self.assertRaises(AppError):
                codex_exec.final_message(events, code)

    def test_cli_gate_never_falls_back_or_starts_a_process(self):
        with (
            patch.object(
                codex_exec,
                "runtime_status",
                return_value={
                    "available": False,
                    "status": "not_installed",
                    "reason": "ai_cli_not_installed",
                },
            ),
            patch("app.integrations.responses.analyze") as api,
            patch.object(codex_exec.subprocess, "Popen") as process,
        ):
            with self.assertRaises(AppError):
                ai_client.analyze(
                    "https://example.com",
                    "test",
                    "fake-key",
                    "default",
                    "规则",
                    [{"type": "input_text", "text": "固定正文"}],
                    call_mode="CODEX_EXEC",
                )
            api.assert_not_called()
            process.assert_not_called()

    def test_silent_call_cancelled_and_late_result_rejected(self):
        stopped = Event()
        with execution_scope(stopped):
            control = CallControl(None)
        stopped.set()
        with self.assertRaises(AppError):
            control.run(lambda **kw: "late answer")

    def test_worker_scope_interrupts_a_silent_response_socket(self):
        from types import SimpleNamespace

        from app.integrations.call_control import connected

        stopped = Event()
        local, remote = socket.socketpair()
        local.settimeout(4)  # Bound this offline test if cancellation regresses.
        try:

            def transport(**kwargs):
                connected(SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(_sock=local))))
                local.recv(1)
                return "late answer"

            trigger = Thread(target=lambda: (stopped.wait(0.1), stopped.set()))
            with execution_scope(stopped):
                control = CallControl(None)
            trigger.start()
            started = monotonic()
            with self.assertRaises(AppError) as caught:
                control.run(transport)
            trigger.join()
            self.assertEqual(caught.exception.detail, "ai_worker_interrupted")
            self.assertLess(monotonic() - started, 3)
        finally:
            local.close()
            remote.close()


@unittest.skipUnless(os.name == "nt", "Windows Job Object integration")
class CLIProcessTests(unittest.TestCase):
    def run_fake(self, script, payload=b"fixed input", cancel=None, diagnostics=None):
        root = Path(__file__).resolve().parents[1] / "outputs"
        root.mkdir(exist_ok=True)
        original = subprocess.Popen
        with tempfile.TemporaryDirectory(dir=root, prefix="cli-process-") as temp:
            folder = Path(temp)
            fake = folder / "fake.py"
            fake.write_text(script, encoding="utf-8")
            settings = SimpleNamespace(
                ai_cli_executable=Path(sys.executable), ai_cli_work_path=folder / "attempts"
            )
            cipher = Fernet(Fernet.generate_key())
            seen = []

            def spawn(args, **kwargs):
                self.assertNotIn("fake-only-key", " ".join(args))
                self.assertEqual(kwargs["env"]["VERITY_CODEX_KEY"], "fake-only-key")
                self.assertNotIn("DATABASE_URL", kwargs["env"])
                self.assertFalse(kwargs["shell"])
                seen.append(args)
                return original([sys.executable, str(fake)], **kwargs)

            with (
                patch.object(codex_exec, "Settings", return_value=settings),
                patch.object(codex_exec, "runtime_status", return_value={"version": "0.169.1"}),
                patch.object(codex_exec.subprocess, "Popen", side_effect=spawn),
                patch.object(codex_exec, "credential_cipher", return_value=cipher),
            ):
                result = codex_exec._execute(
                    "https://example.com",
                    "test-model",
                    "fake-only-key",
                    "default",
                    payload,
                    on_progress=cancel,
                    diagnostics=diagnostics,
                )
            self.assertEqual(len(seen), 1)
            attempt = next((folder / "attempts").iterdir())
            self.assertFalse((attempt / "state").exists())
            self.assertNotIn(
                b"fake-only-key", cipher.decrypt((attempt / "events.enc").read_bytes())
            )
            return result

    def test_large_pipes_stdin_integrity_child_environment_and_raw_redaction(self):
        payload = ("完整输入\n" * 200000).encode()
        script = """import sys,json,hashlib,os
raw=sys.stdin.buffer.read()
sys.stderr.write('x'*1048576+'fake-only-key')
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':hashlib.sha256(raw).hexdigest()}}),flush=True)
print(json.dumps({'type':'turn.completed'}),flush=True)
"""
        self.assertEqual(self.run_fake(script, payload), hashlib.sha256(payload).hexdigest())

    def test_silent_process_cancel_is_bounded_and_owned_job_is_closed(self):
        started = monotonic()

        def check():
            if monotonic() - started > 0.4:
                raise AppError(409, "test_cancelled")

        with self.assertRaises(AppError) as caught:
            self.run_fake("import time; time.sleep(120)", cancel=check)
        self.assertEqual(caught.exception.detail, "test_cancelled")
        self.assertLess(monotonic() - started, 10)

    def test_small_flushed_events_are_visible_before_process_finishes(self):
        stats, observed = {}, []

        def check():
            observed.append(
                (
                    stats.get("phase"),
                    stats.get("received_bytes", 0),
                    stats.get("output_characters", 0),
                )
            )

        script = """import sys,json,time
sys.stdin.buffer.read()
print(json.dumps({"type":"thread.started","thread_id":"12345678-1234-1234-1234-123456789abc"}),flush=True)
print(json.dumps({"type":"turn.started"}),flush=True)
time.sleep(1)
print(json.dumps({"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"OK"}}),flush=True)
print(json.dumps({"type":"turn.completed"}),flush=True)
"""
        self.assertEqual(self.run_fake(script, cancel=check, diagnostics=stats), "OK")
        self.assertTrue(
            any(
                phase == "cli_waiting" and received > 0 and output == 0
                for phase, received, output in observed
            )
        )
        self.assertEqual(stats["output_characters"], 2)
        self.assertEqual(stats["cli_event_count"], 4)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class CallModeDatabaseTests(AIDatabaseTests):
    def test_native_cli_can_be_saved_and_selected_then_fixed_after_api_switch(self):
        self.login(self.member_name)
        self.encrypted("/api/ai-service/personal", PAYLOAD)
        with patch("app.integrations.ai_client.probe_model") as no_model:
            result = self.encrypted(
                "/api/ai-service/configuration",
                {
                    **PAYLOAD,
                    "api_key": "NATIVE-CLI-FAKE-KEY",
                    "call_mode": "CODEX_EXEC",
                    "preference_version": 0,
                    "activate": True,
                },
            )
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["call_mode"], "CODEX_EXEC")
            self.assertTrue(result.json()["activated"])
            self.assertTrue(result.json()["cli_runtime"]["available"])
            no_model.assert_not_called()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            actor = db.get(test_auth.UserAccount, self.member_id)
            current, key = service.analysis_configuration(actor, db)
            self.assertEqual(key, "NATIVE-CLI-FAKE-KEY")
            frozen = service.configuration_snapshot(current)
            self.assertEqual(frozen["execution_policy"], "native-v1")
        switched = self.encrypted(
            "/api/ai-service/activate",
            {"call_mode": "RESPONSES_API", "version": 1, "preference_version": 1},
        )
        self.assertEqual(switched.status_code, 200, switched.text)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            actor = db.get(test_auth.UserAccount, self.member_id)
            fixed, key = service.analysis_configuration(actor, db, frozen)
            self.assertEqual(fixed["call_mode"], "CODEX_EXEC")
            self.assertEqual(key, "NATIVE-CLI-FAKE-KEY")

    def test_claim_keeps_blocked_user_queued_and_runs_another_user(self):
        self.login(self.member_name)
        self.encrypted("/api/ai-service/personal", PAYLOAD)
        self.login(self.admin_name)
        self.encrypted("/api/ai-service/personal", {**PAYLOAD, "api_key": "another-fake-key"})
        with Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as db:
            scheduler = str(uuid4())
            held = reservations.reserve(
                db,
                self.member_id,
                PAYLOAD["base_url"],
                PAYLOAD["api_key"],
                kind="TEST",
                task_id=None,
                request_id=str(uuid4()),
                scheduler_id=scheduler,
            )
            rows = []
            for owner in (self.member_id, self.admin_id):
                actor = db.get(test_auth.UserAccount, owner)
                config, _ = service.analysis_configuration(actor, db)
                row = SkillChatTurn(
                    actor_id=owner,
                    skill_key="case-generation",
                    request_id=str(uuid4()),
                    fingerprint="a" * 64,
                    question="合成测试",
                    context={},
                    ai_config=service.configuration_snapshot(config),
                )
                db.add(row)
                rows.append(row)
            db.commit()
            item = scheduling.claim(db, SkillChatTurn, scheduler)
            self.assertEqual(item[0], rows[1].id)
            self.assertEqual(
                db.get(SkillChatTurn, rows[0].id, populate_existing=True).status, "QUEUED"
            )
            self.assertEqual(
                db.get(SkillChatTurn, rows[1].id, populate_existing=True).status, "RUNNING"
            )
            reservations.release(db, item[1])
            reservations.release(db, held)

    def test_independent_configs_atomic_preference_and_conflicts(self):
        self.login(self.member_name)
        api = self.encrypted("/api/ai-service/personal", PAYLOAD)
        self.assertEqual(api.status_code, 200)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            encrypted = db.get(AIConnection, self.member_id).encrypted_key
        cli = self.encrypted(
            "/api/ai-service/configuration",
            {
                **PAYLOAD,
                "name": "独立CLI",
                "api_key": "different-fake-key",
                "call_mode": "CODEX_EXEC",
                "preference_version": 0,
                "activate": False,
            },
        )
        self.assertEqual(cli.status_code, 200, cli.text)
        self.assertEqual(cli.json()["call_mode"], "RESPONSES_API")
        self.assertFalse(cli.json()["activated"])
        self.assertNotIn("different-fake-key", cli.text)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertEqual(db.get(AIConnection, self.member_id).encrypted_key, encrypted)
            saved_cli = db.get(AICLIConnection, self.member_id)
            self.assertEqual(
                service.cipher().decrypt(saved_cli.encrypted_key.encode()), b"different-fake-key"
            )
        # Pure activation never re-encrypts or increments configuration revision.
        saved = self.encrypted(
            "/api/ai-service/configuration",
            {
                **PAYLOAD,
                "api_key": "",
                "version": 1,
                "call_mode": "RESPONSES_API",
                "preference_version": 0,
                "activate": True,
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["personal"]["version"], 1)
        self.assertEqual(saved.json()["preference_version"], 1)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertEqual(db.get(AIConnection, self.member_id).encrypted_key, encrypted)
        conflict = self.encrypted(
            "/api/ai-service/configuration",
            {
                **PAYLOAD,
                "version": 1,
                "call_mode": "RESPONSES_API",
                "preference_version": 0,
                "activate": True,
            },
        )
        self.assertEqual(conflict.status_code, 409)
        # Old save clients never switch preference.
        self.assertEqual(
            self.encrypted("/api/ai-service/personal", {**PAYLOAD, "version": 1}).status_code, 200
        )
        self.assertEqual(self.client.get("/api/ai-service").json()["preference_version"], 1)
        self.login(self.admin_name)
        self.assertIsNone(self.client.get("/api/ai-service").json()["cli"])

    def test_unverified_analysis_can_probe_without_saving_or_activating(self):
        self.login(self.member_name)
        with (
            patch("app.integrations.ai_client.probe_model") as probe,
            patch.object(
                codex_exec,
                "runtime_status",
                return_value={
                    "available": False,
                    "probe_available": True,
                    "status": "unverified",
                    "reason": "ai_cli_unverified",
                },
            ),
        ):
            response = self.encrypted(
                "/api/ai-service/configuration",
                {
                    **PAYLOAD,
                    "call_mode": "CODEX_EXEC",
                    "preference_version": 0,
                    "activate": True,
                },
            )
            self.assertEqual(response.status_code, 503)
            response = self.encrypted(
                "/api/ai-service/test", {**PAYLOAD, "call_mode": "CODEX_EXEC"}
            )
            self.assertEqual(response.status_code, 200, response.text)
            probe.assert_called_once_with(
                PAYLOAD["base_url"],
                PAYLOAD["model"],
                PAYLOAD["api_key"],
                "default",
                call_mode="CODEX_EXEC",
            )
        self.assertIsNone(self.client.get("/api/ai-service").json()["cli"])

        saved = self.client.get("/api/ai-service").json()
        self.assertEqual(saved["call_mode"], "RESPONSES_API")
        self.assertEqual(saved["preference_version"], 0)

    def test_uninstalled_cli_cannot_probe_and_never_uses_api(self):
        self.login(self.member_name)
        with (
            patch("app.integrations.ai_client.probe_model") as probe,
            patch.object(
                codex_exec,
                "runtime_status",
                return_value={
                    "available": False,
                    "probe_available": False,
                    "status": "not_installed",
                    "reason": "ai_cli_not_installed",
                },
            ),
        ):
            result = self.encrypted("/api/ai-service/test", {**PAYLOAD, "call_mode": "CODEX_EXEC"})
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json()["detail"], "ai_cli_not_installed")
            probe.assert_not_called()

    def test_queued_snapshot_survives_preference_switch_and_detects_config_change(self):
        self.login(self.member_name)
        self.encrypted("/api/ai-service/personal", PAYLOAD)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            actor = db.get(test_auth.UserAccount, self.member_id)
            config, _ = service.analysis_configuration(actor, db)
            frozen = service.configuration_snapshot(config)
            db.add(AICallPreference(owner_id=actor.id, call_mode="CODEX_EXEC", version=1))
            db.flush()
            actual, _ = service.analysis_configuration(actor, db, frozen)
            self.assertEqual(actual["call_mode"], "RESPONSES_API")
            actual, _ = service.analysis_configuration(actor, db, {"version": 1})
            self.assertEqual(actual["call_mode"], "RESPONSES_API")
            connection = db.get(AIConnection, actor.id)
            connection.version = 2
            db.flush()
            with self.assertRaises(AppError) as caught:
                service.analysis_configuration(actor, db, frozen)
            self.assertEqual(caught.exception.detail, "ai_configuration_changed")

    def test_request_replay_and_service_path_aliases_cannot_bypass_budget(self):
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            args = dict(
                kind="code_analysis_task",
                task_id=123,
                request_id=str(uuid4()),
                scheduler_id=str(uuid4()),
            )
            reservation = reservations.reserve(
                db, self.member_id, "https://example.com/v1", "fake-key", **args
            )
            self.assertIsNotNone(reservation)
            self.assertIsNone(
                reservations.reserve(
                    db,
                    self.admin_id,
                    "https://example.com/relay/v1",
                    "fake-key",
                    kind="TEST",
                    task_id=None,
                    request_id=str(uuid4()),
                    scheduler_id=str(uuid4()),
                )
            )
            db.commit()
            reservations.release(db, reservation)
            with self.assertRaises(AppError) as caught:
                reservations.reserve(
                    db, self.member_id, "https://example.com/v1", "fake-key", **args
                )
            self.assertEqual(caught.exception.detail, "ai_call_already_attempted")

    def test_global_user_credential_budgets_and_api_test_busy(self):
        self.login(self.member_name)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:

            def reserve(owner, key, url="https://example.com"):
                return reservations.reserve(
                    db,
                    owner,
                    url,
                    key,
                    kind="TEST",
                    task_id=None,
                    request_id=str(uuid4()),
                    scheduler_id=str(uuid4()),
                )

            first = reserve(self.member_id, "same-fake-key")
            self.assertIsNotNone(first)
            self.assertIsNone(reserve(self.member_id, "another-key"))
            self.assertIsNone(reserve(self.admin_id, "same-fake-key"))
            second = reserve(self.admin_id, "another-key")
            self.assertIsNotNone(second)
            self.assertIsNone(reserve(self.member_id, "third-key", "https://other.example"))
            db.commit()
        with patch("app.integrations.ai_client.probe_model") as probe:
            response = self.encrypted(
                "/api/ai-service/test", {**PAYLOAD, "call_mode": "RESPONSES_API"}
            )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"], "ai_call_busy")
            probe.assert_not_called()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            reservations.release(db, first)
            self.assertEqual(db.get(AICallReservation, first).state, "RELEASED")
            # A live owning process is never reclaimed by age.
            reservations.recover_exited(db)
            self.assertEqual(db.get(AICallReservation, second).state, "HELD")
