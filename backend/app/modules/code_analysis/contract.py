"""Strict Skill v2 documents and cross-reference validation; no IO or model calls."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError
from app.security.source_content import contains_private_key

Target = Literal["BUG", "REQUIREMENT_DEVIATION", "FRONTEND_BACKEND_MISMATCH"]
SourceKind = Literal["GITHUB", "LOCAL"]
RepositoryKind = Literal["BACKEND", "WEB", "FLUTTER", "OTHER"]
ReadState = Literal["READABLE", "PARTIAL", "UNREADABLE", "NOT_LOADED"]
Outcome = Literal["COMPLETE", "PARTIAL", "BLOCKED"]
Certainty = Literal["STATIC_SUPPORTED", "INSUFFICIENT"]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(max_length=10000)]
Nonempty = Annotated[str, Field(min_length=1, max_length=10000)]
Refs = Annotated[list[Identifier], Field(max_length=20000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Segment(Strict):
    segment_id: Identifier
    start_line: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=2_000_000)


class CodeFile(Strict):
    file_id: Identifier
    path: str = Field(min_length=1, max_length=512)
    read_state: ReadState
    read_note: Text
    segments: list[Segment] = Field(max_length=10000)


class Source(Strict):
    source_id: Identifier
    source_kind: SourceKind
    repository_kind: RepositoryKind
    name: str = Field(min_length=1, max_length=500)
    snapshot_ref: Text
    commit: str = Field(max_length=40)
    files: list[CodeFile]


class MaterialSegment(Strict):
    segment_id: Identifier
    location: str = Field(min_length=1, max_length=1000)
    text: str = Field(max_length=2_000_000)
    image_ref: Text


class Material(Strict):
    source_id: Identifier
    name: str = Field(min_length=1, max_length=500)
    origin: Literal["REQUIREMENT", "PROTOTYPE", "CONTRACT", "DECISION"]
    snapshot_ref: Text
    read_state: ReadState
    read_note: Text
    segments: list[MaterialSegment] = Field(max_length=10000)


class AnalysisInput(Strict):
    contract_version: Literal[2]
    analysis_type: Literal["CODE_REVIEW"]
    request_id: Identifier
    source_mode: SourceKind
    targets: list[Target] = Field(min_length=1, max_length=3)
    focus: Text
    sources: list[Source] = Field(max_length=100)
    materials: list[Material] = Field(max_length=1000)
    input_limitations: list[Nonempty] = Field(max_length=1000)


class CodeEvidence(Strict):
    key: Identifier
    kind: Literal["CODE"]
    source_id: Identifier
    file_id: Identifier
    segment_id: Identifier
    start_line: int = Field(gt=0)
    end_line: int = Field(gt=0)
    excerpt: str = Field(min_length=1, max_length=2_000_000)
    observation: Text


class MaterialEvidence(Strict):
    key: Identifier
    kind: Literal["MATERIAL"]
    source_id: Identifier
    segment_id: Identifier
    excerpt: str = Field(max_length=2_000_000)
    observation: Text


Evidence = Annotated[CodeEvidence | MaterialEvidence, Field(discriminator="kind")]


class Side(Strict):
    statement: Nonempty
    evidence_refs: Refs


class Comparison(Strict):
    label: Nonempty
    left: Side
    right: Side


class TargetView(Strict):
    target: Target
    evidence_state: Certainty
    expected: Nonempty
    basis: Nonempty
    basis_refs: Refs
    explanation: Nonempty
    evidence_refs: Refs
    comparison_rows: list[Comparison] = Field(max_length=1000)


class MissingEvidence(Strict):
    needed: Nonempty
    reason: Nonempty
    effect: Nonempty


class Finding(Strict):
    key: Identifier
    target_refs: list[Target] = Field(min_length=1, max_length=3)
    title: str = Field(min_length=1, max_length=500)
    category: Nonempty
    severity: Literal["HIGH", "MEDIUM", "LOW", "UNASSESSED"]
    severity_reason: Nonempty
    evidence_state: Certainty
    trigger: Nonempty
    actual: Nonempty
    impact: Nonempty
    evidence_refs: Refs
    chain_refs: Refs
    target_views: list[TargetView] = Field(min_length=1, max_length=3)
    fix_suggestion: Nonempty
    verification_suggestion: Nonempty
    missing_evidence: list[MissingEvidence] = Field(max_length=1000)


class Check(Strict):
    key: Identifier
    subject: Nonempty
    assessment: Literal["CONSISTENT", "DEVIATION", "SUSPECTED", "UNRESOLVED", "OUT_OF_SCOPE"]
    evidence_refs: Refs
    finding_refs: Refs
    note: Text


class TargetResult(Strict):
    target: Target
    status: Outcome
    scope: Nonempty
    checks: list[Check] = Field(max_length=20000)
    finding_refs: Refs
    limitation_refs: Refs


class Node(Strict):
    key: Identifier
    label: Nonempty
    observation: Nonempty
    inputs: Text
    outputs: Text
    evidence_refs: Refs


class Edge(Strict):
    from_: Identifier = Field(alias="from")
    to: Identifier
    relation: Literal["CALL", "RETURN", "FIELD_MAPPING", "STATE_ASSIGNMENT", "UNKNOWN"]
    evidence_refs: Refs
    note: Nonempty


class Chain(Strict):
    key: Identifier
    nodes: list[Node] = Field(min_length=1, max_length=10000)
    edges: list[Edge] = Field(max_length=10000)


class CoverageTarget(Strict):
    target: Target
    disposition: Literal["REVIEWED", "NOT_RELEVANT", "UNPROCESSED"]
    check_refs: Refs
    reason: Nonempty


class Coverage(Strict):
    kind: Literal["CODE", "MATERIAL"]
    source_id: Identifier
    file_id: str = Field(max_length=200)
    segment_id: str = Field(max_length=200)
    targets: list[CoverageTarget] = Field(min_length=1, max_length=3)


class Limitation(Strict):
    key: Identifier
    kind: Literal[
        "INVALID_INPUT",
        "MISSING_CODE",
        "MISSING_MATERIAL",
        "PARTIAL_CONTENT",
        "UNREADABLE",
        "UNRESOLVED_RELATION",
        "OUT_OF_SCOPE",
    ]
    target_refs: list[Target] = Field(min_length=1, max_length=3)
    source_refs: Refs
    detail: Nonempty
    effect: Nonempty


class Summary(Strict):
    conclusion: Nonempty
    priority_finding_keys: Refs


class Report(Strict):
    contract_version: Literal[2]
    analysis_type: Literal["CODE_REVIEW"]
    request_id: Identifier
    outcome: Outcome
    summary: Summary
    target_results: list[TargetResult] = Field(min_length=1, max_length=3)
    findings: list[Finding] = Field(max_length=20000)
    evidence: list[Evidence] = Field(max_length=50000)
    chains: list[Chain] = Field(max_length=10000)
    coverage: list[Coverage] = Field(max_length=50000)
    limitations: list[Limitation] = Field(max_length=10000)


def require(value, code="code_contract_invalid"):
    if not value:
        raise AppError(422, code)


def unique(values):
    require(len(values) == len(set(values)))
    return set(values)


def index(items, key="key"):
    unique([item[key] for item in items])
    return {item[key]: item for item in items}


def refs(values, allowed, required=False):
    require(unique(values) <= set(allowed) and (bool(values) or not required))


def safe_path(path):
    parts = path.replace("\\", "/").split("/")
    excluded = {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        ".venv",
        "venv",
        "target",
        "build",
        "dist",
        "__pycache__",
        ".next",
        ".nuxt",
        ".idea",
        ".vscode",
        ".ssh",
        ".aws",
        ".azure",
        "coverage",
        ".codex",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".git-credentials",
        "credentials",
        "credentials.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
    return (
        bool(path)
        and not any(p in {"", ".", ".."} or p.lower() in excluded for p in parts)
        and ":" not in path
        and not any(ord(c) < 32 for c in path)
        and not any(p.lower().startswith(".env") for p in parts)
        and not any(
            p.lower().split(".")[0] in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"} for p in parts
        )
        and not path.lower().endswith(
            (
                ".pem",
                ".key",
                ".p12",
                ".pfx",
                ".keystore",
                ".jks",
                ".log",
                ".zip",
                ".tar",
                ".gz",
                ".7z",
                ".exe",
                ".dll",
                ".so",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".pdf",
                ".mp4",
                ".mp3",
                ".woff",
                ".woff2",
                ".ttf",
                ".ico",
            )
        )
    )


def validate_input(value: AnalysisInput):
    data = value.model_dump()
    targets = unique(data["targets"])
    sources = index(data["sources"], "source_id")
    materials = index(data["materials"], "source_id")
    require(not sources.keys() & materials.keys())
    segments, states, roles = {}, {}, set()
    units = []
    for source in sources.values():
        require(source["source_kind"] == data["source_mode"])
        commit = source["commit"]
        require(
            (len(commit) == 40 and all(c in "0123456789abcdefABCDEF" for c in commit))
            if data["source_mode"] == "GITHUB"
            else commit == ""
        )
        index(source["files"], "file_id")
        unique([f["path"] for f in source["files"]])
        units.extend(("CODE", source, file) for file in source["files"])
    units.extend(("MATERIAL", material, material) for material in materials.values())
    for kind, source, item in units:
        fid = item["file_id"] if kind == "CODE" else ""
        if kind == "CODE":
            require(safe_path(item["path"]), "code_path_excluded")
        state = item["read_state"]
        require(state == "READABLE" or bool(item["read_note"].strip()))
        require(bool(item["segments"]) == (state in {"READABLE", "PARTIAL"}))
        require(not item["segments"] or bool(source["snapshot_ref"].strip()))
        index(item["segments"], "segment_id")
        if kind == "CODE" and item["segments"]:
            roles.add(source["repository_kind"])
        previous = 0
        for segment in item["segments"]:
            key = kind, source["source_id"], fid, segment["segment_id"]
            segments[key] = segment
            states[key] = state
            if kind == "CODE":
                require(bool(segment["text"].strip()), "code_text_required")
                require("\r" not in segment["text"] and "\x00" not in segment["text"])
                require(not contains_private_key(segment["text"]), "code_private_key_content")
                start = segment["start_line"]
                require(start > previous and (state != "READABLE" or start == previous + 1))
                previous = start + len(segment["text"].split("\n")) - 1
            else:
                require(bool(segment["text"] or segment["image_ref"]))
        if not item["segments"]:
            states[(kind, source["source_id"], fid, "")] = state
    if "FRONTEND_BACKEND_MISMATCH" in targets:
        require("BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}), "code_both_sides_required")
    return data, sources, materials, segments, states


def normalize_code_evidence(value: AnalysisInput, result: Report) -> tuple[Report, list[dict]]:
    # Repair only a unique, complete original line range; never guess a missing source or excerpt.
    _, _, _, segments, _ = validate_input(value)
    report = result.model_dump(by_alias=True)
    corrections = []
    for evidence in report["evidence"]:
        if evidence["kind"] != "CODE":
            continue
        segment = segments.get(
            ("CODE", evidence["source_id"], evidence["file_id"], evidence["segment_id"])
        )
        if segment is None:
            continue
        lines = segment["text"].split("\n")
        start = evidence["start_line"] - segment["start_line"]
        end = evidence["end_line"] - segment["start_line"]
        if 0 <= start <= end < len(lines) and evidence["excerpt"] == "\n".join(
            lines[start : end + 1]
        ):
            continue
        excerpt = evidence["excerpt"].removesuffix("\n")
        text = segment["text"]
        position = text.find(excerpt) if excerpt else -1
        if (
            position < 0
            or text.find(excerpt, position + 1) >= 0
            or position > 0
            and text[position - 1] != "\n"
            or position + len(excerpt) < len(text)
            and text[position + len(excerpt)] != "\n"
        ):
            continue
        actual_start = segment["start_line"] + text.count("\n", 0, position)
        actual_end = actual_start + excerpt.count("\n")
        if excerpt != "\n".join(
            lines[actual_start - segment["start_line"] : actual_end - segment["start_line"] + 1]
        ):
            continue
        corrections.append(
            {
                "evidence_key": evidence["key"],
                "original_start_line": evidence["start_line"],
                "original_end_line": evidence["end_line"],
                "start_line": actual_start,
                "end_line": actual_end,
                "removed_trailing_lf": excerpt != evidence["excerpt"],
            }
        )
        evidence.update(start_line=actual_start, end_line=actual_end, excerpt=excerpt)
    return Report.model_validate(report), corrections


def validate_report(value: AnalysisInput, result: Report):
    data, sources, materials, segments, states = validate_input(value)
    report = result.model_dump(by_alias=True)
    require(report["request_id"] == data["request_id"], "code_request_mismatch")
    goals = index(report["target_results"], "target")
    require(set(goals) == set(data["targets"]))
    findings, evidence, chains, limits = (
        index(report[key]) for key in ("findings", "evidence", "chains", "limitations")
    )
    index([c for goal in goals.values() for c in goal["checks"]])
    refs(report["summary"]["priority_finding_keys"], findings)
    code_keys = {k for k, e in evidence.items() if e["kind"] == "CODE"}
    for e in evidence.values():
        key = e["kind"], e["source_id"], e.get("file_id", ""), e["segment_id"]
        require(key in segments, "code_evidence_invalid")
        segment = segments[key]
        if e["kind"] == "CODE":
            start, end = (
                e["start_line"] - segment["start_line"],
                e["end_line"] - segment["start_line"],
            )
            lines = segment["text"].split("\n")
            require(0 <= start <= end < len(lines), "code_evidence_invalid")
            require(e["excerpt"] == "\n".join(lines[start : end + 1]), "code_evidence_invalid")
        else:
            require(
                e["excerpt"] in segment["text"] and bool(e["excerpt"] or e["observation"]),
                "code_evidence_invalid",
            )
    for limit in limits.values():
        refs(limit["target_refs"], goals, True)
        refs(limit["source_refs"], sources.keys() | materials.keys())
    for chain in chains.values():
        nodes = index(chain["nodes"])
        for node in nodes.values():
            refs(node["evidence_refs"], code_keys, True)
        for edge in chain["edges"]:
            require(edge["from"] in nodes and edge["to"] in nodes and edge["from"] != edge["to"])
            refs(edge["evidence_refs"], code_keys, edge["relation"] != "UNKNOWN")
    for finding in findings.values():
        refs(finding["target_refs"], goals, True)
        refs(finding["evidence_refs"], evidence, True)
        refs(finding["chain_refs"], chains)
        views = index(finding["target_views"], "target")
        require(set(views) == set(finding["target_refs"]))
        for target, view in views.items():
            refs(view["evidence_refs"], finding["evidence_refs"], True)
            refs(view["basis_refs"], finding["evidence_refs"])
            if target == "REQUIREMENT_DEVIATION":
                require(
                    any(
                        evidence[k]["kind"] == "MATERIAL"
                        and materials[evidence[k]["source_id"]]["origin"]
                        in {"REQUIREMENT", "PROTOTYPE", "DECISION"}
                        for k in view["basis_refs"]
                    )
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
                require("BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}))
            require(target == "BUG" or bool(view["comparison_rows"]))
            for row in view["comparison_rows"]:
                for side in ("left", "right"):
                    refs(
                        row[side]["evidence_refs"],
                        finding["evidence_refs"],
                        view["evidence_state"] == "STATIC_SUPPORTED",
                    )
        insufficient = any(v["evidence_state"] == "INSUFFICIENT" for v in views.values())
        require(
            finding["evidence_state"] == ("INSUFFICIENT" if insufficient else "STATIC_SUPPORTED")
        )
        require(not insufficient or bool(finding["missing_evidence"]))
    for target, goal in goals.items():
        refs(goal["limitation_refs"], limits, goal["status"] != "COMPLETE")
        require(all(target in limits[k]["target_refs"] for k in goal["limitation_refs"]))
        associated = {k for k, f in findings.items() if target in f["target_refs"]}
        require(unique(goal["finding_refs"]) == associated)
        check_findings = set()
        for check in goal["checks"]:
            assessment = check["assessment"]
            refs(
                check["evidence_refs"],
                evidence,
                assessment in {"CONSISTENT", "DEVIATION", "SUSPECTED"},
            )
            refs(check["finding_refs"], associated, assessment in {"DEVIATION", "SUSPECTED"})
            require(assessment != "CONSISTENT" or not check["finding_refs"])
            certainty = [
                next(v for v in findings[k]["target_views"] if v["target"] == target)[
                    "evidence_state"
                ]
                for k in check["finding_refs"]
            ]
            require(assessment != "DEVIATION" or all(c == "STATIC_SUPPORTED" for c in certainty))
            require(assessment != "SUSPECTED" or "INSUFFICIENT" in certainty)
            check_findings.update(check["finding_refs"])
        require(check_findings == associated)
        require(goal["status"] != "BLOCKED" or not goal["checks"] and not associated)
        require(goal["status"] == "BLOCKED" or bool(goal["checks"]))
        if goal["status"] == "COMPLETE":
            require(not any(c["assessment"] in {"SUSPECTED", "UNRESOLVED"} for c in goal["checks"]))
        if not any(key[0] == "CODE" for key in segments):
            require(goal["status"] == "BLOCKED")
        if target == "REQUIREMENT_DEVIATION" and not any(
            m["origin"] in {"REQUIREMENT", "PROTOTYPE", "DECISION"} and m["segments"]
            for m in materials.values()
        ):
            require(goal["status"] == "BLOCKED")
    statuses = [g["status"] for g in goals.values()]
    require(
        report["outcome"]
        == (
            "COMPLETE"
            if all(s == "COMPLETE" for s in statuses)
            else "BLOCKED"
            if all(s == "BLOCKED" for s in statuses)
            else "PARTIAL"
        )
    )
    covered = []
    for entry in report["coverage"]:
        key = entry["kind"], entry["source_id"], entry["file_id"], entry["segment_id"]
        require(key in states)
        covered.append(key)
        require(set(index(entry["targets"], "target")) == set(goals))
        for item in entry["targets"]:
            target, disposition = item["target"], item["disposition"]
            refs(
                item["check_refs"],
                {c["key"] for c in goals[target]["checks"]},
                disposition == "REVIEWED",
            )
            require(disposition == "REVIEWED" or not item["check_refs"])
            require(disposition != "UNPROCESSED" or goals[target]["status"] != "COMPLETE")
            require(states[key] not in {"UNREADABLE", "NOT_LOADED"} or disposition == "UNPROCESSED")
            require(
                states[key] != "PARTIAL"
                or disposition == "NOT_RELEVANT"
                or goals[target]["status"] != "COMPLETE"
            )
    require(unique(covered) == set(states))
    return report
