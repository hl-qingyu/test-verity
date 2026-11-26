"""Strict CHANGE_IMPACT v2 shapes and cross-file evidence invariants."""

import hashlib
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.modules.code_analysis.contract import safe_path
from app.security.source_content import contains_private_key

Key = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=10000)]
Title = Annotated[str, Field(min_length=1, max_length=500)]
Refs = list[Key]
Mode = Literal["REQUIREMENT_CHANGE", "CODE_CHANGE", "PROTOTYPE_CHANGE"]
Target = Literal[
    "BUSINESS_IMPACT",
    "IMPLEMENTATION_FOLLOWUP",
    "CASE_REGRESSION",
    "BUG",
    "REQUIREMENT_DEVIATION",
    "FRONTEND_BACKEND_MISMATCH",
]
State = Literal["STATIC_SUPPORTED", "INSUFFICIENT"]
Status = Literal["COMPLETE", "PARTIAL", "BLOCKED"]
Side = Literal["BEFORE", "AFTER", "CONTEXT"]
Certainty = Literal["STATIC_SUPPORTED", "POSSIBLE", "UNKNOWN"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Segment(Strict):
    segment_id: Key
    location: Annotated[str, Field(min_length=1, max_length=1000)]
    start_line: int | None
    text: str
    image_ref: str


class Unit(Strict):
    unit_id: Key
    path: Annotated[str, Field(min_length=1, max_length=512)]
    presence: Literal["PRESENT", "VERIFIED_ABSENT", "OUT_OF_SCOPE", "UNKNOWN"]
    read_state: Literal["READABLE", "PARTIAL", "UNREADABLE", "NOT_LOADED"]
    read_note: Text
    content_sha256: str
    segments: list[Segment]


class Provenance(Strict):
    source_kind: Literal["UPLOAD", "GITHUB", "LOCAL", "LINK", "PROVIDED"]
    version_ref: Key
    commit: str
    captured_at: Key


class Snapshot(Strict):
    snapshot_ref: Key
    source_id: Key
    kind: Literal["REQUIREMENT", "PROTOTYPE", "CODE", "CONTRACT", "DECISION"]
    repository_kind: Literal["BACKEND", "WEB", "FLUTTER", "OTHER", "NONE"]
    name: Title
    provenance: Provenance
    scope_complete: bool
    scope_note: Text
    units: list[Unit] = Field(min_length=1)


class Mapping(Strict):
    mapping_id: Key
    before_unit_ids: Refs
    after_unit_ids: Refs
    relation: Literal["MATCH", "RENAME", "SPLIT", "MERGE", "CANDIDATE"]
    confirmed: bool
    note: Text


class SegmentRef(Strict):
    unit_id: Key
    segment_id: Key


class Diff(Strict):
    diff_id: Key
    mapping_ref: Key
    before_segment_refs: list[SegmentRef]
    after_segment_refs: list[SegmentRef]
    note: Text


class Pair(Strict):
    pair_id: Key
    name: Annotated[str, Field(min_length=1, max_length=1000)]
    before_ref: Key
    after_ref: Key
    update_mode: Literal["FULL_REPLACEMENT", "INCREMENTAL_SUPPLEMENT", "CODE_SNAPSHOT"]
    scope: Refs
    scope_confirmed: bool
    unit_mappings: list[Mapping]
    text_diffs: list[Diff]


class Design(Strict):
    preconditions: str
    data_requirements: str
    steps: str
    expected: str


class Case(Strict):
    case_ref: Key
    case_id: int = Field(gt=0)
    design_version: int = Field(gt=0)
    library_revision: int = Field(gt=0)
    display_number: str
    title: str
    design: Design


class History(Strict):
    history_ref: Key
    module: Literal["REQUIREMENT_ANALYSIS", "CODE_REVIEW"]
    report_id: int = Field(gt=0)
    item_key: Key
    title: str
    statement: str
    handling_revision: int = Field(gt=0)
    handling_snapshot: str
    basis_refs: Refs
    review_warnings: list[str]


class Identity(Strict):
    contract_version: Literal[2]
    analysis_type: Literal["CHANGE_IMPACT"]
    request_id: Key
    project_id: int = Field(gt=0)
    revision: int = Field(gt=0)
    mode: Mode


class AnalysisInput(Identity):
    targets: list[Target] = Field(min_length=1, max_length=3)
    focus: Text
    comparison_pairs: list[Pair] = Field(min_length=1, max_length=100)
    snapshots: list[Snapshot] = Field(min_length=2, max_length=500)
    context_refs: Refs
    cases: list[Case]
    historical_items: list[History]
    input_limitations: list[str]


class Evidence(Strict):
    key: Key
    side: Side
    pair_ref: str
    snapshot_ref: Key
    unit_id: Key
    segment_id: str
    kind: Literal["TEXT", "IMAGE", "ABSENCE"]
    start_line: int | None
    end_line: int | None
    excerpt: str
    observation: Text


class Change(Strict):
    key: Key
    pair_ref: Key
    mapping_refs: Refs
    diff_refs: Refs
    title: Title
    function: str
    kind: Literal[
        "ADD", "MODIFY", "REMOVE", "RENAME", "SPLIT", "MERGE", "TEXT_ONLY", "CONFLICT", "UNCERTAIN"
    ]
    evidence_state: State
    before: Text
    after: Text
    business_effect: Text
    evidence_refs: Refs
    questions: list[str]
    limitation_refs: Refs


class SubjectRef(Strict):
    snapshot_ref: Key
    unit_id: Key


class Impact(Strict):
    key: Key
    title: Title
    change_refs: Refs
    subject: Text
    subject_refs: list[SubjectRef]
    directness: Literal["DIRECT", "INDIRECT"]
    certainty: Certainty
    description: Text
    evidence_refs: Refs
    chain_refs: Refs
    suggestion: Text
    limitation_refs: Refs


class ProposedField(Strict):
    field: Literal["title", "preconditions", "data_requirements", "steps", "expected"]
    proposal: Text
    basis_refs: Refs


class CaseImpact(Strict):
    key: Key
    case_ref: Key
    change_refs: Refs
    action: Literal["KEEP", "UPDATE", "RETIRE"]
    certainty: Certainty
    reason: Text
    proposed_fields: list[ProposedField]
    evidence_refs: Refs
    limitation_refs: Refs


class Statement(Strict):
    statement: Text
    evidence_refs: Refs


class Comparison(Strict):
    label: Text
    left: Statement
    right: Statement


class TargetView(Strict):
    target: Target
    evidence_state: State
    expected: Text
    basis: Text
    basis_refs: Refs
    comparison_rows: list[Comparison]


class Attribution(Strict):
    kind: Literal["introduced", "pre_existing", "unknown"]
    explanation: Text
    before_refs: Refs
    after_refs: Refs
    causal_change_refs: Refs
    impact_expansion: Text
    limitation_refs: Refs


class Risk(Strict):
    key: Key
    title: Title
    target_refs: list[Target]
    change_refs: Refs
    severity: Literal["HIGH", "MEDIUM", "LOW", "UNASSESSED"]
    severity_reason: Text
    evidence_state: State
    trigger: Text
    actual: Text
    impact: Text
    root_cause: Text
    target_views: list[TargetView]
    attribution: Attribution
    history_refs: Refs
    evidence_refs: Refs
    chain_refs: Refs
    counterevidence_note: Text
    fix_suggestion: Text
    verification_suggestion: Text
    limitation_refs: Refs


class Node(Strict):
    node_id: Key
    label: Text
    evidence_refs: Refs


class Edge(Strict):
    from_: Key = Field(alias="from")
    to: Key
    relation: Literal[
        "CALL",
        "RETURN",
        "FIELD_MAPPING",
        "STATE_ASSIGNMENT",
        "RULE_TO_IMPLEMENTATION",
        "DEPENDENCY",
        "UNKNOWN",
    ]
    certainty: Literal["STATIC_SUPPORTED", "UNKNOWN"]
    evidence_refs: Refs
    note: Text


class Chain(Strict):
    key: Key
    nodes: list[Node]
    edges: list[Edge]


class HistoricalReview(Strict):
    key: Key
    history_ref: Key
    result: Literal["STILL_PRESENT", "STATIC_IMPROVED", "UNVERIFIABLE", "NOT_CHECKED"]
    note: Text
    evidence_refs: Refs
    risk_refs: Refs
    limitation_refs: Refs


class Regression(Strict):
    key: Key
    title: Title
    function: str
    change_refs: Refs
    risk_refs: Refs
    case_refs: Refs
    action: Literal["KEEP", "UPDATE", "RETIRE", "ADD_SCENARIO"]
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    reason: Text
    preconditions: Text
    data_requirements: Text
    steps: Text
    expected: Text
    expected_basis_refs: Refs
    certainty: Literal["STATIC_SUPPORTED", "NEEDS_CLARIFICATION"]
    questions: list[str]
    limitation_refs: Refs


class Check(Strict):
    subject: Text
    assessment: Literal["CONSISTENT", "DEVIATION", "SUSPECTED", "UNRESOLVED", "OUT_OF_SCOPE"]
    evidence_refs: Refs
    risk_refs: Refs
    note: Text


class TargetResult(Strict):
    target: Target
    status: Status
    scope: Text
    checks: list[Check]
    risk_refs: Refs
    limitation_refs: Refs


class SegmentReview(Strict):
    segment_id: Key
    status: Literal["CHECKED", "IRRELEVANT", "UNPROCESSED"]
    note: Text


class Coverage(Strict):
    snapshot_ref: Key
    unit_id: Key
    side: Side
    pair_ref: str
    status: Literal["CHECKED", "PARTIAL", "UNAVAILABLE", "OUT_OF_SCOPE"]
    segment_reviews: list[SegmentReview]
    note: Text
    limitation_refs: Refs


LimitationCode = Literal[
    "INVALID_INPUT",
    "READ_GAP",
    "SCOPE_GAP",
    "MAPPING_UNCONFIRMED",
    "MISSING_DEPENDENCY",
    "AMBIGUOUS_RULE",
    "UNPROCESSED",
    "NO_CASE_SCOPE",
    "HISTORY_NOT_CHECKED",
    "ATTRIBUTION_GAP",
    "VISUAL_NOT_PROVIDED",
    "REVIEW_WARNING",
]


class Limitation(Strict):
    key: Key
    code: LimitationCode
    description: Text
    affects: list[str]
    needed: Text


class Summary(Strict):
    conclusion: Text
    priority_risk_refs: Refs
    inheritance_note: Text


class ReportBody(Identity):
    summary: Summary
    target_results: list[TargetResult]
    changes: list[Change]
    function_impacts: list[Impact]
    code_impacts: list[Impact]
    case_impacts: list[CaseImpact]
    risks: list[Risk]
    historical_reviews: list[HistoricalReview]
    regression_scope: list[Regression]
    evidence: list[Evidence]
    chains: list[Chain]
    limitations: list[Limitation]


class Report(ReportBody):
    outcome: Status
    coverage: list[Coverage]


class EvidenceV3(Evidence):
    segment_id: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class LimitationV3(Limitation):
    code: LimitationCode | Literal["NOT_ASSESSED"]
    unit_refs: list[SubjectRef] = Field(default_factory=list)


class CandidateV3(ReportBody):
    contract_version: Literal[3]
    evidence: list[EvidenceV3]
    limitations: list[LimitationV3]


def require(condition, code="change_evidence_invalid"):
    if not condition:
        raise AppError(422, code)


def index(items, key):
    result = {getattr(x, key): x for x in items}
    require(len(result) == len(items))
    return result


def refs(values, allowed):
    require(len(values) == len(set(values)) and set(values) <= set(allowed))


def readable(snapshot):
    return any(
        u.presence == "PRESENT" and any(s.text.strip() or s.image_ref for s in u.segments)
        for u in snapshot.units
    )


def validate_input(data):
    allowed = (
        {"BUG", "REQUIREMENT_DEVIATION", "FRONTEND_BACKEND_MISMATCH"}
        if data.mode == "CODE_CHANGE"
        else {"BUSINESS_IMPACT", "IMPLEMENTATION_FOLLOWUP", "CASE_REGRESSION"}
    )
    refs(data.targets, allowed)
    snapshots, pairs = (
        index(data.snapshots, "snapshot_ref"),
        index(data.comparison_pairs, "pair_id"),
    )
    refs(data.context_refs, snapshots)
    kind = {
        "CODE_CHANGE": "CODE",
        "REQUIREMENT_CHANGE": "REQUIREMENT",
        "PROTOTYPE_CHANGE": "PROTOTYPE",
    }[data.mode]
    used = set(data.context_refs)
    main_modes = set()
    for s in snapshots.values():
        require((s.kind == "CODE") == (s.repository_kind != "NONE"))
        require(s.scope_complete or bool(s.scope_note))
        p = s.provenance
        require(
            bool(re.fullmatch(r"[0-9a-f]{40}", p.commit))
            if p.source_kind == "GITHUB"
            else p.commit == ""
        )
        units = index(s.units, "unit_id")
        for u in units.values():
            require(
                bool(u.path)
                and not u.path.startswith(("/", "\\"))
                and ":" not in u.path
                and ".." not in u.path.split("/")
            )
            if s.kind == "CODE":
                require(safe_path(u.path), "code_path_excluded")
            segments = index(u.segments, "segment_id")
            if u.presence != "PRESENT" or u.read_state in ("UNREADABLE", "NOT_LOADED"):
                require(not segments and not u.content_sha256 and bool(u.read_note))
                require(u.presence == "PRESENT" or u.read_state == "NOT_LOADED")
                continue
            require(u.read_state != "PARTIAL" or bool(segments) and bool(u.read_note))
            require(
                u.content_sha256
                == hashlib.sha256("\n".join(x.text for x in u.segments).encode()).hexdigest()
            )
            last = 0
            for seg in u.segments:
                require(bool(seg.text) or bool(seg.image_ref))
                require("\x00" not in seg.text)
                require(not contains_private_key(seg.text), "code_private_key_content")
                if s.kind == "CODE":
                    require(
                        seg.start_line is not None and seg.start_line > last and not seg.image_ref
                    )
                    if u.read_state == "READABLE":
                        require(seg.start_line == last + 1)
                    last = seg.start_line + len(seg.text.split("\n")) - 1
    for p in pairs.values():
        require(p.scope_confirmed and p.scope and p.before_ref != p.after_ref)
        require(p.before_ref in snapshots and p.after_ref in snapshots)
        a, b = snapshots[p.before_ref], snapshots[p.after_ref]
        require(a.kind == b.kind == kind)
        require(a.source_id != b.source_id or a.provenance.version_ref != b.provenance.version_ref)
        if kind == "CODE":
            require(
                p.update_mode == "CODE_SNAPSHOT"
                and a.source_id == b.source_id
                and a.repository_kind == b.repository_kind
            )
            require(
                a.provenance.source_kind == b.provenance.source_kind
                and a.provenance.source_kind in {"GITHUB", "LOCAL", "PROVIDED"}
            )
            main_modes.add(a.provenance.source_kind)
        else:
            require(p.update_mode != "CODE_SNAPSHOT")
        au, bu = index(a.units, "unit_id"), index(b.units, "unit_id")
        require(
            (readable(a) and readable(b))
            or (readable(a) and any(u.presence == "VERIFIED_ABSENT" for u in b.units))
            or (readable(b) and any(u.presence == "VERIFIED_ABSENT" for u in a.units))
        )
        maps = index(p.unit_mappings, "mapping_id")
        diffs = index(p.text_diffs, "diff_id")
        for m in maps.values():
            require(m.before_unit_ids and m.after_unit_ids)
            refs(m.before_unit_ids, au)
            refs(m.after_unit_ids, bu)
            require(m.relation != "CANDIDATE" or not m.confirmed)
        for d in diffs.values():
            require(d.mapping_ref in maps)
            for side, units in (("before", au), ("after", bu)):
                for ref in getattr(d, side + "_segment_refs"):
                    require(
                        ref.unit_id in units
                        and ref.segment_id in index(units[ref.unit_id].segments, "segment_id")
                    )
        used.update((p.before_ref, p.after_ref))
    require(len(main_modes) <= 1 and used == set(snapshots))
    if "FRONTEND_BACKEND_MISMATCH" in data.targets:
        target_refs = {p.after_ref for p in pairs.values()} | set(data.context_refs)
        roles = {
            s.repository_kind
            for ref, s in snapshots.items()
            if ref in target_refs and s.kind == "CODE" and readable(s)
        }
        require(
            "BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}), "change_both_sides_required"
        )
    index(data.cases, "case_ref")
    index(data.cases, "case_id")
    for h in index(data.historical_items, "history_ref").values():
        refs(h.basis_refs, snapshots)


def validate_report(data, report):
    validate_input(data)
    for k in ("request_id", "project_id", "revision", "mode", "analysis_type"):
        require(getattr(data, k) == getattr(report, k))
    legacy = isinstance(report, Report)
    if legacy:
        require(data.contract_version == report.contract_version)
    snapshots, pairs = (
        index(data.snapshots, "snapshot_ref"),
        index(data.comparison_pairs, "pair_id"),
    )
    groups = (
        report.changes,
        report.function_impacts,
        report.code_impacts,
        report.case_impacts,
        report.risks,
        report.historical_reviews,
        report.regression_scope,
        report.evidence,
        report.chains,
        report.limitations,
    )
    index([x for group in groups for x in group], "key")
    evidence, changes, risks = (
        index(report.evidence, "key"),
        index(report.changes, "key"),
        index(report.risks, "key"),
    )
    limits, chains = index(report.limitations, "key"), index(report.chains, "key")
    cases, histories = index(data.cases, "case_ref"), index(data.historical_items, "history_ref")

    def locate(side, pair_ref, snapshot_ref, unit_id):
        require(snapshot_ref in snapshots)
        if side == "CONTEXT":
            require(not pair_ref and snapshot_ref in data.context_refs)
        else:
            require(
                pair_ref in pairs
                and getattr(pairs[pair_ref], side.lower() + "_ref") == snapshot_ref
            )
        units = index(snapshots[snapshot_ref].units, "unit_id")
        require(unit_id in units)
        return snapshots[snapshot_ref], units[unit_id]

    for e in evidence.values():
        s, u = locate(e.side, e.pair_ref, e.snapshot_ref, e.unit_id)
        if e.kind == "ABSENCE":
            require(
                u.presence == "VERIFIED_ABSENT"
                and not e.segment_id
                and not e.excerpt
                and bool(e.observation)
                and e.start_line is None
                and e.end_line is None
            )
            continue
        segments = index(u.segments, "segment_id")
        require(e.segment_id in segments)
        seg = segments[e.segment_id]
        if e.kind == "IMAGE":
            require(
                bool(seg.image_ref)
                and s.kind != "CODE"
                and not e.excerpt
                and bool(e.observation)
                and e.start_line is None
                and e.end_line is None
            )
        else:
            require(bool(e.excerpt) and e.excerpt in seg.text)
            if s.kind == "CODE":
                require(
                    e.start_line is not None
                    and e.end_line is not None
                    and seg.start_line <= e.start_line <= e.end_line
                    and e.end_line < seg.start_line + len(seg.text.split("\n"))
                )
                require(
                    "\n".join(
                        seg.text.split("\n")[
                            e.start_line - seg.start_line : e.end_line - seg.start_line + 1
                        ]
                    )
                    == e.excerpt
                )
            else:
                require(e.start_line is None and e.end_line is None)

    def references(value):
        if isinstance(value, dict):
            for key, v in value.items():
                allowed = {
                    "evidence_refs": evidence,
                    "basis_refs": evidence,
                    "expected_basis_refs": evidence,
                    "before_refs": evidence,
                    "after_refs": evidence,
                    "change_refs": changes,
                    "causal_change_refs": changes,
                    "risk_refs": risks,
                    "priority_risk_refs": risks,
                    "limitation_refs": limits,
                    "chain_refs": chains,
                    "case_refs": cases,
                    "history_refs": histories,
                    "target_refs": data.targets,
                }.get(key)
                if allowed is not None:
                    refs(v, allowed)
                references(v)
        elif isinstance(value, list):
            for item in value:
                references(item)

    references(report.model_dump(by_alias=True))
    for chain in chains.values():
        nodes = index(chain.nodes, "node_id")
        require(chain.nodes and all(n.evidence_refs for n in chain.nodes))
        for edge in chain.edges:
            require(edge.from_ in nodes and edge.to in nodes)
            require(
                bool(edge.note)
                and (
                    edge.certainty != "STATIC_SUPPORTED"
                    or bool(edge.evidence_refs)
                    and edge.relation != "UNKNOWN"
                )
            )
    for c in changes.values():
        require(c.pair_ref in pairs and c.evidence_refs)
        p = pairs[c.pair_ref]
        maps = index(p.unit_mappings, "mapping_id")
        refs(c.mapping_refs, maps)
        refs(c.diff_refs, index(p.text_diffs, "diff_id"))
        require(all(evidence[x].pair_ref == c.pair_ref for x in c.evidence_refs))
        if c.evidence_state == "STATIC_SUPPORTED":
            require({"BEFORE", "AFTER"} <= {evidence[x].side for x in c.evidence_refs})
            require(all(maps[x].confirmed for x in c.mapping_refs))
            require(c.kind != "UNCERTAIN")
        else:
            require(c.limitation_refs)
        if c.kind == "REMOVE":
            # Incremental cancellation is semantic; require the model to expose its exact new rule.
            after = [evidence[x] for x in c.evidence_refs if evidence[x].side == "AFTER"]
            if p.update_mode == "INCREMENTAL_SUPPLEMENT":
                require(any(e.kind == "TEXT" for e in after) and bool(c.after))
            else:
                require(
                    snapshots[p.before_ref].scope_complete and snapshots[p.after_ref].scope_complete
                )
                require(
                    all(
                        u.read_state == "READABLE" or u.presence == "VERIFIED_ABSENT"
                        for u in snapshots[p.after_ref].units
                    )
                )
    for item in report.function_impacts + report.code_impacts:
        require(item.change_refs)
        for ref in item.subject_refs:
            require(
                ref.snapshot_ref in snapshots
                and ref.unit_id in index(snapshots[ref.snapshot_ref].units, "unit_id")
            )
        if item.certainty == "STATIC_SUPPORTED":
            require(item.subject_refs and item.evidence_refs)
            if item.directness == "INDIRECT":
                require(
                    item.chain_refs
                    and all(
                        edge.certainty == "STATIC_SUPPORTED"
                        for key in item.chain_refs
                        for edge in chains[key].edges
                    )
                )
    for item in report.case_impacts:
        require(item.case_ref in cases and item.change_refs)
        require(bool(item.proposed_fields) == (item.action == "UPDATE"))
        if item.action == "RETIRE" and item.certainty == "STATIC_SUPPORTED":
            require(
                any(
                    changes[k].kind == "REMOVE" and changes[k].evidence_state == "STATIC_SUPPORTED"
                    for k in item.change_refs
                )
            )
    for risk in risks.values():
        require(risk.target_refs and risk.change_refs and risk.evidence_refs)
        views = index(risk.target_views, "target")
        require(set(views) == set(risk.target_refs))
        require(
            bool(risk.trigger) and bool(risk.actual) and bool(risk.impact) and bool(risk.root_cause)
        )
        require(
            risk.evidence_state
            == (
                "INSUFFICIENT"
                if any(v.evidence_state == "INSUFFICIENT" for v in views.values())
                else "STATIC_SUPPORTED"
            )
        )
        if risk.evidence_state == "INSUFFICIENT":
            require(risk.limitation_refs)
        for v in views.values():
            refs(v.basis_refs, risk.evidence_refs)
            for row in v.comparison_rows:
                refs(row.left.evidence_refs, risk.evidence_refs)
                refs(row.right.evidence_refs, risk.evidence_refs)
            require(v.target == "BUG" or v.comparison_rows)
            if v.evidence_state == "STATIC_SUPPORTED":
                require(v.expected and v.basis and v.basis_refs)
                if v.target in ("IMPLEMENTATION_FOLLOWUP", "REQUIREMENT_DEVIATION"):
                    require(
                        any(
                            snapshots[evidence[k].snapshot_ref].kind
                            in {"REQUIREMENT", "PROTOTYPE", "DECISION"}
                            for k in v.basis_refs
                        )
                    )
                    require(
                        any(
                            snapshots[evidence[k].snapshot_ref].kind == "CODE"
                            and evidence[k].side != "BEFORE"
                            for k in risk.evidence_refs
                        )
                    )
                if v.target == "FRONTEND_BACKEND_MISMATCH":
                    roles = {
                        snapshots[evidence[k].snapshot_ref].repository_kind
                        for row in v.comparison_rows
                        for obj in (row.left, row.right)
                        for k in obj.evidence_refs
                        if evidence[k].side != "BEFORE"
                        and snapshots[evidence[k].snapshot_ref].kind == "CODE"
                    }
                    require("BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}))
        a = risk.attribution
        refs(a.causal_change_refs, risk.change_refs)
        if a.kind in {"introduced", "pre_existing"}:
            require(a.before_refs and a.after_refs and a.explanation)
            require(
                all(evidence[k].side == "BEFORE" for k in a.before_refs)
                and all(evidence[k].side == "AFTER" for k in a.after_refs)
            )
            refs(a.before_refs, risk.evidence_refs)
            refs(a.after_refs, risk.evidence_refs)
            require(
                {evidence[k].pair_ref for k in a.before_refs}
                & {evidence[k].pair_ref for k in a.after_refs}
            )
            if a.kind == "introduced":
                require(a.causal_change_refs and risk.evidence_state == "STATIC_SUPPORTED")
                if set(risk.target_refs) & {
                    "BUG",
                    "IMPLEMENTATION_FOLLOWUP",
                    "REQUIREMENT_DEVIATION",
                    "FRONTEND_BACKEND_MISMATCH",
                }:
                    require(
                        any(
                            snapshots[evidence[k].snapshot_ref].kind == "CODE"
                            for k in a.before_refs
                        )
                    )
                    require(
                        any(
                            snapshots[evidence[k].snapshot_ref].kind == "CODE" for k in a.after_refs
                        )
                    )
                require(
                    all(
                        changes[k].evidence_state == "STATIC_SUPPORTED"
                        for k in a.causal_change_refs
                    )
                )
        else:
            require(a.explanation and a.limitation_refs)
    reviews = index(report.historical_reviews, "history_ref")
    require(set(reviews) == set(histories))
    for h in reviews.values():
        if h.result in {"STILL_PRESENT", "STATIC_IMPROVED"}:
            require(h.evidence_refs)
        else:
            require(h.note and h.limitation_refs)
        if h.result == "STATIC_IMPROVED":
            require(histories[h.history_ref].basis_refs)
            require(any(evidence[k].side == "BEFORE" for k in h.evidence_refs))
            require(any(evidence[k].side in {"AFTER", "CONTEXT"} for k in h.evidence_refs))
    for item in report.regression_scope:
        require(item.change_refs and item.reason)
        require(item.action != "ADD_SCENARIO" or not item.case_refs)
        if item.certainty == "STATIC_SUPPORTED":
            require(item.expected and item.expected_basis_refs)
        else:
            require(item.questions and item.limitation_refs)
        for ref in item.case_refs:
            actions = {x.action for x in report.case_impacts if x.case_ref == ref}
            require(item.action in actions)
    targets = index(report.target_results, "target")
    require(set(targets) == set(data.targets))
    for name, t in targets.items():
        require(set(t.risk_refs) == {r.key for r in risks.values() if name in r.target_refs})
        require(set(t.risk_refs) == {key for c in t.checks for key in c.risk_refs})
        if t.status != "COMPLETE":
            require(t.limitation_refs)
        if t.status == "BLOCKED":
            require(not t.checks and not t.risk_refs)
        for c in t.checks:
            require(all(name in risks[k].target_refs for k in c.risk_refs))
            if c.assessment in {"DEVIATION", "SUSPECTED"}:
                require(c.evidence_refs and c.risk_refs)
                desired = "STATIC_SUPPORTED" if c.assessment == "DEVIATION" else "INSUFFICIENT"
                require(
                    any(
                        next(v for v in risks[k].target_views if v.target == name).evidence_state
                        == desired
                        for k in c.risk_refs
                    )
                )
            if c.assessment == "CONSISTENT":
                require(c.evidence_refs and not c.risk_refs)
    if not legacy:
        for limit in report.limitations:
            identities = [(ref.snapshot_ref, ref.unit_id) for ref in limit.unit_refs]
            require(len(identities) == len(set(identities)))
            require(
                all(
                    ref in snapshots and uid in index(snapshots[ref].units, "unit_id")
                    for ref, uid in identities
                )
            )
            if limit.code == "NOT_ASSESSED":
                require(bool(identities))
        return
    expected = {
        (p.pair_id, side, ref, u.unit_id)
        for p in pairs.values()
        for side, ref in (("BEFORE", p.before_ref), ("AFTER", p.after_ref))
        for u in snapshots[ref].units
    }
    expected |= {
        ("", "CONTEXT", ref, u.unit_id) for ref in data.context_refs for u in snapshots[ref].units
    }
    actual = [(c.pair_ref, c.side, c.snapshot_ref, c.unit_id) for c in report.coverage]
    require(len(actual) == len(set(actual)) and set(actual) == expected)
    partial = False
    for c in report.coverage:
        s, u = locate(c.side, c.pair_ref, c.snapshot_ref, c.unit_id)
        sr = index(c.segment_reviews, "segment_id")
        require(set(sr) == {x.segment_id for x in u.segments})
        incomplete = (
            not s.scope_complete
            or u.read_state in {"PARTIAL", "UNREADABLE", "NOT_LOADED"}
            and u.presence != "VERIFIED_ABSENT"
            or any(x.status == "UNPROCESSED" for x in sr.values())
        )
        if incomplete:
            require(c.status != "CHECKED" and c.limitation_refs)
        if c.status != "CHECKED":
            partial = True
            require(c.limitation_refs)
    all_complete = all(t.status == "COMPLETE" for t in targets.values()) and not partial
    all_blocked = (
        all(t.status == "BLOCKED" for t in targets.values())
        and not report.changes
        and not report.risks
    )
    require(
        report.outcome == ("COMPLETE" if all_complete else "BLOCKED" if all_blocked else "PARTIAL")
    )
