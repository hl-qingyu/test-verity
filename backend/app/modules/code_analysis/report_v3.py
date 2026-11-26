"""Platform coverage for code analysis v3 and its fixed CLI reading layout."""

from collections import Counter

from app.modules.code_analysis import contract
from app.modules.requirements import analysis_materials


def validate(value, output, *, normalize=True):
    output, corrections = (
        contract.normalize_code_evidence(value, output) if normalize else (output, [])
    )
    report = contract.validate_report(value, output)
    sources, gaps = [], []
    for source in value.sources:
        counts = Counter(file.read_state for file in source.files)
        sources.append(
            {
                "source_id": source.source_id,
                "files": len(source.files),
                "readable": counts["READABLE"],
                "partial": counts["PARTIAL"],
                "unreadable": counts["UNREADABLE"] + counts["NOT_LOADED"],
            }
        )
        gaps.extend(
            {
                "source_id": source.source_id,
                "file_id": file.file_id,
                "read_state": file.read_state,
                "note": file.read_note,
            }
            for file in source.files
            if file.read_state != "READABLE"
        )
    missing = {
        (reference.source_id, reference.file_id)
        for limit in output.limitations
        if limit.kind == "NOT_ASSESSED"
        for reference in limit.file_refs
    }
    statuses = [target.status for target in output.target_results]
    if all(status == "BLOCKED" for status in statuses):
        outcome = "BLOCKED"
    elif all(status == "COMPLETE" for status in statuses) and not gaps and not missing:
        outcome = "COMPLETE"
    else:
        outcome = "PARTIAL"
    report.update(
        outcome=outcome,
        platform_coverage={
            "sources": sources,
            "file_gaps": gaps,
            "not_assessed_files": [
                {"source_id": source, "file_id": file} for source, file in sorted(missing)
            ],
        },
    )
    return report, corrections


def reading_options(mode, data, binaries):
    if mode != "CODEX_EXEC":
        return {}
    files, sources = [], []
    for number, source in enumerate(data["sources"], 1):
        manifest = []
        for position, file in enumerate(source["files"], 1):
            path = f"sources/source-{number:03d}/file-{position:05d}.txt"
            lines, next_line = [], 1
            for segment in file["segments"]:
                if segment["start_line"] > next_line:
                    lines.append(f"[原文件第 {next_line}–{segment['start_line'] - 1} 行未读取]")
                current = segment["text"].split("\n")
                lines.extend(current)
                next_line = segment["start_line"] + len(current)
            files.append(
                {
                    "path": path,
                    "description": f"{source['source_id']} / {file['file_id']} / {file['path']}",
                    "text": "\n".join(lines),
                }
            )
            manifest.append(
                {
                    **{k: v for k, v in file.items() if k != "segments"},
                    "reading_path": path,
                    "segments": [
                        {"segment_id": s["segment_id"], "start_line": s["start_line"]}
                        for s in file["segments"]
                    ],
                }
            )
        sources.append({**source, "files": manifest})
    return analysis_materials.structured_reading_options(
        mode, {**data, "sources": sources}, binaries, files=files
    )
