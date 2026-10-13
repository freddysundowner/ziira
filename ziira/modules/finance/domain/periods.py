"""Accounting periods (monthly) and when an entry may be posted into one. Pure Python."""

import calendar
from datetime import date

from ziira.sdk import ValidationFailed

OPEN, SOFT_CLOSED, LOCKED = "open", "soft_closed", "locked"
STATUSES = (OPEN, SOFT_CLOSED, LOCKED)
POST, REDIRECT = "post", "redirect"


def month_bounds(day: date) -> tuple[date, date]:
    """First and last day of the month containing `day`."""
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def decide(status: str, *, automatic: bool, can_close: bool, policy: str) -> str:
    """Where an entry dated in a period with this status goes: 'post' (there) or 'redirect' (to the current period).

    - open: post.
    - soft-closed: only people who may close periods can post (manual entries); an automatic posting (a sale, a stock
      movement) follows the company's late-posting policy.
    - locked: nothing posts there. An automatic posting follows the policy; a manual one is refused.
    Raises ValidationFailed when the entry is refused.
    """
    if status == OPEN:
        return POST
    if status == SOFT_CLOSED and not automatic and can_close:
        return POST
    if automatic and policy == "redirect":
        return REDIRECT
    if status == LOCKED:
        raise ValidationFailed("That accounting period is locked: nothing can be posted into it")
    raise ValidationFailed("That accounting period is closed: only someone who can close periods may post into it"
                           if not automatic else "That accounting period is closed")


def check_status_change(current: str, new: str, *, can_close: bool) -> None:
    """Closing and reopening: open -> soft_closed -> locked, and soft_closed -> open again. Locked stays locked."""
    if new not in STATUSES:
        raise ValidationFailed(f"Status must be one of: {', '.join(STATUSES)}")
    if not can_close:
        raise ValidationFailed("Closing periods needs the 'period.close' permission")
    allowed = {OPEN: {SOFT_CLOSED}, SOFT_CLOSED: {OPEN, LOCKED}, LOCKED: set()}
    if new == current:
        raise ValidationFailed(f"The period is already {current.replace('_', ' ')}")
    if new not in allowed[current]:
        raise ValidationFailed("A locked period cannot be reopened" if current == LOCKED
                               else f"A period cannot go from {current.replace('_', ' ')} to {new.replace('_', ' ')}")
