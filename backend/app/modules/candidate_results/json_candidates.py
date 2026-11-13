"""Lossless JSON member parsing for displaying untrusted model candidates."""

import json


class Pairs(list):
    """Keep every object member, including conflicting duplicates, for human review."""


def original_json(value):
    if isinstance(value, Pairs):
        return (
            "{\n"
            + ",\n".join(
                json.dumps(k, ensure_ascii=True) + ": " + original_json(v) for k, v in value
            )
            + "\n}"
        )
    if isinstance(value, list):
        return "[" + ",\n".join(original_json(v) for v in value) + "]"
    text = json.dumps(value, ensure_ascii=False)
    try:
        text.encode("utf-8")
    except UnicodeError:
        text = json.dumps(value, ensure_ascii=True)
    return text


def display(value):
    """Render invalid Unicode/control content visibly without mutating the private original."""
    return value.encode("utf-8", errors="backslashreplace").decode().replace("\0", "\\u0000")


def duplicate_fields(value, path=""):
    result = []
    if isinstance(value, Pairs):
        grouped = {}
        for key, item in value:
            grouped.setdefault(key, []).append(item)
        for key, items in grouped.items():
            name = display(key)
            location = (path + "." if path else "") + name
            if len(items) > 1:
                result.append({"path": location, "values": [original_json(v) for v in items]})
            for item in items:
                result.extend(duplicate_fields(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(duplicate_fields(item, f"{path}[{index}]"))
    return result
