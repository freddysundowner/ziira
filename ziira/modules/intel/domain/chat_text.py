"""Cutting an answer into the pieces the chat releases one at a time: pure text, no database, no HTTP."""

import re

_BREAK = re.compile(r"((?<=[.!?])\s+|\n+)")


def split_chunks(text: str) -> list[str]:
    """`text` as sentences (and list lines), each with the white space that follows it, so that joining the chunks gives
    the text back exactly. A decimal such as 1,250.00 is never cut (the full stop has no space after it)."""
    parts = _BREAK.split(text)
    chunks = ["".join(parts[i:i + 2]) for i in range(0, len(parts), 2)]
    return [c for c in chunks if c]
