import hashlib
import json

from pydantic import ValidationError

from app.core.errors import AppError
from app.modules.case_analysis.schemas import Report
from app.modules.cases.schemas import DESIGN_FIELDS

LIMIT = 16 * 1024 * 1024


def require(condition, code="case_analysis_invalid"):
    if not condition:
        raise AppError(422, code)


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate(data, value):
    try:
        report = Report.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise AppError(422, "case_analysis_report_invalid") from None
    require(
        len(json.dumps(report, ensure_ascii=False).encode()) <= LIMIT,
        "case_analysis_input_too_large",
    )
    ids = {c["id"] for c in data["cases"]}
    require(
        len(report["checked_case_ids"]) == len(set(report["checked_case_ids"]))
        and set(report["checked_case_ids"]) <= ids
    )
    items = report["findings"] + report["notes"]
    require(len({f["key"] for f in items}) == len(items))
    for f in items:
        require(f["key"] != "manual")
        require(len(f["case_ids"]) == len(set(f["case_ids"])) and set(f["case_ids"]) <= ids)
        require(set(f["fields"]) <= set(DESIGN_FIELDS))
        require(f["kind"] not in ("MISMATCH", "QUALITY") or f["case_ids"])
        require(data["mode"] != "QUALITY" or f["kind"] not in ("MISMATCH", "MISSING"))
        for e in f["evidence"]:
            sources = [m for m in data["materials"] if m["source_id"] == e["source"]]
            require(len(sources) == 1, "case_analysis_quote_invalid")
            require(
                any(e["quote"] in s["text"] for s in sources[0]["segments"])
                if e["quote"]
                else any(s.get("image_ref") for s in sources[0]["segments"]),
                "case_analysis_quote_invalid",
            )
        require(
            f["kind"] not in ("MISMATCH", "MISSING") or f["evidence"],
            "case_analysis_evidence_required",
        )
    require(all(f["kind"] not in ("SETUP", "QUESTION") for f in report["findings"]))
    require(all(f["kind"] in ("SETUP", "QUESTION") for f in report["notes"]))
    return report
