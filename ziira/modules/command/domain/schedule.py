"""When a brief is due. Pure: the clock is passed in."""

from datetime import datetime, time


def is_due(*, now_local: datetime, send_time: time, kind: str, weekday: int | None, already_sent: bool,
           is_active: bool = True) -> bool:
    """True when a brief should be sent now: active, not yet sent for today, the send time has passed, and (for a
    weekly one) today is the chosen weekday (1 Monday ... 7 Sunday). A brief missed because the worker was down is
    still sent later the same day; a day that has passed is not made up."""
    if not is_active or already_sent:
        return False
    if kind == "weekly" and (weekday is None or now_local.isoweekday() != weekday):
        return False
    return now_local.time() >= send_time
