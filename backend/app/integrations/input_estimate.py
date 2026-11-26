"""Estimate text input size without including attachments or protocol overhead."""

import re

_CJK = re.compile(
    r"[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7ff\uf900-\ufaff"
    r"\U00020000-\U0002fa1f\U00030000-\U000323af]+"
)


def estimate(instructions: str, messages: list[dict]) -> dict[str, int]:
    parts = [instructions]
    images = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                kind, value = part.get("type"), part.get("text")
                if kind == "input_image":
                    images += 1
                elif kind in ("input_text", "output_text") and isinstance(value, str):
                    parts.append(value)
    characters = byte_count = cjk_characters = cjk_bytes = 0
    for part in parts:
        characters += len(part)
        byte_count += len(part.encode("utf-8", errors="surrogatepass"))
        for cjk in _CJK.finditer(part):
            cjk_characters += cjk.end() - cjk.start()
            cjk_bytes += len(cjk[0].encode("utf-8"))
    return {
        "characters": characters,
        "bytes": byte_count,
        "approx_tokens": cjk_characters + (byte_count - cjk_bytes + 3) // 4,
        "images": images,
    }
