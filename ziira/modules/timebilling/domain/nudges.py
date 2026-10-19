"""Missed-time reminders: which day to look at and who has not logged enough. Pure rules."""

from datetime import date, timedelta


def previous_working_day(today: date, work_days: list[int] | tuple[int, ...]) -> date | None:
    """The most recent working day before `today` (ISO weekdays, Monday = 1), or None if no day is a working day."""
    if not work_days:
        return None
    day = today - timedelta(days=1)
    for _ in range(7):
        if day.isoweekday() in work_days:
            return day
        day -= timedelta(days=1)
    return None


def is_last_working_day(day: date, work_days: list[int] | tuple[int, ...]) -> bool:
    """True when `day` is the last working day of its week."""
    return day.isoweekday() in work_days and not any(
        (day + timedelta(days=n)).isocalendar()[:2] == day.isocalendar()[:2]
        and (day + timedelta(days=n)).isoweekday() in work_days for n in range(1, 7))


def short_of(logged: int, wanted: int) -> bool:
    """True when a person logged less than the minimum a working day should have (0 means reminders are off)."""
    return wanted > 0 and logged < wanted
