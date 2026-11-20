"""Read a bounded declarative prototype registry; never execute JavaScript."""

import re

from app.core.errors import AppError

TOKEN = re.compile(
    r"\s+|//[^\n]*|/\*[\s\S]*?\*/|\"(?:\\[\s\S]|[^\"\\])*\"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`|[A-Za-z_$][\w$]*|-?\d+(?:\.\d+)?|\|\||[{}\[\]().,:;=+]"
)
REGISTRIES = {"PROTOTYPE_PAGES", "PROTOTYPE_ANNOTATIONS"}


def reject():
    raise AppError(422, "prototype_link_unsupported")


def string(raw):
    if raw[0] == "`" and "${" in raw:
        reject()
    value, i = [], 1
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    while i < len(raw) - 1:
        char = raw[i]
        if char != "\\":
            value.append(char)
            i += 1
            continue
        i += 1
        char = raw[i]
        if char in {"u", "x"}:
            count = 4 if char == "u" else 2
            try:
                value.append(chr(int(raw[i + 1 : i + 1 + count], 16)))
            except ValueError:
                reject()
            i += count + 1
        elif char in "\r\n":
            i += 2 if char == "\r" and raw[i + 1] == "\n" else 1
        else:
            value.append(escapes.get(char, char))
            i += 1
    return "".join(value).encode("utf-16", "surrogatepass").decode("utf-16")


class RegistryReader:
    def __init__(self, source):
        self.tokens, self.pos, self.constants, self.registries = [], 0, {}, {}
        offset = 0
        while offset < len(source):
            match = TOKEN.match(source, offset)
            if not match:
                reject()
            token = match.group()
            offset = match.end()
            if token.isspace() or token.startswith(("//", "/*")):
                continue
            self.tokens.append(token)
            if len(self.tokens) > 200_000:
                reject()

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ""

    def take(self, expected=None):
        value = self.peek()
        if not value or expected is not None and value != expected:
            reject()
        self.pos += 1
        return value

    def accept(self, value):
        if self.peek() == value:
            self.pos += 1
            return True
        return False

    def value(self, depth=0):
        if depth > 64:
            reject()
        token = self.take()
        if token == "[":
            result = []
            while not self.accept("]"):
                result.append(self.value(depth + 1))
                if len(result) > 10_000:
                    reject()
                if self.accept("]"):
                    break
                self.take(",")
        elif token == "{":
            result = {}
            while not self.accept("}"):
                key = self.take()
                key = string(key) if key[0] in "\"'`" else key
                if not re.fullmatch(r"[\w$*.-]+", key) or key in result:
                    reject()
                self.take(":")
                result[key] = self.value(depth + 1)
                if self.accept("}"):
                    break
                self.take(",")
        elif token[0] in "\"'`":
            result = string(token)
        elif token in {"true", "false", "null"}:
            result = {"true": True, "false": False, "null": None}[token]
        elif re.fullmatch(r"-?\d+(?:\.\d+)?", token):
            result = float(token) if "." in token else int(token)
        elif token in self.constants:
            result = self.constants[token]
        else:
            reject()
        while self.accept("+"):
            other = self.value(depth + 1)
            if not isinstance(result, str) or not isinstance(other, str):
                reject()
            result += other
        return result

    def registry(self):
        self.take("window")
        self.take(".")
        name = self.take()
        if name not in REGISTRIES:
            reject()
        return name

    def loop(self):
        entries = self.value()
        self.take(".")
        self.take("forEach")
        self.take("(")
        self.take("function")
        self.take("(")
        param = self.take()
        self.take(")")
        self.take("{")
        body = []
        while self.peek() != "}":
            body.append(self.take())
        self.take("}")
        self.take(")")
        canonical = "".join(body)
        target = "window.PROTOTYPE_ANNOTATIONS[file]"
        pair = f"varfile={param}[0],sections={param}[1];{target}="
        append = f"{pair}({target}||[]).concat(sections);"
        prepend = f"{pair}sections.concat({target}||[]);"
        alias = (
            f"window.PROTOTYPE_ANNOTATIONS[{param}[0]]="
            f"window.PROTOTYPE_ANNOTATIONS[{param}[1]]||[];"
        )
        if canonical not in {append, prepend, alias} or not isinstance(entries, list):
            reject()
        notes = self.registries.get("PROTOTYPE_ANNOTATIONS")
        if not isinstance(notes, dict):
            reject()
        for entry in entries:
            if not isinstance(entry, list) or len(entry) != 2 or not isinstance(entry[0], str):
                reject()
            file, value = entry
            if canonical in {append, prepend}:
                previous = notes.get(file, [])
                if not isinstance(value, list) or not isinstance(previous, list):
                    reject()
                notes[file] = value + previous if canonical == prepend else previous + value
            else:
                if not isinstance(value, str):
                    reject()
                notes[file] = list(notes.get(value, []))

    def read(self):
        while self.peek():
            if self.accept(";"):
                continue
            if self.peek() in {"const", "let", "var"}:
                self.take()
                name = self.take()
                self.take("=")
                self.constants[name] = self.value()
            elif self.peek() == "[":
                self.loop()
            else:
                name = self.registry()
                if self.accept("["):
                    file = self.value()
                    self.take("]")
                    self.take("=")
                    if not isinstance(file, str) or not isinstance(self.registries.get(name), dict):
                        reject()
                    self.registries[name][file] = self.value()
                elif self.accept("."):
                    self.take("push")
                    self.take("(")
                    if name != "PROTOTYPE_PAGES" or not isinstance(self.registries.get(name), list):
                        reject()
                    while not self.accept(")"):
                        self.registries[name].append(self.value())
                        if self.accept(")"):
                            break
                        self.take(",")
                else:
                    self.take("=")
                    self.registries[name] = self.value()
            self.accept(";")
        return self.registries


def read_registry(source):
    try:
        return RegistryReader(source).read()
    except (ValueError, IndexError, RecursionError, UnicodeError):
        reject()
