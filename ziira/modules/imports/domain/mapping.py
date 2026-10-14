"""Suggesting which column of the file holds which field, by comparing names."""

import re
from difflib import SequenceMatcher

MIN_SIMILARITY = 0.78


def normalise(name: str) -> str:
    """A header reduced to lower-case letters and digits, so 'Unit Price (KES)' and 'unit_price' compare alike."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", name.lower()))


def _similarity(header: str, wanted: str) -> float:
    """How alike two normalised names are (0 to 1); a header containing the whole name (unitprice, price) is close."""
    if len(wanted) >= 4 and wanted in header:
        return max(0.8, SequenceMatcher(None, header, wanted).ratio())
    return SequenceMatcher(None, header, wanted).ratio()


def suggest_mapping(headers: list[str], fields: list[tuple[str, tuple[str, ...]]]) -> dict[str, str | None]:
    """For each field (name, aliases) the header that best matches it, or None. A header is used for one field only;
    exact matches (of the name or an alias) win over similar ones."""
    heads = {h: normalise(h) for h in headers}
    result: dict[str, str | None] = {name: None for name, _ in fields}
    taken: set[str] = set()
    for name, aliases in fields:                                   # exact first
        wanted = {normalise(name), *(normalise(a) for a in aliases)}
        for header, key in heads.items():
            if header not in taken and key in wanted:
                result[name] = header
                taken.add(header)
                break
    for name, aliases in fields:                                   # then the closest above the threshold
        if result[name] is not None:
            continue
        best, best_score = None, MIN_SIMILARITY
        for header, key in heads.items():
            if header in taken or not key:
                continue
            score = max(_similarity(key, normalise(w)) for w in (name, *aliases))
            if score >= best_score:
                best, best_score = header, score
        if best is not None:
            result[name] = best
            taken.add(best)
    return result
