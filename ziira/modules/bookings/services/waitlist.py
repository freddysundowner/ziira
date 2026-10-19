"""Use cases: the waitlist. A client who wants an earlier or different time waits; when a time frees up the business
offers it (they are messaged), and when the client says yes it becomes a real appointment."""

from datetime import date, datetime
from uuid import UUID

from ziira.modules.bookings.permissions import BOOKINGS_MANAGE
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Appointment, WaitlistEntry
from ziira.modules.bookings.services import access, appointments, notify
from ziira.modules.bookings.services.common import now, require_aware, user_id, zone
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)


def _visible(session: Session, entry_id: UUID, *, lock: bool = False) -> WaitlistEntry:
    entry = repo.get_waitlist(session, entry_id, lock=lock)
    if entry is None or not access.can_view(entry.company_id, entry.branch_id):
        raise NotFound("Waitlist entry not found")
    return entry


def get_entry(session: Session, entry_id: UUID) -> WaitlistEntry:
    return _visible(session, entry_id)


def join(session: Session, *, offer_id: UUID, branch_id: UUID, wanted_from: date, wanted_to: date,
         customer_id: UUID | None = None, client_name: str | None = None, client_phone: str | None = None,
         client_email: str | None = None, resource_id: UUID | None = None, note: str | None = None) -> WaitlistEntry:
    """Put a client on the waitlist for a service between two dates. Needs 'bookings.manage' at the branch."""
    ctx = current_context()
    offer = repo.get_offer(session, offer_id)
    if offer is None or not access.can_see_company(offer.company_id):
        raise NotFound("Service not found")
    ctx.require(BOOKINGS_MANAGE, company_id=offer.company_id, branch_id=branch_id)
    check_company(session, offer.company_id, branch_id)
    if wanted_to < wanted_from:
        raise ValidationFailed("The last day cannot be before the first day")
    name, phone, email = appointments._customer_details(session, offer.company_id, customer_id, client_name,
                                                        client_phone, client_email)
    if not name:
        raise ValidationFailed("Say who is waiting")
    if resource_id is not None:
        found = repo.get_resource(session, resource_id)
        if found is None or found.branch_id != branch_id:
            raise ValidationFailed("That resource is not in this branch")
    entry = WaitlistEntry(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=offer.company_id,
                          branch_id=branch_id, offer_id=offer.id, resource_id=resource_id, customer_id=customer_id,
                          client_name=name, client_phone=phone, client_email=email, wanted_from=wanted_from,
                          wanted_to=wanted_to, note=(note or "").strip() or None)
    repo.add(session, entry)
    audit_record(session, "join", "bookings.waitlist_entry", entry.id, {"name": name})
    return entry


def list_entries(session: Session, **filters: object) -> list[WaitlistEntry]:
    return repo.list_waitlist(session, access.view_scopes(), **filters)  # type: ignore[arg-type]


def remove(session: Session, entry_id: UUID) -> WaitlistEntry:
    """Take someone off the waitlist."""
    entry = _visible(session, entry_id, lock=True)
    current_context().require(BOOKINGS_MANAGE, company_id=entry.company_id, branch_id=entry.branch_id)
    if entry.status in ("booked", "removed"):
        raise ValidationFailed(f"That entry is already {entry.status}")
    entry.status = "removed"
    entry.updated_by, entry.updated_at = user_id(), now()
    session.flush()
    audit_record(session, "remove", "bookings.waitlist_entry", entry.id, {})
    return entry


def matches_for(session: Session, appointment: Appointment) -> list[WaitlistEntry]:
    """People waiting who could take the time a cancelled appointment freed, longest waiting first."""
    local_day = appointment.starts_at.astimezone(zone(session, appointment.company_id)).date()
    found = repo.waiting_for(session, appointment.branch_id, appointment.offer_id, local_day)
    resources = set(repo.appointment_resources(session, {appointment.id}).get(appointment.id, []))
    return [e for e in found if e.resource_id is None or e.resource_id in resources]


def offer_slot(session: Session, entry_id: UUID, *, starts_at: datetime,
               resource_id: UUID | None = None) -> WaitlistEntry:
    """Offer a free time to a waiting client and message them. The time must be free now. Needs 'bookings.manage'."""
    require_aware(starts_at)
    entry = _visible(session, entry_id, lock=True)
    current_context().require(BOOKINGS_MANAGE, company_id=entry.company_id, branch_id=entry.branch_id)
    if entry.status not in ("waiting", "offered"):
        raise ValidationFailed(f"That entry is {entry.status}")
    offer = repo.get_offer(session, entry.offer_id)
    assert offer is not None
    settings = repo.ensure_settings(session, entry.company_id)
    wanted = resource_id or entry.resource_id
    _, chosen = appointments._choose_resources(
        session, offer, settings, entry.branch_id, starts_at, [wanted] if wanted else None, for_client=False,
        allow_outside_hours=False, source="staff")
    entry.status, entry.offered_starts_at, entry.offered_resource_id = "offered", starts_at, chosen[0].id
    entry.offered_at = now()
    entry.updated_by, entry.updated_at = user_id(), now()
    session.flush()
    notify.offer_slot(session, entry, starts_at)
    audit_record(session, "offer", "bookings.waitlist_entry", entry.id, {"start": starts_at.isoformat()})
    return entry


def accept(session: Session, entry_id: UUID) -> tuple[WaitlistEntry, Appointment]:
    """The client took the offered time: book it. If someone else took it meanwhile, nothing changes and another time
    can be offered."""
    entry = _visible(session, entry_id, lock=True)
    current_context().require(BOOKINGS_MANAGE, company_id=entry.company_id, branch_id=entry.branch_id)
    if entry.status != "offered" or entry.offered_starts_at is None:
        raise ValidationFailed("Offer a time first")
    try:
        with session.begin_nested():
            appt = appointments.create_appointment(
                session, offer_id=entry.offer_id, starts_at=entry.offered_starts_at, branch_id=entry.branch_id,
                resource_ids=[entry.offered_resource_id] if entry.offered_resource_id else None,
                customer_id=entry.customer_id, client_name=entry.client_name, client_phone=entry.client_phone,
                client_email=entry.client_email, note=entry.note, source="waitlist")
    except (Conflict, ValidationFailed) as exc:
        raise Conflict(f"That time is no longer free, offer {entry.client_name} another one: {exc}") from None
    entry.status, entry.appointment_id = "booked", appt.id
    entry.updated_by, entry.updated_at = user_id(), now()
    session.flush()
    audit_record(session, "accept", "bookings.waitlist_entry", entry.id, {"appointment": appt.number})
    return entry, appt
