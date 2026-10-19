"""The front desk: who is free now, who is next, who is waiting, and a visit of several services in sequence.

A barber who takes mostly walk-ins and a spa that takes only bookings use the same screen: people who arrive are checked
in and either start at once (a person is free) or join the queue, with an estimated start time from the calendar itself.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from ziira.modules.bookings.domain import availability as av
from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import access, appointments, scheduling
from ziira.modules.bookings.services.common import now, unit_enabled, zone
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, company_today


def _branch(session: Session, branch_id: UUID) -> UUID:
    company = session.execute(text("select company_id from kernel.branch where id = :b"),
                              {"b": str(branch_id)}).first()
    if company is None or not access.can_view(company.company_id, branch_id):
        raise NotFound("Branch not found")
    return UUID(str(company.company_id))


def _brief(session: Session, a: Appointment, names: dict[UUID, str]) -> dict[str, Any]:
    return {"appointment_id": a.id, "number": a.number, "client_name": a.client_name,
            "service": names.get(a.offer_id, ""), "starts_at": a.starts_at, "ends_at": a.ends_at, "status": a.status,
            "customer_id": a.customer_id,
            "checked_in_at": a.checked_in_at, "source": a.source, "price": a.price}


def board(session: Session, branch_id: UUID) -> dict[str, Any]:
    """The branch right now: each person (free, busy until, processing, off), their next booking, who is waiting in the
    queue, who is due to arrive, and who is ready to be billed."""
    company_id = _branch(session, branch_id)
    moment = now()
    zn = zone(session, company_id)
    today = company_today(session, company_id)
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=zn)
    day_end = day_start + timedelta(days=1)
    rows = repo.list_resources(session, access.view_scopes(), branch_id=branch_id, active_only=True)
    live = repo.list_appointments(session, access.view_scopes(), branch_id=branch_id, start=day_start, end=day_end,
                                  status=sorted(life.LIVE | {life.COMPLETED}), kind="appointment", limit=500)
    names = {o.id: o.name for o in repo.offers_by_ids(session, {a.offer_id for a in live}).values()}
    held = repo.appointment_resources(session, {a.id for a in live})
    by_resource: dict[UUID, list[Appointment]] = {}
    for a in live:
        for rid in held.get(a.id, []):
            by_resource.setdefault(rid, []).append(a)
    cals = {c.resource_id: c for c in scheduling.calendars(
        session, [r.id for r in rows], day_start - timedelta(hours=12), day_end + timedelta(hours=12))}
    offers = repo.offers_by_ids(session, {a.offer_id for a in live})
    people: list[dict[str, Any]] = []
    for r in rows:
        cal = cals[r.id]
        in_hours = any(w.start <= moment < w.end for w in av.working_windows(cal, today, zn))
        on_leave = any(t.start <= moment < t.end for t in cal.time_off)
        mine = sorted(by_resource.get(r.id, []), key=lambda a: a.starts_at)
        current = next((a for a in mine
                        if a.status in (life.CHECKED_IN, life.IN_SERVICE) and a.starts_at <= moment < a.ends_at
                        or a.status == life.IN_SERVICE), None)
        state, until = "free", None
        if on_leave or not in_hours:
            state = "off"
        elif current is not None:
            offer = offers.get(current.offer_id)
            state, until = "busy", current.ends_at
            if offer is not None and offer.processing_minutes > 0:
                free_from = current.starts_at + timedelta(minutes=offer.processing_start_minutes)
                if free_from <= moment < free_from + timedelta(minutes=offer.processing_minutes):
                    state, until = "processing", free_from + timedelta(minutes=offer.processing_minutes)
        else:
            held_now = next((b for b in cal.booked if b.start <= moment < b.end), None)
            if held_now is not None:
                state, until = "busy", held_now.end
        upcoming = next((a for a in mine if a.starts_at > moment and a.status in (life.REQUESTED, life.CONFIRMED,
                                                                                   life.CHECKED_IN)), None)
        free_for = None
        if state == "free" and upcoming is not None:
            free_for = max(int((upcoming.starts_at - moment).total_seconds() // 60), 0)
        people.append({
            "resource_id": r.id, "name": r.name, "kind": r.kind, "level": r.level, "colour": r.colour, "state": state,
            "until": until, "free_for_minutes": free_for,
            "current": _brief(session, current, names) if current else None,
            "next": _brief(session, upcoming, names) if upcoming else None})
    waiting = sorted((a for a in live if a.status == life.CHECKED_IN and a.completed_at is None),
                     key=lambda a: (a.checked_in_at or a.starts_at, a.id))
    arriving = [a for a in live if a.status in (life.REQUESTED, life.CONFIRMED)
                and a.starts_at <= moment + timedelta(hours=2)]
    in_service = [a for a in live if a.status == life.IN_SERVICE]
    unbilled = [a for a in live if a.status in (life.IN_SERVICE, life.COMPLETED) and a.invoice_id is None
                and not _on_checkout(session, a.id)]
    return {
        "day": today, "timezone": str(zn), "now": moment, "resources": people,
        "waiting": [{**_brief(session, a, names),
                     "waited_minutes": int((moment - (a.checked_in_at or moment)).total_seconds() // 60),
                     "resource_ids": held.get(a.id, [])} for a in waiting],
        "arriving": [_brief(session, a, names) for a in arriving],
        "in_service": [{**_brief(session, a, names), "resource_ids": held.get(a.id, [])} for a in in_service],
        "to_bill": [{**_brief(session, a, names), "resource_ids": held.get(a.id, [])} for a in unbilled],
    }


def _on_checkout(session: Session, appointment_id: UUID) -> bool:
    return bool(session.execute(text(
        "select 1 from bookings.checkout_line l join bookings.checkout c on c.id = l.checkout_id "
        "where l.appointment_id = :a and c.status = 'done' limit 1"), {"a": str(appointment_id)}).first())


# --------------------------------------------------------------------------- walk-ins
def walk_in(session: Session, *, offer_id: UUID, branch_id: UUID | None = None, resource_ids: list[UUID] | None = None,
            customer_id: UUID | None = None, client_name: str | None = None, client_phone: str | None = None,
            note: str | None = None, local_id: str | None = None) -> tuple[Appointment, int]:
    """A client has walked in. Someone free starts them now; when everyone is busy they join the queue at the earliest
    time the calendar allows. Returns (appointment, minutes to wait: 0 when they start now)."""
    try:
        appt = appointments.create_walk_in(session, offer_id=offer_id, branch_id=branch_id, resource_ids=resource_ids,
                                           customer_id=customer_id, client_name=client_name, client_phone=client_phone,
                                           note=note, local_id=local_id)
        return appt, 0
    except Conflict:
        pass
    offer = repo.get_offer(session, offer_id)
    if offer is None:
        raise NotFound("Service not found")
    settings = repo.ensure_settings(session, offer.company_id)
    moment = now()
    zn = zone(session, offer.company_id)
    pool = scheduling.usable_resources(session, offer, resource_ids[0] if resource_ids and offer.resource_mode == "any"
                                       else None, branch_id)
    day = moment.astimezone(zn).date()
    for plus in range(0, 2):
        slots = scheduling.free_slots(session, offer, settings, day + timedelta(days=plus), resource_id=(
            resource_ids[0] if resource_ids and offer.resource_mode == "any" else None), branch_id=branch_id,
            for_client=False)
        for slot in slots:
            if slot.start > moment:
                chosen = [r for r in slot.resource_ids]
                appt = appointments.create_appointment(
                    session, offer_id=offer_id, starts_at=slot.start, branch_id=branch_id or pool[0].branch_id,
                    resource_ids=chosen if offer.resource_mode == "all" else chosen[:1], customer_id=customer_id,
                    client_name=client_name or "Walk-in", client_phone=client_phone, note=note, source="walk_in",
                    local_id=local_id, status=life.CHECKED_IN, notify_client=False)
                return appt, max(int((slot.start - moment).total_seconds() // 60), 1)
    raise Conflict("No one is free today: book a time on another day")


# --------------------------------------------------------------------------- a visit of several services
def create_visit(session: Session, *, items: list[dict[str, Any]], starts_at: datetime, branch_id: UUID | None = None,
                 customer_id: UUID | None = None, client_name: str | None = None, client_phone: str | None = None,
                 client_email: str | None = None, note: str | None = None, source: str = "staff",
                 payer: dict[str, Any] | None = None, allow_outside_hours: bool = False) -> list[Appointment]:
    """Book several services for one client, one after the other (each may be done by someone different). A leg starts
    when the one before ends; if the same person does the next leg and needs set-up time, it starts after that. All legs
    are booked or none: a leg that does not fit stops the visit with the reason."""
    if not 1 <= len(items) <= 8:
        raise ValidationFailed("A visit has between 1 and 8 services")
    visit_id = uuid4()
    made: list[Appointment] = []
    cursor, gap = starts_at, 0
    with session.begin_nested():
        for index, item in enumerate(items):
            offer = repo.get_offer(session, item["offer_id"])
            if offer is None or not access.can_see_company(offer.company_id):
                raise NotFound("Service not found")
            settings = repo.ensure_settings(session, offer.company_id)
            when = _first_fit(session, offer, settings, [cursor, cursor + timedelta(minutes=gap)] if gap else [cursor],
                              item.get("resource_ids"), branch_id, allow_outside_hours)
            leg = appointments.create_appointment(
                session, offer_id=offer.id, starts_at=when, branch_id=branch_id, resource_ids=item.get("resource_ids"),
                customer_id=customer_id, client_name=client_name, client_phone=client_phone, client_email=client_email,
                note=note if index == 0 else None, source=source, visit_id=visit_id, payer=payer,
                price_variant=item.get("price_variant"), allow_outside_hours=allow_outside_hours, for_client=False,
                notify_client=False)
            made.append(leg)
            cursor, gap = leg.ends_at, offer.buffer_after_minutes
    if made:
        notify_visit(session, made)
    return made


def _first_fit(session: Session, offer: Any, settings: Any, times: list[datetime], requested: list[UUID] | None,
               branch_id: UUID | None, allow_outside_hours: bool) -> datetime:
    """The first of the candidate times at which someone can do the service (the first when none can: the booking itself
    then explains why)."""
    pool = scheduling.usable_resources(session, offer, None, branch_id)
    ids = list(requested) if requested else [r.id for r in pool]
    for t in times:
        groups = [ids] if offer.resource_mode == "all" else [[i] for i in ids]
        for group in groups:
            if group and not scheduling.check_fits(session, offer, settings, t, group, for_client=False,
                                                   allow_outside_hours=allow_outside_hours):
                return t
    return times[0]


def notify_visit(session: Session, legs: list[Appointment]) -> None:
    """One confirmation for the visit (the first leg's), not one per service."""
    from ziira.modules.bookings.services import notify

    if legs[0].status != life.REQUESTED:
        notify.confirmation(session, legs[0])


def visit_appointments(session: Session, visit_id: UUID) -> list[Appointment]:
    return repo.list_appointments(session, access.view_scopes(), visit_id=visit_id, limit=50)


def crm_available(session: Session) -> bool:
    return unit_enabled(session, "crm")
