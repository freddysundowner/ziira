"""The public booking page: what a visitor sees and does without signing in.

A visitor reaches a company by its booking address (a slug). Nothing about other clients is ever returned: only the
services, the resources the business chose to show, and free start times (never who is booked or when a person's day is
busy). Booking checks the same rules as the front desk plus the client rules (notice, distance), needs the visitor's
consent and a way to reach them, and is safe to send twice.
"""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import BookingSettings
from ziira.modules.bookings.services import appointments, scheduling
from ziira.modules.bookings.services.common import now, unit_enabled, zone
from ziira.modules.bookings.services.settings import DEFAULT_CONSENT
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    idempotent,
    rate_limit,
    resolve_booking_slug,
    system_session,
)

CLOSED = "Online booking is not available here"


def _open(session: Session, tenant_company: tuple[UUID, UUID]) -> BookingSettings:
    if not unit_enabled(session, "bookings"):
        raise NotFound(CLOSED)
    settings = repo.ensure_settings(session, tenant_company[1])
    if not settings.online_enabled or not settings.slug:
        raise NotFound(CLOSED)
    return settings


def _resolve(slug: str) -> tuple[UUID, UUID]:
    found = resolve_booking_slug(slug)
    if found is None:
        raise NotFound(CLOSED)
    return found


def page(slug: str, ip: str | None) -> dict[str, Any]:
    """The business's booking page: its name, services and (if it chose to show them) resources."""
    rate_limit("book-page", slug, ip, per_subject=600, per_ip=300)
    found = _resolve(slug)
    with system_session(found[0]) as session:
        settings = _open(session, found)
        company = session.execute(text("select name, base_currency from kernel.company where id = :c"),
                                  {"c": str(found[1])}).one()
        offers = repo.list_offers(session, {found[1]}, company_id=found[1], active_only=True, public_only=True)
        links = repo.offer_resource_ids(session, {o.id for o in offers})
        live = {r.id: r for r in repo.list_resources(session, None, company_id=found[1], active_only=True,
                                                     public_only=True)}
        show = settings.show_resources_publicly
        services = [{"id": o.id, "name": o.name, "description": o.description, "duration_minutes": o.duration_minutes,
                     "price": str(o.price), "mode": o.resource_mode,
                     "resource_ids": [r for r in links.get(o.id, []) if r in live] if show else []}
                    for o in offers if links.get(o.id) and (o.resource_mode == "all"
                                                            or any(r in live for r in links[o.id]))]
        shown = [{"id": r.id, "name": r.name, "kind": r.kind} for r in live.values()] if show else []
        return {
            "business": settings.public_name or company.name, "note": settings.public_note,
            "currency": company.base_currency, "timezone": str(zone(session, found[1])),
            "consent_text": settings.consent_text or DEFAULT_CONSENT, "max_days_ahead": settings.max_days_ahead,
            "services": services, "resources": shown}


def slots(slug: str, service_id: UUID, day: date, resource_id: UUID | None, ip: str | None) -> list[dict[str, str]]:
    """Free start times for a service on a day, in the company's time zone. Nothing says who else is booked."""
    rate_limit("book-slots", slug, ip, per_subject=2000, per_ip=240)
    found = _resolve(slug)
    with system_session(found[0]) as session:
        settings = _open(session, found)
        offer = repo.get_offer(session, service_id)
        if offer is None or offer.company_id != found[1] or not offer.is_active or not offer.show_publicly \
                or offer.kind != "appointment":
            raise NotFound("That service is not on offer")
        zn = zone(session, found[1])
        today = now().astimezone(zn).date()
        if day < today or day > today + timedelta(days=settings.max_days_ahead):
            return []
        wanted = resource_id if settings.show_resources_publicly else None
        free = scheduling.free_slots(session, offer, settings, day, resource_id=wanted, for_client=True)
        return [{"start": s.start.astimezone(zn).isoformat(), "end": s.end.astimezone(zn).isoformat()} for s in free]


def book(slug: str, ip: str | None, key: str | None, *, service_id: UUID, start: datetime, name: str,
         phone: str | None, email: str | None, consent: bool, resource_id: UUID | None, note: str | None,
         honeypot: str | None) -> dict[str, Any]:
    """Make a booking request from the public page."""
    if honeypot and honeypot.strip():
        # a robot filled the hidden field: answer like a success, keep nothing
        return {"status": "received", "number": None, "starts_at": start.isoformat(), "service": ""}
    subject = (phone or email or "").strip().lower()
    rate_limit("book-create", subject or slug, ip, per_subject=5, per_ip=60)
    found = _resolve(slug)
    if not consent:
        raise ValidationFailed("Please agree to the terms so we can keep your booking details")
    if not (phone or "").strip() and not (email or "").strip():
        raise ValidationFailed("Give a phone number or an email so we can reach you")
    request = {"slug": slug, "service": str(service_id), "start": start.isoformat(), "name": name, "phone": phone,
               "email": email, "resource": str(resource_id) if resource_id else None}
    with system_session(found[0]) as session:
        settings = _open(session, found)

        def make() -> dict[str, Any]:
            offer = repo.get_offer(session, service_id)
            if offer is None or offer.company_id != found[1] or not offer.is_active or not offer.show_publicly \
                    or offer.kind != "appointment":
                raise NotFound("That service is not on offer")
            customer_id = None
            if unit_enabled(session, "crm"):
                from ziira.modules.crm.public import match_or_create_customer

                customer, _ = match_or_create_customer(session, found[1], name=name, phone=phone, email=email)
                customer_id = customer.id
            wanted = [resource_id] if resource_id and settings.show_resources_publicly else None
            try:
                appt = appointments.create_appointment(
                    session, offer_id=offer.id, starts_at=start, resource_ids=wanted, customer_id=customer_id,
                    client_name=name, client_phone=phone, client_email=email, note=(note or "")[:300],
                    source="online", for_client=True, consent_at=now())
            except Conflict:
                raise Conflict("Sorry, that time was just taken. Please pick another time.") from None
            audit_record(session, "online_booking", "bookings.appointment", appt.id, {"number": appt.number})
            return {"status": "confirmed" if appt.status == life.CONFIRMED else "requested", "number": appt.number,
                    "starts_at": appt.starts_at.astimezone(zone(session, found[1])).isoformat(),
                    "service": offer.name, "deposit_due": str(appt.deposit_amount) if appt.deposit_amount > 0 else None,
                    "deposit_note": repo.ensure_settings(session, found[1]).deposit_note if appt.deposit_amount > 0
                    else None}

        response, _ = idempotent(session, key, request, make)
        return dict(response)
