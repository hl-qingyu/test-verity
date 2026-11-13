"""Bounded local file validation and text-only office previews; never execute document content."""

import codecs
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.core.errors import AppError
from app.modules.documents.office import preview_office, xml

MEDIA = {
    "html": "text/plain",
    "htm": "text/plain",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "md": "text/plain",
    "txt": "text/plain",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def validate_file(path: Path, extension: str) -> None:
    if extension not in MEDIA:
        raise AppError(422, "document_format")
    with path.open("rb") as f:
        head = f.read(16)
    valid = {
        "png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": head.startswith(b"\xff\xd8\xff"),
        "jpeg": head.startswith(b"\xff\xd8\xff"),
        "webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
        "pdf": head.startswith(b"%PDF-"),
        "doc": head.startswith(bytes.fromhex("D0CF11E0A1B11AE1")),
        "xls": head.startswith(bytes.fromhex("D0CF11E0A1B11AE1")),
    }
    if extension in valid and not valid[extension]:
        raise AppError(422, "document_format_mismatch")
    if extension in ("txt", "md", "html", "htm"):
        text_prefix(path)
    if extension in ("docx", "xlsx"):
        try:
            with zipfile.ZipFile(path) as z:
                required = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
                if z.getinfo(required).file_size <= 2 * 1024 * 1024:
                    xml(z.read(required))
                if any("vbaproject" in name.lower() for name in z.namelist()):
                    raise ValueError("macros")
        except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError, ElementTree.ParseError):
            raise AppError(422, "document_format_mismatch") from None


def decode_text(data: bytes, final: bool = True) -> str:
    for encoding in (
        "utf-8-sig",
        "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "gb18030",
    ):
        try:
            text = codecs.getincrementaldecoder(encoding)().decode(data, final=final)
            if "\x00" not in text:
                return text
        except UnicodeError:
            pass
    raise AppError(422, "document_text_encoding")


def text_prefix(path: Path) -> tuple[str, bool]:
    with path.open("rb") as stream:
        data = stream.read(500001)
    truncated = len(data) > 500000
    return decode_text(data[:500000], final=not truncated), truncated


def preview(path: Path, extension: str) -> dict:
    if extension == "doc":
        return {
            "kind": "unsupported",
            "text": "此旧版格式暂不支持在线预览，请下载原件，或另存为 DOCX 后上传新版本。",
        }
    if extension in ("png", "jpg", "jpeg", "webp", "pdf"):
        return {"kind": "pdf" if extension == "pdf" else "image", "text": ""}
    if extension in ("docx", "xlsx", "xls"):
        return preview_office(path, extension)
    try:
        text, truncated = text_prefix(path)
        return {"kind": "text", "text": text[:100000], "truncated": truncated or len(text) > 100000}
    except AppError:
        return {
            "kind": "unsupported",
            "text": "文件已完整保存，但内容超过安全预览范围或编码无法识别，请下载原件查看。",
        }
    except (
        ValueError,
        IndexError,
        KeyError,
        AttributeError,
        zipfile.BadZipFile,
        RuntimeError,
        ElementTree.ParseError,
    ):
        return {
            "kind": "unsupported",
            "text": "文件内容无法解析，请下载原件检查，或上传修复后的新版本。",
        }
