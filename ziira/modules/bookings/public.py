"""Public interface of the Appointments and Bookings module.

Other units normally talk to Bookings through its events (`appointment.completed`, `class.attendee_booked`, ...). These
functions let a service-business pack or another unit ask simple questions and use group sessions without reading
Bookings' tables. All take the caller's session; the ones that change something check the caller's own
`bookings.manage` right at the branch (as they would if the caller were the front desk).

**Group sessions** (classes, workshops, lessons: gyms, studios and schools build on these; the signatures are kept
stable):

* `list_sessions(session, *, branch_id=None, start=None, end=None, offer_id=None, include_cancelled=False)`
* `get_session_view(session, session_id)`, `session_roster(session, session_id)`, `session_waitlist(session,
  session_id)`
* `create_session(session, *, offer_id, starts_at, branch_id=None, resource_ids=None, capacity=None, note=None)`
* `create_weekly_sessions(session, *, offer_id, starts_at, weeks, branch_id=None, resource_ids=None)`
* `book_attendee(session, session_id, *, customer_id=None, name=None, phone=None, email=None, join_waitlist=True)`:
  a place, or (when full) a place on the waitlist. Race-safe: the last place can only be taken once.
* `cancel_attendee(session, attendee_id, *, by_client=False)`: marks `late` inside the late window and offers the freed
  place to the first person waiting.
* `mark_attendee(session, attendee_id, status)`: `attended`, `no_show` or back to `booked`.
* `confirm_waitlist_offer(session, waitlist_id)`, `leave_waitlist(session, waitlist_id)`
* `set_session_capacity(session, session_id, capacity)`, `substitute_session_resource(session, session_id, resource_id)`
* `cancel_session(session, session_id, *, reason_code_id, note=None)`

Events (aggregate `bookings.appointment`, id = the session): `class.attendee_booked`, `class.attendee_cancelled`
(payload `late`, `by_client`, `session_cancelled`), `class.attendee_attended`, `class.attendee_no_show`,
`class.attendee_reset` (an attended/no-show mark undone), `class.waitlist_joined`, `class.waitlist_offered`,
`class.waitlist_promoted`, `class.waitlist_expired`, `class.cancelled`, `class.resource_changed`. Every payload has
`company_id`, `branch_id`, `appointment_id`, `offer_id`, `starts_at`; attendee events add `attendee_id` and
`customer_id`. The unit that owns credits spends them on `class.attendee_attended` (or on booking, as it chooses) with
the attendee id as the source, and gives them back on `class.attendee_cancelled` (not late) or `class.attendee_reset`.
Bookings itself takes no money.

**Checkout** (`bookings.checkout_tender`): a unit that holds credit the client can pay with (gift vouchers, loyalty
points) implements `CheckoutTender` (below) and plugs it into that extension point. **Commission**: `commission_figure`.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.services import commission as _commission
from ziira.modules.bookings.services import sessions as _sessions
from ziira.modules.bookings.tender import CHECKOUT_TENDER, CheckoutTender, TenderBalance, TenderUse
from ziira.sdk import Session

__all__ = [
    "CHECKOUT_TENDER", "AppointmentView", "AttendeeView", "BookResult", "CheckoutTender", "SessionView",
    "TenderBalance", "TenderUse", "WaitlistView", "book_attendee", "cancel_attendee", "cancel_session",
    "commission_figure",
    "confirm_waitlist_offer", "create_session", "create_weekly_sessions", "customer_appointments", "find_appointment",
    "get_session_view", "leave_waitlist", "list_sessions", "mark_attendee", "session_roster", "session_waitlist",
    "set_session_capacity", "substitute_session_resource"]


@dataclass(frozen=True)
class AppointmentView:
    """What other units may know about an appointment."""

    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    offer_id: UUID
    customer_id: UUID | None
    status: str
    starts_at: datetime
    ends_at: datetime
    minutes_worked: int | None
    invoice_id: UUID | None


def _view(a: Any) -> AppointmentView:
    return AppointmentView(a.id, a.company_id, a.branch_id, a.number, a.offer_id, a.customer_id, a.status, a.starts_at,
                           a.ends_at, a.minutes_worked, a.invoice_id)


def find_appointment(session: Session, appointment_id: UUID) -> AppointmentView | None:
    """An appointment, or None."""
    a = repo.get_appointment(session, appointment_id)
    return _view(a) if a is not None else None


def customer_appointments(session: Session, customer_id: UUID, limit: int = 50) -> list[AppointmentView]:
    """A customer's appointments, newest first (for a customer screen)."""
    rows = repo.list_appointments(session, None, customer_id=customer_id, order_desc=True, limit=min(limit, 200))
    return [_view(a) for a in rows]


# --------------------------------------------------------------------------- group sessions
@dataclass(frozen=True)
class SessionView:
    """A group session: one class at one time with a room of `capacity` places."""

    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    offer_id: UUID
    name: str
    status: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    booked: int                 # people on it
    held: int                   # places held for waiting people who were offered one
    waiting: int                # people waiting
    free: int                   # places a new booking can take now (capacity - booked - held)
    resource_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class AttendeeView:
    id: UUID
    customer_id: UUID | None
    name: str
    phone: str | None
    email: str | None
    status: str                 # booked | attended | no_show | cancelled
    late_cancellation: bool
    source: str                 # staff | online | waitlist
    checked_in_at: datetime | None


@dataclass(frozen=True)
class WaitlistView:
    id: UUID
    customer_id: UUID | None
    name: str
    status: str                 # waiting | offered
    joined_at: datetime
    confirm_by: datetime | None


@dataclass(frozen=True)
class BookResult:
    """`status` is "booked" (`attendee` is set) or "waitlisted" (`waitlist` and `position` are set)."""

    status: str
    attendee: AttendeeView | None = None
    waitlist: WaitlistView | None = None
    position: int | None = None


def _session_view(session: Session, appt: Any) -> SessionView:
    c = _sessions.counts(session, appt)
    offer = repo.get_offer(session, appt.offer_id)
    res = repo.appointment_resources(session, {appt.id}).get(appt.id, [])
    return SessionView(appt.id, appt.company_id, appt.branch_id, appt.number, appt.offer_id,
                       offer.name if offer else "", appt.status, appt.starts_at, appt.ends_at, appt.capacity,
                       c["booked"], c["held"], c["waiting"], c["free"], tuple(res))


def _attendee(a: Any) -> AttendeeView:
    return AttendeeView(a.id, a.customer_id, a.name, a.phone, a.email, a.status, a.late_cancellation, a.source,
                        a.checked_in_at)


def _waiting(row: dict[str, Any]) -> WaitlistView:
    return WaitlistView(row["id"], row["customer_id"], row["name"], row["status"], row["created_at"], row["confirm_by"])


def list_sessions(session: Session, *, branch_id: UUID | None = None, start: datetime | None = None,
                  end: datetime | None = None, offer_id: UUID | None = None,
                  include_cancelled: bool = False) -> list[SessionView]:
    """Group sessions the caller may see in a stretch of time, soonest first, with their places."""
    return [_session_view(session, a) for a in _sessions.list_sessions(
        session, branch_id=branch_id, start=start, end=end, offer_id=offer_id, include_cancelled=include_cancelled)]


def get_session_view(session: Session, session_id: UUID) -> SessionView:
    return _session_view(session, _sessions.get_session(session, session_id))


def session_roster(session: Session, session_id: UUID) -> list[AttendeeView]:
    """Everyone on the session (cancelled people are listed with status `cancelled`)."""
    return [_attendee(a) for a in _sessions.roster(session, session_id)]


def session_waitlist(session: Session, session_id: UUID) -> list[WaitlistView]:
    """People waiting for (or offered) a place, in the order they joined."""
    return [_waiting(r) for r in _sessions.waitlist_of(session, session_id)]


def create_session(session: Session, *, offer_id: UUID, starts_at: datetime, branch_id: UUID | None = None,
                   resource_ids: list[UUID] | None = None, capacity: int | None = None,
                   note: str | None = None) -> SessionView:
    """Schedule one group session of a class offer (a service of kind `class`)."""
    return _session_view(session, _sessions.create_session(session, offer_id=offer_id, starts_at=starts_at,
                                                           branch_id=branch_id, resource_ids=resource_ids, note=note,
                                                           capacity=capacity))


def create_weekly_sessions(session: Session, *, offer_id: UUID, starts_at: datetime, weeks: int,
                           branch_id: UUID | None = None, resource_ids: list[UUID] | None = None) -> dict[str, Any]:
    """The same session each week at the same local time. Returns `{"created": [SessionView], "skipped": [{"starts_at",
    "problem"}]}`: a closed day (a holiday), a taken instructor or time off is skipped, not forced."""
    out = _sessions.create_weekly(session, offer_id=offer_id, starts_at=starts_at, weeks=weeks, branch_id=branch_id,
                                  resource_ids=resource_ids)
    return {"created": [_session_view(session, a) for a in out["created"]],
            "skipped": [{"starts_at": c["starts_at"], "problem": c["problem"]} for c in out["conflicts"]]}


def book_attendee(session: Session, session_id: UUID, *, customer_id: UUID | None = None, name: str | None = None,
                  phone: str | None = None, email: str | None = None, join_waitlist: bool = True) -> BookResult:
    """Put a person on a session, or on its waitlist when it is full (`join_waitlist=False`: raise Conflict instead)."""
    r = _sessions.book_attendee(session, session_id, customer_id=customer_id, name=name, phone=phone, email=email,
                                join_waitlist=join_waitlist)
    return BookResult(r.status, _attendee(r.attendee) if r.attendee else None,
                      _waiting(r.waitlist) if r.waitlist else None, r.position)


def cancel_attendee(session: Session, attendee_id: UUID, *, by_client: bool = False) -> AttendeeView:
    """Take a person off a session. Inside the late window the attendee is marked `late_cancellation`."""
    return _attendee(_sessions.cancel_attendee(session, attendee_id, by_client=by_client))


def mark_attendee(session: Session, attendee_id: UUID, status: str) -> AttendeeView:
    """`attended`, `no_show`, or `booked` (undo)."""
    return _attendee(_sessions.mark_attendee(session, attendee_id, status))


def confirm_waitlist_offer(session: Session, waitlist_id: UUID) -> BookResult:
    """The waiting person takes the place they were offered."""
    r = _sessions.confirm_offer(session, waitlist_id)
    return BookResult(r.status, _attendee(r.attendee) if r.attendee else None)


def leave_waitlist(session: Session, waitlist_id: UUID) -> None:
    """Remove a person from the waitlist (the next one is offered a freed place)."""
    _sessions.leave_waitlist(session, waitlist_id)


def set_session_capacity(session: Session, session_id: UUID, capacity: int) -> SessionView:
    return _session_view(session, _sessions.set_capacity(session, session_id, capacity))


def substitute_session_resource(session: Session, session_id: UUID, resource_id: UUID) -> SessionView:
    """Another instructor or room takes the session."""
    return _session_view(session, _sessions.substitute_resource(session, session_id, resource_id))


def cancel_session(session: Session, session_id: UUID, *, reason_code_id: UUID | None,
                   note: str | None = None) -> SessionView:
    """Call a session off: everyone booked is told and each cancellation is published with `session_cancelled`."""
    return _session_view(session, _sessions.cancel_session(session, session_id, reason_code_id=reason_code_id,
                                                           note=note))


# --------------------------------------------------------------------------- commission
def commission_figure(session: Session, *, company_id: UUID, start: date, end: date, resource_id: UUID | None = None,
                      user_id: UUID | None = None) -> Decimal:
    """What a person earned in commission in a period (both days included), as one number for Payroll to read. Name
    them by their staff resource or by the user it is linked to. Commission is information: nothing is paid or
    posted."""
    return _commission.commission_figure(session, company_id=company_id, start=start, end=end, resource_id=resource_id,
                                         user_id_=user_id)
