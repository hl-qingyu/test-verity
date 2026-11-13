import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import test_requirements
from sqlalchemy.orm import Session

from app.db.models import (
    CaseAnalysisApplication,
    CaseAnalysisRun,
    CaseGenerationBatch,
    CaseGenerationRun,
    CodeAnalysisTask,
    ManagedCase,
    RequirementRiskAnalysis,
    RequirementRiskReport,
    SourceDocument,
)
from app.modules.overview import service


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL")
class OverviewDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_requirements.RequirementDatabaseTests.setUpClass.__func__)
    login = test_requirements.RequirementDatabaseTests.login
    setUp = test_requirements.RequirementDatabaseTests.setUp
    tearDown = test_requirements.RequirementDatabaseTests.tearDown

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def seed(self):
        now = datetime.now(UTC)
        with self.factory() as db:
            for purpose, deleted in [
                ("REQUIREMENT", False),
                ("PROTOTYPE", False),
                ("REQUIREMENT", True),
            ]:
                db.add(
                    SourceDocument(
                        project_id=self.project,
                        current_version=1,
                        purpose=purpose,
                        deleted_at=now if deleted else None,
                    )
                )
            for n, lifecycle, deleted in [
                (1, "ACTIVE", False),
                (2, "RETIRED", False),
                (3, "ACTIVE", True),
            ]:
                db.add(
                    ManagedCase(
                        project_id=self.project,
                        number=n,
                        current_version=1,
                        request_id=str(uuid4()),
                        created_by=self.member_id,
                        updated_by=self.member_id,
                        lifecycle=lifecycle,
                        deleted_at=now if deleted else None,
                    )
                )
            for i in range(25):
                db.add(
                    CodeAnalysisTask(
                        project_id=self.project,
                        actor_id=self.member_id,
                        request_id=str(uuid4()),
                        title=f"合成代码{i}",
                        targets=[],
                        input_snapshot={"never_return": "PRIVATE_BODY"},
                        ai_config={},
                        status="RUNNING" if i == 0 else "COMPLETED",
                        report={
                            "findings": [
                                {"key": "F1", "description": "PRIVATE_BODY"},
                                {"key": "F2"},
                            ],
                            "outcome": "PARTIAL",
                        },
                        handling={"F2": {"status": "RESOLVED", "note": "PRIVATE_BODY"}},
                        created_at=now + timedelta(minutes=i),
                    )
                )
            report = RequirementRiskReport(
                project_id=self.project,
                title="合成风险",
                input_filename="input.json",
                report_filename="report.json",
                sha256=uuid4().hex * 2,
                input={"never_return": "PRIVATE_BODY"},
                report={"risks": [{"key": "R1"}, {"key": "R2"}], "outcome": "PARTIAL"},
                bindings=[],
                created_by=self.member_id,
                handling={"R2": {"status": "NEEDS_INFO"}},
                created_at=now,
            )
            db.add(report)
            db.flush()
            self.report_id = report.id
            for i in range(2):
                db.add(
                    RequirementRiskAnalysis(
                        project_id=self.project,
                        actor_id=self.member_id,
                        request_id=str(uuid4()),
                        title="绑定同一报告",
                        selections=[],
                        ai_config={},
                        status="COMPLETED",
                        report_id=report.id,
                        created_at=now + timedelta(seconds=i),
                    )
                )
            run = CaseGenerationRun(
                project_id=self.project,
                actor_id=self.member_id,
                request_id=str(uuid4()),
                title="合成旧批次与人工候选",
                mode="INITIAL",
                status="FAILED",
                input_snapshot={"materials": []},
                handling={
                    "manual_suggestions": {"M": {"suggestion": {"key": "M"}}},
                    "suggestions": {"S1": [{"status": "已忽略"}, {"status": "已复用"}]},
                    "decisions": [{"questionKey": "Q1"}],
                    "failures": [{"key": "S1"}],
                },
            )
            db.add(run)
            db.flush()
            self.generation_id = run.id
            for i in range(21):
                db.add(
                    CaseGenerationRun(
                        project_id=self.project,
                        actor_id=self.member_id,
                        request_id=str(uuid4()),
                        title=f"后续未开始记录{i}",
                        mode="INITIAL",
                        status="PREPARED",
                        input_snapshot={"materials": []},
                        created_at=now - timedelta(days=2),
                    )
                )
            for i in range(2):
                db.add(
                    CaseGenerationBatch(
                        run_id=run.id,
                        batch_ref=f"B{i}",
                        request_id=str(uuid4()),
                        actor_id=self.member_id,
                        status="COMPLETED" if i == 0 else "FAILED",
                        report={
                            "suggestions": [{"key": "S1"}],
                            "requirement_questions": [{"key": "Q1"}, {"key": "Q2"}],
                            "outcome": "COMPLETE",
                        },
                    )
                )
            review = CaseAnalysisRun(
                project_id=self.project,
                actor_id=self.member_id,
                request_id=str(uuid4()),
                title="草案已应用但问题未关闭",
                mode="QUALITY",
                status="COMPLETED",
                input_snapshot={"cases": [{"id": 1, "body": "PRIVATE_BODY"}]},
                metadata_snapshot={},
                report={
                    "findings": [{"key": "F1"}],
                    "notes": [],
                    "complete": True,
                    "checked_case_ids": [1],
                },
                handling={
                    "F1": {"state": "待确认", "applied": {"case_id": 1}},
                    "manual": [{"key": "M1"}],
                },
            )
            db.add(review)
            db.flush()
            self.review_id = review.id
            db.add(
                CaseAnalysisApplication(
                    run_id=review.id,
                    project_id=self.project,
                    actor_id=self.member_id,
                    request_id=str(uuid4()),
                    fingerprint=uuid4().hex * 2,
                    status="COMPLETED",
                    items=[{"key": "F1", "status": "FAILED"}],
                )
            )
            db.add(
                CaseAnalysisApplication(
                    run_id=review.id,
                    project_id=self.project,
                    actor_id=self.member_id,
                    request_id=str(uuid4()),
                    fingerprint=uuid4().hex * 2,
                    status="COMPLETED",
                    items=[{"key": "F1", "status": "SUCCESS"}],
                )
            )
            db.commit()

    def read(self, query=""):
        response = self.client.get(f"/api/projects/{self.project}/overview{query}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["unavailable"], [])
        self.assertNotIn("PRIVATE_BODY", response.text)
        return response.json()

    def test_counts_scope_status_filtering_and_no_writes(self):
        self.seed()
        value = self.read()
        self.assertEqual(
            value["counts"],
            {
                "requirements": 1,
                "prototypes": 1,
                "cases": 1,
                "queued": 0,
                "running": 1,
            },
        )
        self.assertEqual(len(value["recent"]), 8)
        self.assertEqual([r["status"] for r in self.read("?filter=running")["recent"]], ["RUNNING"])
        self.assertTrue(
            all(r["status"] == "COMPLETED" for r in self.read("?filter=completed")["recent"])
        )
        self.assertEqual(len(self.read("?filter=failed")["recent"]), 1)
        self.assertEqual(self.client.get(f"/api/projects/{self.other}/overview").status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.project}/overview?filter=arbitrary").status_code,
            422,
        )
        self.assertEqual(
            self.client.post(f"/api/projects/{self.project}/overview").status_code, 405
        )
        with self.factory() as db:
            self.assertEqual(db.get(CaseGenerationRun, self.generation_id).status, "FAILED")
            self.assertEqual(db.get(CaseAnalysisRun, self.review_id).revision, 1)

    def test_adoption_aggregates_all_generation_runs_without_averaging_or_reading_bodies(self):
        now = datetime.now(UTC)
        with self.factory() as db:
            for i in range(25):
                run = CaseGenerationRun(
                    project_id=self.project,
                    actor_id=self.member_id,
                    request_id=str(uuid4()),
                    title=f"采纳统计合成记录{i}",
                    mode="INITIAL" if i == 0 else "UPDATE",
                    status="FAILED" if i == 0 else "COMPLETED" if i == 1 else "PREPARED",
                    metadata_snapshot={"origin": "IMPORT" if i == 1 else "AI"},
                    input_snapshot={"never_return": "PRIVATE_BODY"},
                    created_at=now + timedelta(minutes=i),
                )
                db.add(run)
                db.flush()
                if i > 1:
                    continue
                if i == 0:
                    self.adoption_run = run.id
                candidates = [
                    {"key": f"C{n}", "kind": "UPDATE" if n else "NEW", "design": "PRIVATE_BODY"}
                    for n in range(2 if i == 0 else 8)
                ]
                candidates += [
                    {"key": "R", "kind": "REUSE"},
                    {"key": "T", "kind": "RETIRE"},
                    {"key": "manual:forged", "kind": "NEW"},
                ]
                run.handling = {
                    "manual_suggestions": {"manual:M": {"suggestion": {"key": "manual:M"}}},
                    "suggestions": {
                        "C0": [
                            {"status": "需人工确认"},
                            {"status": "已应用"},
                            {"status": "已应用"},
                        ],
                        "C1": [{"status": "需人工确认" if i == 0 else "已忽略"}],
                        "C2": [{"status": "待审阅", "draft": "PRIVATE_BODY"}],
                        "C3": [{"status": "已复用"}],
                        "R": [{"status": "已复用"}],
                        "T": [{"status": "已应用"}],
                        "manual:forged": [{"status": "已应用"}],
                        "manual:M": [{"status": "已应用"}],
                    },
                }
                for n, status in enumerate(["COMPLETED", "FAILED"]):
                    db.add(
                        CaseGenerationBatch(
                            run_id=run.id,
                            batch_ref=f"B{n}",
                            request_id=str(uuid4()),
                            actor_id=self.member_id,
                            status=status,
                            report={"suggestions": candidates, "outcome": "PARTIAL"},
                        )
                    )
            foreign = CaseGenerationRun(
                project_id=self.other,
                actor_id=self.admin_id,
                request_id=str(uuid4()),
                title="另一个项目",
                mode="INITIAL",
                status="COMPLETED",
                input_snapshot={},
                handling={"suggestions": {"F": [{"status": "已应用"}]}},
            )
            db.add(foreign)
            db.flush()
            db.add(
                CaseGenerationBatch(
                    run_id=foreign.id,
                    batch_ref="B1",
                    request_id=str(uuid4()),
                    actor_id=self.admin_id,
                    status="COMPLETED",
                    report={"suggestions": [{"key": "F", "kind": "NEW"}]},
                )
            )
            db.commit()
        for filter_name in ["all", "running", "completed", "failed"]:
            value = self.read(f"?filter={filter_name}")
            self.assertNotIn("generation_candidates", value["counts"])
            self.assertNotIn("generation_adopted", value["counts"])
            self.assertNotIn("adoption:TOTAL", str(value))
            if filter_name == "all":
                self.assertEqual(len(value["recent"]), 8)
                self.assertNotIn(self.adoption_run, [r["record_id"] for r in value["recent"]])
        acceptance_url = f"/api/projects/{self.project}/analysis-acceptance"
        self.assertEqual(self.client.get(acceptance_url).status_code, 403)
        self.login(self.admin_name)
        aggregate = self.client.get(acceptance_url)
        self.assertEqual(aggregate.status_code, 200, aggregate.text)
        generate = next(g for g in aggregate.json()["modules"] if g["module"] == "generate")[
            "metrics"
        ]
        self.assertEqual((generate["total"], generate["adopted"]), (10, 2))
        with self.factory() as db:
            run = db.get(CaseGenerationRun, self.adoption_run)
            run.handling = {
                **run.handling,
                "suggestions": {**run.handling["suggestions"], "C1": [{"status": "已应用"}]},
            }
            db.commit()
        generate = next(
            g
            for g in self.client.get(acceptance_url).json()["modules"]
            if g["module"] == "generate"
        )["metrics"]
        self.assertEqual(generate["adopted"], 3)

    def test_handling_manual_candidates_questions_and_paged_targets(self):
        self.seed()
        value = self.read()
        groups = {g["module"]: g for g in value["attention"]}
        self.assertEqual([p["count"] for p in groups["requirements"]["parts"]], [1, 1])
        self.assertEqual([p["count"] for p in groups["generate"]["parts"]], [1, 1])
        self.assertEqual([p["count"] for p in groups["coverage"]["parts"]], [2, 0])
        self.assertEqual(groups["code"]["parts"][0]["count"], 24)
        url = f"/api/projects/{self.project}/overview/attention"
        first = self.client.get(
            url, params={"module": "code", "group": "findings", "state": "PENDING", "page": 1}
        ).json()
        second = self.client.get(
            url, params={"module": "code", "group": "findings", "state": "PENDING", "page": 2}
        ).json()
        self.assertEqual((first["total"], len(first["items"]), len(second["items"])), (24, 20, 4))
        self.assertFalse(
            {r["record_id"] for r in first["items"]} & {r["record_id"] for r in second["items"]}
        )
        page = self.client.get(
            url, params={"module": "requirements", "group": "risks", "state": "PENDING"}
        ).json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["record_id"], self.report_id)
        self.assertEqual(page["items"][0]["record_type"], "report")
        review = self.client.get(
            url, params={"module": "coverage", "group": "findings", "state": "待确认"}
        ).json()["items"][0]
        self.assertFalse(review["application_failed"])
        self.assertEqual(
            self.client.get(
                url, params={"module": "code", "group": "risks", "state": "PENDING"}
            ).status_code,
            422,
        )
        summary = self.client.get(
            f"/api/projects/{self.project}/case-generation",
            params={"summary": True, "run_id": self.generation_id},
        )
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["items"][0]["id"], str(self.generation_id))
        first_page = self.client.get(
            f"/api/projects/{self.project}/case-generation", params={"summary": True}
        ).json()
        self.assertNotIn(str(self.generation_id), {r["id"] for r in first_page["items"]})

    def test_partial_module_failure_never_claims_zero_or_hides_other_modules(self):
        def unavailable(*args):
            raise ValueError("synthetic private error")

        with patch.dict(service.PROVIDERS, {"code": unavailable}):
            response = self.client.get(f"/api/projects/{self.project}/overview")
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            self.assertEqual(value["unavailable"], ["code"])
            self.assertIsNone(value["counts"]["running"])
            self.assertNotIn("generation_candidates", value["counts"])
            self.assertNotIn("generation_adopted", value["counts"])
            self.assertIsNone(
                next(g for g in value["attention"] if g["module"] == "code")["parts"][0]["count"]
            )
            self.assertNotIn("synthetic private error", response.text)
            self.assertEqual(
                self.client.get(
                    f"/api/projects/{self.project}/overview/attention",
                    params={"module": "code", "group": "findings", "state": "PENDING"},
                ).status_code,
                503,
            )
        with patch.dict(service.PROVIDERS, {"generate": unavailable}):
            value = self.client.get(f"/api/projects/{self.project}/overview").json()
            self.assertNotIn("generation_candidates", value["counts"])
            self.assertNotIn("generation_adopted", value["counts"])
