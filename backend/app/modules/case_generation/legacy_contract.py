"""Strict generation v2 shapes, fixed evidence, protection and coverage invariants."""

import copy
import hashlib
import json
import re

from pydantic import ValidationError

from app.core.errors import AppError
from app.modules.cases.schemas import DESIGN_FIELDS, CaseDesign
from app.modules.requirements.risk_service import json_object

LIMIT = 16 * 1024 * 1024
DESIGNED_STATES = {"READY", "DESIGN_READY_SETUP_PENDING"}


def require(value, code="generation_contract_invalid"):
    if not value:
        status = (
            403
            if code in {"generation_owner_only", "github_repository_not_allowed"}
            else 409
            if code
            in {
                "generation_request_conflict",
                "generation_changed",
                "generation_case_changed",
                "generation_application_busy",
                "generation_chat_busy",
                "generation_import_rebinding_forbidden",
            }
            else 422
        )
        raise AppError(status, code)


def read(text):
    require(len(text.encode()) <= LIMIT, "generation_input_too_large")
    return json_object(text.lstrip("\ufeff"))


def read_ai_report(data, text):
    if data["contract_version"] == 3:
        fence = re.fullmatch(r"\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*", text)
        if fence:
            return read(fence[1]), ["response.code_fence"]
    return read(text), []


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


# These are the actual contract shapes, not arbitrary model-provided schemas.
SPECS = {
    "input": (
        "analysis_type:s contract_version:n request_id:s project_id:n revision:n "
        "mode:s scope:scope focus:s materials:material[] update_pairs:pair[] "
        "decisions:decision[] related_reports:related[] cases:case[] "
        "supplement:?supplement batch:batch input_limitations:s[]"
    ),
    "scope": "name:s full_scope:b functions:function[] target_ends:s[] case_scope:case_scope",
    "function": "function_ref:s name:s scope_note:s",
    "case_scope": "description:s complete:b count:n library_revision:?n",
    "batch": "plan_ref:s batch_ref:s index:n total:n function_refs:s[] namespace:s limitations:s[]",
    "material": (
        "snapshot_ref:s source_id:s kind:s side:s name:s version_ref:s read_state:s "
        "read_note:s content_sha256:s segments:segment[]"
    ),
    "segment": "segment_id:s location:s text:t image_ref:s",
    "pair": (
        "pair_ref:s before_ref:s after_ref:s update_mode:s function_refs:s[] "
        "scope_confirmed:b scope_note:s comparison_complete:b"
    ),
    "decision": (
        "decision_ref:s version:n statement:s scope_note:s function_refs:s[] actor:s "
        "confirmed_at:s applicability:s supersedes:s[] origin:?origin basis_refs:s[]"
    ),
    "origin": "request_id:s question_key:s",
    "related": (
        "report_ref:s analysis_type:s report_id:s item_key:s statement:s "
        "handling_snapshot:s review_warnings:s[] basis_refs:s[]"
    ),
    "case": (
        "case_ref:s case_id:n design_version:n display_number:s category_id:?n "
        "lifecycle:s design:design baseline:?baseline"
    ),
    "baseline": "design_version:n design:design origin:s adoption_ref:s",
    "supplement": "parent_request_id:s decision_refs:s[] affected_scenario_refs:s[] scope_note:s",
    "report": (
        "analysis_type:s contract_version:n request_id:s project_id:n revision:n "
        "mode:s batch_ref:s outcome:s summary:s evidence:evidence[] rules:rule[] "
        "transitions:transition[] flows:flow[] scenarios:scenario[] "
        "suggestions:suggestion[] unchanged:unchanged[] conflicts:conflict[] "
        "requirement_questions:question[] discovery_gaps:gap[] coverage:coverage "
        "limitations:s[]"
    ),
    "evidence": "key:s kind:s target_ref:s segment_id:s side:s field:s quote:t note:s",
    "rule": (
        "key:s semantic_key:s function_ref:s object:s actor:s statement:s "
        "branches:branch[] evidence_refs:s[]"
    ),
    "branch": "branch_ref:s conditions:s[] result:s state:s evidence_refs:s[]",
    "transition": (
        "key:s flow_ref:s rule_refs:s[] branch_refs:s[] object:s from_state:s "
        "action:s actor:s action_end:s to_state:s observation_ends:s[] "
        "evidence_refs:s[]"
    ),
    "flow": "key:s object:s transition_refs:s[] state:s note:s",
    "scenario": (
        "key:s semantic_key:s function_ref:s rule_refs:s[] branch_refs:s[] "
        "transition_refs:s[] actor:s action_end:s observation_end:s entry:s "
        "conditions:s[] action:s expected:s state:s evidence_refs:s[] note:s"
    ),
    "suggestion": (
        "key:s kind:s function_ref:s scenario_refs:s[] case_ref:?s base_version:?n "
        "design:?design changes:change[] reason:s priority_reason:s evidence_refs:s[] "
        "basis_status:s"
    ),
    "change": "field:s before:t after:t reason:s evidence_refs:s[]",
    "unchanged": "key:s case_ref:s base_version:n scenario_refs:s[] reason:s evidence_refs:s[]",
    "conflict": (
        "key:s kind:s function_ref:s scenario_refs:s[] suggestion_refs:s[] "
        "field_comparisons:comparison[] statement:s options:s[] evidence_refs:s[]"
    ),
    "comparison": "case_ref:s field:s baseline:?t current:t proposed:t",
    "question": (
        "key:s function_ref:s scenario_refs:s[] parent_key:?s trigger:s question:s "
        "options:s[] evidence_refs:s[] impact:s"
    ),
    "gap": (
        "key:s kind:s function_ref:s scenario_refs:s[] case_refs:s[] "
        "material_refs:s[] reason:s next_step:s"
    ),
    "coverage": (
        "input_units:unit_coverage[] functions:function_coverage[] "
        "branches:branch_coverage[] scenarios:scenario_coverage[] "
        "cases:case_coverage[]"
    ),
    "unit_coverage": (
        "snapshot_ref:s segment_id:?s state:s rule_refs:s[] scenario_refs:s[] issue_refs:s[] note:s"
    ),
    "function_coverage": "function_ref:s scenario_refs:s[] issue_refs:s[] state:s note:s",
    "branch_coverage": "rule_ref:s branch_ref:s scenario_refs:s[] issue_refs:s[] state:s note:s",
    "scenario_coverage": (
        "scenario_ref:s suggestion_refs:s[] unchanged_refs:s[] issue_refs:s[] state:s note:s"
    ),
    "case_coverage": (
        "case_ref:s suggestion_refs:s[] unchanged_refs:s[] issue_refs:s[] state:s note:s"
    ),
}


def shape(value, spec):
    if spec.startswith("?"):
        if value is None:
            return
        spec = spec[1:]
    if spec.endswith("[]"):
        require(isinstance(value, list) and len(value) <= 20000)
        for item in value:
            shape(item, spec[:-2])
    elif spec in {"s", "t"}:
        require(isinstance(value, str) and "\x00" not in value)
        require(len(value) <= (LIMIT if spec == "t" else 10000))
    elif spec == "n":
        require(type(value) is int and 0 <= value <= 2**53 - 1)
    elif spec == "b":
        require(type(value) is bool)
    elif spec == "design":
        require(isinstance(value, dict) and set(value) == set(DESIGN_FIELDS))
        try:
            CaseDesign.model_validate(value)
        except ValidationError:
            raise AppError(422, "generation_design_invalid") from None
        require(all(isinstance(v, str) for v in value.values()))
        require(value["priority"] in {"", "P0", "P1", "P2", "P3", "P4"})
    else:
        fields = dict(part.split(":", 1) for part in SPECS[spec].split())
        require(isinstance(value, dict) and set(value) == set(fields))
        for k, sub in fields.items():
            shape(value[k], sub)


def index(items, field="key"):
    result = {}
    for item in items:
        key = item[field]
        require(isinstance(key, str | int) and bool(key) and key not in result)
        if isinstance(key, str):
            require(len(key) <= 200 and key not in {"__proto__", "prototype", "constructor"})
        result[key] = item
    return result


def refs(values, known, *, nonempty=False):
    require(not nonempty or values)
    require(len(values) == len(set(values)) and set(values) <= set(known))


def acyclic(mapping):
    for key in mapping:
        seen = set()
        current = key
        while current is not None:
            require(current not in seen and current in mapping)
            seen.add(current)
            current = mapping[current]


def unique_quote(text, quote):
    if not quote:
        return False
    start = text.find(quote)
    return start >= 0 and text.find(quote, start + 1) < 0


def validate_input(data):
    shape(data, "input")
    require(data["analysis_type"] == "CASE_GENERATION" and data["contract_version"] in {2, 3})
    require(data["project_id"] > 0 and data["revision"] > 0 and data["request_id"])
    require(data["mode"] in {"INITIAL", "UPDATE"})
    fs = index(data["scope"]["functions"], "function_ref")
    batch = data["batch"]
    refs(batch["function_refs"], fs, nonempty=True)
    require(
        0 < batch["index"] <= batch["total"]
        and batch["namespace"]
        and batch["namespace"] != "manual"
    )
    require(
        data["scope"]["target_ends"]
        and len(set(data["scope"]["target_ends"])) == len(data["scope"]["target_ends"])
    )
    mats = index(data["materials"], "snapshot_ref")
    for mat in mats.values():
        require(mat["kind"] in {"REQUIREMENT", "PROTOTYPE", "CONTRACT", "CODE"})
        require(mat["side"] in {"CURRENT", "BEFORE", "SUPPLEMENT", "CONTEXT"})
        require(mat["read_state"] in {"READABLE", "PARTIAL", "UNREADABLE", "NOT_LOADED"})
        require(mat["version_ref"] and mat["source_id"])
        index(mat["segments"], "segment_id")
        if mat["read_state"] in {"READABLE", "PARTIAL"}:
            require(mat["segments"])
            for seg in mat["segments"]:
                require(seg["location"] and (seg["text"].strip() or seg["image_ref"]))
            if any(s["text"] for s in mat["segments"]):
                text = "\n".join(s["text"] for s in mat["segments"])
                require(hashlib.sha256(text.encode()).hexdigest() == mat["content_sha256"])
            else:
                require(len(mat["content_sha256"]) == 64)
        else:
            require(not mat["segments"] and not mat["content_sha256"] and mat["read_note"])
        require(mat["read_state"] != "PARTIAL" or mat["read_note"])
    index(data["update_pairs"], "pair_ref")
    if data["mode"] == "INITIAL":
        require(
            not data["update_pairs"]
            and all(m["side"] not in {"BEFORE", "SUPPLEMENT"} for m in mats.values())
        )
    for pair in data["update_pairs"]:
        refs(pair["function_refs"], batch["function_refs"], nonempty=True)
        require(
            pair["before_ref"] in mats
            and pair["after_ref"] in mats
            and pair["before_ref"] != pair["after_ref"]
        )
        before, after = mats[pair["before_ref"]], mats[pair["after_ref"]]
        require(before["kind"] == after["kind"] and before["kind"] != "CODE")
        require(before["side"] == "BEFORE" and pair["scope_confirmed"] and pair["scope_note"])
        require(pair["update_mode"] in {"FULL_REPLACEMENT", "INCREMENTAL_SUPPLEMENT"})
        require(
            after["side"]
            == ("CURRENT" if pair["update_mode"] == "FULL_REPLACEMENT" else "SUPPLEMENT")
        )
        require(
            (before["source_id"], before["version_ref"])
            != (after["source_id"], after["version_ref"])
        )
    decisions = index(data["decisions"], "decision_ref")
    for d in decisions.values():
        refs(d["function_refs"], fs, nonempty=True)
        refs(d["basis_refs"], mats)
        refs(d["supersedes"], decisions)
        require(
            d["applicability"] in {"VERIFIED_CURRENT", "UNVERIFIED"}
            and d["version"] > 0
            and d["actor"]
            and d["confirmed_at"]
        )

    def visit(key, trail):
        require(key not in trail)
        for old in decisions[key]["supersedes"]:
            visit(old, trail | {key})

    for key in decisions:
        visit(key, set())
    reports = index(data["related_reports"], "report_ref")
    for item in reports.values():
        refs(item["basis_refs"], mats)
        require(item["analysis_type"] in {"REQUIREMENT_ANALYSIS", "CODE_REVIEW", "CHANGE_IMPACT"})
    cases = index(data["cases"], "case_ref")
    index(data["cases"], "case_id")
    require(
        data["scope"]["case_scope"]["count"] == len(cases)
        and data["scope"]["case_scope"]["complete"]
    )
    for c in cases.values():
        require(
            c["case_id"] > 0
            and c["design_version"] > 0
            and c["lifecycle"] in {"ACTIVE", "RETIRED", "UNKNOWN"}
        )
        if c["baseline"]:
            b = c["baseline"]
            require(
                0 < b["design_version"] <= c["design_version"]
                and b["origin"] in {"APPLIED", "DESIGN_HISTORY"}
            )
            require(b["origin"] != "APPLIED" or b["adoption_ref"])
            require(b["design_version"] != c["design_version"] or b["design"] == c["design"])
    if data["supplement"]:
        refs(data["supplement"]["decision_refs"], decisions, nonempty=True)
        require(data["contract_version"] == 3 or data["supplement"]["affected_scenario_refs"])
        require(
            all(
                decisions[k]["applicability"] == "VERIFIED_CURRENT"
                for k in data["supplement"]["decision_refs"]
            )
        )
    return data


def normalize_ai_report(report):
    """Correct only lossless condition-list formatting; leave strict validation intact."""
    normalized, fields = copy.deepcopy(report), []
    if not isinstance(normalized, dict):
        return normalized, fields
    rules = normalized.get("rules", [])
    if isinstance(rules, list):
        for i, rule in enumerate(rules):
            branches = rule.get("branches", []) if isinstance(rule, dict) else []
            if not isinstance(branches, list):
                continue
            for j, branch in enumerate(branches):
                if isinstance(branch, dict) and isinstance(branch.get("conditions"), str):
                    branch["conditions"] = [branch["conditions"]]
                    fields.append(f"rules[{i}].branches[{j}].conditions")
    scenarios = normalized.get("scenarios", [])
    if isinstance(scenarios, list):
        for i, scenario in enumerate(scenarios):
            if isinstance(scenario, dict) and isinstance(scenario.get("conditions"), str):
                scenario["conditions"] = [scenario["conditions"]]
                fields.append(f"scenarios[{i}].conditions")
    return normalized, fields


def validate_report(data, report):
    validate_input(data)
    shape(report, "report")
    for field in (
        "analysis_type",
        "contract_version",
        "request_id",
        "project_id",
        "revision",
        "mode",
    ):
        require(data[field] == report[field])
    require(report["batch_ref"] == data["batch"]["batch_ref"])
    require(report["outcome"] in {"COMPLETE", "PARTIAL", "BLOCKED"})
    mats, cases = index(data["materials"], "snapshot_ref"), index(data["cases"], "case_ref")
    decisions, related = (
        index(data["decisions"], "decision_ref"),
        index(data["related_reports"], "report_ref"),
    )
    ev = index(report["evidence"])
    business = set()
    superseded = {
        k
        for d in decisions.values()
        if d["applicability"] == "VERIFIED_CURRENT"
        for k in d["supersedes"]
    }
    for key, e in ev.items():
        if e["kind"] == "MATERIAL":
            require(e["target_ref"] in mats and not e["field"])
            mat = mats[e["target_ref"]]
            segs = index(mat["segments"], "segment_id")
            require(e["segment_id"] in segs and e["side"] == mat["side"])
            seg = segs[e["segment_id"]]
            if seg["text"]:
                require(unique_quote(seg["text"], e["quote"]), "generation_evidence_invalid")
            else:
                require(seg["image_ref"] and not e["quote"] and e["note"])
            effective_old = any(
                p["before_ref"] == mat["snapshot_ref"]
                and p["update_mode"] == "INCREMENTAL_SUPPLEMENT"
                for p in data["update_pairs"]
            )
            if mat["kind"] != "CODE" and (
                mat["side"] in {"CURRENT", "SUPPLEMENT", "CONTEXT"} or effective_old
            ):
                business.add(key)
        elif e["kind"] == "CASE":
            require(
                e["target_ref"] in cases and e["field"] in DESIGN_FIELDS and not e["segment_id"]
            )
            c = cases[e["target_ref"]]
            require(e["side"] in {"CURRENT", "BASELINE"})
            require(e["side"] != "BASELINE" or c["baseline"])
            d = c["design"] if e["side"] == "CURRENT" else c["baseline"]["design"]
            require(unique_quote(d[e["field"]], e["quote"]))
        else:
            require(
                e["kind"] in {"DECISION", "REPORT"}
                and e["side"] == "CONTEXT"
                and not e["field"]
                and not e["segment_id"]
            )
            pool = decisions if e["kind"] == "DECISION" else related
            require(e["target_ref"] in pool)
            require(unique_quote(pool[e["target_ref"]]["statement"], e["quote"]))
            if (
                e["kind"] == "DECISION"
                and decisions[e["target_ref"]]["applicability"] == "VERIFIED_CURRENT"
                and e["target_ref"] not in superseded
            ):
                business.add(key)
    groups = (
        "rules",
        "transitions",
        "flows",
        "scenarios",
        "suggestions",
        "unchanged",
        "conflicts",
        "requirement_questions",
        "discovery_gaps",
    )
    pools = {g: index(report[g]) for g in groups}
    branches = {b["branch_ref"]: (r, b) for r in report["rules"] for b in r["branches"]}
    all_keys = list(ev) + [k for p in pools.values() for k in p] + list(branches)
    require(len(all_keys) == len(set(all_keys)))
    require(len(branches) == sum(len(r["branches"]) for r in report["rules"]))
    require(all(k.startswith(data["batch"]["namespace"] + ":") for k in all_keys))
    issue_keys = (
        set(pools["conflicts"]) | set(pools["requirement_questions"]) | set(pools["discovery_gaps"])
    )

    def basis(values):
        refs(values, ev, nonempty=True)
        require(set(values) & business, "generation_business_basis_required")

    for group, pool in pools.items():
        for item in pool.values():
            if "function_ref" in item:
                require(item["function_ref"] in data["batch"]["function_refs"])
            for field, target in (
                ("evidence_refs", ev),
                ("scenario_refs", pools["scenarios"]),
                ("rule_refs", pools["rules"]),
                ("branch_refs", branches),
                ("transition_refs", pools["transitions"]),
                ("suggestion_refs", pools["suggestions"]),
                ("case_refs", cases),
                ("material_refs", mats),
            ):
                if field in item:
                    refs(item[field], target)
    for ru in report["rules"]:
        require(ru["branches"])
        for b in ru["branches"]:
            require(b["state"] in {"CONFIRMED", "PENDING_DISCOVERY", "PENDING_DECISION"})
            refs(b["evidence_refs"], ev)
            if b["state"] == "CONFIRMED":
                require(b["result"].strip())
                basis(b["evidence_refs"])
    for s in report["scenarios"]:
        require(
            s["state"]
            in DESIGNED_STATES | {"PENDING_DISCOVERY", "PENDING_DECISION", "OUT_OF_SCOPE"}
        )
        require(s["rule_refs"] and s["branch_refs"])
        require(all(branches[b][0]["key"] in s["rule_refs"] for b in s["branch_refs"]))
        require(all(pools["rules"][k]["function_ref"] == s["function_ref"] for k in s["rule_refs"]))
        if s["state"] in DESIGNED_STATES:
            require(all(branches[k][1]["state"] == "CONFIRMED" for k in s["branch_refs"]))
            require(
                all(
                    s[k].strip()
                    for k in ("actor", "action_end", "observation_end", "action", "expected")
                )
                and (s["entry"].strip() or s["state"] == "DESIGN_READY_SETUP_PENDING")
            )
            require(
                "ALL_IN_MATERIALS" in data["scope"]["target_ends"]
                or s["action_end"] in data["scope"]["target_ends"]
                and s["observation_end"] in data["scope"]["target_ends"]
            )
            basis(s["evidence_refs"])
            if s["state"] == "DESIGN_READY_SETUP_PENDING":
                require(
                    s["note"].strip()
                    and any(
                        g["kind"] == "EXECUTION_SETUP"
                        and s["key"] in g["scenario_refs"]
                        and g["reason"].strip()
                        and g["next_step"].strip()
                        for g in report["discovery_gaps"]
                    ),
                    "generation_setup_gap_required",
                )
    for suggestion in report["suggestions"]:
        s = suggestion
        require(
            s["kind"] in {"NEW", "REUSE", "UPDATE", "RETIRE"}
            and s["basis_status"] in {"SUPPORTED", "NEEDS_REVIEW"}
        )
        require(
            s["scenario_refs"]
            and all(
                pools["scenarios"][k]["function_ref"] == s["function_ref"]
                for k in s["scenario_refs"]
            )
        )
        basis(s["evidence_refs"])
        if s["kind"] == "NEW":
            require(
                s["case_ref"] is None
                and s["base_version"] is None
                and s["design"] is not None
                and not s["changes"]
            )
            require(
                all(pools["scenarios"][k]["state"] in DESIGNED_STATES for k in s["scenario_refs"])
            )
            d = s["design"]
        else:
            require(s["case_ref"] in cases and s["design"] is None)
            c = cases[s["case_ref"]]
            require(s["base_version"] == c["design_version"])
            d = dict(c["design"])
            if s["kind"] == "UPDATE":
                require(s["changes"])
                index(s["changes"], "field")
                for p in s["changes"]:
                    require(
                        p["field"] in DESIGN_FIELDS
                        and p["before"] == c["design"][p["field"]]
                        and p["before"] != p["after"]
                    )
                    basis(p["evidence_refs"])
                    d[p["field"]] = p["after"]
                    if c["baseline"] and c["baseline"]["design"][p["field"]] != p["before"]:
                        require(
                            s["basis_status"] == "NEEDS_REVIEW"
                            and any(
                                k["kind"] == "MANUAL_CHANGE" and s["key"] in k["suggestion_refs"]
                                for k in report["conflicts"]
                            )
                        )
                if not c["baseline"]:
                    require(
                        s["basis_status"] == "NEEDS_REVIEW"
                        and any(
                            g["kind"] == "MISSING_BASELINE" and c["case_ref"] in g["case_refs"]
                            for g in report["discovery_gaps"]
                        )
                    )
            else:
                require(not s["changes"])
            if s["kind"] == "REUSE":
                require(c["lifecycle"] != "RETIRED")
            if s["kind"] == "RETIRE":
                sides = {ev[k]["side"] for k in s["evidence_refs"]}
                decision_cancel = any(
                    ev[k]["kind"] == "DECISION" and k in business for k in s["evidence_refs"]
                )
                require(
                    decision_cancel
                    or ("BEFORE" in sides and bool(sides & {"CURRENT", "SUPPLEMENT"}))
                )
                require(
                    decision_cancel
                    or any(
                        p["comparison_complete"]
                        and mats[p["before_ref"]]["read_state"]
                        == mats[p["after_ref"]]["read_state"]
                        == "READABLE"
                        for p in data["update_pairs"]
                    )
                )
        shape(d, "design")
        if any(
            pools["scenarios"][k]["state"] == "DESIGN_READY_SETUP_PENDING"
            for k in s["scenario_refs"]
        ):
            require(
                s["kind"] in {"NEW", "UPDATE"}
                and s["basis_status"] == "NEEDS_REVIEW"
                and d["data_requirements"].strip()
                and d["remark"].strip(),
                "generation_setup_note_required",
            )
        if s["kind"] in {"NEW", "UPDATE"}:
            require(all(d[k].strip() for k in ("title", "steps", "expected")))
    for u in report["unchanged"]:
        require(
            data["mode"] == "UPDATE"
            and u["case_ref"] in cases
            and u["base_version"] == cases[u["case_ref"]]["design_version"]
        )
        require(
            u["scenario_refs"]
            and not any(s["case_ref"] == u["case_ref"] for s in report["suggestions"])
        )
        basis(u["evidence_refs"])
    for k in report["conflicts"]:
        require(
            k["kind"]
            in {
                "SOURCE_CONFLICT",
                "MANUAL_CHANGE",
                "AMBIGUOUS_MATCH",
                "RETIRED_MATCH",
                "TARGET_COLLISION",
            }
        )
        require(
            all(
                pools["suggestions"][sk]["basis_status"] == "NEEDS_REVIEW"
                for sk in k["suggestion_refs"]
            )
        )
        require(k["kind"] != "MANUAL_CHANGE" or k["field_comparisons"])
        for p in k["field_comparisons"]:
            require(p["case_ref"] in cases and p["field"] in DESIGN_FIELDS)
            c = cases[p["case_ref"]]
            require(p["current"] == c["design"][p["field"]])
            require(
                p["baseline"] == (c["baseline"]["design"][p["field"]] if c["baseline"] else None)
            )
            require(k["kind"] != "MANUAL_CHANGE" or c["baseline"])
            require(
                any(
                    p["proposed"] == patch["after"] and p["field"] == patch["field"]
                    for sk in k["suggestion_refs"]
                    for patch in pools["suggestions"][sk]["changes"]
                )
            )
    for gap in report["discovery_gaps"]:
        require(
            gap["kind"]
            in {
                "UNREAD_CONTENT",
                "UNMODELED",
                "EXECUTION_SETUP",
                "MISSING_BASELINE",
                "UNPROCESSED_SCOPE",
            }
        )
        require(gap["reason"].strip() and gap["next_step"].strip())
    questions = pools["requirement_questions"]
    acyclic({key: q["parent_key"] for key, q in questions.items()})
    for q in questions.values():
        require(
            q["scenario_refs"]
            and all(
                pools["scenarios"][k]["state"] == "PENDING_DECISION" for k in q["scenario_refs"]
            )
        )
    for t in report["transitions"]:
        require(
            t["flow_ref"] in pools["flows"]
            and t["key"] in pools["flows"][t["flow_ref"]]["transition_refs"]
        )
        require(
            "ALL_IN_MATERIALS" in data["scope"]["target_ends"]
            or t["action_end"] in data["scope"]["target_ends"]
        )
        require(t["observation_ends"])
        if "ALL_IN_MATERIALS" not in data["scope"]["target_ends"]:
            refs(t["observation_ends"], data["scope"]["target_ends"], nonempty=True)
        require(all(t[k].strip() for k in ("object", "from_state", "action", "actor", "to_state")))
        basis(t["evidence_refs"])
    for flow in report["flows"]:
        require(flow["state"] in {"COMPLETE", "PARTIAL"} and flow["transition_refs"])
        if flow["state"] == "COMPLETE":
            ts = [pools["transitions"][k] for k in flow["transition_refs"]]
            connected = {ts[0]["from_state"], ts[0]["to_state"]}
            pending = ts[1:]
            while pending:
                found = [t for t in pending if {t["from_state"], t["to_state"]} & connected]
                require(found)
                for t in found:
                    connected.update((t["from_state"], t["to_state"]))
                    pending.remove(t)
            require(
                all(
                    any(
                        t["key"] in s["transition_refs"] and s["state"] == "READY"
                        for s in report["scenarios"]
                    )
                    for t in ts
                )
            )
    coverage = report["coverage"]
    units = {(m["snapshot_ref"], s["segment_id"]) for m in mats.values() for s in m["segments"]} | {
        (m["snapshot_ref"], None) for m in mats.values() if not m["segments"]
    }
    actual = [(u["snapshot_ref"], u["segment_id"]) for u in coverage["input_units"]]
    require(len(actual) == len(set(actual)) and set(actual) == units)
    for group, field, expected, states in (
        (
            "functions",
            "function_ref",
            data["batch"]["function_refs"],
            {"COMPLETE", "PARTIAL", "BLOCKED"},
        ),
        ("branches", "branch_ref", branches, {"MODELED", "QUESTION", "GAP", "OUT_OF_SCOPE"}),
        (
            "scenarios",
            "scenario_ref",
            pools["scenarios"],
            {"SUGGESTED", "EXISTING", "QUESTION", "GAP", "OUT_OF_SCOPE"},
        ),
        ("cases", "case_ref", cases, {"SUGGESTED", "UNCHANGED", "UNMATCHED", "NOT_CHECKED"}),
    ):
        require(set(index(coverage[group], field)) == set(expected))
        for item in coverage[group]:
            require(item["state"] in states)
            for f, pool in (
                ("issue_refs", issue_keys),
                ("scenario_refs", pools["scenarios"]),
                ("suggestion_refs", pools["suggestions"]),
                ("unchanged_refs", pools["unchanged"]),
            ):
                if f in item:
                    refs(item[f], pool)
            if item["state"] in {"QUESTION", "GAP", "NOT_CHECKED"}:
                require(item["issue_refs"])
            if group == "branches":
                require(item["rule_ref"] == branches[item["branch_ref"]][0]["key"])
                require(
                    all(
                        item["branch_ref"] in pools["scenarios"][k]["branch_refs"]
                        for k in item["scenario_refs"]
                    )
                )
                if item["state"] == "MODELED":
                    require(
                        any(
                            pools["scenarios"][k]["state"] in DESIGNED_STATES
                            for k in item["scenario_refs"]
                        )
                    )
            if group == "scenarios" and item["state"] in {"SUGGESTED", "EXISTING"}:
                require(item["suggestion_refs"] or item["unchanged_refs"])
                require(
                    all(
                        item["scenario_ref"] in pools["suggestions"][k]["scenario_refs"]
                        for k in item["suggestion_refs"]
                    )
                )
            if group == "cases":
                require(item["state"] != "UNCHANGED" or item["unchanged_refs"])
                require(item["state"] != "SUGGESTED" or item["suggestion_refs"])
                require(
                    all(
                        item["case_ref"] == pools["unchanged"][k]["case_ref"]
                        for k in item["unchanged_refs"]
                    )
                )
                require(
                    all(
                        item["case_ref"] == pools["suggestions"][k]["case_ref"]
                        for k in item["suggestion_refs"]
                    )
                )
    for u in coverage["input_units"]:
        require(u["state"] in {"PROCESSED", "NON_BUSINESS", "UNPROCESSED", "CONTEXT_ONLY"})
        refs(u["rule_refs"], pools["rules"])
        refs(u["scenario_refs"], pools["scenarios"])
        refs(u["issue_refs"], issue_keys)
        require(u["state"] != "UNPROCESSED" or u["issue_refs"])
        require(
            u["state"] != "PROCESSED" or u["rule_refs"] or u["scenario_refs"] or u["issue_refs"]
        )
        require(u["state"] not in {"NON_BUSINESS", "CONTEXT_ONLY"} or u["note"])
    primary = any(
        m["kind"] in {"REQUIREMENT", "PROTOTYPE"} and m["side"] != "BEFORE" and m["segments"]
        for m in mats.values()
    ) or any(
        p["update_mode"] == "INCREMENTAL_SUPPLEMENT" and mats[p["before_ref"]]["segments"]
        for p in data["update_pairs"]
    )
    if not primary:
        require(report["outcome"] == "BLOCKED")
    if report["outcome"] == "COMPLETE":
        require(
            not issue_keys and all(s["basis_status"] == "SUPPORTED" for s in report["suggestions"])
        )
        require(all(s["state"] in {"READY", "OUT_OF_SCOPE"} for s in report["scenarios"]))
        require(all(u["state"] != "UNPROCESSED" for u in coverage["input_units"]))
        require(all(f["state"] == "COMPLETE" for f in coverage["functions"]))
        if data["scope"]["full_scope"]:
            require(
                all(
                    m["read_state"] == "READABLE"
                    for m in mats.values()
                    if m["kind"] in {"REQUIREMENT", "PROTOTYPE"} and m["side"] != "CONTEXT"
                )
            )
    if report["outcome"] == "BLOCKED":
        require(not report["suggestions"] and not report["unchanged"])
    require(set(data["input_limitations"]) <= set(report["limitations"]))
    return report
