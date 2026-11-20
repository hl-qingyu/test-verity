"""Saved candidate rounds from completed turns in this record's private CLI history."""

import re

from app.core.errors import AppError
from app.db.models import AnalysisTerminalResume
from app.integrations import codex_terminal, native_candidates
from app.modules.analysis_terminal import service
from app.modules.case_analysis import contract as case_contract
from app.modules.change_analysis import contract as change_contract
from app.modules.change_analysis import execution as change_execution
from app.modules.change_analysis import service as changes
from app.modules.code_analysis import contract as code_contract
from app.modules.code_analysis import execution as code_execution
from app.modules.code_analysis import service as code
from app.modules.requirements import risk_analysis_execution, risk_service

REPORT_SECTIONS = {
    "requirements": {"functions": "功能", "risks": "风险"},
    "code": {"findings": "发现"},
    "changes": {"changes": "变化项", "risks": "风险", "regression_scope": "回归建议"},
    "coverage": {"findings": "用例问题", "notes": "待澄清 / 准备"},
}


def report_json(text, kind):
    fence = re.fullmatch(r"\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*", text)
    raw = fence[1] if fence else text
    if not raw.lstrip().startswith("{"):
        return None
    keys = REPORT_SECTIONS[kind]
    if not any(re.search(rf'"{key}"\s*:', raw) for key in keys):
        return None
    return raw


def candidates(project_id, kind, row, db):
    identity = service.terminal_spec(row)["identity"]
    executions = list(
        db.scalars(
            service.resumes(project_id, kind, row).with_only_columns(AnalysisTerminalResume.id)
        )
    )
    db.rollback()
    finished = {
        (event["thread_id"], event["turn_id"])
        for execution_id in executions
        for event in codex_terminal.turn_events(identity, execution_id)[0]
        if event["method"] == "turn/completed"
        and event.get("status") == "completed"
        and event.get("thread_id")
        and event.get("turn_id")
    }
    seen = set()
    if finished:
        for item in native_candidates.completed_messages(identity, turns=finished):
            key = (item["thread_id"], item["turn_id"])
            if key in seen:
                continue
            seen.add(key)
            if raw := report_json(item["text"], kind):
                yield item, raw


def listing(project_id, kind, record_id, actor, db):
    row = service.own(project_id, kind, record_id, actor, db)
    return {
        "items": [
            {"id": item["id"], "timestamp": item["timestamp"]}
            for item, _ in candidates(project_id, kind, row, db)
        ]
    }


def validated(kind, raw, data, project_id):
    if kind == "requirements":
        report, _, _, warnings = risk_analysis_execution.validate_result(raw, data, project_id)
        return report, len(warnings)
    if kind == "code":
        parsed = code.parse(code_contract.AnalysisInput, data)
        return code_execution.validate_result(raw, parsed)[0], 0
    if kind == "changes":
        parsed = changes.parse(change_contract.AnalysisInput, data)
        return change_execution.validate_result(raw, parsed)[0], 0
    return case_contract.validate(data, risk_service.json_object(raw)), 0


def preview(project_id, kind, record_id, result_id, actor, db):
    if not re.fullmatch(r"[0-9a-f]{64}", result_id):
        raise AppError(404, "analysis_terminal_candidate_not_found")
    row = service.own(project_id, kind, record_id, actor, db, full=True)
    data = row.context["input"] if kind == "requirements" else row.input_snapshot
    selected = next(
        (
            (item, raw)
            for item, raw in candidates(project_id, kind, row, db)
            if item["id"] == result_id
        ),
        None,
    )
    if selected is None:
        raise AppError(404, "analysis_terminal_candidate_not_found")
    item, raw = selected
    result = {"id": item["id"], "raw": item["text"]}
    try:
        report, warnings = validated(kind, raw, data, project_id)
    except AppError as exc:
        return {**result, "error_code": exc.detail, "counts": {}, "warnings": 0}
    return {
        **result,
        "error_code": "",
        "warnings": warnings,
        "counts": {label: len(report[key]) for key, label in REPORT_SECTIONS[kind].items()},
    }
