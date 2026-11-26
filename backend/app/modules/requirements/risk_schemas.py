"""Requirement-risk contracts and validation of fixed evidence references."""

import re
from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.errors import AppError
from app.modules.ai.schemas import AISelectionInput

Text = Annotated[str, Field(max_length=10000)]
Nonempty = Annotated[str, Field(min_length=1, max_length=10000)]
Key = Annotated[str, Field(min_length=1, max_length=200)]
Name = Annotated[str, Field(min_length=1, max_length=80)]
Title = Annotated[str, Field(min_length=1, max_length=500)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Evidence(Strict):
    source_id: Key
    segment_id: Key
    location: Annotated[str, Field(max_length=1000)]
    excerpt: Text
    observation: Text

    @model_validator(mode="after")
    def has_content(self):
        if not self.excerpt.strip() and not self.observation.strip():
            raise ValueError("evidence_empty")
        return self


class Function(Strict):
    key: Key
    module: Annotated[str, Field(max_length=80)]
    name: Name
    scope: Nonempty
    evidence: list[Evidence] = Field(min_length=1)
    risk_keys: list[Key]


class Improvement(Strict):
    proposal: Nonempty
    rationale: Nonempty
    tradeoffs: Text
    requires_confirmation: Literal[True]


class Side(Strict):
    statement: Nonempty
    evidence: list[Evidence] = Field(min_length=1)


class Comparison(Strict):
    relation: Literal["EXPRESSION_DIFFERENCE", "CONFLICT"]
    sides: list[Side] = Field(min_length=2)
    known_facts: Nonempty
    unknowns: Text


class CheckedScope(Strict):
    source_id: Key
    segment_ids: list[Key] = Field(min_length=1)


class Risk(Strict):
    key: Key
    function_keys: list[Key] = Field(min_length=1)
    title: Title
    type: Literal[
        "FLOW_GAP",
        "RULE_GAP",
        "PERMISSION_GAP",
        "AMBIGUITY",
        "SOURCE_DIFFERENCE",
        "DATA_GAP",
        "NOT_VERIFIABLE",
    ]
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    severity_reason: Nonempty
    basis: Literal["EXPLICIT", "OBSERVED", "SCOPE_GAP", "MIXED"]
    description: Nonempty
    evidence: list[Evidence] = Field(min_length=1)
    checked_scope: list[CheckedScope]
    impact: Nonempty
    questions: list[Nonempty] = Field(min_length=1)
    improvement: Improvement
    source_comparison: Comparison | None


class Suggestion(Improvement):
    key: Key
    function_keys: list[Key] = Field(min_length=1)
    title: Title


class Segment(Strict):
    segment_id: Key
    disposition: Literal["REVIEWED", "NOT_RELEVANT", "UNPROCESSED"]
    function_keys: list[Key]
    risk_keys: list[Key]
    reason: Nonempty


class Coverage(Strict):
    source_id: Key
    segments: list[Segment]
    limitation: Text


LimitationKind = Literal[
    "UNREADABLE",
    "NOT_LOADED",
    "PARTIAL_CONTENT",
    "MISSING_RELATED_MATERIAL",
    "OUT_OF_SCOPE",
    "INVALID_INPUT",
]


class Limitation(Strict):
    kind: LimitationKind
    source_ids: list[Key]
    detail: Nonempty
    effect: Nonempty


class LimitationV4(Limitation):
    kind: LimitationKind | Literal["NOT_PROCESSED"]


class Summary(Strict):
    assessment: Literal["NEEDS_CLARIFICATION", "NO_MATERIAL_RISK_FOUND", "INSUFFICIENT_MATERIAL"]
    conclusion: Nonempty
    priority_risk_keys: list[Key]


Outcome = Literal["COMPLETE", "PARTIAL", "BLOCKED"]


class ReportBody(Strict):
    request_id: Key
    summary: Summary
    functions: list[Function]
    risks: list[Risk]
    optional_suggestions: list[Suggestion]


class Report(ReportBody):
    contract_version: Literal[3]
    outcome: Outcome
    coverage: list[Coverage]
    limitations: list[Limitation]


class CandidateV4(ReportBody):
    contract_version: Literal[4]
    limitations: list[LimitationV4]


class SegmentV4(Strict):
    segment_id: Key
    disposition: Literal["REFERENCED", "UNREFERENCED"]
    function_keys: list[Key]
    risk_keys: list[Key]


class CoverageV4(Strict):
    source_id: Key
    segments: list[SegmentV4]
    limitation: Text


class ReportV4(CandidateV4):
    outcome: Outcome
    coverage: list[CoverageV4]


class InputSegment(Strict):
    segment_id: Key
    location: Annotated[str, Field(max_length=1000)]
    text: str
    image_ref: Annotated[str, Field(max_length=200)]


class Material(Strict):
    source_id: Key
    name: Annotated[str, Field(min_length=1, max_length=500)]
    origin: Literal["REQUIREMENT", "PROTOTYPE"]
    kind: Literal["TEXT", "IMAGE", "PROTOTYPE_CODE", "LINK"]
    snapshot_ref: Annotated[str, Field(max_length=1000)]
    read_state: Literal["READABLE", "PARTIAL", "UNREADABLE", "NOT_LOADED"]
    read_note: Text
    segments: list[InputSegment]


class AnalysisInput(Strict):
    contract_version: Literal[3, 4]
    request_id: Key
    project_id: Annotated[int, Field(gt=0)] | None
    revision: Annotated[int, Field(ge=0)] | None
    focus: Text
    materials: list[Material]


class SourceBinding(Strict):
    source_id: Key
    document_id: Annotated[int, Field(gt=0)]
    version_id: Annotated[int, Field(gt=0)] | None


class ImportPayload(Strict):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    input_filename: Annotated[str, Field(min_length=1, max_length=200)]
    report_filename: Annotated[str, Field(min_length=1, max_length=200)]
    input_json: str
    report_json: str
    bindings: list[SourceBinding]


class HandlingInput(Strict):
    risk_key: Key
    status: Literal["PENDING", "NEEDS_INFO", "RESOLVED", "NOT_APPLICABLE"]
    note: Annotated[str, Field(max_length=3000)]
    revision: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def conclusion_required(self):
        self.note = self.note.strip()
        if self.status != "PENDING" and not self.note:
            raise ValueError("note_required")
        return self


class AnalysisSelection(Strict):
    document_id: Annotated[int, Field(gt=0)]
    version_id: Annotated[int, Field(gt=0)] | None
    paths: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(default_factory=list)
    snapshot: Annotated[str, Field(pattern=r"^$|^[0-9a-f]{64}$")] = ""
    url: Annotated[str, Field(max_length=8192)] | None = None

    @model_validator(mode="after")
    def link_paths(self):
        if self.version_id is None and (
            len(self.paths) > 1000
            or any(
                not re.fullmatch(r"(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.html", p) for p in self.paths
            )
        ):
            raise ValueError("invalid link path")
        return self


class AnalysisRequest(Strict, AISelectionInput):
    request_id: Annotated[str, Field(min_length=36, max_length=36)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    focus: Annotated[str, Field(max_length=3000)] = ""
    selections: list[AnalysisSelection] = Field(min_length=1)
    retry_of: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def unique_documents(self):
        UUID(self.request_id)
        if len({item.document_id for item in self.selections}) != len(self.selections):
            raise ValueError("duplicate_document")
        self.title = self.title.strip()
        self.focus = self.focus.strip()
        return self


class ManualRiskInput(Strict):
    request_id: Annotated[str, Field(min_length=36, max_length=36)]
    message_turn_id: Annotated[int, Field(gt=0)]
    function_key: Key
    title: Title
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    risk_type: Literal[
        "FLOW_GAP",
        "RULE_GAP",
        "PERMISSION_GAP",
        "AMBIGUITY",
        "SOURCE_DIFFERENCE",
        "DATA_GAP",
        "NOT_VERIFIABLE",
    ]
    description: Nonempty
    evidence: list[Evidence] = Field(min_length=1)
    impact: Nonempty
    questions: list[Nonempty] = Field(min_length=1)
    improvement: Improvement

    @model_validator(mode="after")
    def valid_request_id(self):
        UUID(self.request_id)
        return self


class ManualHandlingInput(Strict):
    status: Literal["PENDING", "NEEDS_INFO", "RESOLVED", "NOT_APPLICABLE"]
    note: Annotated[str, Field(max_length=3000)]
    revision: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def conclusion_required(self):
        self.note = self.note.strip()
        if self.status != "PENDING" and not self.note:
            raise ValueError("note_required")
        return self


def require(condition: bool, path: str, reason: str) -> None:
    if not condition:
        raise AppError(422, f"risk_report_invalid|{path}|{reason}")


def unique(items, field: str, path: str) -> dict:
    values = {getattr(item, field): item for item in items}
    require(len(values) == len(items), path, "duplicate_id")
    return values


def refs(keys: list[str], available: dict, path: str) -> None:
    require(len(keys) == len(set(keys)), path, "duplicate_reference")
    require(all(k in available for k in keys), path, "unknown_reference")


def normalize_comparison_text(raw: dict) -> tuple[dict, list[dict]]:
    """Join explicit AI list items without inventing comparison facts."""
    result = deepcopy(raw)
    corrections = []
    if not isinstance(result, dict) or not isinstance(result.get("risks"), list):
        return result, corrections
    for index, risk in enumerate(result["risks"]):
        comparison = risk.get("source_comparison") if isinstance(risk, dict) else None
        if not isinstance(comparison, dict):
            continue
        for field in ("known_facts", "unknowns"):
            value = comparison.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                continue
            if field == "known_facts" and (not value or not all(item.strip() for item in value)):
                continue
            joined = "\n".join(value)
            if len(joined) > 10000:
                continue
            comparison[field] = joined
            corrections.append({"risk_index": index, "field": field, "items": len(value)})
    return result, corrections


def normalize_function_risks[T: ReportBody](report: T) -> tuple[T, list[dict]]:
    """Derive the redundant function-side index from the risk's declared owners."""
    functions = unique(report.functions, "key", "functions")
    risks = unique(report.risks, "key", "risks")
    for i, function in enumerate(report.functions):
        refs(function.risk_keys, risks, f"functions[{i}].risk_keys")
    for i, risk in enumerate(report.risks):
        refs(risk.function_keys, functions, f"risks[{i}].function_keys")
    normalized = report.model_copy(deep=True)
    corrections = []
    for function in normalized.functions:
        derived = [risk.key for risk in normalized.risks if function.key in risk.function_keys]
        if set(function.risk_keys) != set(derived):
            corrections.append(
                {"function_key": function.key, "before": function.risk_keys, "after": derived}
            )
            function.risk_keys = derived
    return normalized, corrections


def validate_report(
    report: Report | CandidateV4,
    input_data: AnalysisInput,
    project_id: int,
    review_warnings: list[dict] | None = None,
) -> None:
    def review(condition, path, reason, source_id="", segment_id="", risk_key=""):
        if condition:
            return
        if review_warnings is None:
            require(False, path, reason)
        else:
            review_warnings.append(
                {
                    "path": path,
                    "code": reason,
                    "source_id": source_id,
                    "segment_id": segment_id,
                    "risk_key": risk_key,
                }
            )

    require(input_data.project_id in (None, project_id), "input.project_id", "project_mismatch")
    require(
        input_data.project_id is not None or input_data.revision is None,
        "input.revision",
        "invalid_revision",
    )
    require(report.request_id == input_data.request_id, "request_id", "request_mismatch")
    require(
        report.contract_version == input_data.contract_version,
        "contract_version",
        "version_mismatch",
    )
    legacy = isinstance(report, Report)
    inputs = unique(input_data.materials, "source_id", "input.materials")
    input_segments = {}
    for i, material in enumerate(input_data.materials):
        path = f"input.materials[{i}]"
        input_segments[material.source_id] = unique(material.segments, "segment_id", path)
        if material.read_state in ("UNREADABLE", "NOT_LOADED"):
            require(not material.segments, path, "unreadable_has_content")
        else:
            require(
                bool(material.snapshot_ref.strip()) and bool(material.segments),
                path,
                "snapshot_required",
            )
            require(
                all(s.text.strip() or s.image_ref.strip() for s in material.segments),
                path,
                "empty_segment",
            )
        if material.read_state != "READABLE":
            require(bool(material.read_note.strip()), path, "limitation_required")
            if legacy:
                review(report.outcome != "COMPLETE", "outcome", "incomplete_coverage")
    functions = unique(report.functions, "key", "functions")
    risks = unique(report.risks, "key", "risks")
    unique(report.optional_suggestions, "key", "optional_suggestions")
    segments = {}
    if legacy:
        sources = unique(report.coverage, "source_id", "coverage")
        require(set(sources) <= set(inputs), "coverage", "unknown_reference")
        review(set(sources) == set(inputs), "coverage", "source_coverage_mismatch")
        for i, cover in enumerate(report.coverage):
            segments[cover.source_id] = unique(
                cover.segments, "segment_id", f"coverage[{i}].segments"
            )
            require(
                set(segments[cover.source_id]) <= set(input_segments[cover.source_id]),
                f"coverage[{i}].segments",
                "unknown_reference",
            )
            review(
                set(segments[cover.source_id]) == set(input_segments[cover.source_id]),
                f"coverage[{i}].segments",
                "segment_coverage_mismatch",
                source_id=cover.source_id,
            )
            if inputs[cover.source_id].read_state != "READABLE":
                review(
                    bool(cover.limitation.strip())
                    and any(cover.source_id in limit.source_ids for limit in report.limitations),
                    f"coverage[{i}]",
                    "limitation_required",
                    source_id=cover.source_id,
                )
            if not cover.segments:
                review(bool(cover.limitation.strip()), f"coverage[{i}]", "limitation_required")
                review(report.outcome != "COMPLETE", "outcome", "incomplete_coverage")
            for j, segment in enumerate(cover.segments):
                path = f"coverage[{i}].segments[{j}]"
                refs(segment.function_keys, functions, path)
                refs(segment.risk_keys, risks, path)
                if segment.disposition != "REVIEWED":
                    review(
                        not segment.function_keys and not segment.risk_keys,
                        path,
                        "invalid_coverage",
                        source_id=cover.source_id,
                        segment_id=segment.segment_id,
                    )
                if segment.disposition == "UNPROCESSED":
                    review(report.outcome != "COMPLETE", "outcome", "incomplete_coverage")
                for key in segment.risk_keys:
                    review(
                        bool(set(risks[key].function_keys) & set(segment.function_keys)),
                        path,
                        "invalid_coverage",
                        source_id=cover.source_id,
                        segment_id=segment.segment_id,
                        risk_key=key,
                    )

    def evidence(values: list[Evidence], path: str, risk_key=""):
        for e in values:
            original = input_segments.get(e.source_id, {}).get(e.segment_id)
            require(original is not None, path, "invalid_evidence")
            if legacy:
                segment = segments.get(e.source_id, {}).get(e.segment_id)
                review(
                    segment is not None and segment.disposition == "REVIEWED",
                    path,
                    "invalid_evidence",
                    source_id=e.source_id,
                    segment_id=e.segment_id,
                    risk_key=risk_key,
                )
            review(
                original.location == e.location,
                path,
                "evidence_location_mismatch",
                source_id=e.source_id,
                segment_id=e.segment_id,
                risk_key=risk_key,
            )
            review(
                not e.excerpt or e.excerpt in original.text,
                path,
                "evidence_excerpt_mismatch",
                source_id=e.source_id,
                segment_id=e.segment_id,
                risk_key=risk_key,
            )

    refs(report.summary.priority_risk_keys, risks, "summary.priority_risk_keys")
    review(
        not report.risks or report.summary.assessment == "NEEDS_CLARIFICATION",
        "summary.assessment",
        "invalid_assessment",
    )
    for i, function in enumerate(report.functions):
        path = f"functions[{i}]"
        refs(function.risk_keys, risks, path)
        evidence(function.evidence, path + ".evidence")
        if legacy:
            review(
                any(function.key in s.function_keys for c in report.coverage for s in c.segments),
                path,
                "missing_coverage",
            )
    for i, risk in enumerate(report.risks):
        path = f"risks[{i}]"
        refs(risk.function_keys, functions, path)
        evidence(risk.evidence, path + ".evidence", risk.key)
        for function in report.functions:
            require(
                (function.key in risk.function_keys) == (risk.key in function.risk_keys),
                path,
                "inconsistent_reference",
            )
        if legacy:
            review(
                any(risk.key in s.risk_keys for c in report.coverage for s in c.segments),
                path,
                "missing_coverage",
                risk_key=risk.key,
            )
        if risk.basis == "SCOPE_GAP":
            review(
                bool(risk.checked_scope),
                path + ".checked_scope",
                "scope_required",
                risk_key=risk.key,
            )
        unique(risk.checked_scope, "source_id", path + ".checked_scope")
        for scope in risk.checked_scope:
            scope_segments = segments if legacy else input_segments
            refs(
                scope.segment_ids, scope_segments.get(scope.source_id, {}), path + ".checked_scope"
            )
            if legacy:
                review(
                    all(
                        segments[scope.source_id][key].disposition == "REVIEWED"
                        for key in scope.segment_ids
                    ),
                    path,
                    "invalid_coverage",
                    source_id=scope.source_id,
                    risk_key=risk.key,
                )
        if risk.type == "SOURCE_DIFFERENCE":
            review(
                risk.source_comparison is not None, path, "comparison_required", risk_key=risk.key
            )
        if risk.source_comparison:
            for side in risk.source_comparison.sides:
                evidence(side.evidence, path + ".source_comparison", risk.key)
    for i, suggestion in enumerate(report.optional_suggestions):
        refs(suggestion.function_keys, functions, f"optional_suggestions[{i}]")
    for i, limitation in enumerate(report.limitations):
        refs(limitation.source_ids, sources if legacy else inputs, f"limitations[{i}]")
        if limitation.kind == "NOT_PROCESSED":
            require(bool(limitation.source_ids), f"limitations[{i}].source_ids", "scope_required")
        if legacy and limitation.kind in (
            "UNREADABLE",
            "NOT_LOADED",
            "PARTIAL_CONTENT",
            "INVALID_INPUT",
        ):
            review(report.outcome != "COMPLETE", "outcome", "incomplete_coverage")
    if not legacy:
        if not any(material.segments for material in input_data.materials):
            review(
                not report.functions and not report.risks and not report.optional_suggestions,
                "outcome",
                "blocked_has_results",
            )
        return
    if report.outcome == "BLOCKED":
        review(
            not report.functions and not report.risks and not report.optional_suggestions,
            "outcome",
            "blocked_has_results",
        )
        review(
            report.summary.assessment == "INSUFFICIENT_MATERIAL" and bool(report.limitations),
            "summary",
            "invalid_assessment",
        )
    if report.outcome == "PARTIAL":
        review(bool(report.limitations), "limitations", "limitation_required")
    if report.outcome != "BLOCKED":
        review(
            any(s.disposition == "REVIEWED" for c in report.coverage for s in c.segments),
            "coverage",
            "no_reviewed_content",
        )


def derive_report(candidate: CandidateV4, input_data: AnalysisInput) -> ReportV4:
    """Project evidence into the fixed material order after reference validation."""
    functions: dict[tuple[str, str], dict[str, None]] = {}
    risks: dict[tuple[str, str], dict[str, None]] = {}
    for function in candidate.functions:
        for item in function.evidence:
            functions.setdefault((item.source_id, item.segment_id), {})[function.key] = None
    for risk in candidate.risks:
        evidence = risk.evidence
        if risk.source_comparison:
            evidence = [
                *evidence,
                *(item for side in risk.source_comparison.sides for item in side.evidence),
            ]
        for item in evidence:
            risks.setdefault((item.source_id, item.segment_id), {})[risk.key] = None

    coverage = []
    for material in input_data.materials:
        segments = []
        for segment in material.segments:
            ref = (material.source_id, segment.segment_id)
            segments.append(
                SegmentV4(
                    segment_id=segment.segment_id,
                    disposition="REFERENCED"
                    if ref in functions or ref in risks
                    else "UNREFERENCED",
                    function_keys=list(functions.get(ref, {})),
                    risk_keys=list(risks.get(ref, {})),
                )
            )
        coverage.append(
            CoverageV4(
                source_id=material.source_id,
                segments=segments,
                limitation=material.read_note if material.read_state != "READABLE" else "",
            )
        )

    outcome: Outcome = "COMPLETE"
    if not any(material.segments for material in input_data.materials):
        outcome = "BLOCKED"
    elif any(material.read_state != "READABLE" for material in input_data.materials) or any(
        limitation.kind == "NOT_PROCESSED" for limitation in candidate.limitations
    ):
        outcome = "PARTIAL"
    return ReportV4(**candidate.model_dump(), coverage=coverage, outcome=outcome)
