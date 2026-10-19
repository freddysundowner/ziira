"""Group sessions: a class, a workshop, a group lesson. One appointment of kind `class` with a capacity, a roster, a
waitlist that fills a freed place by itself, and a late-cancel rule.

Gyms (classes), schools (lessons) and studios build on this through `bookings.public`. The rules:

* a place is **taken** by a booked attendee and **held** for a waiting person who has been offered it, so the room is
  never oversold; every change locks the session row, so two desks booking the last place cannot both win;
* when a place frees up (a cancellation, a bigger capacity, an offer that ran out) the first person waiting is offered
  it: put straight in when the business set the confirm window to 0, else told and held for the window;
* nothing here takes money or credits. It publishes events (`class.attendee_booked`, `.attendee_cancelled` with `late`,
  `.attendee_attended`, `.attendee_no_show`, `.attendee_reset`, `.waitlist_offered`, `.waitlist_promoted`, `.cancelled`)
  and the unit that owns the credits (Memberships, a gym pack) spends or returns them from those events.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.permissions import BOOKINGS_MANAGE
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Appointment, AppointmentAttendee
from ziira.modules.bookings.services import access, appointments, notify
from ziira.modules.bookings.services.common import now, user_id
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    publish,
)

OPEN_STATUSES = (life.REQUESTED, life.CONFIRMED, life.CHECKED_IN)
ATTENDEE_STATUSES = ("booked", "attended", "no_show", "cancelled")


@dataclass(frozen=True)
class BookResult:
    """The answer to booking someone on a class: they got a place, or they are waiting for one."""

    status: str                                   # "booked" | "waitlisted"
    attendee: AppointmentAttendee | None = None
    waitlist: dict[str, Any] | None = None
    position: int | None = None


# --------------------------------------------------------------------------- reading
def get_session(session: Session, appointment_id: UUID, *, lock: bool = False) -> Appointment:
    """A class session, or NotFound. `lock` serialises changes to its places."""
    appt = repo.get_appointment(session, appointment_id, lock=lock)
    if appt is None or not access.can_view(appt.company_id, appt.branch_id):
        raise NotFound("Class not found")
    if appt.kind != "class":
        raise ValidationFailed("That is not a class: only a class has a roster")
    return appt


def _manage(appt: Appointment) -> None:
    current_context().require(BOOKINGS_MANAGE, company_id=appt.company_id, branch_id=appt.branch_id)


def counts(session: Session, appt: Appointment) -> dict[str, int]:
    """Places: `booked` (taking a place), `held` (offered to someone waiting), `waiting`, `free`."""
    booked = int(raw.scalar(session, "select count(*) from bookings.appointment_attendee where appointment_id = :a "
                                     "and status <> 'cancelled'", a=appt.id))
    rows = raw.many(session, "select status, count(*) as n from bookings.session_waitlist where appointment_id = :a "
                             "and status in ('waiting', 'offered') group by status", a=appt.id)
    by = {r["status"]: int(r["n"]) for r in rows}
    held, waiting = by.get("offered", 0), by.get("waiting", 0)
    return {"booked": booked, "held": held, "waiting": waiting, "free": max(appt.capacity - booked - held, 0)}


def roster(session: Session, appointment_id: UUID) -> list[AppointmentAttendee]:
    """Everyone on the class (cancelled people too, marked as such)."""
    get_session(session, appointment_id)
    return repo.attendees_of(session, appointment_id)


def waitlist_of(session: Session, appointment_id: UUID) -> list[dict[str, Any]]:
    """The people waiting for (or offered) a place, in the order they joined."""
    get_session(session, appointment_id)
    return raw.many(session, "select * from bookings.session_waitlist where appointment_id = :a "
                             "and status in ('waiting', 'offered') order by created_at, id", a=appointment_id)


def list_sessions(session: Session, *, branch_id: UUID | None = None, start: datetime | None = None,
                  end: datetime | None = None, offer_id: UUID | None = None, include_cancelled: bool = False,
                  limit: int = 200) -> list[Appointment]:
    """Class sessions in a stretch of time that the user may see, soonest first."""
    status = None if include_cancelled else sorted(life.LIVE | {life.COMPLETED})
    return repo.list_appointments(session, access.view_scopes(), branch_id=branch_id, start=start, end=end,
                                  offer_id=offer_id, kind="class", status=status, limit=min(limit, 500))


# --------------------------------------------------------------------------- making sessions
def create_session(session: Session, *, offer_id: UUID, starts_at: datetime, branch_id: UUID | None = None,
                   resource_ids: list[UUID] | None = None, note: str | None = None,
                   capacity: int | None = None) -> Appointment:
    """Schedule one class. The offer must be a class (`kind = "class"`); `capacity` overrides the offer's for this
    one."""
    offer = repo.get_offer(session, offer_id)
    if offer is None or not access.can_see_company(offer.company_id):
        raise NotFound("Service not found")
    if offer.kind != "class":
        raise ValidationFailed("Pick a class (a service with room for several people)")
    appt = appointments.create_appointment(session, offer_id=offer_id, starts_at=starts_at, branch_id=branch_id,
                                           resource_ids=resource_ids, note=note, status=life.CONFIRMED,
                                           notify_client=False)
    if capacity is not None and capacity != appt.capacity:
        if not 1 <= capacity <= 500:
            raise ValidationFailed("Room for 1 to 500 people")
        appt.capacity = capacity
        session.flush()
    return appt


def create_weekly(session: Session, *, offer_id: UUID, starts_at: datetime, weeks: int,
                  branch_id: UUID | None = None, resource_ids: list[UUID] | None = None) -> dict[str, Any]:
    """The same class at the same local time each week for `weeks` weeks. A date the business is closed (a holiday), a
    taken instructor or a time off is skipped and reported, not forced."""
    if not 1 <= weeks <= 52:
        raise ValidationFailed("Repeat for 1 to 52 weeks")
    return appointments.create_series(session, offer_id=offer_id, starts_at=starts_at, frequency="weekly", count=weeks,
                                      branch_id=branch_id, resource_ids=resource_ids, client_name="Class",
                                      notify_client=False)


# --------------------------------------------------------------------------- booking people on
def _template_vars(session: Session, appt: Appointment, name: str, **more: str) -> dict[str, str]:
    offer = repo.get_offer(session, appt.offer_id)
    return {"customer": name, "service": offer.name if offer else "",
            "business": notify.business_name(session, appt.company_id),
            "when": notify.when_text(session, appt.company_id, appt.starts_at), **more}


def _payload(appt: Appointment, **more: Any) -> dict[str, Any]:
    return {"company_id": appt.company_id, "branch_id": appt.branch_id, "appointment_id": appt.id,
            "number": appt.number, "offer_id": appt.offer_id, "starts_at": appt.starts_at.isoformat(), **more}


def _add_attendee(session: Session, appt: Appointment, *, customer_id: UUID | None, name: str, phone: str | None,
                  email: str | None, source: str) -> AppointmentAttendee:
    ctx = current_context()
    row = AppointmentAttendee(tenant_id=ctx.tenant_id, created_by=ctx.user_id, appointment_id=appt.id,
                              customer_id=customer_id, name=name, phone=phone, email=email, source=source)
    repo.add(session, row)
    audit_record(session, "add_attendee", "bookings.appointment", appt.id, {"name": name, "source": source})
    publish(session, Event("class.attendee_booked", "bookings.appointment", appt.id, _payload(
        appt, attendee_id=row.id, customer_id=customer_id, source=source)))
    return row


def book_attendee(session: Session, appointment_id: UUID, *, customer_id: UUID | None = None, name: str | None = None,
                  phone: str | None = None, email: str | None = None, join_waitlist: bool = True,
                  source: str = "staff", tell_client: bool = True) -> BookResult:
    """Put a person on a class while there is room; when it is full they join the waitlist (unless `join_waitlist` is
    False, then it is a Conflict). Needs 'bookings.manage' at the branch. The session row is locked, so the last place
    can only be taken once. A person already on the class (or already offered a place) is not added twice."""
    appt = get_session(session, appointment_id, lock=True)
    _manage(appt)
    if appt.status not in OPEN_STATUSES or appt.ends_at <= now():
        raise ValidationFailed("This class can no longer take people")
    who, phone, email = appointments._customer_details(session, appt.company_id, customer_id, name, phone, email)  # noqa: SLF001
    if not who:
        raise ValidationFailed("Say who is joining")
    live = [a for a in repo.attendees_of(session, appt.id) if a.status != "cancelled"]
    if customer_id is not None and any(a.customer_id == customer_id for a in live):
        raise Conflict("That person is already on this class")
    if customer_id is not None:
        offered = raw.one(session, "select * from bookings.session_waitlist where appointment_id = :a and "
                                   "customer_id = :c and status in ('waiting', 'offered') order by created_at limit 1",
                          a=appt.id, c=customer_id)
        if offered is not None and offered["status"] == "offered":
            return _confirm(session, appt, offered, tell_client=tell_client)
        if offered is not None:
            raise Conflict("That person is already on the waitlist")
    c = counts(session, appt)
    if c["free"] > 0 and c["waiting"] == 0:
        row = _add_attendee(session, appt, customer_id=customer_id, name=who, phone=phone, email=email, source=source)
        if tell_client:
            _tell_booked(session, appt, row)
        return BookResult("booked", attendee=row)
    if not join_waitlist:
        raise Conflict("The class is full")
    entry = raw.insert(session, "session_waitlist", {
        "company_id": appt.company_id, "branch_id": appt.branch_id, "appointment_id": appt.id,
        "customer_id": customer_id, "name": who, "phone": phone, "email": email, "source": source},
        user_id=user_id())
    audit_record(session, "waitlist_join", "bookings.appointment", appt.id, {"name": who})
    publish(session, Event("class.waitlist_joined", "bookings.appointment", appt.id, _payload(
        appt, waitlist_id=entry["id"], customer_id=customer_id)))
    promote_next(session, appt)                       # a place may be free (people waiting ahead were not yet offered)
    entry = raw.one(session, "select * from bookings.session_waitlist where id = :i", i=entry["id"]) or entry
    if entry["status"] == "promoted":
        promoted = repo.get_attendee(session, entry["attendee_id"])
        return BookResult("booked", attendee=promoted)
    position = int(raw.scalar(session, "select count(*) from bookings.session_waitlist where appointment_id = :a "
                                       "and status in ('waiting', 'offered') and created_at <= :t",
                              a=appt.id, t=entry["created_at"]))
    return BookResult("waitlisted", waitlist=entry, position=position)


def _tell_booked(session: Session, appt: Appointment, row: AppointmentAttendee) -> None:
    notify.to_contact(session, company_id=appt.company_id, phone=row.phone, email=row.email, template="class_booked",
                      variables=_template_vars(session, appt, row.name), ref_type="bookings.attendee", ref_id=row.id,
                      dedupe_key=f"class-booked:{row.id}")


def late_window_hours(session: Session, appt: Appointment) -> int:
    """How many hours before the start a cancellation counts as late: the class's own rule, else the business's."""
    offer = repo.get_offer(session, appt.offer_id)
    if offer is not None and offer.group_late_cancel_hours is not None:
        return int(offer.group_late_cancel_hours)
    return int(repo.ensure_settings(session, appt.company_id).cancel_window_hours)


def cancel_attendee(session: Session, attendee_id: UUID, *, by_client: bool = False) -> AppointmentAttendee:
    """Take a person off a class. A cancellation inside the late window is marked `late_cancellation` (the event says
    so, and whoever owns the credit decides whether it is spent). The freed place goes to the first person waiting."""
    row = repo.get_attendee(session, attendee_id)
    if row is None:
        raise NotFound("Attendee not found")
    appt = get_session(session, row.appointment_id, lock=True)
    _manage(appt)
    if row.status == "cancelled":
        return row
    if row.status in ("attended", "no_show"):
        raise ValidationFailed("That person was already marked as attended or as not coming")
    moment = now()
    row.status, row.cancelled_at = "cancelled", moment
    row.late_cancellation = life.is_late_cancellation(appt.starts_at, moment, late_window_hours(session, appt))
    row.updated_by, row.updated_at = user_id(), moment
    session.flush()
    audit_record(session, "cancel_attendee", "bookings.appointment", appt.id,
                 {"name": row.name, "late": row.late_cancellation, "by_client": by_client})
    publish(session, Event("class.attendee_cancelled", "bookings.appointment", appt.id, _payload(
        appt, attendee_id=row.id, customer_id=row.customer_id, late=row.late_cancellation, by_client=by_client)))
    promote_next(session, appt)
    return row


def mark_attendee(session: Session, attendee_id: UUID, status: str) -> AppointmentAttendee:
    """Mark a person as `attended`, `no_show`, or back to `booked`. Publishes the matching event (once per change) so a
    class pack can use up a credit on attendance, or give it back when the mark is undone."""
    if status not in ("booked", "attended", "no_show"):
        raise ValidationFailed("Mark a person as attended, not coming, or booked")
    row = repo.get_attendee(session, attendee_id)
    if row is None:
        raise NotFound("Attendee not found")
    appt = get_session(session, row.appointment_id, lock=True)
    _manage(appt)
    if row.status == "cancelled":
        raise ValidationFailed("That person cancelled")
    before = row.status
    if before == status:
        return row
    row.status = status
    row.checked_in_at = now() if status == "attended" else None
    row.updated_by, row.updated_at = user_id(), now()
    session.flush()
    audit_record(session, "attendee", "bookings.appointment", appt.id, {"status": status, "name": row.name})
    kind = {"attended": "attendee_attended", "no_show": "attendee_no_show", "booked": "attendee_reset"}[status]
    publish(session, Event(f"class.{kind}", "bookings.appointment", appt.id, _payload(
        appt, attendee_id=row.id, customer_id=row.customer_id, previous=before)))
    return row


# --------------------------------------------------------------------------- the waitlist
def promote_next(session: Session, appt: Appointment) -> int:
    """Fill free places from the waitlist, first come first served. With a confirm window of 0 the person is put on the
    class at once; otherwise the place is held and they are told. Returns how many were offered or put in. The caller
    holds the session lock."""
    if appt.status not in OPEN_STATUSES or appt.ends_at <= now():
        return 0
    settings = repo.ensure_settings(session, appt.company_id)
    done = 0
    while counts(session, appt)["free"] > 0:
        entry = raw.one(session, "select * from bookings.session_waitlist where appointment_id = :a and "
                                 "status = 'waiting' order by created_at, id limit 1 for update skip locked",
                        a=appt.id)
        if entry is None:
            break
        if settings.waitlist_confirm_minutes == 0:
            _promote(session, appt, entry)
        else:
            until = now() + timedelta(minutes=settings.waitlist_confirm_minutes)
            raw.update(session, "session_waitlist", entry["id"], {"status": "offered", "offered_at": now(),
                                                                "confirm_by": until}, user_id=user_id())
            audit_record(session, "waitlist_offer", "bookings.appointment", appt.id, {"name": entry["name"]})
            publish(session, Event("class.waitlist_offered", "bookings.appointment", appt.id, _payload(
                appt, waitlist_id=entry["id"], customer_id=entry["customer_id"], confirm_by=until.isoformat())))
            notify.to_contact(
                session, company_id=appt.company_id, phone=entry["phone"], email=entry["email"],
                template="class_place_offered",
                variables=_template_vars(session, appt, entry["name"], until=notify.when_text(
                    session, appt.company_id, until)),
                ref_type="bookings.session_waitlist", ref_id=entry["id"], dedupe_key=f"class-offer:{entry['id']}")
        done += 1
    return done


def _promote(session: Session, appt: Appointment, entry: dict[str, Any]) -> AppointmentAttendee:
    row = _add_attendee(session, appt, customer_id=entry["customer_id"], name=entry["name"], phone=entry["phone"],
                        email=entry["email"], source="waitlist")
    raw.update(session, "session_waitlist", entry["id"], {"status": "promoted", "attendee_id": row.id},
               user_id=user_id())
    publish(session, Event("class.waitlist_promoted", "bookings.appointment", appt.id, _payload(
        appt, waitlist_id=entry["id"], attendee_id=row.id, customer_id=entry["customer_id"])))
    _tell_booked(session, appt, row)
    return row


def _confirm(session: Session, appt: Appointment, entry: dict[str, Any], *, tell_client: bool = True) -> BookResult:
    if entry["status"] != "offered":
        raise ValidationFailed("There is no place on offer")
    if entry["confirm_by"] is not None and entry["confirm_by"] < now():
        raise ValidationFailed("The offer has run out")
    row = _add_attendee(session, appt, customer_id=entry["customer_id"], name=entry["name"], phone=entry["phone"],
                        email=entry["email"], source="waitlist")
    raw.update(session, "session_waitlist", entry["id"], {"status": "promoted", "attendee_id": row.id},
               user_id=user_id())
    publish(session, Event("class.waitlist_promoted", "bookings.appointment", appt.id, _payload(
        appt, waitlist_id=entry["id"], attendee_id=row.id, customer_id=entry["customer_id"])))
    if tell_client:
        _tell_booked(session, appt, row)
    return BookResult("booked", attendee=row)


def confirm_offer(session: Session, waitlist_id: UUID) -> BookResult:
    """The person (or the desk for them) takes the place they were offered. Needs 'bookings.manage'."""
    entry = raw.one(session, "select * from bookings.session_waitlist where id = :i", i=waitlist_id)
    if entry is None:
        raise NotFound("Waitlist entry not found")
    appt = get_session(session, entry["appointment_id"], lock=True)
    _manage(appt)
    entry = raw.one(session, "select * from bookings.session_waitlist where id = :i", i=waitlist_id) or entry
    return _confirm(session, appt, entry)


def leave_waitlist(session: Session, waitlist_id: UUID) -> dict[str, Any]:
    """Take a person off the waitlist (or withdraw an offer). The next person is offered the place."""
    entry = raw.one(session, "select * from bookings.session_waitlist where id = :i", i=waitlist_id)
    if entry is None:
        raise NotFound("Waitlist entry not found")
    appt = get_session(session, entry["appointment_id"], lock=True)
    _manage(appt)
    if entry["status"] not in ("waiting", "offered"):
        return entry
    row = raw.update(session, "session_waitlist", entry["id"], {"status": "removed"}, user_id=user_id())
    audit_record(session, "waitlist_leave", "bookings.appointment", appt.id, {"name": entry["name"]})
    promote_next(session, appt)
    return row


def expire_offers(session: Session) -> int:
    """Offers whose confirm window has run out lapse and the next person is offered the place. Run by the worker every
    few minutes. Returns how many lapsed."""
    lapsed = raw.many(session, "update bookings.session_waitlist set status = 'expired', updated_at = now() "
                               "where status = 'offered' and confirm_by < now() returning id, appointment_id, name")
    for appointment_id in {r["appointment_id"] for r in lapsed}:
        appt = repo.get_appointment(session, appointment_id, lock=True)
        if appt is not None:
            publish(session, Event("class.waitlist_expired", "bookings.appointment", appt.id, _payload(appt)))
            promote_next(session, appt)
    return len(lapsed)


# --------------------------------------------------------------------------- changing the session
def set_capacity(session: Session, appointment_id: UUID, capacity: int) -> Appointment:
    """Change how many people the class takes. It cannot go below the people already on it; a bigger room offers the
    new places to the waitlist."""
    appt = get_session(session, appointment_id, lock=True)
    _manage(appt)
    c = counts(session, appt)
    if not 1 <= capacity <= 500:
        raise ValidationFailed("Room for 1 to 500 people")
    if capacity < c["booked"] + c["held"]:
        raise ValidationFailed(f"{c['booked']} people are on this class: the room cannot be smaller than that")
    appt.capacity = capacity
    appt.updated_by, appt.updated_at = user_id(), now()
    session.flush()
    audit_record(session, "capacity", "bookings.appointment", appt.id, {"capacity": capacity})
    promote_next(session, appt)
    return appt


def substitute_resource(session: Session, appointment_id: UUID, resource_id: UUID) -> Appointment:
    """Another instructor or room takes this class (the time is unchanged). The new one must be free and able to do
    the service; the old one is released."""
    from sqlalchemy import text

    appt = get_session(session, appointment_id, lock=True)
    _manage(appt)
    if appt.status not in OPEN_STATUSES:
        raise ValidationFailed("This class can no longer be changed")
    offer = repo.get_offer(session, appt.offer_id)
    assert offer is not None
    settings = repo.ensure_settings(session, appt.company_id)
    _, resources = appointments._choose_resources(  # noqa: SLF001
        session, offer, settings, appt.branch_id, appt.starts_at, [resource_id], for_client=False,
        allow_outside_hours=True, source="staff", exclude=appt.id)
    session.execute(text("delete from bookings.appointment_resource where appointment_id = :a"), {"a": str(appt.id)})
    session.flush()
    appointments._hold(session, appt, offer, resources)  # noqa: SLF001
    audit_record(session, "substitute", "bookings.appointment", appt.id, {"resource": str(resource_id)})
    publish(session, Event("class.resource_changed", "bookings.appointment", appt.id, _payload(
        appt, resource_ids=[r.id for r in resources])))
    return appt


def cancel_session(session: Session, appointment_id: UUID, *, reason_code_id: UUID | None,
                   note: str | None = None) -> Appointment:
    """Call a class off. Everyone booked is told, each cancellation is published as `class.attendee_cancelled` with
    `late = False` and `session_cancelled = True` (so credits come back), and the waitlist is cleared."""
    appt = get_session(session, appointment_id, lock=True)
    _manage(appt)
    check_reason(session, "appointment_cancel", reason_code_id, note)
    people = [a for a in repo.attendees_of(session, appt.id) if a.status == "booked"]
    appt = appointments.cancel(session, appointment_id, reason_code_id=reason_code_id, note=note)
    for row in people:
        row.status, row.cancelled_at, row.late_cancellation = "cancelled", now(), False
        publish(session, Event("class.attendee_cancelled", "bookings.appointment", appt.id, _payload(
            appt, attendee_id=row.id, customer_id=row.customer_id, late=False, by_client=False,
            session_cancelled=True)))
        notify.to_contact(session, company_id=appt.company_id, phone=row.phone, email=row.email,
                          template="class_cancelled", variables=_template_vars(session, appt, row.name),
                          ref_type="bookings.attendee", ref_id=row.id, dedupe_key=f"class-cancel:{row.id}")
    session.flush()
    raw.run(session, "update bookings.session_waitlist set status = 'removed', updated_at = now() "
                     "where appointment_id = :a and status in ('waiting', 'offered')", a=appt.id)
    publish(session, Event("class.cancelled", "bookings.appointment", appt.id, _payload(appt, people=len(people))))
    return appt
