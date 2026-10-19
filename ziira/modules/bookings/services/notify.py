"""Messages to clients about their appointments: confirmation, reminder, cancellation, a freed slot on the waitlist.

Messages are only ever queued here (the worker sends them), through the business's own channels in the order the
notification layer ranks them (a chat channel, then SMS, then email), using the shipped templates in English and
Swahili. Someone who asked not to be contacted is skipped by the notification layer. Each kind is queued once per
appointment (`appointment_message`), and reminders wait out the business's quiet hours.
"""

from datetime import datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Appointment, WaitlistEntry
from ziira.modules.bookings.services.common import now, unit_enabled, zone
from ziira.sdk import Session, channel_names, configured_channels, format_day, send_templated

SW = "sw"


def when_text(session: Session, company_id: UUID, moment: datetime) -> str:
    """'20 Oct 2026 09:30' in the company's own time zone."""
    local = moment.astimezone(zone(session, company_id))
    return f"{format_day(local.date())} {local:%H:%M}"


def contact_of(session: Session, appt: Appointment | WaitlistEntry) -> tuple[str | None, str | None, str]:
    """(phone, email, name) to reach the client: what the booking holds, else what the customer record holds."""
    phone = getattr(appt, "client_phone", None)
    email = getattr(appt, "client_email", None)
    name = getattr(appt, "client_name", None) or ""
    if appt.customer_id is not None and (not phone and not email) and unit_enabled(session, "crm"):
        from ziira.modules.crm.public import find_customer

        found = find_customer(session, appt.customer_id)
        if found is not None:
            phone, email, name = found.phone, found.email, name or found.name
    return phone, email, name


def plan(session: Session, company_id: UUID, phone: str | None, email: str | None) -> list[dict[str, str]]:
    """The ways to reach the client, best first: [{"channel", "recipient"}]. Only channels the business has set up."""
    ready = configured_channels(session, company_id)
    out: list[dict[str, str]] = []
    for channel in channel_names(session):
        if channel not in ready:
            continue
        recipient = email if channel == "email" else phone
        if recipient:
            out.append({"channel": channel, "recipient": recipient})
    return out


def _variables(session: Session, appt: Appointment, name: str) -> dict[str, str]:
    business = session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(appt.company_id)}).scalar_one()
    service = repo.get_offer(session, appt.offer_id)
    settings = repo.ensure_settings(session, appt.company_id)
    return {"customer": name or "", "service": service.name if service else "",
            "business": settings.public_name or business,
            "when": when_text(session, appt.company_id, appt.starts_at)}


def queue(session: Session, appt: Appointment, kind: str, template: str) -> UUID | None:
    """Queue one message of `kind` ('confirmation', 'reminder', 'cancelled') for the appointment, once. Nothing is
    queued (and nothing recorded) when the client has no contact the business can reach, so a later run may try
    again."""
    phone, email, name = contact_of(session, appt)
    route = plan(session, appt.company_id, phone, email)
    if not route:
        return None
    marked = session.execute(text(
        "insert into bookings.appointment_message (tenant_id, appointment_id, kind) "
        "values (kernel.current_tenant(), :a, :k) on conflict (appointment_id, kind) do nothing returning id"),
        {"a": str(appt.id), "k": kind}).first()
    if marked is None:
        return None
    first, rest = route[0], route[1:]
    return send_templated(
        session, company_id=appt.company_id, channel=first["channel"], recipient=first["recipient"],
        template=template, variables=_variables(session, appt, name), fallbacks=rest, ref_type="bookings.appointment",
        ref_id=appt.id, dedupe_key=f"appt:{appt.id}:{kind}:{int(appt.starts_at.timestamp())}")


def forget(session: Session, appointment_id: UUID, *kinds: str) -> None:
    """Allow these messages to be queued again (the appointment moved)."""
    session.execute(text("delete from bookings.appointment_message where appointment_id = :a and kind = any(:k)"),
                    {"a": str(appointment_id), "k": list(kinds)})


def confirmation(session: Session, appt: Appointment) -> UUID | None:
    template = "appointment_confirmation" if appt.status != "requested" else "appointment_received"
    return queue(session, appt, "confirmation", template)


def cancelled(session: Session, appt: Appointment) -> UUID | None:
    return queue(session, appt, "cancelled", "appointment_cancelled")


def offer_slot(session: Session, entry: WaitlistEntry, starts_at: datetime) -> UUID | None:
    """Tell a waiting client a slot is free (not recorded per appointment: there is none yet)."""
    phone, email, name = contact_of(session, entry)
    route = plan(session, entry.company_id, phone, email)
    if not route:
        return None
    offer = repo.get_offer(session, entry.offer_id)
    business = session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(entry.company_id)}).scalar_one()
    return send_templated(
        session, company_id=entry.company_id, channel=route[0]["channel"], recipient=route[0]["recipient"],
        template="waitlist_offer", fallbacks=route[1:],
        variables={"customer": name, "service": offer.name if offer else "", "business": business,
                   "when": when_text(session, entry.company_id, starts_at)},
        ref_type="bookings.waitlist_entry", ref_id=entry.id,
        dedupe_key=f"waitlist:{entry.id}:{int(starts_at.timestamp())}")


def to_contact(session: Session, *, company_id: UUID, phone: str | None, email: str | None, template: str,
               variables: dict[str, str], ref_type: str, ref_id: UUID, dedupe_key: str) -> UUID | None:
    """Queue one shipped template for a person (an attendee, a waiting client). Nothing happens when the business has
    no channel that can reach them. The notification layer skips someone on the do-not-contact list."""
    route = plan(session, company_id, phone, email)
    if not route:
        return None
    return send_templated(session, company_id=company_id, channel=route[0]["channel"],
                          recipient=route[0]["recipient"], template=template, variables=variables,
                          fallbacks=route[1:], ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key)


def business_name(session: Session, company_id: UUID) -> str:
    """The name clients know the business by (public name, else the company name)."""
    settings = repo.ensure_settings(session, company_id)
    if settings.public_name:
        return settings.public_name
    return str(session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def in_quiet_hours(session: Session, company_id: UUID, moment: datetime, start: time, end: time) -> bool:
    """True when the company-local clock at `moment` is inside the quiet period (it may cross midnight)."""
    local = moment.astimezone(zone(session, company_id)).time().replace(tzinfo=None)
    if start == end:
        return False
    return start <= local or local < end if start > end else start <= local < end


def send_due_reminders(session: Session, *, at: datetime | None = None) -> int:
    """Queue the reminders that are due: confirmed appointments starting within the company's reminder lead time, once
    each, never inside quiet hours and never after the start. Returns how many were queued."""
    moment = at or now()
    queued = 0
    companies: list[Any] = list(session.execute(text(
        "select company_id, reminder_hours_before, quiet_start, quiet_end, reminder_template "
        "from bookings.booking_settings "
        "where reminders_enabled")))
    for c in companies:
        if in_quiet_hours(session, c.company_id, moment, c.quiet_start, c.quiet_end):
            continue
        horizon = moment + timedelta(hours=c.reminder_hours_before)
        for appt in repo.list_appointments(
                session, None, status=["confirmed"], start=moment, end=horizon, limit=500):
            if appt.company_id != c.company_id or appt.starts_at <= moment:
                continue
            if repo.message_sent(session, appt.id, "reminder"):
                continue
            if queue(session, appt, "reminder", c.reminder_template or "appointment_reminder") is not None:
                queued += 1
    return queued
