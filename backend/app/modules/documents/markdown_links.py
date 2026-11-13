"""Parse link identities, never resolve a URL as a filesystem or network location."""

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

from app.modules.documents.files import text_prefix


def link_key(href: str) -> str:
    if re.search(r"%(?![0-9a-fA-F]{2})", href):
        return href
    try:
        return unquote(href, encoding="utf-8", errors="strict")
    except UnicodeError:
        return href


def link_hash(href: str) -> str:
    return hashlib.sha256(link_key(href).encode()).hexdigest()


def extract_links(text: str) -> list[dict]:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    # Local file URLs are legitimate identities; they are never opened by this module.
    original_validator = parser.validateLink
    parser.validateLink = lambda href: href.lower().startswith("file:") or original_validator(href)
    found: dict[str, dict] = {}
    for block in parser.parse(text):
        children = block.children or []
        for i, token in enumerate(children):
            if token.type != "link_open":
                continue
            href = token.attrGet("href") or ""
            if not href or href.startswith("#") or len(href) > 8192:
                continue
            label = []
            for child in children[i + 1 :]:
                if child.type == "link_close":
                    break
                if child.type in ("text", "code_inline", "image"):
                    label.append(child.content)
            found.setdefault(
                link_key(href), {"href": href, "label": "".join(label) or link_key(href)}
            )
    return list(found.values())


def file_links(path: Path) -> tuple[list[dict], bool]:
    text, truncated = text_prefix(path)
    # The original preview has this same bound. Never interpret code blocks as links.
    return extract_links(text[:100000]), truncated or len(text) > 100000
