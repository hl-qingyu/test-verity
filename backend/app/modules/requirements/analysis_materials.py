"""Read complete selected contents without executing HTML, scripts or Office formulas."""

import base64
import hashlib
import json
from pathlib import Path

import openpyxl
import xlrd

from app.modules.documents.files import MEDIA, decode_text
from app.modules.documents.office import W, archive, paragraph_text, xml


def text_segments(text: str, location: str) -> list[dict]:
    # Split for precise evidence references, not truncation: all pieces are retained.
    return [
        {
            "segment_id": f"s{i + 1}",
            "location": f"{location} · 字符{start + 1}–{min(start + 16000, len(text))}",
            "text": text[start : start + 16000],
            "image_ref": "",
        }
        for i, start in enumerate(range(0, len(text), 16000))
    ]


def file_material(path: Path, extension: str, source: str, filename: str) -> dict:
    data = path.read_bytes()
    item = {
        "source_id": source,
        "role": "DOCUMENT",
        "kind": "TEXT",
        "snapshot_ref": hashlib.sha256(data).hexdigest(),
        "read_state": "READABLE",
        "read_note": "",
        "segments": [],
    }
    if extension in ("png", "jpg", "jpeg", "webp", "pdf"):
        item["kind"] = "IMAGE" if extension != "pdf" else "TEXT"
        item["segments"] = [
            {
                "segment_id": "s1",
                "location": filename + " · 全文/整图",
                "text": "",
                "image_ref": source,
            }
        ]
        return item
    if extension in ("md", "txt", "html", "htm"):
        text = decode_text(data)
    elif extension == "docx":
        with archive(path) as z:
            root = xml(z.read("word/document.xml"))
            text = "\n".join(paragraph_text(p) for p in root.iter(W + "p"))
            if any(n.startswith("word/media/") for n in z.namelist()):
                item["read_state"], item["read_note"] = (
                    "PARTIAL",
                    "已读取正文；内嵌图片未提取，请另选图片资料",
                )
    elif extension in ("xlsx", "xls"):
        lines = []
        if extension == "xlsx":
            with archive(path):
                book = openpyxl.load_workbook(
                    path, read_only=True, data_only=False, keep_links=False
                )
                try:
                    for sheet in book:
                        sheet.reset_dimensions()
                        for row in sheet.iter_rows():
                            lines.extend(
                                f"{sheet.title}!{cell.coordinate}: {cell.value}"
                                for cell in row
                                if cell.value is not None
                            )
                finally:
                    book.close()
        else:
            book = xlrd.open_workbook(path, on_demand=True)
            try:
                for sheet in book.sheets():
                    for r in range(sheet.nrows):
                        lines.extend(
                            f"{sheet.name}!R{r + 1}C{c + 1}: {sheet.cell_value(r, c)}"
                            for c in range(sheet.ncols)
                            if sheet.cell_value(r, c) != ""
                        )
            finally:
                book.release_resources()
        text = "\n".join(lines)
        item["read_state"], item["read_note"] = (
            "PARTIAL",
            "已读取工作表单元格；图片、图表和宏不作为已读取内容",
        )
    else:
        item["read_state"], item["read_note"] = "UNREADABLE", "旧DOC暂不能解析，请转换为DOCX或PDF"
        return item
    item["segments"] = text_segments(text, filename)
    return item


def model_content(
    context: dict, binaries: list[tuple[Path, str, str, str]], *, attachment_key: str = "source_id"
) -> list[dict]:
    result = [{"type": "input_text", "text": json.dumps(context, ensure_ascii=False)}]
    # Resolve image references from fixed input; an imported source ID may itself contain '#'.
    references = {}
    pending = [context] if binaries and attachment_key != "image_ref" else []
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            identity = value.get(attachment_key)
            if isinstance(identity, str):
                units = value.get("units", [])
                if not isinstance(units, list):
                    units = []
                sections = [value.get("segments", [])] + [
                    unit.get("segments", []) for unit in units if isinstance(unit, dict)
                ]
                for section in sections:
                    if not isinstance(section, list):
                        continue
                    for segment in section:
                        if (
                            isinstance(segment, dict)
                            and isinstance(segment.get("image_ref"), str)
                            and segment["image_ref"]
                            and isinstance(segment.get("segment_id"), str)
                        ):
                            key, target = segment["image_ref"], (identity, segment["segment_id"])
                            references[key] = (
                                target
                                if key not in references or references[key] == target
                                else None
                            )
            pending.extend(v for v in value.values() if isinstance(v, dict | list))
        elif isinstance(value, list):
            pending.extend(v for v in value if isinstance(v, dict | list))
    for path, extension, source, filename in binaries:
        mapping_key = attachment_key
        mapping_ref, segment_id = references.get(source) or (source, "s1")
        if "#" in source and not references.get(source):
            mapping_key, mapping_ref, segment_id = "image_ref", source, ""
        segment_note = f"segment_id={segment_id}；" if segment_id else "对应固定输入同名图片引用；"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        result.append(
            {
                "type": "input_text",
                "text": (
                    f"以下附件对应{mapping_key}={mapping_ref}，{segment_note}"
                    "使用observation描述，不能伪造文字excerpt或精确页码。"
                ),
            }
        )
        if extension == "pdf":
            result.append(
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": "data:application/pdf;base64," + encoded,
                }
            )
        else:
            result.append(
                {
                    "type": "input_image",
                    "image_url": "data:" + MEDIA[extension] + ";base64," + encoded,
                }
            )
    return result


READING_GUIDANCE = "先读 index.md，再按清单读完全部任务和资料文件。按照固定来源和片段标识引用原文。"


def reading_files(materials: list, attachments: list) -> list[dict]:
    files = []
    for position, material in enumerate(materials, 1):
        directory = f"material-{position:04d}"
        source = material.get("snapshot_ref") or material["source_id"]
        files.append(
            {
                "path": f"{directory}/source.json",
                "description": source,
                "text": json.dumps(
                    {k: v for k, v in material.items() if k != "segments"}, ensure_ascii=False
                ),
            }
        )
        for number, segment in enumerate(material["segments"], 1):
            metadata = json.dumps(
                {
                    "source_id": material.get("source_id", source),
                    "snapshot_ref": source,
                    **{k: v for k, v in segment.items() if k != "text"},
                },
                ensure_ascii=False,
            )
            files.append(
                {
                    "path": f"{directory}/segment-{number:04d}.txt",
                    "description": f"{source} · {segment['location']}",
                    "text": f"{metadata}\n{segment['text']}",
                }
            )
    for number, (path, extension, source, _) in enumerate(attachments, 1):
        kind = "jpeg" if extension in ("jpg", "jpeg") else extension
        if kind in {"png", "jpeg", "gif", "webp"}:
            files.append(
                {
                    "path": f"media/image-{number:04d}.{kind}",
                    "description": f"固定图片引用 {source}",
                    "kind": kind,
                    "media": path.read_bytes(),
                }
            )
    return files


def structured_reading_options(call_mode, data, attachments, *, files=()):
    if call_mode != "CODEX_EXEC":
        return {}
    context = {k: v for k, v in data.items() if k != "materials"}
    return {
        "reading_guidance": READING_GUIDANCE,
        "reading_files": [
            {"path": "task.json", "text": json.dumps(context, ensure_ascii=False)},
            *reading_files(data["materials"], attachments),
            *files,
        ],
    }
