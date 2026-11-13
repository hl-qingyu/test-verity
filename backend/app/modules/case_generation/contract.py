"""Dispatch compact output while preserving immutable legacy reports."""

from app.modules.case_generation import compact, legacy_contract

LIMIT = legacy_contract.LIMIT
SPECS = legacy_contract.SPECS
require = legacy_contract.require
read = legacy_contract.read
json_object = legacy_contract.json_object
read_ai_report = legacy_contract.read_ai_report
digest = legacy_contract.digest
shape = legacy_contract.shape
index = legacy_contract.index
refs = legacy_contract.refs
validate_input = legacy_contract.validate_input


def normalize_ai_report(report):
    if isinstance(report, dict) and "cases" in report:
        return compact.normalize(report, recover_titles=True)
    return legacy_contract.normalize_ai_report(report)


def validate_report(data, report):
    if data.get("contract_version") == 3:
        return compact.validate(data, report)
    return legacy_contract.validate_report(data, report)
