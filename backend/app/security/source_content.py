"""Keep private-key headers blocked while allowing literal PEM-header cleanup code."""

import re

_PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")
_HEADER_REMOVAL = re.compile(
    rf"""\.replace(?:All)?\(\s*(["']){_PRIVATE_KEY_HEADER.pattern}\1\s*,\s*(["'])\2\s*\)"""
)


def contains_private_key(text: str) -> bool:
    # A literal header-removal call does not embed a private key.
    return _PRIVATE_KEY_HEADER.search(_HEADER_REMOVAL.sub("", text)) is not None
