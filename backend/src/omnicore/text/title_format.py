"""Deterministic title boundaries: no extra inference and no partial-word truncation."""

import re
import unicodedata

PREFIX = re.compile(
    r"^(?:(?:title|tytuł|temat)\s*:\s*|"
    r"(?:rozmowa (?:na temat|o)|pytanie (?:dotyczące|o)|"
    r"(?:a )?(?:conversation|discussion) (?:about|on)|question (?:about|regarding))\s*[:–—-]?\s+)",
    re.IGNORECASE,
)


def short_title(value: str, limit: int = 42) -> str | None:
    value = unicodedata.normalize("NFC", value[:2048])
    lines = [
        re.sub(r"^#{1,6}\s+", "", line.strip()).strip('`* "“„”«»') for line in value.splitlines()
    ]
    text = next((line for line in lines if line), "")
    for _ in range(3):
        text = PREFIX.sub("", text).strip(' "“„”«»:–—-')
    if not text or "<" in text or any(ord(char) < 32 for char in text):
        return None
    words = text.split()
    selected = []
    for word in words[:5]:
        candidate = " ".join([*selected, word])
        if len(candidate) > limit:
            break
        selected.append(word)
    return " ".join(selected).rstrip(" ,;:!?–—-").strip() or None
