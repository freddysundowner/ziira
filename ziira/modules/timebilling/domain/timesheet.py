"""Time arithmetic: rounding, weeks, days. Pure rules."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

MINUTES_PER_DAY = 1440
STEPS = (1, 5, 6, 10, 15, 30, 60)
ROUND_MODES = ("up", "nearest", "down")


def round_to_step(minutes: int, step: int, mode: str = "nearest") -> int:
    """Round a number of minutes to a multiple of `step` ("up", "down" or "nearest": halves go up). A step of 0 or 1
    changes nothing. Never rounds a positive amount down to zero when going `up` or `nearest` (a minute of work is at
    least one step)."""
    if step <= 1 or minutes <= 0:
        return max(minutes, 0)
    low = minutes // step * step
    if mode == "down":
        return low
    if mode == "up":
        return low if low == minutes else low + step
    rounded = low + step if (minutes - low) * 2 >= step else low
    return rounded if rounded > 0 else step


def seconds_to_minutes(seconds: int, step: int, mode: str = "nearest") -> int:
    """A timer's running time in whole minutes: seconds are rounded to the nearest minute first (30 seconds counts as a
    minute), then to the rounding step. A timer that ran at all is at least one minute."""
    if seconds <= 0:
        return 0
    minutes = max(1, int((Decimal(seconds) / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
    return round_to_step(minutes, step, mode)


def hours(minutes: int) -> Decimal:
    """Minutes as hours to two places, for display ("1.50")."""
    return (Decimal(minutes) / 60).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def week_start(day: date, starts_on: int = 1) -> date:
    """The first day of the week containing `day`; `starts_on` is 1 (Monday) to 7 (Sunday)."""
    if not 1 <= starts_on <= 7:
        raise ValueError("A week starts on a day from 1 (Monday) to 7 (Sunday)")
    return day - timedelta(days=(day.isoweekday() - starts_on) % 7)


def week_days(start: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(7)]


def utilisation(billable_minutes: int, capacity_minutes: int) -> Decimal:
    """Billable time as a percentage of capacity (0 when there is no capacity)."""
    if capacity_minutes <= 0:
        return Decimal(0)
    return (Decimal(billable_minutes) * 100 / capacity_minutes).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
