"""Build a difference-first projection without changing the frozen change input."""

import json
import re
from collections import defaultdict
from difflib import unified_diff
from itertools import zip_longest


def _units(data):
    return {
        snapshot["snapshot_ref"]: {unit["unit_id"]: unit for unit in snapshot["units"]}
        for snapshot in data["snapshots"]
    }


def changed_mappings(pair, units):
    changed = {diff["mapping_ref"] for diff in pair["text_diffs"]}
    for mapping in pair["unit_mappings"]:
        if mapping["relation"] == "RENAME":
            changed.add(mapping["mapping_id"])
            continue
        identities = [
            [
                (
                    units[pair[f"{side}_ref"]][unit_id]["presence"],
                    units[pair[f"{side}_ref"]][unit_id]["content_sha256"],
                )
                for unit_id in mapping[f"{side}_unit_ids"]
            ]
            for side in ("before", "after")
        ]
        if identities[0] != identities[1]:
            changed.add(mapping["mapping_id"])
    return changed


def has_mapping_changes(data):
    units = _units(data)
    return any(changed_mappings(pair, units) for pair in data["comparison_pairs"])


def _content(unit):
    return "\n".join(segment["text"] for segment in unit["segments"])


def _hunks(pair, mapping, units):
    before, after = (
        [units[pair[f"{side}_ref"]][ref] for ref in mapping[f"{side}_unit_ids"]]
        for side in ("before", "after")
    )

    def content(unit):
        if not unit or unit["presence"] == "VERIFIED_ABSENT":
            return [], "/dev/null", []
        lines, coordinates = [], []
        for segment in unit["segments"]:
            parts = segment["text"].splitlines(keepends=True)
            start = segment["start_line"] or len(lines) + 1
            lines.extend(parts)
            coordinates.extend(range(start, start + len(parts)))
        return lines, unit["path"], coordinates

    def actual(number, coordinates):
        index = int(number)
        return coordinates[index - 1] if index else 0

    patches = []
    for old, new in zip_longest(before, after):
        old_lines, old_path, old_coordinates = content(old)
        new_lines, new_path, new_coordinates = content(new)
        for line in unified_diff(old_lines, new_lines, old_path, new_path, n=3):
            header = re.fullmatch(r"@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@\n", line)
            if header:
                left = actual(header[1], old_coordinates)
                right = actual(header[3], new_coordinates)
                line = f"@@ -{left}{header[2] or ''} +{right}{header[4] or ''} @@\n"
            if not line.endswith("\n"):
                line += "\n\\ No newline at end of file\n"
            patches.append(line)
    return "".join(patches)


def build(root_input: dict, mode: str) -> dict:
    units = _units(root_input)
    changed_units, compared, pairs = defaultdict(set), set(), []
    for pair in root_input["comparison_pairs"]:
        changed = changed_mappings(pair, units)
        mappings = {m["mapping_id"]: m for m in pair["unit_mappings"] if m["mapping_id"] in changed}
        for side in ("before", "after"):
            snapshot = pair[f"{side}_ref"]
            compared.add(snapshot)
            changed_units[snapshot].update(
                uid for mapping in mappings.values() for uid in mapping[f"{side}_unit_ids"]
            )
        pairs.append(
            {
                **pair,
                "unit_mappings": list(mappings.values()),
                "unchanged_mapping_count": len(pair["unit_mappings"]) - len(mappings),
                "text_diffs": [
                    {**diff, "hunks": _hunks(pair, mappings[diff["mapping_ref"]], units)}
                    for diff in pair["text_diffs"]
                ],
            }
        )
    snapshots, unchanged, context = [], 0, 0
    for snapshot in root_input["snapshots"]:
        ref = snapshot["snapshot_ref"]
        projected = []
        for unit in snapshot["units"]:
            if snapshot["kind"] != "CODE" or unit["unit_id"] in changed_units[ref]:
                projected.append(unit)
                continue
            in_pair = ref in compared
            unchanged += int(in_pair)
            context += int(not in_pair)
            projected.append(
                {
                    **{
                        k: unit[k]
                        for k in ("unit_id", "path", "presence", "read_state", "content_sha256")
                    },
                    "segments": [],
                    "content_provided": "OMITTED_UNCHANGED" if in_pair else "OMITTED_CONTEXT",
                }
            )
        snapshots.append({**snapshot, "units": projected})
    note = f"未变化代码文件 {unchanged} 个、上下文代码文件 {context} 个在此视图中仅列清单。"
    if mode == "CODEX_EXEC":
        note += "完整双侧文件可通过本任务只读目录按需核对。"
    else:
        note += "这些文件未发送正文，需依赖其正文的判断应写入局限。完整核对可使用 CLI。"
    return {
        **root_input,
        "contract_version": 3,
        "view": {"kind": "DIFF_FIRST", "omitted_unit_count": unchanged + context, "note": note},
        "snapshots": snapshots,
        "comparison_pairs": pairs,
        "input_limitations": [
            *root_input["input_limitations"],
            *([note] if mode != "CODEX_EXEC" and unchanged + context else []),
        ],
    }


GUIDANCE = "先读目录和差异，再按影响追踪需要读取两侧原文与上下文。引用使用固定快照和单元标识。"


def reading_files(data: dict, view: dict) -> list[dict]:
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    files = [
        {"path": "task.json", "text": json.dumps(view, ensure_ascii=False)},
        {"path": "cases.json", "text": json.dumps(data["cases"], ensure_ascii=False)},
        {"path": "history.json", "text": json.dumps(data["historical_items"], ensure_ascii=False)},
    ]
    scopes = [
        (f"{side}/pair-{number:03d}", snapshots[pair[f"{side}_ref"]])
        for number, pair in enumerate(data["comparison_pairs"], 1)
        for side in ("before", "after")
    ]
    scopes.extend(
        (f"context/source-{number:03d}", snapshots[ref])
        for number, ref in enumerate(data["context_refs"], 1)
    )
    for directory, snapshot in scopes:
        for number, unit in enumerate(snapshot["units"], 1):
            files.append(
                {
                    "path": f"{directory}/unit-{number:05d}.txt",
                    "description": " / ".join(
                        (snapshot["snapshot_ref"], unit["unit_id"], unit["path"])
                    ),
                    "text": _content(unit),
                }
            )
    for number, pair in enumerate(view["comparison_pairs"], 1):
        for index, diff in enumerate(pair["text_diffs"], 1):
            files.append(
                {
                    "path": f"diffs/pair-{number:03d}/{index:05d}.diff",
                    "description": f"{pair['pair_id']} / {diff['diff_id']}",
                    "text": diff["hunks"] or diff["note"],
                }
            )
    return files
