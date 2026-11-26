"""Validate v3 candidates against the complete frozen root and compute report coverage."""

from collections import Counter

from app.modules.change_analysis import comparison, contract, evidence, model_view


def _resolve_missing(parsed, output):
    units = {
        (s.snapshot_ref, unit.unit_id): (s, unit) for s in parsed.snapshots for unit in s.units
    }
    corrections = []
    for item in output.evidence:
        if item.kind != "TEXT":
            continue
        pair = units.get((item.snapshot_ref, item.unit_id))
        if pair is None:
            continue
        source, unit = pair
        if item.segment_id and (
            source.kind != "CODE" or item.start_line is not None and item.end_line is not None
        ):
            continue
        excerpt = item.excerpt
        if not excerpt.strip():
            continue
        matches = []
        for segment in unit.segments:
            if source.kind != "CODE":
                position = segment.text.find(excerpt)
                if position >= 0:
                    matches.append((segment, None, None))
                    if segment.text.find(excerpt, position + 1) >= 0:
                        matches.append((segment, None, None))
                continue
            if segment.start_line is None:
                continue
            lines, quoted = segment.text.split("\n"), excerpt.split("\n")
            for pos, line in enumerate(lines):
                if line == quoted[0] and lines[pos : pos + len(quoted)] == quoted:
                    start = segment.start_line + pos
                    matches.append((segment, start, start + len(quoted) - 1))
        if len(matches) != 1:
            continue
        segment, start, end = matches[0]
        corrections.append(
            {
                "evidence_key": item.key,
                "kind": "EXACT_V3_COORDINATES",
                "original_segment_id": item.segment_id,
                "original_start_line": item.start_line,
                "original_end_line": item.end_line,
                "segment_id": segment.segment_id,
                "start_line": start,
                "end_line": end,
            }
        )
        item.segment_id, item.start_line, item.end_line = segment.segment_id, start, end
    return corrections


def validate(raw, data, mode, *, normalize=True):
    output = contract.CandidateV3.model_validate(raw)
    corrections = _resolve_missing(data, output) if normalize else []
    if normalize:
        output, other = evidence.normalize_coordinates(data, output)
        corrections.extend(other)
    contract.validate_report(data, output)
    snapshots = data.model_dump()
    units = model_view._units(snapshots)
    pairs = []
    unreadable, changed_unreadable = set(), set()
    for pair in snapshots["comparison_pairs"]:
        changed = model_view.changed_mappings(pair, units)
        counts = Counter(changed=0, unchanged=0, added=0, deleted=0)
        for mapping in pair["unit_mappings"]:
            sides = [pair[f"{side}_ref"] for side in ("before", "after")]
            items = [
                [units[ref][uid] for uid in mapping[f"{side}_unit_ids"]]
                for ref, side in zip(sides, ("before", "after"), strict=True)
            ]
            present = [any(u["presence"] == "PRESENT" for u in side) for side in items]
            updated = mapping["mapping_id"] in changed
            if not updated:
                counts["unchanged"] += 1
            elif not present[0] and present[1]:
                counts["added"] += 1
            elif present[0] and not present[1]:
                counts["deleted"] += 1
            else:
                counts["changed"] += 1
            gaps = {
                (ref, u["unit_id"])
                for ref, side in zip(sides, items, strict=True)
                for u in side
                if u["presence"] != "VERIFIED_ABSENT" and u["read_state"] != "READABLE"
            }
            unreadable.update(gaps)
            if updated:
                changed_unreadable.update(gaps)
        pairs.append({"pair_ref": pair["pair_id"], **counts})
    for ref in snapshots["context_refs"]:
        unreadable.update(
            (ref, u["unit_id"]) for u in units[ref].values() if u["read_state"] != "READABLE"
        )
    outstanding = {
        (ref.snapshot_ref, ref.unit_id)
        for limit in output.limitations
        if limit.code == "NOT_ASSESSED"
        for ref in limit.unit_refs
    }
    targets = [target.status for target in output.target_results]
    if all(status == "BLOCKED" for status in targets) and not output.changes and not output.risks:
        outcome = "BLOCKED"
    elif (
        all(status == "COMPLETE" for status in targets)
        and not changed_unreadable
        and not outstanding
    ):
        outcome = "COMPLETE"
    else:
        outcome = "PARTIAL"

    def refs(identities):
        return [{"snapshot_ref": ref, "unit_id": uid} for ref, uid in sorted(identities)]

    saved = output.model_dump(by_alias=True)
    saved.update(
        outcome=outcome,
        platform_coverage={
            "pairs": pairs,
            "unreadable_units": refs(unreadable),
            "not_assessed_units": refs(outstanding),
            "omitted_unit_count": (
                model_view.build(snapshots, mode)["view"]["omitted_unit_count"]
                if mode == "RESPONSES_API"
                else 0
            ),
        },
    )
    return saved, corrections


def unchanged(data, parsed):
    raw = comparison.unchanged_report(data, include_coverage=False)
    raw["contract_version"] = 3
    raw.pop("outcome")
    return validate(raw, parsed, "SKIPPED")[0]
