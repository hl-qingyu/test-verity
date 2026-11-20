"""Real ConPTY and module contracts with synthetic inputs and a loopback provider."""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import test_auth
import test_case_analysis
import test_case_generation
from test_codex_probe import FakeProvider

from app.core.config import Settings
from app.db.models import AnalysisTerminalResume, RequirementRiskReport
from app.integrations import codex_terminal
from app.modules.ai import native_terminal
from app.modules.analysis_terminal import service as terminal_service
from app.modules.case_analysis import execution as coverage
from app.modules.change_analysis import execution as changes
from app.modules.code_analysis import execution as code
from app.modules.requirements import risk_analysis_execution as requirements

ROOT = Path(__file__).resolve().parents[2] / "skill"


def sample(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("RUN_AUTH_DB_TESTS") == "1",
    "requires Windows and PostgreSQL",
)
class AnalysisTerminalTests(unittest.TestCase):
    setUpClass = classmethod(test_case_generation.GenerationDatabaseTests.setUpClass.__func__)
    setUp = test_case_generation.GenerationDatabaseTests.setUp
    tearDown = test_case_generation.GenerationDatabaseTests.tearDown
    factory = test_case_generation.GenerationDatabaseTests.factory
    login = test_case_generation.GenerationDatabaseTests.login
    configuration = test_case_generation.GenerationDatabaseTests.configuration

    def fixture(self, kind):
        if kind == "requirements":
            data = sample("requirement-analysis/examples/input.json")
            report = sample("requirement-analysis/examples/output.json")
            data.update(project_id=self.project)
            return (
                data,
                report,
                {
                    "selections": [],
                    "context": {
                        "input": data,
                        "bindings": [],
                        "skill": {"instructions": "Fixed requirement Skill"},
                    },
                },
            )
        if kind == "code":
            data = sample("code-review/examples/input.json")
            report = sample("code-review/examples/output.json")
            return data, report, {"targets": data["targets"]}
        if kind == "changes":
            data = sample("change-impact/examples/requirement-input.json")
            report = sample("change-impact/examples/requirement-report.json")
            data.update(project_id=self.project)
            report.update(project_id=self.project)
            return data, report, {"targets": data["targets"], "mode": data["mode"]}
        data = {
            "request_id": str(uuid4()),
            "mode": "QUALITY",
            "cases": [{"id": 11}],
            "materials": [],
        }
        return data, test_case_analysis.report(11), {"mode": "QUALITY"}

    def make_record(self, kind, data, fields, config, *, status="RUNNING"):
        if kind != "requirements":
            fields.update(
                input_snapshot=data,
                metadata_snapshot={
                    "origin": "AI",
                    "skill": {"instructions": "固定示例 Skill", "contract_version": 2},
                    "execution_mode": "FULL_INPUT",
                },
            )
        with self.factory() as db:
            model = terminal_service.MODELS[kind]
            row = model(
                project_id=self.project,
                actor_id=self.member_id,
                title="合成原生终端",
                request_id=data["request_id"],
                status=status,
                ai_config=native_terminal.bind_snapshot(config),
                **fields,
            )
            db.add(row)
            db.flush()
            spec = terminal_service.terminal_spec(row)
            record_id = row.id
            db.commit()
        return record_id, spec

    def test_first_native_result_reaches_each_official_report(self):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("real Codex executable is unavailable")
        for kind, module in (
            ("requirements", requirements),
            ("code", code),
            ("changes", changes),
            ("coverage", coverage),
        ):
            with self.subTest(kind=kind), ExitStack() as stack:
                data, report, fields = self.fixture(kind)
                raw = json.dumps(report, ensure_ascii=False)
                provider = stack.enter_context(FakeProvider(text=raw))
                tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                local = SimpleNamespace(
                    ai_cli_work_path=tmp, ai_cli_executable=settings.ai_cli_executable
                )
                stack.enter_context(patch.object(codex_terminal, "Settings", return_value=local))
                stack.enter_context(
                    patch.dict(
                        os.environ,
                        {
                            name + "_ANALYSIS_RESULT_PATH": str(tmp / name)
                            for name in ("REQUIREMENT", "CODE", "CHANGE")
                        },
                    )
                )
                config = {
                    "base_url": provider.url,
                    "model": "gpt-6.1-sol",
                    "version": 1,
                    "reasoning_effort": "low",
                    "call_mode": "CODEX_EXEC",
                }
                stack.enter_context(
                    patch.object(
                        module,
                        "analysis_configuration",
                        return_value=(config, "SYNTHETIC-CLI-KEY"),
                    )
                )
                if kind == "requirements":
                    stack.enter_context(
                        patch.object(
                            module.risk_analysis_service, "frozen_materials", return_value=[]
                        )
                    )
                else:
                    stack.enter_context(patch.object(module.sources, "recheck"))
                    binary_method = "binaries" if kind == "coverage" else "frozen_binaries"
                    stack.enter_context(
                        patch.object(module.sources, binary_method, return_value=[])
                    )
                record_id, spec = self.make_record(kind, data, fields, config)
                module.execute(record_id, self.factory)
                self.assertEqual(len(provider.requests), 1)
                with self.factory() as db:
                    row = db.get(terminal_service.MODELS[kind], record_id)
                    self.assertEqual(row.status, "COMPLETED", row.error_code)
                    official = (
                        db.get(RequirementRiskReport, row.report_id)
                        if kind == "requirements"
                        else row
                    )
                    self.assertTrue(official.report)
                base = f"/api/projects/{self.project}/analysis-terminal/{kind}/{record_id}"
                session = self.client.get(base).json()["session"]
                self.assertEqual(session["turn_status"], "completed")
                self.assertTrue(session["resumable"])
                chunks = codex_terminal.output(spec["identity"], spec["execution"])["chunks"]
                self.assertIn("OpenAI Codex", "".join(chunks))
                self.assertEqual(self.client.get(base + "/results").json()["items"], [])

    def test_resume_identity_and_completed_candidate_rounds_are_record_owned(self):
        kind = "coverage"
        data, report, fields = self.fixture(kind)
        config = {"model": "gpt-6.1-sol", "call_mode": "CODEX_EXEC", "version": 1}
        key, spec = self.make_record(kind, data, fields, config, status="COMPLETED")
        base = f"/api/projects/{self.project}/analysis-terminal/{kind}/{key}"
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                codex_terminal, "Settings", return_value=SimpleNamespace(ai_cli_work_path=Path(tmp))
            ),
            patch.object(
                terminal_service, "analysis_configuration", return_value=(config, "synthetic")
            ),
        ):
            root = codex_terminal.directory(spec["identity"])
            (root / "input").mkdir(parents=True)
            (root / "input/input.json").write_text("{}", encoding="utf-8")
            (root / "output").mkdir()
            state = root / "state/sessions"
            state.mkdir(parents=True)
            thread = str(uuid4())
            rollout = state / f"rollout-{thread}.jsonl"
            cipher = codex_terminal.credential_cipher("ai_key_storage_unavailable")

            def event(execution, turn, *, status, method="turn/completed"):
                row = {"method": method, "status": status, "thread_id": thread, "turn_id": turn}
                with (root / "output" / f"{execution}.rpc.enc.jsonl").open("ab") as stream:
                    stream.write(cipher.encrypt(json.dumps(row).encode()) + b"\n")

            rollout.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": thread}}) + "\n"
            )
            event(spec["execution"], "first", status="running", method="turn/started")
            event(spec["execution"], "first", status="completed")
            request = {"request_id": str(uuid4()), "resume": True}
            first = self.client.post(base, json=request, headers=test_auth.ORIGIN)
            self.assertEqual(first.status_code, 202, first.text)
            execution_id = first.json()["session"]["id"]
            with self.factory() as db:
                row = db.get(AnalysisTerminalResume, execution_id)
                self.assertEqual((row.record_id, row.status), (key, "QUEUED"))
            repeat = self.client.post(base, json=request, headers=test_auth.ORIGIN)
            self.assertEqual(repeat.json()["session"]["id"], execution_id)
            for index, (turn, status, answer) in enumerate(
                (
                    ("first", "completed", report),
                    ("one", "completed", report),
                    ("two", "completed", {**report, "checked_case_ids": [99]}),
                    ("partial", "interrupted", report),
                )
            ):
                with rollout.open("a", encoding="utf-8") as stream:
                    for category, payload in (
                        ("event_msg", {"type": "task_started", "turn_id": turn}),
                        (
                            "response_item",
                            {
                                "type": "message",
                                "role": "assistant",
                                "phase": "final_answer",
                                "content": [{"text": json.dumps(answer)}],
                            },
                        ),
                        ("event_msg", {"type": "task_complete", "turn_id": turn}),
                    ):
                        stream.write(
                            json.dumps(
                                {
                                    "timestamp": f"2026-11-20T02:41:0{index}Z",
                                    "type": category,
                                    "payload": payload,
                                }
                            )
                            + "\n"
                        )
                if turn != "first":
                    event(execution_id, turn, status=status)
            items = self.client.get(base + "/results").json()["items"]
            self.assertEqual(len(items), 2)
            bad, good = [self.client.get(base + "/results/" + item["id"]).json() for item in items]
            self.assertTrue(bad["error_code"])
            self.assertEqual(good["counts"], {"用例问题": 1, "待澄清 / 准备": 0})
            stopped = self.client.post(f"{base}/{execution_id}/cancel", headers=test_auth.ORIGIN)
            self.assertEqual(stopped.json()["session"]["status"], "CANCELLED")
            self.assertEqual(self.client.get(base + "/results").json()["items"], items)
            with self.factory() as db:
                row = db.get(terminal_service.MODELS[kind], key)
                self.assertEqual(row.report, {})
                self.assertEqual(row.status, "COMPLETED")
            self.login()
            self.assertEqual(self.client.get(base).status_code, 403)
            self.assertEqual(self.client.get(base + "/results/" + items[0]["id"]).status_code, 403)
