"""Embed fixed uploaded assets for an opaque-origin preview without network access."""

import base64
import posixpath
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from app.modules.documents.files import decode_text

CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s)]+))\s*\)", re.I)
CSS_IMPORT = re.compile(r"(@import\s+)([\"'])([^\"']+)\2", re.I)
MEDIA = {
    "css": "text/css",
    "js": "text/javascript",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def local_path(base, reference):
    try:
        value = urlsplit(reference)
        if value.scheme or value.netloc or not value.path or value.path.startswith("/"):
            return None
        relative = unquote(value.path, errors="strict")
    except (ValueError, UnicodeError):
        return None
    if relative.startswith("/") or "\\" in relative or any(ord(c) < 32 for c in relative):
        return None
    result = posixpath.normpath(posixpath.join(posixpath.dirname(base), relative))
    return None if result == ".." or result.startswith("../") else result


class Preview(HTMLParser):
    def __init__(self, source, path, index, read):
        super().__init__(convert_charrefs=False)
        self.source, self.path, self.index, self.read = source, path, index, read
        self.lines = [0] + [m.end() for m in re.finditer("\n", source)]
        self.in_style = False
        self.replacements, self.cache, self.visiting = [], {}, set()

    def resource(self, base, reference, extensions):
        name = local_path(base, reference)
        if name is None or name not in self.index:
            return reference
        extension = self.index[name]["extension"]
        if extension not in extensions:
            return reference
        if name in self.visiting:
            return "data:text/css,"  # A cyclic CSS import cannot add more rules.
        if name not in self.cache:
            self.visiting.add(name)
            raw = self.read(self.index[name])
            if extension == "css":
                raw = self.css(decode_text(raw), name).encode("utf-8")
            elif extension == "js":
                raw = decode_text(raw).encode("utf-8")
            self.visiting.remove(name)
            self.cache[name] = (
                "data:" + MEDIA[extension] + ";base64," + base64.b64encode(raw).decode()
            )
        suffix = urlsplit(reference).fragment
        return self.cache[name] + ("#" + suffix if suffix else "")

    def css(self, text, base):
        def url(match):
            value = next(v for v in match.groups() if v is not None)
            rewritten = self.resource(base, value, {"css", "png", "jpg", "jpeg", "webp", "svg"})
            return match[0] if rewritten == value else 'url("' + rewritten + '")'

        text = CSS_URL.sub(url, text)
        return CSS_IMPORT.sub(
            lambda m: m[1] + m[2] + self.resource(base, m[3], {"css"}) + m[2], text
        )

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self.in_style = True
        original = self.get_starttag_text()
        values = dict(attrs)
        changed = {}
        if tag == "script" and values.get("src"):
            changed["src"] = self.resource(self.path, values["src"], {"js"})
        if tag == "link" and values.get("href"):
            extensions = (
                {"css"}
                if "stylesheet" in (values.get("rel") or "").lower().split()
                else {"png", "jpg", "jpeg", "webp", "svg"}
            )
            changed["href"] = self.resource(self.path, values["href"], extensions)
        if tag in {"img", "source", "input"} and values.get("src"):
            changed["src"] = self.resource(
                self.path, values["src"], {"png", "jpg", "jpeg", "webp", "svg"}
            )
        if values.get("style"):
            changed["style"] = self.css(values["style"], self.path)
        if not any(value != values[key] for key, value in changed.items()):
            return
        attrs = [
            (key, changed.get(key, value))
            for key, value in attrs
            if key not in {"integrity", "crossorigin"}
        ]
        rendered = (
            "<"
            + tag
            + "".join(
                " " + key + ('="' + escape(value, quote=True) + '"' if value is not None else "")
                for key, value in attrs
            )
            + ("/>" if original.endswith("/>") else ">")
        )
        line, column = self.getpos()
        start = self.lines[line - 1] + column
        self.replacements.append((start, start + len(original), rendered))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            rewritten = self.css(data, self.path)
            if rewritten != data:
                line, column = self.getpos()
                start = self.lines[line - 1] + column
                self.replacements.append((start, start + len(data), rewritten))


def render(source, path, index, read):
    preview = Preview(source, path, index, read)
    preview.feed(source)
    preview.close()
    for start, end, value in reversed(preview.replacements):
        source = source[:start] + value + source[end:]
    return source
