"""Recurring engagements: when the next piece of work is due. Pure rules."""

import calendar
from datetime import date

FREQUENCIES = ("monthly", "quarterly", "annual")


def _due(year: int, month: int, day: int) -> date:
    """The due day in a month, clamped to the month's last day (day 31 in February is the 28th or 29th)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def due_dates(frequency: str, due_day: int, due_month: int | None, starts_on: date, ends_on: date | None,
              window_from: date, window_to: date) -> list[tuple[str, date]]:
    """(period label, due date) for every due date from `window_from` to `window_to` that is also within
    `starts_on`..`ends_on`. Monthly: every month on `due_day` ('2026-10'). Quarterly: every third month starting
    with `due_month` ('2026-Q4' by the due date's quarter). Annual: `due_month` each year ('2026')."""
    if frequency not in FREQUENCIES:
        raise ValueError(f"Frequency is one of: {', '.join(FREQUENCIES)}")
    first = max(window_from, starts_on)
    last = min(window_to, ends_on) if ends_on else window_to
    found: list[tuple[str, date]] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        wanted = frequency == "monthly" or (
            frequency == "quarterly" and (month - (due_month or 1)) % 3 == 0) or (
            frequency == "annual" and month == (due_month or 1))
        if wanted:
            due = _due(year, month, due_day)
            if first <= due <= last:
                label = (f"{year}-{month:02d}" if frequency == "monthly"
                         else f"{year}-Q{(month - 1) // 3 + 1}" if frequency == "quarterly" else str(year))
                found.append((label, due))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return found
