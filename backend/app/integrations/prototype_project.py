"""Parse the declarative multi-app prototype format without executing its viewer."""

import re
from html.parser import HTMLParser

from app.integrations.prototype_data import RegistryReader, reject

PAGE_PATH = re.compile(r"(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.html\Z")


class ProjectScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline = []
        self.sources = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            src = dict(attrs).get("src")
            if src:
                self.sources.append(src)
            self.current = [] if not src else None

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.inline.append("".join(self.current))
            self.current = None


def assignments(source: str, names: set[str]) -> dict:
    """Accept literal assignments and an empty-registry initializer only."""
    try:
        reader = RegistryReader(source)
        result = {}
        while reader.peek():
            if reader.accept(";"):
                continue
            reader.take("window")
            reader.take(".")
            name = reader.take()
            if name not in names:
                reject()
            key = None
            if reader.accept("["):
                key = reader.value()
                reader.take("]")
                if not isinstance(key, str) or not isinstance(result.get(name), dict):
                    reject()
            reader.take("=")
            if reader.peek() == "window":
                for token in ("window", ".", name, "||", "{", "}"):
                    reader.take(token)
                if key is not None:
                    reject()
                result.setdefault(name, {})
            else:
                value = reader.value()
                if key is None:
                    if name in result:
                        reject()
                    result[name] = value
                else:
                    if key in result[name]:
                        reject()
                    result[name][key] = value
            reader.accept(";")
        return result
    except (ValueError, IndexError, RecursionError, UnicodeError):
        reject()


def manifest(html: str) -> list[dict] | None:
    scripts = ProjectScripts()
    scripts.feed(html)
    sources = [s for s in scripts.inline if re.search(r"\bwindow\.PROTO_PROJECT\s*=", s)]
    if not sources:
        return None
    if len(sources) != 1:
        reject()
    data = assignments(sources[0], {"PROTO_PROJECT", "PROTO_TREES", "PROTO_ANNOTATIONS"})
    project = data.get("PROTO_PROJECT")
    if (
        not isinstance(project, dict)
        or project.get("format") != "html-prototype-project"
        or project.get("version") != 1
        or not isinstance(project.get("apps"), list)
        or not 1 <= len(project["apps"]) <= 100
    ):
        reject()
    seen = set()
    for app in project["apps"]:
        if not isinstance(app, dict):
            reject()
        key = app.get("key")
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", key)
            or key in seen
            or not isinstance(app.get("name"), str)
            or not app["name"].strip()
            or app.get("pages") != f"pages/{key}/"
            or app.get("tree") != f"trees/{key}.js"
            or scripts.sources.count(app["tree"]) != 1
        ):
            reject()
        seen.add(key)
    return project["apps"]


def tree_pages(source: str, app: dict, root: str) -> list[dict]:
    # This exporter hides one configured top-level group with this exact filter.
    # Interpret that fixed predicate as data; never evaluate an arrow function.
    filtered = re.search(
        r"\.filter\(group\s*=>\s*group\.group\s*!==\s*(['\"])需求资料\1\);"
        r"(?:\s|//[^\n]*|/\*[\s\S]*?\*/)*\Z",
        source,
    )
    if filtered:
        source = source[: filtered.start()] + ";"
    tree = assignments(source, {"PROTO_TREE"}).get("PROTO_TREE")
    if not isinstance(tree, list):
        reject()
    if filtered:
        tree = [
            node for node in tree if not isinstance(node, dict) or node.get("group") != "需求资料"
        ]
    pages, seen = [], set()
    count = 0

    def visit(nodes, parents, depth=0):
        nonlocal count
        if not isinstance(nodes, list) or depth > 32:
            reject()
        for node in nodes:
            count += 1
            if count > 5000 or not isinstance(node, dict):
                reject()
            filename = node.get("file")
            name = (
                node.get("title", node.get("name"))
                if filename
                else node.get("group", node.get("title"))
            )
            if not isinstance(name, str) or not name.strip():
                reject()
            path = [*parents, name]
            if filename:
                if not isinstance(filename, str) or not PAGE_PATH.fullmatch(filename):
                    reject()
                filename = filename.removeprefix("pages/").removeprefix(app["key"] + "/")
                file = app["key"] + "/" + filename
                if file in seen:
                    reject()
                seen.add(file)
                pages.append(
                    {"file": file, "path": " / ".join(path), "url": root + "pages/" + file}
                )
            else:
                visit(node.get("pages", []), path, depth + 1)
            visit(node.get("groups", node.get("children", [])), path, depth + 1)

    visit(tree, [app["name"]])
    return pages


def annotation_blocks(source: str, file: str) -> dict[str, list[str]]:
    registry = assignments(source, {"PROTO_ANNOTATIONS"}).get("PROTO_ANNOTATIONS")
    key = "pages/" + file
    if not isinstance(registry, dict) or set(registry) != {key}:
        reject()
    data = registry[key]
    if not isinstance(data, dict):
        reject()
    blocks = {}
    sections = data.get("sections", [])
    if not isinstance(sections, list):
        reject()
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("t"), str):
            reject()
        detail = section.get("d", [])
        if isinstance(detail, str):
            detail = [detail]
        if not isinstance(detail, list) or any(not isinstance(item, str) for item in detail):
            reject()
        blocks.setdefault(section["t"], []).extend(detail)
    note = data.get("note", "")
    if not isinstance(note, str):
        reject()
    if note and not sections:
        blocks.setdefault("页面说明", []).append(note)
    annos = data.get("annos", [])
    if not isinstance(annos, list):
        reject()
    for i, anno in enumerate(annos, 1):
        if not isinstance(anno, dict) or not isinstance(anno.get("text", ""), str):
            reject()
        blocks.setdefault(f"标记批注 {i}", []).append(anno.get("text", ""))
    return blocks
