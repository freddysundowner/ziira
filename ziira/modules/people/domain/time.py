"""Working time: leave days, attendance hours and overtime. Pure Python: no database, no HTTP.

Which days of the week are the weekend is the business's own setting (`weekend_days`), so nothing here assumes one.
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ziira.sdk import ValidationFailed

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HUNDREDTH = Decimal("0.01")


def weekend_numbers(names: list[str] | tuple[str, ...]) -> frozenset[int]:
    """Weekday numbers (Monday is 0) of the named weekend days."""
    return frozenset(DAYS.index(n) for n in names if n in DAYS)


def working_days(start: date, end: date, weekend: frozenset[int]) -> int:
    """The days from start to end (both included) that are not weekend days."""
    if end < start:
        return 0
    return sum(1 for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() not in weekend)


def requested_days(start: date, end: date, days: Decimal | None, weekend: frozenset[int]) -> Decimal:
    """The days a leave request takes: those given (half days allowed), or the working days from start to end."""
    if end < start:
        raise ValidationFailed("The leave cannot end before it starts")
    if (end - start).days > 366:
        raise ValidationFailed("Leave is at most a year long")
    possible = Decimal(working_days(start, end, weekend))
    if possible == 0:
        raise ValidationFailed("Those dates are all weekend days: there is nothing to take")
    if days is None:
        return possible
    if days <= 0 or days > possible or (days * 2) % 1 != 0:
        raise ValidationFailed(f"Days must be in half days, more than 0 and at most {possible}")
    return days


def days_in_period(start: date, end: date, days: Decimal, period_start: date, period_end: date,
                   weekend: frozenset[int]) -> Decimal:
    """How many of a leave request's days fall inside a period (one that crosses a month is split by working days)."""
    total = working_days(start, end, weekend)
    if total == 0:
        return Decimal(0)
    inside = working_days(max(start, period_start), min(end, period_end), weekend)
    return (days * inside / total).quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def hours_between(clock_in: datetime, clock_out: datetime) -> Decimal:
    """Hours worked between two moments, to the hundredth. Raises if the end is before the start or it is over a day."""
    if clock_out < clock_in:
        raise ValidationFailed("Clock-out is before clock-in")
    hours = Decimal((clock_out - clock_in).total_seconds()) / Decimal(3600)
    if hours > 24:
        raise ValidationFailed("A shift is at most 24 hours")
    return hours.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def shift_hours(start: time, end: time) -> Decimal:
    """The length of a shift in hours; one that ends before it starts runs through midnight."""
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        minutes += 24 * 60
    return (Decimal(minutes) / Decimal(60)).quantize(HUNDREDTH)


def overtime_for(hours: Decimal, normal_hours: Decimal) -> Decimal:
    """Hours beyond a shift's normal length."""
    return max(hours - normal_hours, Decimal(0)).quantize(HUNDREDTH)
