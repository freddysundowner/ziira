"""The life of an appointment: which status may follow which. Pure rules."""

from datetime import datetime, timedelta

from ziira.sdk import ValidationFailed

REQUESTED, CONFIRMED, CHECKED_IN, IN_SERVICE, COMPLETED, CANCELLED, NO_SHOW = (
    "requested", "confirmed", "checked_in", "in_service", "completed", "cancelled", "no_show")

STATUSES = (REQUESTED, CONFIRMED, CHECKED_IN, IN_SERVICE, COMPLETED, CANCELLED, NO_SHOW)
TERMINAL = frozenset({COMPLETED, CANCELLED, NO_SHOW})
LIVE = frozenset({REQUESTED, CONFIRMED, CHECKED_IN, IN_SERVICE})        # they hold their resource
MOVABLE = frozenset({REQUESTED, CONFIRMED})                             # they can still be rescheduled

NEXT: dict[str, frozenset[str]] = {
    REQUESTED: frozenset({CONFIRMED, CANCELLED}),
    CONFIRMED: frozenset({CHECKED_IN, CANCELLED, NO_SHOW}),
    CHECKED_IN: frozenset({IN_SERVICE, CANCELLED, NO_SHOW}),
    IN_SERVICE: frozenset({COMPLETED}),
    COMPLETED: frozenset(),
    CANCELLED: frozenset(),
    NO_SHOW: frozenset(),
}


def check_move(current: str, target: str) -> None:
    """ValidationFailed unless an appointment may go from `current` to `target`."""
    if target not in NEXT.get(current, frozenset()):
        raise ValidationFailed(f"An appointment that is {current.replace('_', ' ')} cannot become "
                               f"{target.replace('_', ' ')}")


def is_late_cancellation(starts_at: datetime, now: datetime, window_hours: int) -> bool:
    """True when a cancellation comes inside the window before the start (or after the start)."""
    return now > starts_at - timedelta(hours=window_hours)
