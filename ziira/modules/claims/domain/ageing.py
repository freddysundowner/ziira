"""Ageing of what payers owe. Pure Python."""

from datetime import date
from decimal import Decimal

BUCKETS = ("not_due", "d1_30", "d31_60", "d61_90", "d90_plus")


def bucket(due: date, as_of: date) -> str:
    """Where an unpaid invoice falls by the days past its due date."""
    late = (as_of - due).days
    if late <= 0:
        return "not_due"
    if late <= 30:
        return "d1_30"
    if late <= 60:
        return "d31_60"
    if late <= 90:
        return "d61_90"
    return "d90_plus"


def empty() -> dict[str, Decimal]:
    return {b: Decimal(0) for b in BUCKETS}
