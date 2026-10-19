"""Repeating appointments: the dates of each occurrence. Pure rules."""

import calendar
from datetime import date, timedelta

from ziira.sdk import ValidationFailed

FREQUENCIES = ("weekly", "biweekly", "monthly")
MAX_OCCURRENCES = 52


def _add_month(day: date, months: int, anchor_day: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def occurrence_dates(first: date, frequency: str, *, count: int | None = None, until: date | None = None) -> list[date]:
    """The days of a series: `first` and then every week, two weeks or month, for `count` times or until the date
    (inclusive). Monthly keeps the day of the month (the last day when the month is shorter). At most 52."""
    if frequency not in FREQUENCIES:
        raise ValidationFailed(f"Repeat must be one of: {', '.join(FREQUENCIES)}")
    if count is None and until is None:
        raise ValidationFailed("Say how many times to repeat, or until when")
    if count is not None and count < 1:
        raise ValidationFailed("Repeat at least once")
    days: list[date] = []
    n = 0
    while True:
        if frequency == "monthly":
            day = _add_month(first, n, first.day)
        else:
            day = first + timedelta(days=7 * (2 if frequency == "biweekly" else 1) * n)
        if (count is not None and n >= count) or (until is not None and day > until):
            break
        days.append(day)
        n += 1
        if n > MAX_OCCURRENCES:
            raise ValidationFailed(f"A series has at most {MAX_OCCURRENCES} appointments")
    return days
