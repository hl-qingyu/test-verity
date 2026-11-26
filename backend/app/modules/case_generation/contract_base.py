"""Shared generation input and primitive contract validation."""

import hashlib
import json
import re

from pydantic import ValidationError

from app.core.errors import AppError
from app.modules.cases.schemas import DESIGN_FIELDS, CaseDesign
from app.modules.requirements.risk_service import json_object

LIMIT = 16 * 1024 * 1024


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
