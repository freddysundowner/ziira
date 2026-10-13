"""Rules for stock locations. Pure Python: no database, no HTTP."""

import re

from ziira.sdk import ValidationFailed

LOCATION_KINDS = ("store", "warehouse", "transit", "virtual")
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-_.]{0,19}$")


def normalise_location_code(code: str) -> str:
    """Upper-case a location code: 1-20 letters, digits, - _ or ., starting with a letter or digit."""
    value = code.strip().upper()
    if not CODE_PATTERN.match(value):
        raise ValidationFailed(
            "Location code must be 1-20 characters: letters, digits, '-', '_' or '.', starting with a letter or digit")
    return value


def check_location(kind: str, has_branch: bool) -> None:
    """Stores and warehouses belong to a branch; in-transit and virtual locations do not."""
    if kind not in LOCATION_KINDS:
        raise ValidationFailed(f"Location kind must be one of: {', '.join(LOCATION_KINDS)}")
    if kind in ("store", "warehouse") and not has_branch:
        raise ValidationFailed(f"A {kind} belongs to a branch")
    if kind in ("transit", "virtual") and has_branch:
        raise ValidationFailed(f"A {kind} location belongs to the company, not to a branch")
