"""Offline fixture checks, not a production API validator or an AI evaluation."""

import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"BUG", "REQUIREMENT_DEVIATION", "FRONTEND_BACKEND_MISMATCH"}
FINDING_FIELDS = set(
    "key target_refs title category severity severity_reason evidence_state trigger actual impact evidence_refs chain_refs target_views fix_suggestion verification_suggestion missing_evidence".split()
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(values):
    require(len(values) == len(set(values)), "duplicate identifier or reference")
    return set(values)


def indexed(items, key="key"):
    keys = [item[key] for item in items]
    unique(keys)
    require(all(isinstance(k, str) and k for k in keys), "empty identifier")
    return dict(zip(keys, items))


def references(values, allowed, nonempty=False):
    require(unique(values) <= set(allowed), "unknown reference")
    require(not nonempty or bool(values), "missing required reference")


def validate_input(data):
    require(
        data["contract_version"] == 2 and data["analysis_type"] == "CODE_REVIEW",
        "v2 required",
    )
    require(bool(data["request_id"]), "request id required")
    targets = unique(data["targets"])
    require(bool(targets) and targets <= TARGETS, "invalid targets")
    require(data["source_mode"] in {"GITHUB", "LOCAL"}, "invalid source mode")
    sources = indexed(data["sources"], "source_id")
    materials = indexed(data["materials"], "source_id")
    require(not sources.keys() & materials.keys(), "source identities overlap")
    segments, reads, expected_coverage, readable_roles = {}, {}, set(), set()
    for source in data["sources"]:
        require(source["source_kind"] == data["source_mode"], "mixed source modes")
        require(
            source["repository_kind"] in {"BACKEND", "WEB", "FLUTTER", "OTHER"},
            "invalid repository type",
        )
        if source["source_kind"] == "GITHUB":
            require(
                bool(re.fullmatch(r"[0-9a-fA-F]{40}", source["commit"])),
                "fixed commit required",
            )
        else:
            require(source["commit"] == "", "local snapshot is not a git commit")
        indexed(source["files"], "file_id")
    units = [
        ("CODE", source, file) for source in data["sources"] for file in source["files"]
    ]
    units += [("MATERIAL", material, material) for material in data["materials"]]
    for kind, source, item in units:
        sid, fid = source["source_id"], item["file_id"] if kind == "CODE" else ""
        if kind == "CODE":
            path = item["path"].replace("\\", "/")
            require(
                path
                and not path.startswith("/")
                and ":" not in path
                and ".." not in path.split("/"),
                "invalid relative path",
            )
        else:
            require(
                source["origin"]
                in {"REQUIREMENT", "PROTOTYPE", "CONTRACT", "DECISION"},
                "invalid material origin",
            )
        state = item["read_state"]
        require(
            state in {"READABLE", "PARTIAL", "UNREADABLE", "NOT_LOADED"},
            "invalid read state",
        )
        require(state == "READABLE" or bool(item["read_note"]), "missing read reason")
        require(
            bool(item["segments"]) == (state in {"READABLE", "PARTIAL"}),
            "read state contradicts segments",
        )
        require(
            not item["segments"] or bool(source["snapshot_ref"]), "snapshot required"
        )
        indexed(item["segments"], "segment_id")
        if kind == "CODE" and item["segments"]:
            readable_roles.add(source["repository_kind"])
        previous_end = 0
        for segment in item["segments"]:
            key = (kind, sid, fid, segment["segment_id"])
            segments[key] = segment
            if kind == "CODE":
                start = segment["start_line"]
                require(
                    type(start) is int
                    and start > previous_end
                    and bool(segment["text"]),
                    "invalid code range",
                )
                require("\r" not in segment["text"], "code newlines must be LF")
                if state == "READABLE":
                    require(start == previous_end + 1, "full file has omitted lines")
                previous_end = start + len(segment["text"].split("\n")) - 1
            else:
                require(
                    bool(segment["text"] or segment["image_ref"])
                    and bool(segment["location"]),
                    "empty material segment",
                )
        for segment in item["segments"] or [{"segment_id": ""}]:
            key = (kind, sid, fid, segment["segment_id"])
            expected_coverage.add(key)
            reads[key] = state
    if "FRONTEND_BACKEND_MISMATCH" in targets:
        require(
            "BACKEND" in readable_roles and bool(readable_roles & {"WEB", "FLUTTER"}),
            "consistency requires readable code from both roles",
        )
    return sources, materials, segments, reads, expected_coverage


def validate_pair(data, report):
    sources, materials, segments, reads, expected_coverage = validate_input(data)
    require(
        set(report)
        == set(
            "contract_version analysis_type request_id outcome summary target_results findings evidence chains coverage limitations".split()
        ),
        "unexpected report fields",
    )
    require(
        report["contract_version"] == 2 and report["analysis_type"] == "CODE_REVIEW",
        "report version mismatch",
    )
    require(report["request_id"] == data["request_id"], "request mismatch")
    targets = indexed(report["target_results"], "target")
    require(set(targets) == set(data["targets"]), "selected targets must match results")
    findings, evidence, chains, limits = (
        indexed(report[name])
        for name in ("findings", "evidence", "chains", "limitations")
    )
    indexed([check for target in targets.values() for check in target["checks"]])
    references(report["summary"]["priority_finding_keys"], findings)
    code_keys = {key for key, e in evidence.items() if e["kind"] == "CODE"}
    for e in evidence.values():
        require(e["kind"] in {"CODE", "MATERIAL"}, "invalid evidence kind")
        key = (e["kind"], e["source_id"], e.get("file_id", ""), e["segment_id"])
        require(key in segments, "evidence outside supplied content")
        segment = segments[key]
        if e["kind"] == "CODE":
            start, end = (
                e["start_line"] - segment["start_line"],
                e["end_line"] - segment["start_line"],
            )
            lines = segment["text"].split("\n")
            require(0 <= start <= end < len(lines), "evidence line out of bounds")
            require(
                e["excerpt"] == "\n".join(lines[start : end + 1]),
                "code excerpt mismatch",
            )
        else:
            require(e["excerpt"] in segment["text"], "material excerpt mismatch")
            require(bool(e["excerpt"] or e["observation"]), "empty material evidence")
    for limit in limits.values():
        references(limit["target_refs"], targets, True)
        references(limit["source_refs"], sources.keys() | materials.keys())
    for chain in chains.values():
        nodes = indexed(chain["nodes"])
        require(bool(nodes), "empty chain")
        for node in nodes.values():
            references(node["evidence_refs"], code_keys, True)
        for edge in chain["edges"]:
            require(
                edge["from"] in nodes
                and edge["to"] in nodes
                and edge["from"] != edge["to"],
                "invalid chain endpoints",
            )
            require(
                edge["relation"]
                in {"CALL", "RETURN", "FIELD_MAPPING", "STATE_ASSIGNMENT", "UNKNOWN"},
                "invalid relation",
            )
            references(edge["evidence_refs"], code_keys, edge["relation"] != "UNKNOWN")
            require(bool(edge["note"]), "relation explanation required")
    for finding in findings.values():
        require(
            set(finding) == FINDING_FIELDS,
            "unexpected finding field, including manual state",
        )
        references(finding["target_refs"], targets, True)
        references(finding["evidence_refs"], evidence, True)
        references(finding["chain_refs"], chains)
        require(
            finding["severity"] in {"HIGH", "MEDIUM", "LOW", "UNASSESSED"},
            "invalid severity",
        )
        views = indexed(finding["target_views"], "target")
        require(set(views) == set(finding["target_refs"]), "missing target view")
        for target, view in views.items():
            require(
                view["evidence_state"] in {"STATIC_SUPPORTED", "INSUFFICIENT"},
                "invalid evidence state",
            )
            references(view["evidence_refs"], finding["evidence_refs"], True)
            references(view["basis_refs"], finding["evidence_refs"])
            if target == "REQUIREMENT_DEVIATION":
                require(
                    any(
                        evidence[k]["kind"] == "MATERIAL"
                        and materials[evidence[k]["source_id"]]["origin"]
                        in {"REQUIREMENT", "PROTOTYPE", "DECISION"}
                        for k in view["basis_refs"]
                    ),
                    "requirement basis missing",
                )
            if (
                target == "FRONTEND_BACKEND_MISMATCH"
                and view["evidence_state"] == "STATIC_SUPPORTED"
            ):
                roles = {
                    sources[evidence[k]["source_id"]]["repository_kind"]
                    for k in view["evidence_refs"]
                    if k in code_keys
                }
                require(
                    "BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}),
                    "comparison lacks two code roles",
                )
            require(
                target == "BUG" or bool(view["comparison_rows"]),
                "comparison rows required",
            )
            for row in view["comparison_rows"]:
                for side in ("left", "right"):
                    references(row[side]["evidence_refs"], finding["evidence_refs"])
        aggregate = (
            "INSUFFICIENT"
            if any(v["evidence_state"] == "INSUFFICIENT" for v in views.values())
            else "STATIC_SUPPORTED"
        )
        require(
            finding["evidence_state"] == aggregate,
            "finding certainty must preserve uncertainty",
        )
        require(
            aggregate != "INSUFFICIENT" or bool(finding["missing_evidence"]),
            "missing evidence explanation required",
        )
    statuses = []
    for target, result in targets.items():
        status = result["status"]
        require(status in {"COMPLETE", "PARTIAL", "BLOCKED"}, "invalid target status")
        statuses.append(status)
        references(result["limitation_refs"], limits, status != "COMPLETE")
        require(
            all(target in limits[k]["target_refs"] for k in result["limitation_refs"]),
            "limitation target mismatch",
        )
        associated = {key for key, f in findings.items() if target in f["target_refs"]}
        require(
            unique(result["finding_refs"]) == associated,
            "finding/target association mismatch",
        )
        check_findings = set()
        for check in result["checks"]:
            require(
                check["assessment"]
                in {
                    "CONSISTENT",
                    "DEVIATION",
                    "SUSPECTED",
                    "UNRESOLVED",
                    "OUT_OF_SCOPE",
                },
                "invalid assessment",
            )
            references(
                check["evidence_refs"],
                evidence,
                check["assessment"] in {"CONSISTENT", "DEVIATION", "SUSPECTED"},
            )
            references(
                check["finding_refs"],
                associated,
                check["assessment"] in {"DEVIATION", "SUSPECTED"},
            )
            require(
                check["assessment"] != "CONSISTENT" or not check["finding_refs"],
                "consistent check cannot assert defect",
            )
            states = [
                next(v for v in findings[k]["target_views"] if v["target"] == target)[
                    "evidence_state"
                ]
                for k in check["finding_refs"]
            ]
            require(
                check["assessment"] != "DEVIATION"
                or all(s == "STATIC_SUPPORTED" for s in states),
                "unproven deviation",
            )
            require(
                check["assessment"] != "SUSPECTED" or "INSUFFICIENT" in states,
                "suspected check without uncertainty",
            )
            check_findings.update(check["finding_refs"])
        require(check_findings == associated, "checks do not cover associated findings")
        require(
            status != "BLOCKED" or not result["checks"] and not associated,
            "blocked target contains conclusions",
        )
    expected_outcome = (
        "COMPLETE"
        if all(s == "COMPLETE" for s in statuses)
        else "BLOCKED"
        if all(s == "BLOCKED" for s in statuses)
        else "PARTIAL"
    )
    require(report["outcome"] == expected_outcome, "outcome mismatch")
    coverage_keys = []
    for entry in report["coverage"]:
        key = (entry["kind"], entry["source_id"], entry["file_id"], entry["segment_id"])
        coverage_keys.append(key)
        require(key in expected_coverage, "foreign coverage")
        require(
            set(indexed(entry["targets"], "target")) == set(targets),
            "coverage target mismatch",
        )
        for record in entry["targets"]:
            target, disposition = record["target"], record["disposition"]
            require(
                disposition in {"REVIEWED", "NOT_RELEVANT", "UNPROCESSED"},
                "invalid disposition",
            )
            target_checks = {c["key"] for c in targets[target]["checks"]}
            references(record["check_refs"], target_checks, disposition == "REVIEWED")
            require(
                disposition == "REVIEWED" or not record["check_refs"],
                "unreviewed checks",
            )
            require(
                disposition != "UNPROCESSED" or targets[target]["status"] != "COMPLETE",
                "unprocessed content declared complete",
            )
            if reads[key] in {"UNREADABLE", "NOT_LOADED"}:
                require(
                    disposition == "UNPROCESSED",
                    "unread content cannot be reviewed or irrelevant",
                )
            if reads[key] == "PARTIAL" and disposition != "NOT_RELEVANT":
                require(
                    targets[target]["status"] != "COMPLETE",
                    "partial source declared complete",
                )
    require(unique(coverage_keys) == expected_coverage, "coverage is incomplete")
    return True


def expect_invalid(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Invalid fixture was accepted")


def main():
    pairs = []
    for prefix in ("", "local-"):
        data, report = [
            json.loads(
                (ROOT / "examples" / f"{prefix}{name}.json").read_text(encoding="utf-8")
            )
            for name in ("input", "output")
        ]
        validate_pair(data, report)
        pairs.append((data, report))
    data, report = pairs[0]
    bad = copy.deepcopy(data)
    bad["sources"] = [s for s in bad["sources"] if s["repository_kind"] == "BACKEND"]
    expect_invalid(lambda: validate_input(bad))
    bad = copy.deepcopy(data)
    bad["sources"][0]["repository_kind"] = "OTHER"
    expect_invalid(lambda: validate_input(bad))
    bad = copy.deepcopy(data)
    bad["sources"][0]["files"] = []
    expect_invalid(lambda: validate_input(bad))
    bad = copy.deepcopy(data)
    bad["sources"][0]["source_kind"] = "LOCAL"
    expect_invalid(lambda: validate_input(bad))
    for field, value in (
        ("excerpt", "invented"),
        ("end_line", 999),
        ("source_id", "unread-source"),
    ):
        invalid = copy.deepcopy(report)
        invalid["evidence"][0][field] = value
        expect_invalid(lambda: validate_pair(data, invalid))
    invalid = copy.deepcopy(report)
    invalid["findings"][0]["status"] = "已处理"
    expect_invalid(lambda: validate_pair(data, invalid))
    invalid = copy.deepcopy(report)
    invalid["target_results"][0]["finding_refs"] = []
    expect_invalid(lambda: validate_pair(data, invalid))
    invalid = copy.deepcopy(report)
    invalid["coverage"].pop()
    expect_invalid(lambda: validate_pair(data, invalid))
    invalid = copy.deepcopy(report)
    invalid["chains"][0]["edges"][0]["evidence_refs"] = []
    expect_invalid(lambda: validate_pair(data, invalid))
    local, local_report = pairs[1]
    invalid = copy.deepcopy(local_report)
    invalid["outcome"] = "COMPLETE"
    expect_invalid(lambda: validate_pair(local, invalid))
    # Preserve uncertainty across finding, target checks and aggregate status.
    valid = copy.deepcopy(report)
    valid["chains"][0]["edges"][0].update(
        relation="UNKNOWN", evidence_refs=[], note="连接待核查；仅验证结构可表达性。"
    )
    finding = next(f for f in valid["findings"] if f["key"] == "F1")
    finding["evidence_state"] = "INSUFFICIENT"
    finding["missing_evidence"] = [
        {"needed": "接口关联", "reason": "连接未核实", "effect": "不能确定当前配对关系"}
    ]
    for view in finding["target_views"]:
        view["evidence_state"] = "INSUFFICIENT"
    for result in valid["target_results"]:
        if result["target"] in finding["target_refs"]:
            result["status"] = "PARTIAL"
            result["limitation_refs"] = ["L1"]
            for check in result["checks"]:
                if "F1" in check["finding_refs"]:
                    check["assessment"] = "SUSPECTED"
    valid["limitations"] = [
        {
            "key": "L1",
            "kind": "UNRESOLVED_RELATION",
            "target_refs": finding["target_refs"],
            "source_refs": [],
            "detail": "连接未核实",
            "effect": "两个目标只能部分完成",
        }
    ]
    valid["outcome"] = "PARTIAL"
    validate_pair(data, valid)
    for path in ROOT.glob("*.md"):
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if not re.match(r"[a-z]+://", link):
                require(
                    (path.parent / link.split("#")[0]).exists(),
                    "broken local Markdown link",
                )
    print(
        "PASS: 2 synthetic pairs and negative checks; no AI, network, database, or code execution"
    )


if __name__ == "__main__":
    main()
