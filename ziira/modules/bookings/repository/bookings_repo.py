"""Database access for the bookings schema. Row-level security scopes every query to the tenant."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, text, true
from sqlalchemy.orm import Session

from ziira.modules.bookings.repository.models import (
    Appointment,
    AppointmentAttendee,
    AppointmentMessage,
    BookingSettings,
    Resource,
    ResourceHours,
    ResourceTimeOff,
    ServiceOffer,
    ServiceOfferResource,
    WaitlistEntry,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None


def in_scope(scopes: Scopes, company_col: Any, branch_col: Any) -> ColumnElement[bool]:
    """Rows of the companies and branches the user may see (None means everywhere)."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(company_col == c, true() if b is None else branch_col == b) for c, b in scopes))


def add(session: Session, record: Any) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def _locked(query: Any) -> Any:
    return query.with_for_update().execution_options(populate_existing=True)


def like(search: str) -> str:
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --------------------------------------------------------------------------- settings
def ensure_settings(session: Session, company_id: UUID) -> BookingSettings:
    """The company's booking settings, made with the defaults on first use."""
    session.execute(text(
        "insert into bookings.booking_settings (tenant_id, company_id) values (kernel.current_tenant(), :c) "
        "on conflict (company_id) do nothing"), {"c": str(company_id)})
    found = session.scalar(select(BookingSettings).where(BookingSettings.company_id == company_id))
    assert found is not None
    return found


# --------------------------------------------------------------------------- resources
def get_resource(session: Session, resource_id: UUID, *, lock: bool = False) -> Resource | None:
    if lock:
        return session.scalars(_locked(select(Resource).where(Resource.id == resource_id))).first()
    return session.get(Resource, resource_id)


def resources_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Resource]:
    if not ids:
        return {}
    return {r.id: r for r in session.scalars(select(Resource).where(Resource.id.in_(ids)))}


def list_resources(session: Session, scopes: Scopes, *, branch_id: UUID | None = None, company_id: UUID | None = None,
                   active_only: bool = False, public_only: bool = False) -> list[Resource]:
    query = select(Resource).where(in_scope(scopes, Resource.company_id, Resource.branch_id)).order_by(
        Resource.sort_order, Resource.name, Resource.id)
    if branch_id:
        query = query.where(Resource.branch_id == branch_id)
    if company_id:
        query = query.where(Resource.company_id == company_id)
    if active_only:
        query = query.where(Resource.is_active)
    if public_only:
        query = query.where(Resource.show_publicly)
    return list(session.scalars(query))


def hours_of(session: Session, resource_ids: set[UUID]) -> dict[UUID, list[ResourceHours]]:
    found: dict[UUID, list[ResourceHours]] = {}
    if resource_ids:
        for h in session.scalars(select(ResourceHours).where(ResourceHours.resource_id.in_(resource_ids))
                                 .order_by(ResourceHours.weekday, ResourceHours.start_time)):
            found.setdefault(h.resource_id, []).append(h)
    return found


def time_off_of(session: Session, resource_ids: set[UUID], start: datetime | None = None,
                end: datetime | None = None) -> dict[UUID, list[ResourceTimeOff]]:
    found: dict[UUID, list[ResourceTimeOff]] = {}
    if not resource_ids:
        return found
    query = select(ResourceTimeOff).where(ResourceTimeOff.resource_id.in_(resource_ids)).order_by(
        ResourceTimeOff.starts_at)
    if start is not None:
        query = query.where(ResourceTimeOff.ends_at > start)
    if end is not None:
        query = query.where(ResourceTimeOff.starts_at < end)
    for t in session.scalars(query):
        found.setdefault(t.resource_id, []).append(t)
    return found


def get_time_off(session: Session, time_off_id: UUID) -> ResourceTimeOff | None:
    return session.get(ResourceTimeOff, time_off_id)


def booked_ranges(session: Session, resource_ids: set[UUID], start: datetime, end: datetime,
                  exclude_appointment: UUID | None = None) -> dict[UUID, list[tuple[datetime, datetime]]]:
    """The blocked ranges of live appointments that touch [start, end), per resource."""
    found: dict[UUID, list[tuple[datetime, datetime]]] = {}
    if not resource_ids:
        return found
    rows = session.execute(text(
        "select resource_id, lower(blocked) as lo, upper(blocked) as hi from bookings.appointment_resource "
        "where holds and resource_id = any(cast(:ids as uuid[])) and blocked && tstzrange(:a, :b, '[)') "
        "and (cast(:x as uuid) is null or appointment_id <> cast(:x as uuid))"),
        {"ids": [str(i) for i in resource_ids], "a": start, "b": end,
         "x": str(exclude_appointment) if exclude_appointment else None})
    for r in rows:
        found.setdefault(r.resource_id, []).append((r.lo, r.hi))
    return found


def appointments_on_resource(session: Session, resource_id: UUID, start: datetime, end: datetime) -> int:
    """How many live appointments hold the resource at some point in [start, end)."""
    return int(session.execute(text(
        "select count(*) from bookings.appointment_resource where holds and resource_id = :r "
        "and blocked && tstzrange(:a, :b, '[)')"), {"r": str(resource_id), "a": start, "b": end}).scalar_one())


# --------------------------------------------------------------------------- offers
def get_offer(session: Session, offer_id: UUID, *, lock: bool = False) -> ServiceOffer | None:
    if lock:
        return session.scalars(_locked(select(ServiceOffer).where(ServiceOffer.id == offer_id))).first()
    return session.get(ServiceOffer, offer_id)


def offers_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, ServiceOffer]:
    if not ids:
        return {}
    return {o.id: o for o in session.scalars(select(ServiceOffer).where(ServiceOffer.id.in_(ids)))}


def list_offers(session: Session, company_ids: set[UUID] | None, *, company_id: UUID | None = None,
                active_only: bool = False, public_only: bool = False) -> list[ServiceOffer]:
    query = select(ServiceOffer).order_by(ServiceOffer.name, ServiceOffer.id)
    if company_ids is not None:
        query = query.where(ServiceOffer.company_id.in_(company_ids))
    if company_id:
        query = query.where(ServiceOffer.company_id == company_id)
    if active_only:
        query = query.where(ServiceOffer.is_active)
    if public_only:
        query = query.where(ServiceOffer.show_publicly, ServiceOffer.kind == "appointment")
    return list(session.scalars(query))


def offer_resource_ids(session: Session, offer_ids: set[UUID]) -> dict[UUID, list[UUID]]:
    found: dict[UUID, list[UUID]] = {}
    if offer_ids:
        for row in session.scalars(select(ServiceOfferResource).where(ServiceOfferResource.offer_id.in_(offer_ids))
                                   .order_by(ServiceOfferResource.created_at, ServiceOfferResource.id)):
            found.setdefault(row.offer_id, []).append(row.resource_id)
    return found


def offer_product_taken(session: Session, company_id: UUID, product_id: UUID, except_offer: UUID | None) -> bool:
    query = select(func.count()).select_from(ServiceOffer).where(
        ServiceOffer.company_id == company_id, ServiceOffer.product_id == product_id, ServiceOffer.is_active)
    if except_offer:
        query = query.where(ServiceOffer.id != except_offer)
    return bool(session.scalar(query))


# --------------------------------------------------------------------------- appointments
def get_appointment(session: Session, appointment_id: UUID, *, lock: bool = False) -> Appointment | None:
    if lock:
        return session.scalars(_locked(select(Appointment).where(Appointment.id == appointment_id))).first()
    return session.get(Appointment, appointment_id)


def by_local_id(session: Session, company_id: UUID, local_id: str) -> Appointment | None:
    return session.scalar(select(Appointment).where(Appointment.company_id == company_id,
                                                    Appointment.local_id == local_id))


def appointment_resources(session: Session, appointment_ids: set[UUID]) -> dict[UUID, list[UUID]]:
    found: dict[UUID, list[UUID]] = {}
    if appointment_ids:
        for r in session.execute(text(
                "select appointment_id, resource_id from bookings.appointment_resource "
                "where appointment_id = any(cast(:ids as uuid[])) order by created_at, part, id"),
                {"ids": [str(i) for i in appointment_ids]}):
            if r.resource_id not in found.setdefault(r.appointment_id, []):
                found[r.appointment_id].append(r.resource_id)
    return found


def list_appointments(session: Session, scopes: Scopes, *, branch_id: UUID | None = None,
                      resource_id: UUID | None = None, status: list[str] | None = None,
                      start: datetime | None = None, end: datetime | None = None, search: str | None = None,
                      customer_id: UUID | None = None, offer_id: UUID | None = None, series_id: UUID | None = None,
                      kind: str | None = None, visit_id: UUID | None = None, order_desc: bool = False, limit: int = 100,
                      offset: int = 0) -> list[Appointment]:
    query = select(Appointment).where(in_scope(scopes, Appointment.company_id, Appointment.branch_id))
    if branch_id:
        query = query.where(Appointment.branch_id == branch_id)
    if resource_id:
        query = query.where(Appointment.id.in_(text(
            "select appointment_id from bookings.appointment_resource where resource_id = :rid")).params(
            rid=str(resource_id)))
    if status:
        query = query.where(Appointment.status.in_(status))
    if start is not None:
        query = query.where(Appointment.ends_at > start)
    if end is not None:
        query = query.where(Appointment.starts_at < end)
    if customer_id:
        query = query.where(Appointment.customer_id == customer_id)
    if offer_id:
        query = query.where(Appointment.offer_id == offer_id)
    if series_id:
        query = query.where(Appointment.series_id == series_id)
    if kind:
        query = query.where(Appointment.kind == kind)
    if visit_id:
        query = query.where(Appointment.visit_id == visit_id)
    if search:
        pattern = like(search.strip())
        query = query.where(or_(Appointment.client_name.ilike(pattern, escape="\\"),
                                Appointment.number.ilike(pattern, escape="\\"),
                                Appointment.client_phone.ilike(pattern, escape="\\")))
    order = (Appointment.starts_at.desc(), Appointment.id) if order_desc else (Appointment.starts_at, Appointment.id)
    return list(session.scalars(query.order_by(*order).limit(limit).offset(offset)))


def attendees_of(session: Session, appointment_id: UUID) -> list[AppointmentAttendee]:
    return list(session.scalars(select(AppointmentAttendee).where(AppointmentAttendee.appointment_id == appointment_id)
                                .order_by(AppointmentAttendee.created_at, AppointmentAttendee.id)))


def attendee_counts(session: Session, appointment_ids: set[UUID]) -> dict[UUID, int]:
    if not appointment_ids:
        return {}
    rows = session.execute(
        select(AppointmentAttendee.appointment_id, func.count()).where(
            AppointmentAttendee.appointment_id.in_(appointment_ids), AppointmentAttendee.status != "cancelled")
        .group_by(AppointmentAttendee.appointment_id))
    return {r[0]: int(r[1]) for r in rows}


def get_attendee(session: Session, attendee_id: UUID) -> AppointmentAttendee | None:
    return session.get(AppointmentAttendee, attendee_id)


def message_sent(session: Session, appointment_id: UUID, kind: str) -> bool:
    return bool(session.scalar(select(func.count()).select_from(AppointmentMessage).where(
        AppointmentMessage.appointment_id == appointment_id, AppointmentMessage.kind == kind)))


# --------------------------------------------------------------------------- waitlist
def get_waitlist(session: Session, entry_id: UUID, *, lock: bool = False) -> WaitlistEntry | None:
    if lock:
        return session.scalars(_locked(select(WaitlistEntry).where(WaitlistEntry.id == entry_id))).first()
    return session.get(WaitlistEntry, entry_id)


def list_waitlist(session: Session, scopes: Scopes, *, branch_id: UUID | None = None,
                  status: list[str] | None = None, offer_id: UUID | None = None, limit: int = 100,
                  offset: int = 0) -> list[WaitlistEntry]:
    query = select(WaitlistEntry).where(in_scope(scopes, WaitlistEntry.company_id, WaitlistEntry.branch_id))
    if branch_id:
        query = query.where(WaitlistEntry.branch_id == branch_id)
    if status:
        query = query.where(WaitlistEntry.status.in_(status))
    if offer_id:
        query = query.where(WaitlistEntry.offer_id == offer_id)
    return list(session.scalars(query.order_by(WaitlistEntry.created_at, WaitlistEntry.id).limit(limit).offset(offset)))


def waiting_for(session: Session, branch_id: UUID, offer_id: UUID, day: date) -> list[WaitlistEntry]:
    """People waiting for this service at the branch whose wanted dates include `day`, longest waiting first."""
    return list(session.scalars(select(WaitlistEntry).where(
        WaitlistEntry.branch_id == branch_id, WaitlistEntry.offer_id == offer_id, WaitlistEntry.status == "waiting",
        WaitlistEntry.wanted_from <= day, WaitlistEntry.wanted_to >= day)
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id)))
