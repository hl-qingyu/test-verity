"""Deterministic coordinate repair; original candidates and strict imports are unchanged."""


def normalize_coordinates(data, report):
    snapshots = {s.snapshot_ref: s for s in data.snapshots}
    pairs = {p.pair_id: p for p in data.comparison_pairs}
    normalized = report.model_copy(deep=True)
    corrections = []
    for e in normalized.evidence:
        source = snapshots.get(e.snapshot_ref)
        if source is None or e.kind != "TEXT":
            continue
        unit = next((u for u in source.units if u.unit_id == e.unit_id), None)
        segment = (
            next((s for s in unit.segments if s.segment_id == e.segment_id), None) if unit else None
        )
        if segment is None:
            continue
        if source.kind != "CODE":
            pair = pairs.get(e.pair_ref)
            bound = (
                not e.pair_ref and e.snapshot_ref in data.context_refs
                if e.side == "CONTEXT"
                else pair is not None and getattr(pair, e.side.lower() + "_ref") == e.snapshot_ref
            )
            if (
                not bound
                or not e.excerpt.strip()
                or e.excerpt in segment.text
                or e.start_line is not None
                or e.end_line is not None
            ):
                continue
            # Only an exact, unique occurrence inside the same fixed unit can move a citation.
            matches = []
            for candidate in unit.segments:
                pos = candidate.text.find(e.excerpt)
                if pos >= 0:
                    matches.append(candidate)
                    if candidate.text.find(e.excerpt, pos + 1) >= 0:
                        matches.append(candidate)
                if len(matches) > 1:
                    break
            if len(matches) == 1:
                corrections.append(
                    {
                        "evidence_key": e.key,
                        "kind": "EXACT_TEXT_SEGMENT",
                        "original_segment_id": e.segment_id,
                        "segment_id": matches[0].segment_id,
                        "original_location": segment.location,
                        "location": matches[0].location,
                    }
                )
                e.segment_id = matches[0].segment_id
            continue
        lines = segment.text.split("\n")
        if e.start_line is not None and e.end_line is not None:
            lo, hi = e.start_line - segment.start_line, e.end_line - segment.start_line
            if 0 <= lo <= hi < len(lines) and "\n".join(lines[lo : hi + 1]) == e.excerpt:
                continue
        excerpt = e.excerpt.removesuffix("\n")
        pos = segment.text.find(excerpt) if excerpt else -1
        if (
            pos < 0
            or segment.text.find(excerpt, pos + 1) >= 0
            or pos > 0
            and segment.text[pos - 1] != "\n"
            or pos + len(excerpt) < len(segment.text)
            and segment.text[pos + len(excerpt)] != "\n"
        ):
            continue
        start = segment.start_line + segment.text.count("\n", 0, pos)
        end = start + excerpt.count("\n")
        corrections.append(
            {
                "evidence_key": e.key,
                "original_start_line": e.start_line,
                "original_end_line": e.end_line,
                "start_line": start,
                "end_line": end,
                "removed_trailing_lf": e.excerpt != excerpt,
            }
        )
        e.start_line, e.end_line, e.excerpt = start, end, excerpt
    return normalized, corrections
