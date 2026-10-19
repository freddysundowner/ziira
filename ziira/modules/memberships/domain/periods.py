"""Billing periods: pure date rules for memberships and recurring invoices. No database, no clock."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

MONTHS_IN = {"month": 1, "quarter": 3, "year": 12}
INTERVALS = ("week", "month", "quarter", "year")
MAX_PERIODS_LOOKED_AT = 2000          # a safety stop for a schedule left untouched for decades


def _year_month(month_index: int) -> tuple[int, int]:
    """(year, month 1-12) for a count of months since year 0 (month_index = year * 12 + month - 1)."""
    return month_index // 12, month_index % 12 + 1


def shift(start: date, interval: str, count: int = 1, anchor_day: int | None = None) -> date:
    """The date `count` intervals after `start`. A monthly interval keeps the anchor day (default: the day of `start`),
    stopping at the last day of a shorter month (31 January + 1 month = 28 or 29 February). Past the last date the
    calendar can hold the result is that last date, so a loop over periods always ends."""
    try:
        if interval == "week":
            return start + timedelta(days=7 * count)
        year, month = _year_month(start.year * 12 + start.month - 1 + MONTHS_IN[interval] * count)
        return date(year, month, min(anchor_day or start.day, calendar.monthrange(year, month)[1]))
    except (OverflowError, ValueError):
        return date.max


def nth_start(first: date, interval: str, count: int, anchor_day: int | None, n: int) -> date:
    """Start of the n-th period (0 is `first`), always counted from `first` so a clamped month does not drift."""
    if interval == "week":
        return shift(first, "week", count * n)
    return shift(first, interval, count * n, anchor_day or first.day)


@dataclass(frozen=True)
class Period:
    index: int
    start: date
    end: date               # the first day of the next period


def period_at(first: date, interval: str, count: int, anchor_day: int | None, n: int) -> Period:
    return Period(n, nth_start(first, interval, count, anchor_day, n),
                  nth_start(first, interval, count, anchor_day, n + 1))


@dataclass(frozen=True)
class DuePeriods:
    issue: list[Period]
    skipped: list[Period]           # older periods dropped because more than `max_catch_up` were missed


def due_periods(first: date, interval: str, count: int, anchor_day: int | None, *, next_index: int, today: date,
                end_date: date | None = None, max_runs: int | None = None, max_catch_up: int = 3) -> DuePeriods:
    """The periods due on `today` (start on or before it), from `next_index` on, within the end date and the run limit.
    When more than `max_catch_up` are due the oldest are returned as `skipped` (the caller flags them)."""
    found: list[Period] = []
    n = next_index
    while len(found) < MAX_PERIODS_LOOKED_AT:
        if max_runs is not None and n >= max_runs:
            break
        period = period_at(first, interval, count, anchor_day, n)
        if period.start > today or (end_date is not None and period.start > end_date):
            break
        found.append(period)
        n += 1
    if len(found) <= max_catch_up:
        return DuePeriods(found, [])
    return DuePeriods(found[-max_catch_up:], found[:-max_catch_up])


def schedule_finished(first: date, interval: str, count: int, anchor_day: int | None, *, next_index: int,
                      end_date: date | None, max_runs: int | None) -> bool:
    """True when no further period will ever be due."""
    if max_runs is not None and next_index >= max_runs:
        return True
    return end_date is not None and nth_start(first, interval, count, anchor_day, next_index) > end_date


# --------------------------------------------------------------------------- membership periods
def calendar_period_start(day: date, interval: str) -> date:
    """The first day of the calendar month, quarter or year that contains `day`."""
    if interval == "month":
        return day.replace(day=1)
    if interval == "quarter":
        return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    return date(day.year, 1, 1)


@dataclass(frozen=True)
class FirstPeriod:
    start: date
    end: date               # the first day of the next period (the first renewal)
    fraction: Decimal       # the part of a full period the member pays and gets (1 when not prorated)


def first_period(start: date, interval: str, *, prorate: bool) -> FirstPeriod:
    """Where a membership starting on `start` has its first period. Anniversary billing (default): a full period from
    the start. Prorated: the part of the calendar month, quarter or year that is left, then calendar periods."""
    if prorate:
        whole_start = calendar_period_start(start, interval)
        if whole_start != start:
            whole_end = shift(whole_start, interval)
            days_left = Decimal((whole_end - start).days)
            return FirstPeriod(start, whole_end, days_left / Decimal((whole_end - whole_start).days))
    return FirstPeriod(start, shift(start, interval), Decimal(1))


def prorated_amount(amount: Decimal, fraction: Decimal) -> Decimal:
    """`amount` times the fraction of the period, to 2 decimals, half up."""
    return (amount * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def prorated_credits(credits: Decimal, fraction: Decimal) -> Decimal:
    """Credits for a part period: to the nearest whole credit, half up (never more than a full period gives)."""
    return min((credits * fraction).quantize(Decimal(1), rounding=ROUND_HALF_UP), credits)
