"""Plain checks on what people type in Bookings. Pure rules."""

import re
from datetime import time

from ziira.modules.bookings.domain.availability import Hours
from ziira.sdk import ValidationFailed

RESOURCE_KINDS = ("staff", "room", "chair", "equipment")
OFFER_KINDS = ("appointment", "class")
RESOURCE_MODES = ("any", "all")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_name(name: str, what: str = "Name") -> str:
    clean = " ".join((name or "").split())
    if not clean or len(clean) > 200:
        raise ValidationFailed(f"{what} is required (up to 200 characters)")
    return clean


def check_colour(colour: str | None) -> str | None:
    if colour in (None, ""):
        return None
    if not COLOUR.match(colour):
        raise ValidationFailed("A colour looks like #1a73e8")
    return colour.lower()


def check_email(email: str | None) -> str | None:
    clean = (email or "").strip().lower()
    if not clean:
        return None
    if len(clean) > 200 or not EMAIL.match(clean):
        raise ValidationFailed("That email address does not look right")
    return clean


def check_hours(rows: list[Hours]) -> list[Hours]:
    """Working windows: end after start, none overlapping on a day."""
    for h in rows:
        if not 0 <= h.weekday <= 6:
            raise ValidationFailed("A weekday is 0 (Monday) to 6 (Sunday)")
        if h.end <= h.start:
            raise ValidationFailed("Closing time must be after opening time")
    by_day: dict[int, list[Hours]] = {}
    for h in rows:
        by_day.setdefault(h.weekday, []).append(h)
    for day_rows in by_day.values():
        ordered = sorted(day_rows, key=lambda x: x.start)
        for a, b in zip(ordered, ordered[1:], strict=False):
            if b.start < a.end:
                raise ValidationFailed("Two working periods on one day overlap")
    return sorted(rows, key=lambda x: (x.weekday, x.start))


def parse_time(value: str) -> time:
    try:
        hour, minute = value.split(":")[:2]
        return time(int(hour), int(minute))
    except (ValueError, TypeError):
        raise ValidationFailed("A time looks like 09:30") from None
