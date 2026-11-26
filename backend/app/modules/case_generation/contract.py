"""Dispatch compact output while preserving immutable legacy reports."""

from app.modules.case_generation import compact, contract_base, legacy_contract

LIMIT = contract_base.LIMIT
SPECS = contract_base.SPECS
require = contract_base.require
read = contract_base.read
json_object = contract_base.json_object
read_ai_report = contract_base.read_ai_report
digest = contract_base.digest
shape = contract_base.shape
index = contract_base.index
refs = contract_base.refs
validate_input = contract_base.validate_input


def normalize_ai_report(report):
    if isinstance(report, dict) and "cases" in report:
        return compact.normalize(report, recover_titles=True)
    return legacy_contract.normalize_ai_report(report)


def validate_report(data, report):
    if data.get("contract_version") == 3:
        return compact.validate(data, report)
    return legacy_contract.validate_report(data, report)
