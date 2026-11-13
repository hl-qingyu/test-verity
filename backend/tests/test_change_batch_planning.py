import copy
import hashlib
import json
import unittest
from pathlib import Path

from app.modules.change_analysis import batch_planning, contract

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/change-impact/examples"


def unit(uid, name, text):
    return {
        "unit_id": uid,
        "path": name,
        "presence": "PRESENT",
        "read_state": "READABLE",
        "read_note": "",
        "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "segments": [
            {"segment_id": "full", "location": name, "start_line": 1, "text": text, "image_ref": ""}
        ],
    }


def fixture(files):
    data = json.loads((EXAMPLES / "code-input.json").read_text(encoding="utf-8"))
    pair = data["comparison_pairs"][0]
    pair.update(unit_mappings=[], text_diffs=[], scope=[])
    for s in data["snapshots"]:
        s["units"] = []
    for n, (name, before, after) in enumerate(files, 1):
        pair["scope"].append(name)
        uid, mapping = f"u{n}", f"m{n}"
        for snapshot, text in zip(data["snapshots"], (before, after), strict=True):
            snapshot["units"].append(unit(uid, name, text))
        pair["unit_mappings"].append(
            {
                "mapping_id": mapping,
                "before_unit_ids": [uid],
                "after_unit_ids": [uid],
                "relation": "MATCH",
                "confirmed": True,
                "note": "fixed pair",
            }
        )
        if before != after:
            pair["text_diffs"].append(
                {
                    "diff_id": f"d{n}",
                    "mapping_ref": mapping,
                    "before_segment_refs": [{"unit_id": uid, "segment_id": "full"}],
                    "after_segment_refs": [{"unit_id": uid, "segment_id": "full"}],
                    "note": "fixed diff",
                }
            )
    return data


def context(data, ref, text):
    template = copy.deepcopy(data["snapshots"][0])
    value = unit("rule", ref + ".md", text)
    value["segments"][0]["start_line"] = None
    template.update(
        snapshot_ref=ref, source_id=ref, kind="REQUIREMENT", repository_kind="NONE", units=[value]
    )
    data["snapshots"].append(template)
    data["context_refs"].append(ref)


def keys(batch):
    return {tuple(k) for k in batch["mappings"]}


class ChangeBatchPlanningTests(unittest.TestCase):
    def validate(self, data, plan):
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        self.assertEqual(plan["version"], 2)
        self.assertTrue(
            all(r["review_batch_ids"] for r in plan["relations"] if r["review_required"])
        )
        for b in plan["batches"]:
            if b["callable"]:
                contract.validate_input(
                    contract.AnalysisInput.model_validate(batch_planning.input_for(data, b))
                )

    def test_multilevel_dependencies_and_changed_callers_are_kept_together(self):
        data = fixture(
            [
                (
                    "Alpha.java",
                    "class Alpha { Beta value; }",
                    "class Alpha { Beta value; int changed; }",
                ),
                ("Beta.java", "class Beta { Gamma value; }", "class Beta { Gamma value; }"),
                ("Gamma.java", "class Gamma { int before; }", "class Gamma { int after; }"),
            ]
        )
        original = copy.deepcopy(data)
        _, _, nodes, _ = batch_planning._nodes(data)
        budget = sum(n["weight"] for n in nodes.values()) + 1
        plan = batch_planning.plan(data, budget)
        self.validate(data, plan)
        self.assertTrue(
            any({("p1", "m1"), ("p1", "m2"), ("p1", "m3")} <= keys(b) for b in plan["batches"])
        )
        self.assertEqual(data, original)

    def test_shared_dependency_is_repeated_and_split_relations_have_fixed_checks(self):
        padding = "\n//" + "p" * 2000
        data = fixture(
            [
                (
                    "Alpha.java",
                    "class Alpha { Shared value; }" + padding,
                    "class Alpha { Shared value; int changed; }" + padding,
                ),
                ("Shared.java", "class Shared { int state; }", "class Shared { int state; }"),
                (
                    "Zeta.java",
                    "class Zeta { Shared value; }" + padding,
                    "class Zeta { Shared value; int changed; }" + padding,
                ),
            ]
        )
        plan = batch_planning.plan(data, 2500)
        self.validate(data, plan)
        analyses = [b for b in plan["batches"] if b["kind"] == "ANALYSIS"]
        for primary in (("p1", "m1"), ("p1", "m3")):
            self.assertTrue(any(primary in keys(b) and ("p1", "m2") in keys(b) for b in analyses))
        # Make each step large enough that an entire path cannot fit one ordinary batch.
        data = fixture(
            [
                (
                    f"{name}.java",
                    f"class {name} {{ {dep} value; }}" + padding,
                    f"class {name} {{ {dep} value; int changed; }}" + padding,
                )
                for name, dep in (("Alpha", "Beta"), ("Beta", "Gamma"), ("Gamma", "String"))
            ]
        )
        plan = batch_planning.plan(data, 2500)
        self.validate(data, plan)
        self.assertTrue(
            any(b["kind"] == "INTEGRATION" and b["depends_on"] for b in plan["batches"])
        )
        for relation in plan["relations"]:
            self.assertTrue(
                any(
                    tuple(relation["from"]) in keys(b) and tuple(relation["to"]) in keys(b)
                    for b in plan["batches"]
                )
            )

    def test_real_http_consumer_replaces_arbitrary_frontend_role_filler(self):
        data = fixture(
            [
                (
                    "OrderController.java",
                    '@RestController class OrderController { @GetMapping("/orders") '
                    'String value() { return "amount"; } }',
                    '@RestController class OrderController { @GetMapping("/orders") '
                    'String value() { return "total"; } }',
                ),
            ]
        )
        web_pair = copy.deepcopy(data["comparison_pairs"][0])
        web_pair.update(
            pair_id="web",
            before_ref="web-old",
            after_ref="web-new",
            unit_mappings=[],
            text_diffs=[],
            scope=[],
        )
        for n, name in enumerate(("AppConfig.ts", "OrderPage.ts"), 1):
            web_pair["scope"].append(name)
            web_pair["unit_mappings"].append(
                {
                    "mapping_id": f"w{n}",
                    "before_unit_ids": [f"w{n}"],
                    "after_unit_ids": [f"w{n}"],
                    "relation": "MATCH",
                    "confirmed": True,
                    "note": "fixed",
                }
            )
        for ref, version in (("web-old", "old"), ("web-new", "new")):
            s = copy.deepcopy(data["snapshots"][0])
            s.update(
                snapshot_ref=ref,
                source_id="web-source",
                repository_kind="WEB",
                units=[
                    unit("w1", "AppConfig.ts", "export const appName = 'x';"),
                    unit(
                        "w2", "OrderPage.ts", "fetch('/orders').then(response => response.amount);"
                    ),
                ],
            )
            s["provenance"]["version_ref"] = version
            data["snapshots"].append(s)
        data["comparison_pairs"].append(web_pair)
        data["targets"] = ["FRONTEND_BACKEND_MISMATCH"]
        plan = batch_planning.plan(data, 1000)
        self.validate(data, plan)
        self.assertTrue(all(("web", "w2") in keys(b) for b in plan["batches"] if b["callable"]))
        self.assertTrue(all(("web", "w1") not in keys(b) for b in plan["batches"]))

    def test_rule_packet_and_cases_stay_together_even_above_soft_budget(self):
        data = fixture([("Alpha.java", "class Alpha {}", "class Alpha { int changed; }")])
        context(data, "rule-a", "规则A" * 25000)
        context(data, "rule-b", "规则B" * 25000)
        data["cases"] = [
            {
                "case_ref": "c1",
                "case_id": 1,
                "design_version": 1,
                "library_revision": 1,
                "display_number": "TC-1",
                "title": "合成用例",
                "design": {
                    "preconditions": "规则A和B",
                    "data_requirements": "",
                    "steps": "执行",
                    "expected": "规则组合满足",
                },
            }
        ]
        plan = batch_planning.plan(data, 1000)
        self.validate(data, plan)
        for b in plan["batches"]:
            subset = batch_planning.input_for(data, b)
            self.assertEqual(subset["cases"], data["cases"])
            self.assertEqual(set(subset["context_refs"]), {"rule-a", "rule-b"})
            self.assertTrue(b["oversized"])
        self.assertEqual(len(plan["batches"]), 1)

    def test_missing_actual_http_pair_blocks_only_requested_consistency_target(self):
        data = fixture([("Alpha.java", "class Alpha {}", "class Alpha { int changed; }")])
        web = copy.deepcopy(data["snapshots"][0])
        web.update(
            snapshot_ref="web",
            source_id="web",
            repository_kind="WEB",
            units=[unit("w1", "AppConfig.ts", "export const appName = 'x';")],
        )
        data["snapshots"].append(web)
        data["context_refs"].append("web")
        data["targets"] = ["FRONTEND_BACKEND_MISMATCH"]
        plan = batch_planning.plan(data, 1)
        self.validate(data, plan)
        self.assertTrue(all(not b["callable"] and b["status"] == "FAILED" for b in plan["batches"]))
        data["targets"] = ["BUG", "FRONTEND_BACKEND_MISMATCH"]
        plan = batch_planning.plan(data, 1)
        self.validate(data, plan)
        self.assertEqual(batch_planning.input_for(data, plan["batches"][0])["targets"], ["BUG"])

    def test_explicit_import_disambiguates_same_named_classes_and_ignores_resource_prose(self):
        before = "package a; import b.Service; class Alpha { Service value; }"
        data = fixture(
            [
                ("a/Alpha.java", before, before + "\n// changed"),
                ("b/Service.java", "package b; class Service {}", "package b; class Service {}"),
                ("c/Service.java", "package c; class Service {}", "package c; class Service {}"),
                (
                    "application.yaml",
                    "example: 'class Alpha Service'",
                    "example: 'class Alpha Service'",
                ),
                ("notes.md", "class Alpha references Service", "class Alpha references Service"),
            ]
        )
        plan = batch_planning.plan(data, 1000)
        self.validate(data, plan)
        selected = set().union(*(keys(b) for b in plan["batches"]))
        self.assertIn(("p1", "m2"), selected)
        self.assertNotIn(("p1", "m3"), selected)
        self.assertNotIn(("p1", "m4"), selected)
        self.assertNotIn(("p1", "m5"), selected)

    def test_http_matching_uses_class_prefix_and_method_and_normalizes_path_parameters(self):
        backend = (
            '@RequestMapping("/api/orders") class Orders { @GetMapping("/{id}") String read() {} }'
        )
        self.assertIn(("GET", "/api/orders/{}"), batch_planning._endpoints(backend))
        client = "fetch('/api/orders/${orderId}', {method:'POST'});"
        self.assertIn(("POST", "/api/orders/{}"), batch_planning._endpoints(client))
        self.assertFalse(batch_planning._endpoints("fetch('https://[not-an-address');"))

    def test_requirement_analysis_keeps_explicit_code_and_rules_with_selected_cases(self):
        data = fixture([("requirements.md", "old business", "new business")])
        for s in data["snapshots"]:
            s.update(kind="REQUIREMENT", repository_kind="NONE")
            for u in s["units"]:
                for seg in u["segments"]:
                    seg["start_line"] = None
        data["mode"], data["targets"] = "REQUIREMENT_CHANGE", ["IMPLEMENTATION_FOLLOWUP"]
        data["comparison_pairs"][0]["update_mode"] = "FULL_REPLACEMENT"
        code = copy.deepcopy(data["snapshots"][0])
        code.update(
            snapshot_ref="implementation",
            source_id="code",
            kind="CODE",
            repository_kind="BACKEND",
            units=[unit("impl", "Implementation.java", "class Implementation {}")],
        )
        data["snapshots"].append(code)
        data["context_refs"].append("implementation")
        context(data, "decision", "new business applies to implementation")
        plan = batch_planning.plan(data, 1000)
        self.validate(data, plan)
        for batch in plan["batches"]:
            subset = batch_planning.input_for(data, batch)
            self.assertEqual(set(subset["context_refs"]), {"implementation", "decision"})

    def test_default_budget_keeps_a_complete_path_that_crossed_the_old_half_megabyte_target(self):
        padding = "\n// " + "x" * 160000
        files = [
            (
                "Alpha.java",
                "class Alpha { Beta value; }" + padding,
                "class Alpha { Beta value; int changed; }" + padding,
            ),
            (
                "Beta.java",
                "class Beta { Gamma value; }" + padding,
                "class Beta { Gamma value; }" + padding,
            ),
            ("Gamma.java", "class Gamma {}" + padding, "class Gamma {}" + padding),
            ("Unrelated.java", "class Unrelated {}" + padding, "class Unrelated {}" + padding),
        ]
        data = fixture(files)
        self.assertGreater(batch_planning._size(data), 512 * 1024)
        plan = batch_planning.plan(data)
        self.validate(data, plan)
        self.assertEqual(len(plan["batches"]), 1)
        self.assertEqual(plan["batches"][0]["kind"], "ANALYSIS")
        self.assertEqual(keys(plan["batches"][0]), {("p1", "m1"), ("p1", "m2"), ("p1", "m3")})

    def test_a_snapshot_used_as_comparison_and_context_is_kept_once_with_both_roles(self):
        data = fixture([("Alpha.java", "class Alpha {}", "class Alpha { int changed; }")])
        data["context_refs"] = ["code-new"]
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        plan = batch_planning.plan(data, 1)
        batch = copy.deepcopy(plan["batches"][0])
        batch["context_units"] = {"code-new": ["u1"]}
        subset = batch_planning.input_for(data, batch)
        contract.validate_input(contract.AnalysisInput.model_validate(subset))
        self.assertEqual(subset["context_refs"], ["code-new"])
        self.assertEqual([s["snapshot_ref"] for s in subset["snapshots"]].count("code-new"), 1)
        self.assertEqual(subset["snapshots"][1]["units"], data["snapshots"][1]["units"])

    def test_one_paired_endpoint_cannot_hide_an_unpaired_change_in_the_same_batch(self):
        before = 'class OrderController { @GetMapping("/orders") String read() { return "old"; } }'
        data = fixture(
            [
                ("OrderController.java", before, before.replace('"old"', '"new"')),
                ("Private.java", "class Private {}", "class Private { int changed; }"),
                (
                    "Unrelated.java",
                    "class Unrelated {}\n//" + "x" * 10000,
                    "class Unrelated {}\n//" + "x" * 10000,
                ),
            ]
        )
        web = copy.deepcopy(data["snapshots"][0])
        web.update(
            snapshot_ref="consumer",
            source_id="web",
            repository_kind="WEB",
            units=[unit("page", "OrderPage.ts", "fetch('/orders').then(x => x.amount);")],
        )
        data["snapshots"].append(web)
        data["context_refs"].append("consumer")
        data["targets"] = ["BUG", "FRONTEND_BACKEND_MISMATCH"]
        plan = batch_planning.plan(data, 10000)
        self.validate(data, plan)
        batch = next(b for b in plan["batches"] if {("p1", "m1"), ("p1", "m2")} <= keys(b))
        self.assertEqual(batch["unpaired_primary"], [["p1", "m2"]])
        self.assertEqual(batch["blocked_targets"], ["FRONTEND_BACKEND_MISMATCH"])
        self.assertEqual(batch_planning.input_for(data, batch)["targets"], ["BUG"])
        self.assertTrue(batch["callable"])
