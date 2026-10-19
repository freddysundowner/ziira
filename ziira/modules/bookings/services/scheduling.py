"""Loading what the availability engine needs, and asking it: free slots, and whether one booking fits."""

from datetime import date, datetime, timedelta, tzinfo
from uuid import UUID

from ziira.modules.bookings.domain import availability as av
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import BookingSettings, Resource, ServiceOffer
from ziira.modules.bookings.services.common import now, zone
from ziira.modules.bookings.services.resources import as_domain_hours
from ziira.sdk import Session, ValidationFailed

CLOSED = "closed"
MESSAGES = {
    CLOSED: "The business is closed that day",
    av.OUTSIDE_HOURS: "That time is outside working hours",
    av.TIME_OFF: "That time falls in time off",
    av.CONFLICT: "That time is already taken",
    av.TOO_SOON: "That is too soon to book online",
    av.TOO_FAR: "That is too far ahead to book",
}


def shape_of(offer: ServiceOffer) -> av.ServiceShape:
    return av.ServiceShape(offer.duration_minutes, offer.buffer_before_minutes, offer.buffer_after_minutes,
                           offer.resource_mode, offer.processing_start_minutes, offer.processing_minutes)


def policy_of(settings: BookingSettings) -> av.Policy:
    return av.Policy(settings.slot_granularity_minutes, settings.min_notice_minutes, settings.max_days_ahead)


def calendars(session: Session, resource_ids: list[UUID], start: datetime, end: datetime,
              exclude_appointment: UUID | None = None) -> list[av.ResourceCalendar]:
    """The engine's view of each resource between two moments (keeps the order given)."""
    ids = set(resource_ids)
    hours = repo.hours_of(session, ids)
    off = repo.time_off_of(session, ids, start, end)
    booked = repo.booked_ranges(session, ids, start, end, exclude_appointment)
    return [av.ResourceCalendar(
        resource_id=rid, hours=as_domain_hours(hours.get(rid, [])),
        time_off=tuple(av.Interval(t.starts_at, t.ends_at) for t in off.get(rid, [])),
        booked=tuple(av.Interval(a, b) for a, b in booked.get(rid, []))) for rid in resource_ids]


def usable_resources(session: Session, offer: ServiceOffer, resource_id: UUID | None = None,
                     branch_id: UUID | None = None) -> list[Resource]:
    """The active resources that can do the offer (one of them, when `resource_id` is given), optionally in a branch."""
    ids = repo.offer_resource_ids(session, {offer.id}).get(offer.id, [])
    found = repo.resources_by_ids(session, set(ids))
    chosen = [found[i] for i in ids if i in found and found[i].is_active
              and (branch_id is None or found[i].branch_id == branch_id)]
    if resource_id is not None:
        chosen = [r for r in chosen if r.id == resource_id]
    return chosen


def free_slots(session: Session, offer: ServiceOffer, settings: BookingSettings, day: date, *,
               resource_id: UUID | None = None, branch_id: UUID | None = None,
               for_client: bool = True) -> list[av.Slot]:
    """The free start times on a day. For a client the notice and distance rules apply; staff see everything free."""
    mode = offer.resource_mode
    resources = usable_resources(session, offer, resource_id if mode == "any" else None, branch_id)
    if mode == "all":
        every = repo.offer_resource_ids(session, {offer.id}).get(offer.id, [])
        if len(resources) != len(every) or resource_id is not None:
            return []
    if not resources:
        return []
    zn = zone(session, offer.company_id)
    if for_client and is_closed(session, offer.company_id, datetime.combine(day, datetime.min.time(), tzinfo=zn),
                                [r.id for r in resources], zn):
        return []
    start = datetime.combine(day, datetime.min.time(), tzinfo=zn) - timedelta(hours=12)
    end = start + timedelta(hours=60)
    cals = calendars(session, [r.id for r in resources], start, end)
    return av.free_slots(cals, shape_of(offer), policy_of(settings), day, now(), zn, enforce_policy=for_client)


def check_fits(session: Session, offer: ServiceOffer, settings: BookingSettings, start: datetime,
               resource_ids: list[UUID], *, for_client: bool, exclude_appointment: UUID | None = None,
               allow_outside_hours: bool = False) -> list[str]:
    """Why the booking does not fit (empty list: it fits). Staff may ignore notice, distance and, when
    `allow_outside_hours`, working hours and time off; a taken time is never allowed."""
    zn = zone(session, offer.company_id)
    shape = shape_of(offer)
    held = av.blocked_interval(start, shape)
    cals = calendars(session, resource_ids, held.start - timedelta(days=1), held.end + timedelta(days=1),
                     exclude_appointment)
    found: list[str] = []
    for cal in cals:
        for problem in av.problems(cal, start, shape, zn):
            if (problem == av.CONFLICT or not allow_outside_hours or for_client) and problem not in found:
                found.append(problem)
    if (CLOSED not in found and (for_client or not allow_outside_hours)
            and is_closed(session, offer.company_id, start, resource_ids, zn)):
        found.append(CLOSED)
    if for_client:
        found += [p for p in av.policy_problems(start, policy_of(settings), now(), zn) if p not in found]
    return found


def is_closed(session: Session, company_id: UUID, start: datetime, resource_ids: list[UUID], zn: tzinfo) -> bool:
    """True when the start falls on a day the business (or the branch of these resources) is closed."""
    branches = {r.branch_id for r in repo.resources_by_ids(session, set(resource_ids)).values()}
    return bool(raw.scalar(session, """select exists (select 1 from bookings.closed_day
        where company_id = :c and day = :d
        and (branch_id is null or branch_id = any(cast(:b as uuid[]))))""", c=company_id,
                      d=start.astimezone(zn).date(), b=[str(x) for x in branches]))


def explain(problems: list[str]) -> str:
    return "; ".join(MESSAGES[p] for p in problems)


def check_or_raise(problems: list[str]) -> None:
    if problems:
        raise ValidationFailed(explain(problems))
