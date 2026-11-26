"""Strict JSON decoding for model output and imported data."""

import json
import math

from app.core.errors import AppError


def json_object(value: str, error_code: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("invalid_number")

    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
        pending = [result]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                if "\x00" in item:
                    raise ValueError("null_character")
                item.encode("utf-8")
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("invalid_number")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise AppError(422, error_code) from None
