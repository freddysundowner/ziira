"""The availability engine: when can a service be booked? Pure rules, no database.

Everything is half-open (`start` included, `end` excluded), so one booking may start the moment another ends. A
booking holds its resource from `start - buffer_before` to `end + buffer_after`; the service itself must lie inside one
of the resource's working windows, and neither the service nor its buffers may meet time off or another booking.
Working hours are wall-clock times in the company's time zone, so a 09:00 start stays 09:00 across a clock change.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from uuid import UUID

OUTSIDE_HOURS = "outside_hours"
TIME_OFF = "time_off"
CONFLICT = "conflict"
TOO_SOON = "too_soon"
TOO_FAR = "too_far"


@dataclass(frozen=True)
class Interval:
    """A stretch of time between two aware moments."""

    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class Hours:
    """One working window of a weekday (Monday is 0)."""

    weekday: int
    start: time
    end: time


@dataclass(frozen=True)
class ResourceCalendar:
    """What the engine needs to know about one resource: its hours, its time off and what is already held."""

    resource_id: UUID
    hours: tuple[Hours, ...]
    time_off: tuple[Interval, ...] = ()
    booked: tuple[Interval, ...] = ()          # the blocked ranges of live appointments (buffers included)


@dataclass(frozen=True)
class ServiceShape:
    """How long a service takes and how it uses resources: `any` one of its resources, or `all` of them together."""

    duration_minutes: int
    buffer_before_minutes: int = 0
    buffer_after_minutes: int = 0
    mode: str = "any"
    processing_start_minutes: int = 0        # the person serving is free from here ...
    processing_minutes: int = 0              # ... for this long (colour setting), and serves someone else


@dataclass(frozen=True)
class Policy:
    """The business's booking rules for clients."""

    granularity_minutes: int = 15
    min_notice_minutes: int = 0
    max_days_ahead: int = 365


@dataclass(frozen=True)
class Slot:
    """A start time that can be booked, and the resources that could serve it (all of them when the service needs
    all)."""

    start: datetime
    end: datetime
    resource_ids: tuple[UUID, ...]


def service_interval(start: datetime, service: ServiceShape) -> Interval:
    return Interval(start, start + timedelta(minutes=service.duration_minutes))


def blocked_interval(start: datetime, service: ServiceShape) -> Interval:
    """What a booking at `start` holds: the service and its buffers."""
    return Interval(start - timedelta(minutes=service.buffer_before_minutes),
                    start + timedelta(minutes=service.duration_minutes + service.buffer_after_minutes))


def blocked_intervals(start: datetime, service: ServiceShape) -> list[Interval]:
    """What a booking at `start` really holds: one stretch, or two when the service has processing time (the person is
    free while the colour sits). Buffers belong to the outer ends."""
    outer = blocked_interval(start, service)
    if service.processing_minutes <= 0:
        return [outer]
    free_from = start + timedelta(minutes=service.processing_start_minutes)
    free_to = free_from + timedelta(minutes=service.processing_minutes)
    parts = [Interval(outer.start, free_from), Interval(free_to, outer.end)]
    return [p for p in parts if p.end > p.start]


def _aware(day: date, minute_of_day: int, zone: tzinfo) -> datetime | None:
    """The moment at that wall-clock minute of the day, or None when a clock change skipped it."""
    naive = datetime.combine(day, time(minute_of_day // 60, minute_of_day % 60))
    moment = naive.replace(tzinfo=zone)
    if moment.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return moment


MIDNIGHT = time(23, 59)          # an end time of 23:59 means "until midnight"


def _windows(calendar: ResourceCalendar, day: date, zone: tzinfo) -> list[Interval]:
    out: list[Interval] = []
    for h in calendar.hours:
        if h.weekday != day.weekday():
            continue
        start = _aware(day, h.start.hour * 60 + h.start.minute, zone)
        if h.end >= MIDNIGHT:
            end: datetime | None = datetime.combine(day + timedelta(days=1), time(0, 0)).replace(tzinfo=zone)
        else:
            end = _aware(day, h.end.hour * 60 + h.end.minute, zone)
        if start is not None and end is not None and end > start:
            out.append(Interval(start, end))
    return out


def working_windows(calendar: ResourceCalendar, day: date, zone: tzinfo) -> list[Interval]:
    """The resource's working windows on a calendar day (company zone)."""
    return _windows(calendar, day, zone)


def problems(calendar: ResourceCalendar, start: datetime, service: ServiceShape, zone: tzinfo) -> list[str]:
    """Why this resource cannot take the service at `start` (empty: it can). Does not look at notice or distance."""
    found: list[str] = []
    wanted = service_interval(start, service)
    local_day = start.astimezone(zone).date()
    inside = any(w.start <= wanted.start and wanted.end <= w.end for w in _windows(calendar, local_day, zone))
    if not inside:
        found.append(OUTSIDE_HOURS)
    held = blocked_interval(start, service)
    if any(held.overlaps(t) for t in calendar.time_off):
        found.append(TIME_OFF)
    if any(part.overlaps(b) for part in blocked_intervals(start, service) for b in calendar.booked):
        found.append(CONFLICT)
    return found


def policy_problems(start: datetime, policy: Policy, now: datetime, zone: tzinfo) -> list[str]:
    """Whether `start` is too soon or too far ahead for a client to book."""
    found: list[str] = []
    if start < now + timedelta(minutes=policy.min_notice_minutes):
        found.append(TOO_SOON)
    if start.astimezone(zone).date() > now.astimezone(zone).date() + timedelta(days=policy.max_days_ahead):
        found.append(TOO_FAR)
    return found


def candidate_starts(calendars: list[ResourceCalendar], day: date, granularity: int, zone: tzinfo) -> list[datetime]:
    """Every start on the grid (multiples of `granularity` minutes from midnight) inside any window of the day."""
    seen: set[datetime] = set()
    for c in calendars:
        for w in _windows(c, day, zone):
            local_start = w.start.astimezone(zone)
            first = -(-(local_start.hour * 60 + local_start.minute) // granularity) * granularity
            for minute in range(first, 24 * 60, granularity):
                moment = _aware(day, minute, zone)
                if moment is not None and w.start <= moment < w.end:
                    seen.add(moment)
    return sorted(seen)


def free_slots(calendars: list[ResourceCalendar], service: ServiceShape, policy: Policy, day: date, now: datetime,
               zone: tzinfo, *, enforce_policy: bool = True) -> list[Slot]:
    """The times on `day` (the company's calendar day) at which the service can be booked.

    With mode `any` a slot lists every resource that could take it; with `all` it exists only when every resource can,
    and lists them all. `enforce_policy=False` is for staff, who may book at short notice or far ahead.
    """
    if not calendars:
        return []
    slots: list[Slot] = []
    for start in candidate_starts(calendars, day, policy.granularity_minutes, zone):
        if start.astimezone(zone).date() != day:
            continue
        if enforce_policy and policy_problems(start, policy, now, zone):
            continue
        free = tuple(c.resource_id for c in calendars if not problems(c, start, service, zone))
        if service.mode == "all":
            if len(free) != len(calendars):
                continue
        elif not free:
            continue
        slots.append(Slot(start, start + timedelta(minutes=service.duration_minutes), free))
    return slots
