"""Turning rows into the shapes the Bookings API returns."""

from typing import Any
from uuid import UUID

from ziira.modules.bookings.api import schemas as sc
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import clients, invoicing
from ziira.sdk import Session


def appointments_out(session: Session, rows: list[Appointment], matches: dict[Any, int] | None = None, *,
                      with_warnings: bool = False) -> list[sc.AppointmentOut]:
    ids = {a.id for a in rows}
    res = repo.appointment_resources(session, ids)
    names = {o.id: o.name for o in repo.offers_by_ids(session, {a.offer_id for a in rows}).values()}
    counts = repo.attendee_counts(session, {a.id for a in rows if a.kind == "class"})
    return [sc.AppointmentOut(
        id=a.id, company_id=a.company_id, branch_id=a.branch_id, number=a.number, offer_id=a.offer_id,
        service=names.get(a.offer_id, ""), kind=a.kind, capacity=a.capacity, attendees=counts.get(a.id, 0),
        status=a.status, source=a.source, starts_at=a.starts_at, ends_at=a.ends_at, customer_id=a.customer_id,
        client_name=a.client_name, client_phone=a.client_phone, client_email=a.client_email, price=a.price,
        note=a.note, series_id=a.series_id, series_index=a.series_index, late_cancellation=a.late_cancellation,
        cancelled_at=a.cancelled_at, checked_in_at=a.checked_in_at, started_at=a.started_at,
        completed_at=a.completed_at, minutes_worked=a.minutes_worked, invoice_id=a.invoice_id,
        invoice_number=a.invoice_number, resource_ids=res.get(a.id, []),
        waitlist_matches=(matches or {}).get(a.id, 0), visit_id=a.visit_id, deposit_amount=a.deposit_amount,
        deposit_paid=a.deposit_paid, price_variant=a.price_variant, payer_customer_id=a.payer_customer_id,
        payer_member_no=a.payer_member_no, preauth_ref=a.preauth_ref, copay_amount=a.copay_amount,
        claim_id=a.claim_id, warnings=clients.warnings_for(session, a) if with_warnings else [])
        for a in rows]


def one_appointment(session: Session, appt: Appointment, matches: int = 0) -> sc.AppointmentOut:
    return appointments_out(session, [appt], {appt.id: matches}, with_warnings=True)[0]


def resources_out(session: Session, rows: list[Any]) -> list[sc.ResourceOut]:
    hours = repo.hours_of(session, {r.id for r in rows})
    return [sc.ResourceOut(
        id=r.id, company_id=r.company_id, branch_id=r.branch_id, name=r.name, kind=r.kind, user_id=r.user_id,
        colour=r.colour, note=r.note, show_publicly=r.show_publicly, sort_order=r.sort_order, is_active=r.is_active,
        level=r.level, is_template=r.is_template, hours=[sc.HoursOut.model_validate(h) for h in hours.get(r.id, [])])
            for r in rows]


def offers_out(session: Session, rows: list[Any]) -> list[sc.OfferOut]:
    links = repo.offer_resource_ids(session, {o.id for o in rows})
    variants: dict[UUID, list[Any]] = {}
    for v in raw.many(session, "select * from bookings.price_variant where offer_id = any(cast(:ids as uuid[])) "
                               "order by sort_order, label", ids=[str(o.id) for o in rows]):
        variants.setdefault(v["offer_id"], []).append(v)
    return [sc.OfferOut(
        id=o.id, company_id=o.company_id, product_id=o.product_id, name=o.name, description=o.description,
        kind=o.kind, duration_minutes=o.duration_minutes, buffer_before_minutes=o.buffer_before_minutes,
        buffer_after_minutes=o.buffer_after_minutes, price=o.price, resource_mode=o.resource_mode,
        capacity=o.capacity, show_publicly=o.show_publicly, is_active=o.is_active,
        resource_ids=links.get(o.id, []), processing_start_minutes=o.processing_start_minutes,
        processing_minutes=o.processing_minutes, deposit_amount=o.deposit_amount, deposit_percent=o.deposit_percent,
        recall_days=o.recall_days, needs_patch_test=o.needs_patch_test,
        group_late_cancel_hours=o.group_late_cancel_hours, price_is_example=o.price_is_example,
        variants=[sc.PriceVariantOut.model_validate(v) for v in variants.get(o.id, [])]) for o in rows]


def settings_out(session: Session, row: Any) -> sc.BookingSettingsOut:
    out = sc.BookingSettingsOut.model_validate(row)
    out.invoicing_available = invoicing.available(session)
    return out


