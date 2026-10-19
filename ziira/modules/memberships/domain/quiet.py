"""Quiet hours: when messages to customers wait. Hours are whole hours in the company's time zone."""


def is_quiet(hour: int, start: int, end: int) -> bool:
    """True when `hour` (0-23) falls from `start` up to (not including) `end`; the window may cross midnight
    (21 to 7). Equal start and end means no quiet hours."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
