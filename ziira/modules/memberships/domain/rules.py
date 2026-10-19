"""Small validation rules for memberships, plans, packages and recurring invoice lines. No database."""

import re
from decimal import Decimal
from uuid import UUID

from ziira.sdk import ValidationFailed

CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")


def clean_code(code: str) -> str:
    """A plan or package code: upper case letters, digits and . _ - only."""
    cleaned = code.strip().upper()
    if not CODE.match(cleaned):
        raise ValidationFailed("A code has up to 30 letters, digits, dots, dashes or underscores")
    return cleaned


def clean_name(name: str, what: str = "Name") -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValidationFailed(f"{what} is required")
    return cleaned[:200]


def clean_services(services: list[str] | None) -> list[str]:
    """The services a plan or package pays for: trimmed, no blanks, no repeats, order kept. Empty means all."""
    seen: list[str] = []
    for item in services or []:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned[:100])
    if len(seen) > 200:
        raise ValidationFailed("Too many services listed")
    return seen


def line_total(quantity: Decimal, unit_price: Decimal, discount: Decimal = Decimal(0)) -> Decimal:
    """What a recurring invoice line comes to (prices include tax, as everywhere in sales)."""
    return (quantity * unit_price - discount).quantize(Decimal("0.01"))


TIME = re.compile(r"^([01]?\d|2[0-4]):([0-5]\d)$")


def clean_access_rules(rules: object) -> list[dict[str, object]]:
    """The time windows a plan allows entry in: [{"days": [0..6, Monday is 0], "from": "HH:MM", "to": "HH:MM"}]. Empty
    means any time. Times are on the company's clock."""
    if rules is None:
        return []
    if not isinstance(rules, list) or len(rules) > 14:
        raise ValidationFailed("Time windows are a list of at most 14 entries")
    cleaned: list[dict[str, object]] = []
    for item in rules:
        if not isinstance(item, dict):
            raise ValidationFailed("A time window has days, a start and an end")
        start, end = str(item.get("from", "00:00")), str(item.get("to", "24:00"))
        if not TIME.match(start) or not TIME.match(end) or start == end:
            raise ValidationFailed("A time window needs different start and end times like 06:00 and 10:00")
        days = item.get("days") or []
        if not isinstance(days, list) or any(not isinstance(d, int) or d < 0 or d > 6 for d in days):
            raise ValidationFailed("Days of a time window are numbers 0 (Monday) to 6 (Sunday)")
        cleaned.append({"days": sorted(set(days)), "from": start, "to": end})
    return cleaned


def clean_branch_ids(ids: object) -> list[str]:
    """The branches a plan may enter (empty: all). Checked against the company by the caller."""
    if ids is None:
        return []
    if not isinstance(ids, list) or len(ids) > 200:
        raise ValidationFailed("Branches are a list of ids")
    found: list[str] = []
    for item in ids:
        try:
            text = str(UUID(str(item).strip()))
        except ValueError:
            raise ValidationFailed("A branch id is not valid") from None
        if text not in found:
            found.append(text)
    return found
