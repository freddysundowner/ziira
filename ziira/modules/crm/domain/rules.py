"""Business rules of customers and leads. Pure Python: no database, no HTTP."""

import re
from decimal import Decimal

from ziira.sdk import ValidationFailed

TAX_ID = re.compile(r"^[A-Z0-9][A-Z0-9/\-. ]{2,29}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE = re.compile(r"^[A-Z0-9][A-Z0-9\-_.]{0,19}$")
MAX_CREDIT = Decimal("1000000000")
CUSTOMER_STATUSES = ("active", "on_hold", "inactive")
LEAD_STATUSES = ("new", "contacted", "qualified", "converted", "lost")
# where a lead may go next; converted and lost are final (a lost lead can be reopened as contacted)
LEAD_MOVES: dict[str, tuple[str, ...]] = {
    "new": ("contacted", "qualified", "lost"), "contacted": ("qualified", "lost"), "qualified": ("lost",),
    "lost": ("contacted",), "converted": (),
}
ACTIVITY_KINDS = ("call", "visit", "message", "meeting", "task")


def clean_name(name: str, label: str = "Name") -> str:
    value = " ".join(name.split())
    if not value or len(value) > 200:
        raise ValidationFailed(f"{label} is required (up to 200 characters)")
    return value


def normalise_code(code: str) -> str:
    value = code.strip().upper()
    if not CODE.match(value):
        raise ValidationFailed("A customer code is 1-20 letters, digits, '-', '_' or '.'")
    return value


def clean_email(email: str | None) -> str | None:
    if email is None or not email.strip():
        return None
    value = email.strip().lower()
    if len(value) > 200 or not EMAIL.match(value):
        raise ValidationFailed("That email address does not look right")
    return value


def clean_tax_id(number: str | None) -> str | None:
    """A tax number as the tax authority writes it: 3 to 30 letters, digits, '-', '/' or '.'; None when empty."""
    if number is None or not number.strip():
        return None
    value = " ".join(number.strip().upper().split())
    if not TAX_ID.match(value):
        raise ValidationFailed("A tax number is 3 to 30 letters, digits, '-', '/' or '.'")
    return value


def clean_group(group: str | None) -> str | None:
    if group is None or not group.strip():
        return None
    value = " ".join(group.split())
    if len(value) > 60:
        raise ValidationFailed("A customer group name is up to 60 characters")
    return value


def check_credit(limit: Decimal, terms_days: int) -> None:
    if limit < 0 or limit > MAX_CREDIT or limit != limit.quantize(Decimal("0.01")):
        raise ValidationFailed("A credit limit is an amount of zero or more with at most 2 decimal places")
    if terms_days < 0 or terms_days > 365:
        raise ValidationFailed("Payment terms are between 0 and 365 days")


def credit_change_needs_approval(current_limit: Decimal, new_limit: Decimal) -> bool:
    """Only an increase of the limit is approved by someone else; lowering it, or changing the terms, is not."""
    return new_limit > current_limit


def check_lead_move(current: str, new: str) -> None:
    if new not in LEAD_STATUSES:
        raise ValidationFailed(f"Status must be one of: {', '.join(LEAD_STATUSES)}")
    if new not in LEAD_MOVES.get(current, ()):
        raise ValidationFailed(f"A lead that is {current} cannot become {new}")
