"""Retain local candidate problems while independently validating usable compact items."""

import json
import re
from dataclasses import dataclass

from app.core.errors import AppError
from app.modules.candidate_results.json_candidates import Pairs, duplicate_fields, original_json
from app.modules.case_generation import compact, legacy_contract
from app.modules.requirements.risk_service import json_object


@dataclass
class Delivery:
    report: dict | None
    issues: list[dict]
    repairs: list[str]
    error_code: str = ""
    original: dict | None = None


def issue(key, kind, ordinal, raw, error, duplicates=()):
    return {
        "key": key,
        "kind": kind,
        "ordinal": ordinal,
        "raw_json": raw,
        "error_code": error,
        "duplicates": list(duplicates),
        "status": "PENDING",
    }


def process(data, raw, resolutions=None, *, preserve_partition=False):
    resolutions = resolutions or {}
    if data["contract_version"] != 3:
        try:
            original, repairs = legacy_contract.read_ai_report(data, raw)
            normalized, fields = legacy_contract.normalize_ai_report(original)
            return Delivery(
                legacy_contract.validate_report(data, normalized),
                [],
                repairs + fields,
                original=original,
            )
        except AppError as error:
            return Delivery(
                None, [issue("response", "response", 0, raw, error.detail)], [], error.detail
            )
    # A human may fix an entirely invalid envelope; the original response remains immutable.
    response_resolution = resolutions.get("response", {})
    effective = (
        response_resolution.get("corrected_json", raw)
        if not response_resolution.get("ignored")
        else raw
    )
    repairs = []
    fence = re.fullmatch(r"\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*", effective)
    if fence:
        effective = fence[1]
        repairs = ["response.code_fence"]
    try:
        root = json.loads(effective, object_pairs_hook=Pairs)
        if (
            not isinstance(root, Pairs)
            or len(root) != 3
            or {k for k, _ in root} != {"cases", "notes", "complete"}
        ):
            raise ValueError()
        envelope = dict(root)
        if type(envelope["complete"]) is not bool or any(
            not isinstance(envelope[k], list)
            or isinstance(envelope[k], Pairs)
            or len(envelope[k]) > 20000
            for k in ("cases", "notes")
        ):
            raise ValueError()
        # Validate fixed input and global scope before accepting any item.
        compact.validate(data, {"cases": [], "notes": [], "complete": False})
    except (ValueError, UnicodeError, RecursionError, AppError) as error:
        code = error.detail if isinstance(error, AppError) else "risk_json_invalid"
        problem = issue("response", "response", 0, raw, code)
        if response_resolution.get("ignored"):
            problem["status"] = "IGNORED"
        return Delivery(None, [problem], [], code)
    valid = {"cases": [], "notes": [], "complete": envelope["complete"]}
    try:
        original_report = json_object(effective)
    except AppError:
        original_report = None
    indices = {
        "cases": [],
        "notes": [],
        "case_total": len(envelope["cases"]),
        "note_total": len(envelope["notes"]),
    }
    problems = []
    if response_resolution.get("corrected_json"):
        problems.append(
            {
                **issue("response", "response", 0, raw, "risk_json_invalid"),
                "status": "RESOLVED",
                "corrected_json": response_resolution["corrected_json"],
                "resolution_note": response_resolution.get("reason", ""),
            }
        )
    for collection, kind in (("cases", "case"), ("notes", "note")):
        for ordinal, node in enumerate(envelope[collection], 1):
            key = f"{kind}-{ordinal}"
            text = original_json(node)
            duplicates = duplicate_fields(node)
            problem = None
            try:
                candidate = json_object(text)
                singleton = {"cases": [], "notes": [], "complete": False, collection: [candidate]}
                normalized, fields = compact.normalize(singleton, recover_titles=True)
                compact.validate(data, normalized)
                candidate = normalized[collection][0]
                repairs.extend(
                    field.replace(f"{collection}[0]", f"{collection}[{ordinal - 1}]", 1)
                    for field in fields
                )
            except AppError as error:
                problem = issue(key, kind, ordinal, text, error.detail, duplicates)
            resolution = resolutions.get(key, {})
            if problem:
                if resolution.get("ignored"):
                    problem["status"] = "IGNORED"
                elif resolution.get("corrected_json"):
                    try:
                        corrected = json_object(resolution["corrected_json"])
                        singleton = {
                            "cases": [],
                            "notes": [],
                            "complete": False,
                            collection: [corrected],
                        }
                        normalized, fields = compact.normalize(singleton, recover_titles=True)
                        compact.validate(data, normalized)
                        candidate = normalized[collection][0]
                        problem.update(
                            status="RESOLVED", corrected_json=resolution["corrected_json"]
                        )
                    except AppError:
                        pass
                problem["resolution_note"] = resolution.get("reason", "")
                problems.append(problem)
                if problem["status"] != "RESOLVED":
                    continue
            valid[collection].append(candidate)
            indices[collection].append(ordinal)
    normalized, fields = compact.normalize(valid, recover_titles=True)
    report = compact.validate(
        data, normalized, source_indices=indices if problems or preserve_partition else None
    )
    return Delivery(report, problems, repairs + fields, original=original_report)
