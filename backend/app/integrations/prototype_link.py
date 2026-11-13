"""Read published static prototype catalogs without executing their scripts."""

import hashlib
import json
import posixpath
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from markdown_it import MarkdownIt

from app.core.errors import AppError
from app.integrations.prototype_data import read_registry
from app.integrations.prototype_project import PAGE_PATH, annotation_blocks, manifest, tree_pages

MAX_FILE = 2_000_000
MAX_INPUT = 16 * 1024 * 1024
PAGE_FILE = re.compile(r"[A-Za-z0-9_-]+\.html\Z")
ROOT_PATH = re.compile(r"/p/[A-Za-z0-9]+/\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_opener = build_opener(NoRedirect)


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError:
        raise AppError(422, "prototype_link_unsupported") from None


def base_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme == "http" and parsed.netloc == "127.0.0.1:4173":
        query = parse_qs(parsed.query, keep_blank_values=True)
        fragment = parse_qs(parsed.fragment, keep_blank_values=True)
        if (
            parsed.path not in ("/", "/index.html")
            or (
                parsed.query
                and (
                    set(query) != {"end"}
                    or len(query["end"]) != 1
                    or not re.fullmatch(r"[A-Za-z0-9_-]+", query["end"][0])
                )
            )
            or (
                parsed.fragment
                and (
                    set(fragment) != {"page"}
                    or len(fragment["page"]) != 1
                    or not PAGE_PATH.fullmatch(fragment["page"][0])
                )
            )
        ):
            raise AppError(422, "prototype_link_unsupported")
        return "http://127.0.0.1:4173/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "prototype.geekuat.com"
        or not ROOT_PATH.fullmatch(parsed.path)
        or parsed.query
        or parsed.fragment
    ):
        raise AppError(422, "prototype_link_unsupported")
    return url


def fetch(url: str) -> bytes:
    try:
        request = Request(
            url, headers={"Accept": "text/html, application/javascript, text/markdown, text/plain"}
        )
        with _opener.open(request, timeout=12) as response:
            content = response.read(MAX_FILE + 1)
            if len(content) > MAX_FILE:
                raise AppError(413, "prototype_link_too_large")
            return content
    except (HTTPError, URLError, TimeoutError, OSError):
        raise AppError(422, "prototype_link_unavailable") from None


def assigned_json(source: str, name: str):
    assignment = re.search(r"\bwindow\." + re.escape(name) + r"\s*=\s*", source)
    if not assignment:
        raise AppError(422, "prototype_link_unsupported")
    try:
        return json.JSONDecoder().raw_decode(source[assignment.end() :])[0]
    except (ValueError, RecursionError):
        raise AppError(422, "prototype_link_unsupported") from None


def published_catalog(source: str) -> tuple[list, dict]:
    if not re.search(r"\bwindow\.PROTOTYPE_PAGES\s*=", source):
        tree = assigned_json(source, "XETA_PAGE_TREE")
        if not isinstance(tree, list) or len(tree) > 5000:
            raise AppError(422, "prototype_link_unsupported")
        return tree, assigned_json(source, "XETA_ANNOTATIONS")
    registry = read_registry(source)
    pages = registry.get("PROTOTYPE_PAGES")
    annotations = registry.get("PROTOTYPE_ANNOTATIONS")
    if not isinstance(pages, list) or len(pages) > 5000 or not isinstance(annotations, dict):
        raise AppError(422, "prototype_link_unsupported")
    tree, groups = [], {}
    for page in pages:
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("title"), str)
            or not isinstance(page.get("module", ""), str)
            or not isinstance(page.get("file"), str)
        ):
            raise AppError(422, "prototype_link_unsupported")
        group = page.get("module", "")
        if group and group not in groups:
            groups[group] = len(tree)
            tree.append({"id": len(tree), "type": "folder", "name": group})
        tree.append(
            {
                "id": len(tree),
                "parentId": groups.get(group),
                "type": "page",
                "name": page["title"],
                "file": page["file"],
            }
        )
    notes = {}
    for file, blocks in annotations.items():
        if not isinstance(blocks, list):
            raise AppError(422, "prototype_link_unsupported")
        notes[file] = {}
        for block in blocks:
            if (
                not isinstance(block, dict)
                or not isinstance(block.get("title"), str)
                or not isinstance(block.get("items", []), list)
                or any(not isinstance(item, str) for item in block.get("items", []))
                or not isinstance(block.get("markdown", ""), str)
            ):
                raise AppError(422, "prototype_link_unsupported")
            items = [*block.get("items", [])]
            if block.get("markdown"):
                items.append(block["markdown"])
            notes[file].setdefault(block["title"], []).extend(items)
    return tree, notes


def catalog(url: str) -> dict:
    url = base_url(url)
    html = decode(fetch(url))
    apps = manifest(html)
    if apps is not None:
        pages, hashes = [], [hashlib.sha256(html.encode()).hexdigest()]
        total = len(html.encode())
        for app in apps:
            raw = fetch(url + app["tree"])
            total += len(raw)
            if total > MAX_INPUT:
                raise AppError(413, "prototype_link_too_large")
            hashes.append(hashlib.sha256(raw).hexdigest())
            pages.extend(tree_pages(decode(raw), app, url))
        if not pages or len(pages) > 5000 or len({p["file"] for p in pages}) != len(pages):
            raise AppError(422, "prototype_link_unsupported")
        return {
            "snapshot": hashlib.sha256((url + "".join(hashes)).encode()).hexdigest(),
            "pages": pages,
            "notes": {},
            "page_annotations": True,
        }
    matches = re.findall(r'<script\s+src="(assets/annotations\.js(?:\?[^"<>]*)?)"', html)
    if len(matches) != 1:
        raise AppError(422, "prototype_link_unsupported")
    raw = fetch(url + matches[0])
    source = decode(raw)
    tree, notes = published_catalog(source)
    if not isinstance(tree, list) or not isinstance(notes, dict) or len(tree) > 10000:
        raise AppError(422, "prototype_link_unsupported")
    nodes = {}
    for node in tree:
        if (
            not isinstance(node, dict)
            or type(node.get("id")) is not int
            or node["id"] in nodes
            or not isinstance(node.get("name"), str)
            or node.get("type") not in ("folder", "page")
            or (node["type"] == "page" and not PAGE_FILE.fullmatch(str(node.get("file"))))
        ):
            raise AppError(422, "prototype_link_unsupported")
        nodes[node["id"]] = node
    pages, filenames = [], set()
    for node in tree:
        if node["type"] != "page":
            continue
        path, current, seen = [], node, set()
        while current:
            if current["id"] in seen:
                raise AppError(422, "prototype_link_unsupported")
            seen.add(current["id"])
            path.append(current["name"])
            parent = current.get("parentId")
            if parent is not None and parent not in nodes:
                raise AppError(422, "prototype_link_unsupported")
            current = nodes.get(parent)
        filename = node["file"]
        if filename in filenames:
            raise AppError(422, "prototype_link_unsupported")
        filenames.add(filename)
        pages.append(
            {
                "file": filename,
                "path": " / ".join(reversed(path)),
                "url": url + "pages/" + filename,
            }
        )
    if not pages:
        raise AppError(422, "prototype_link_unsupported")
    if not all(
        isinstance(blocks, dict)
        and all(
            isinstance(title, str)
            and isinstance(items, list)
            and all(isinstance(item, str) for item in items)
            for title, items in blocks.items()
        )
        for blocks in notes.values()
    ):
        raise AppError(422, "prototype_link_unsupported")
    return {
        "snapshot": hashlib.sha256(url.encode() + raw).hexdigest(),
        "pages": pages,
        "notes": notes,
    }


class AnnotationLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key, value in attrs if key == "href" and value)


def markdown_links(text: str) -> list[str]:
    parser = AnnotationLinks()
    # Rendering only parses text; code examples stay escaped and no HTML/JS is executed.
    parser.feed(MarkdownIt("commonmark").render(text))
    return parser.links


def markdown_url(root: str, base: str, href: str) -> str | None:
    try:
        path = unquote(urlsplit(href).path, encoding="utf-8", errors="strict")
        if not path.lower().endswith(".md"):
            return None
        target = urlsplit(urljoin(base, href))
        decoded = unquote(target.path, encoding="utf-8", errors="strict")
        normalized = posixpath.normpath(decoded)
        if (
            target.scheme != urlsplit(root).scheme
            or target.netloc != urlsplit(root).netloc
            or not normalized.startswith(urlsplit(root).path)
            or "\\" in decoded
            or any(ord(c) < 32 for c in href + decoded)
            or re.search(r"%(?![0-9a-fA-F]{2})", href)
            or re.search(r"%[0-9a-fA-F]{2}", decoded)
        ):
            raise ValueError("unsupported Markdown reference")
        result = urlunsplit(
            (
                target.scheme,
                target.netloc,
                quote(normalized, safe="/"),
                quote(target.query, safe="=&/%:+,;?@-._~!"),
                "",
            )
        )
        if len("批注引用 Markdown · " + unquote(result)) > 1000:
            raise ValueError("reference exceeds evidence location limit")
        return result
    except (ValueError, UnicodeError):
        raise AppError(422, "prototype_link_markdown_unsupported") from None


def read_pages(url: str, selected: list[str], snapshot: str) -> dict:
    url = base_url(url)
    index = catalog(url)
    allowed = {page["file"]: page for page in index["pages"]}
    if (
        index["snapshot"] != snapshot
        or not selected
        or len(selected) != len(set(selected))
        or any(file not in allowed for file in selected)
    ):
        raise AppError(409, "prototype_link_changed")
    segments, hashes, total = [], [], 0
    pending, seen = [], set()

    def references(text: str, base: str):
        for href in markdown_links(text):
            target = markdown_url(url, base, href)
            if target and target not in seen:
                seen.add(target)
                pending.append(target)

    # ponytail: sequential GETs; use bounded concurrency if large selections stall the worker.
    for file in selected:
        raw = fetch(allowed[file]["url"])
        hashes.append(hashlib.sha256(raw).hexdigest())
        text = decode(raw)
        total += len(raw)
        segments.append({"location": allowed[file]["path"] + " · HTML原文", "text": text})
        blocks = {}
        if index.get("page_annotations"):
            annotation_url = allowed[file]["url"].removesuffix(".html") + ".annotations.js"
            raw_notes = fetch(annotation_url)
            hashes.append(hashlib.sha256(annotation_url.encode() + raw_notes).hexdigest())
            total += len(raw_notes)
            blocks = annotation_blocks(decode(raw_notes), file)
        for notes in (index["notes"].get("*", {}), index["notes"].get(file, {})):
            for title, items in notes.items():
                blocks.setdefault(title, []).extend(items)
        for title, items in blocks.items():
            if not any(item.strip() for item in items):
                continue
            note = "\n".join(items)
            hashes.append(hashlib.sha256((file + "\n" + title + "\n" + note).encode()).hexdigest())
            total += len(note.encode())
            segments.append(
                {
                    "location": allowed[file]["path"] + " · 批注：" + title,
                    "text": note,
                }
            )
            references(note, allowed[file]["url"] if index.get("page_annotations") else url)
        if total > MAX_INPUT:
            raise AppError(413, "prototype_link_too_large")
    for target in pending:
        try:
            raw = fetch(target)
            text = decode(raw)
            if (
                not text.strip()
                or "\x00" in text
                or re.match(r"\s*(?:<!doctype\s+html|<html\b)", text, re.IGNORECASE)
            ):
                raise AppError(422, "prototype_link_markdown_unavailable")
        except AppError as error:
            if error.detail == "prototype_link_too_large":
                raise
            raise AppError(422, "prototype_link_markdown_unavailable") from None
        total += len(raw)
        if total > MAX_INPUT:
            raise AppError(413, "prototype_link_too_large")
        hashes.append(hashlib.sha256(target.encode() + b"\n" + raw).hexdigest())
        segments.append({"location": "批注引用 Markdown · " + unquote(target), "text": text})
        references(text, target)
    return {
        "snapshot_ref": hashlib.sha256((snapshot + "".join(hashes)).encode()).hexdigest(),
        "segments": segments,
    }
