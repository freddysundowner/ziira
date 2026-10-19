"""HTTP endpoints of the Bookings module. Routes only convert HTTP to service calls.

`public_router` holds the booking page's endpoints (no sign-in): they find the business from its booking address and
reveal only services, shown resources and free times.
"""

from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import text

from ziira.modules.bookings.api import schemas as sc
from ziira.modules.bookings.api.deps import CHECKOUT, MANAGE, SETUP, VIEW
from ziira.modules.bookings.api.outputs import (
    appointments_out as _appointments_out,
)
from ziira.modules.bookings.api.outputs import offers_out as _offers_out
from ziira.modules.bookings.api.outputs import one_appointment as _one
from ziira.modules.bookings.api.outputs import resources_out as _resources_out
from ziira.modules.bookings.api.outputs import settings_out as _settings_out
from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.domain.availability import Hours
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.services import (
    access,
    appointments,
    invoicing,
    offers,
    public_booking,
    resources,
    scheduling,
    sessions,
    waitlist,
)
from ziira.modules.bookings.services import settings as settings_service
from ziira.modules.bookings.services.common import zone
from ziira.sdk import (
    DB_SESSION,
    NotFound,
    Session,
    ValidationFailed,
    client_ip,
    company_today,
    idempotency_key_header,
    page_limit,
    page_offset,
)

router = APIRouter()
public_router = APIRouter()
CREATED = status.HTTP_201_CREATED


# --------------------------------------------------------------------------- settings
@router.get("/settings", response_model=sc.BookingSettingsOut, dependencies=VIEW)
def get_settings(company_id: UUID, session: Session = DB_SESSION) -> object:
    return _settings_out(session, settings_service.get_settings(session, company_id))


@router.patch("/settings", response_model=sc.BookingSettingsOut, dependencies=SETUP)
def patch_settings(company_id: UUID, body: sc.BookingSettingsUpdate, session: Session = DB_SESSION) -> object:
    changes = body.model_dump(exclude_unset=True)
    slug = changes.pop("slug", None) if "slug" in changes else None
    return _settings_out(session, settings_service.update_settings(session, company_id, slug=slug, **changes))


# --------------------------------------------------------------------------- resources
@router.post("/resources", response_model=sc.ResourceOut, status_code=CREATED, dependencies=SETUP)
def post_resource(body: sc.ResourceIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump(exclude={"hours"})
    hours = [Hours(h.weekday, h.start_time, h.end_time) for h in body.hours] if body.hours else None
    made = resources.create_resource(session, hours=hours, **data)
    return _resources_out(session, [made])[0]


@router.get("/resources", response_model=list[sc.ResourceOut], dependencies=VIEW)
def get_resources(branch_id: UUID | None = None, active_only: bool = False, session: Session = DB_SESSION) -> object:
    return _resources_out(session, resources.list_resources(session, branch_id=branch_id, active_only=active_only))


@router.get("/resources/{resource_id}", response_model=sc.ResourceOut, dependencies=VIEW)
def get_resource(resource_id: UUID, session: Session = DB_SESSION) -> object:
    return _resources_out(session, [resources.get_resource(session, resource_id)])[0]


@router.patch("/resources/{resource_id}", response_model=sc.ResourceOut, dependencies=SETUP)
def patch_resource(resource_id: UUID, body: sc.ResourceUpdate, session: Session = DB_SESSION) -> object:
    changed = resources.update_resource(session, resource_id, **body.model_dump(exclude_unset=True))
    return _resources_out(session, [changed])[0]


@router.put("/resources/{resource_id}/hours", response_model=list[sc.HoursOut], dependencies=SETUP)
def put_hours(resource_id: UUID, body: list[sc.HoursIn], session: Session = DB_SESSION) -> object:
    return resources.set_hours(session, resource_id, [Hours(h.weekday, h.start_time, h.end_time) for h in body])


@router.get("/resources/{resource_id}/time-off", response_model=list[sc.TimeOffOut], dependencies=VIEW)
def get_time_off(resource_id: UUID, start: datetime | None = None, end: datetime | None = None,
                 session: Session = DB_SESSION) -> object:
    return resources.time_off(session, resource_id, start, end)


@router.post("/resources/{resource_id}/time-off", response_model=sc.TimeOffOut, status_code=CREATED,
             dependencies=SETUP)
def post_time_off(resource_id: UUID, body: sc.TimeOffIn, session: Session = DB_SESSION) -> object:
    row, affected = resources.add_time_off(session, resource_id, starts_at=body.starts_at, ends_at=body.ends_at,
                                           reason=body.reason)
    out = sc.TimeOffOut.model_validate(row)
    out.affected_appointments = affected
    return out


@router.delete("/time-off/{time_off_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=SETUP)
def delete_time_off(time_off_id: UUID, session: Session = DB_SESSION) -> None:
    resources.remove_time_off(session, time_off_id)


# --------------------------------------------------------------------------- service offers
@router.get("/service-items", response_model=list[sc.ServiceItemOut], dependencies=SETUP)
def get_service_items(company_id: UUID, search: str | None = Query(default=None, max_length=100),
                      session: Session = DB_SESSION) -> object:
    """Service items from Products that can be made bookable."""
    from ziira.modules.products.public import selling_prices, service_items

    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    found = service_items(session, company_id, search)
    prices = selling_prices(session, company_id, None, {p.id for p in found})
    return [sc.ServiceItemOut(id=p.id, sku=p.sku, name=p.name, price=prices.get(p.id)) for p in found]


@router.post("/offers", response_model=sc.OfferOut, status_code=CREATED, dependencies=SETUP)
def post_offer(body: sc.OfferIn, session: Session = DB_SESSION) -> object:
    return _offers_out(session, [offers.create_offer(session, **body.model_dump())])[0]


@router.get("/offers", response_model=list[sc.OfferOut], dependencies=VIEW)
def get_offers(company_id: UUID | None = None, active_only: bool = False, session: Session = DB_SESSION) -> object:
    return _offers_out(session, offers.list_offers(session, company_id=company_id, active_only=active_only))


@router.get("/offers/{offer_id}", response_model=sc.OfferOut, dependencies=VIEW)
def get_offer(offer_id: UUID, session: Session = DB_SESSION) -> object:
    return _offers_out(session, [offers.get_offer(session, offer_id)])[0]


@router.patch("/offers/{offer_id}", response_model=sc.OfferOut, dependencies=SETUP)
def patch_offer(offer_id: UUID, body: sc.OfferUpdate, session: Session = DB_SESSION) -> object:
    return _offers_out(session, [offers.update_offer(session, offer_id, **body.model_dump(exclude_unset=True))])[0]


# --------------------------------------------------------------------------- availability and calendar
@router.get("/availability", response_model=list[sc.SlotOut], dependencies=VIEW)
def get_availability(offer_id: UUID, day: date = Query(alias="date"), resource_id: UUID | None = None,
                     branch_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    """The free start times of a service on a day, as the front desk sees them (notice and distance are not applied)."""
    offer = offers.get_offer(session, offer_id)
    settings = repo.ensure_settings(session, offer.company_id)
    free = scheduling.free_slots(session, offer, settings, day, resource_id=resource_id, branch_id=branch_id,
                                 for_client=False)
    return [sc.SlotOut(start=s.start, end=s.end, resource_ids=list(s.resource_ids)) for s in free]


@router.get("/calendar", response_model=sc.CalendarOut, dependencies=VIEW)
def get_calendar(branch_id: UUID, start: datetime, end: datetime, include_cancelled: bool = False,
                 session: Session = DB_SESSION) -> object:
    """Everything one branch's calendar draws between two moments: its resources with hours, their time off and the
    appointments."""
    if end <= start or end - start > timedelta(days=42):
        raise ValidationFailed("Ask for at most six weeks, ending after it starts")
    rows = resources.list_resources(session, branch_id=branch_id, active_only=True)
    ids = {r.id for r in rows}
    off = repo.time_off_of(session, ids, start, end)
    wanted = None if include_cancelled else sorted(life.LIVE | {life.COMPLETED})
    found = appointments.list_appointments(session, branch_id=branch_id, status=wanted, start=start, end=end, limit=500)
    zn = str(zone(session, rows[0].company_id)) if rows else "UTC"
    return sc.CalendarOut(
        resources=_resources_out(session, rows),
        time_off=[sc.TimeOffOut.model_validate(t) for t in (x for v in off.values() for x in v)],
        appointments=_appointments_out(session, found), timezone=zn)


@router.get("/front-desk", response_model=sc.FrontDeskOut, dependencies=VIEW)
def get_front_desk(branch_id: UUID, session: Session = DB_SESSION) -> object:
    """Today's appointments at a branch (today where the company is), in the order they start."""
    company = session.execute(text("select company_id from kernel.branch where id = :b"),
                              {"b": str(branch_id)}).first()
    if company is None or not access.can_view(company.company_id, branch_id):
        raise NotFound("Branch not found")
    today = company_today(session, company.company_id)
    zn = zone(session, company.company_id)
    start = datetime.combine(today, datetime.min.time(), tzinfo=zn)
    found = appointments.list_appointments(session, branch_id=branch_id, start=start, end=start + timedelta(days=1),
                                           limit=500)
    return sc.FrontDeskOut(day=today, timezone=str(zn), appointments=_appointments_out(session, found))


# --------------------------------------------------------------------------- appointments
@router.post("/appointments", response_model=sc.AppointmentOut, status_code=CREATED, dependencies=MANAGE)
def post_appointment(body: sc.AppointmentIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    payer = {k: data.pop(k) for k in ("payer_customer_id", "payer_member_no", "preauth_ref", "copay_amount")}
    return _one(session, appointments.create_appointment(
        session, payer={k: v for k, v in payer.items() if v is not None} or None, **data))


@router.post("/appointments/walk-in", response_model=sc.AppointmentOut, status_code=CREATED, dependencies=MANAGE)
def post_walk_in(body: sc.WalkInIn, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.create_walk_in(session, **body.model_dump()))


@router.post("/appointments/series", response_model=sc.BookingSeriesOut, status_code=CREATED, dependencies=MANAGE)
def post_series(body: sc.SeriesIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    payer = {k: data.pop(k) for k in ("payer_customer_id", "payer_member_no", "preauth_ref", "copay_amount")}
    result = appointments.create_series(session, payer={k: v for k, v in payer.items() if v is not None} or None,
                                        **data)
    return sc.BookingSeriesOut(series_id=result["series_id"], created=_appointments_out(session, result["created"]),
                        conflicts=[sc.SeriesConflict(**c) for c in result["conflicts"]])


@router.get("/appointments", response_model=list[sc.AppointmentOut], dependencies=VIEW)
def get_appointments(branch_id: UUID | None = None, resource_id: UUID | None = None,
                     status_: list[str] | None = Query(default=None, alias="status"), start: datetime | None = None,
                     end: datetime | None = None, search: str | None = Query(default=None, max_length=100),
                     customer_id: UUID | None = None, offer_id: UUID | None = None, series_id: UUID | None = None,
                     newest_first: bool = False, limit: int = page_limit(50), offset: int = page_offset(),
                     session: Session = DB_SESSION) -> object:
    found = appointments.list_appointments(
        session, branch_id=branch_id, resource_id=resource_id, status=status_, start=start, end=end, search=search,
        customer_id=customer_id, offer_id=offer_id, series_id=series_id, order_desc=newest_first, limit=limit,
        offset=offset)
    return _appointments_out(session, found)


@router.get("/appointments/{appointment_id}", response_model=sc.AppointmentOut, dependencies=VIEW)
def get_appointment(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.get_appointment(session, appointment_id))


@router.post("/appointments/{appointment_id}/reschedule", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_reschedule(appointment_id: UUID, body: sc.RescheduleIn, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.reschedule(session, appointment_id, **body.model_dump()))


@router.post("/appointments/{appointment_id}/cancel", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_cancel(appointment_id: UUID, body: sc.BookingCancelIn, session: Session = DB_SESSION) -> object:
    appt = appointments.cancel(session, appointment_id, reason_code_id=body.reason_code_id, note=body.note)
    return _one(session, appt, len(waitlist.matches_for(session, appt)))


@router.get("/appointments/{appointment_id}/waitlist-matches", response_model=list[sc.WaitlistOut],
            dependencies=VIEW)
def get_waitlist_matches(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    """People waiting who could take the time this appointment held."""
    return waitlist.matches_for(session, appointments.get_appointment(session, appointment_id))


@router.post("/appointments/{appointment_id}/confirm", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_confirm(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.confirm(session, appointment_id))


@router.post("/appointments/{appointment_id}/check-in", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_check_in(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.check_in(session, appointment_id))


@router.post("/appointments/{appointment_id}/start", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_start(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.start_service(session, appointment_id))


@router.post("/appointments/{appointment_id}/finish", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_finish(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    return _one(session, appointments.finish_service(session, appointment_id))


@router.post("/appointments/{appointment_id}/no-show", response_model=sc.AppointmentOut, dependencies=MANAGE)
def post_no_show(appointment_id: UUID, body: sc.NoShowIn | None = None, session: Session = DB_SESSION) -> object:
    body = body or sc.NoShowIn()
    return _one(session, appointments.mark_no_show(session, appointment_id, reason_code_id=body.reason_code_id,
                                                   note=body.note))


@router.post("/appointments/{appointment_id}/invoice", response_model=sc.AppointmentOut, dependencies=CHECKOUT)
def post_invoice(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    """Invoice a finished appointment (once)."""
    return _one(session, invoicing.create_invoice(session, appointment_id))


@router.get("/appointments/{appointment_id}/attendees", response_model=list[sc.AttendeeOut], dependencies=VIEW)
def get_attendees(appointment_id: UUID, session: Session = DB_SESSION) -> object:
    return sessions.roster(session, appointment_id)


@router.post("/appointments/{appointment_id}/attendees", response_model=sc.AttendeeOut, status_code=CREATED,
             dependencies=MANAGE)
def post_attendee(appointment_id: UUID, body: sc.AttendeeIn, session: Session = DB_SESSION) -> object:
    done = sessions.book_attendee(session, appointment_id, join_waitlist=False, **body.model_dump())
    return done.attendee


@router.patch("/attendees/{attendee_id}", response_model=sc.AttendeeOut, dependencies=MANAGE)
def patch_attendee(attendee_id: UUID, body: sc.AttendeeUpdate, session: Session = DB_SESSION) -> object:
    if body.status == "cancelled":
        return sessions.cancel_attendee(session, attendee_id)
    return sessions.mark_attendee(session, attendee_id, body.status)


# --------------------------------------------------------------------------- waitlist
@router.post("/waitlist", response_model=sc.WaitlistOut, status_code=CREATED, dependencies=MANAGE)
def post_waitlist(body: sc.WaitlistIn, session: Session = DB_SESSION) -> object:
    return waitlist.join(session, **body.model_dump())


@router.get("/waitlist", response_model=list[sc.WaitlistOut], dependencies=VIEW)
def get_waitlist(branch_id: UUID | None = None, status_: list[str] | None = Query(default=None, alias="status"),
                 offer_id: UUID | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    return waitlist.list_entries(session, branch_id=branch_id, status=status_, offer_id=offer_id, limit=limit,
                                 offset=offset)


@router.post("/waitlist/{entry_id}/remove", response_model=sc.WaitlistOut, dependencies=MANAGE)
def post_waitlist_remove(entry_id: UUID, session: Session = DB_SESSION) -> object:
    return waitlist.remove(session, entry_id)


@router.post("/waitlist/{entry_id}/offer", response_model=sc.WaitlistOut, dependencies=MANAGE)
def post_waitlist_offer(entry_id: UUID, body: sc.WaitlistOfferIn, session: Session = DB_SESSION) -> object:
    return waitlist.offer_slot(session, entry_id, starts_at=body.starts_at, resource_id=body.resource_id)


@router.post("/waitlist/{entry_id}/accept", response_model=sc.WaitlistAcceptOut, dependencies=MANAGE)
def post_waitlist_accept(entry_id: UUID, session: Session = DB_SESSION) -> object:
    entry, appt = waitlist.accept(session, entry_id)
    return sc.WaitlistAcceptOut(entry=sc.WaitlistOut.model_validate(entry), appointment=_one(session, appt))


# =========================================================================== public booking page (no sign-in)
@public_router.get("/public/book/{slug}", response_model=sc.PublicPageOut, tags=["Bookings (public page)"])
def public_page(slug: str, request: Request) -> object:
    """The business's booking page: name, services, and the resources it chose to show."""
    return public_booking.page(slug, client_ip(request))


@public_router.get("/public/book/{slug}/slots", response_model=list[sc.PublicSlot], tags=["Bookings (public page)"])
def public_slots(slug: str, request: Request, service: UUID, day: date = Query(alias="date"),
                 resource: UUID | None = None) -> object:
    """Free start times for a service on a day. Nothing says who else is booked."""
    return public_booking.slots(slug, service, day, resource, client_ip(request))


@public_router.post("/public/book/{slug}/appointments", response_model=sc.PublicBookingOut, status_code=CREATED,
                    tags=["Bookings (public page)"])
def public_book(slug: str, body: sc.PublicBookingIn, request: Request,
                key: str | None = Depends(idempotency_key_header)) -> object:
    """Ask for an appointment. Needs the visitor's consent and a phone number or email. Send an Idempotency-Key so a
    retry does not book twice."""
    return public_booking.book(
        slug, client_ip(request), key, service_id=body.service_id, start=body.start, name=body.name, phone=body.phone,
        email=body.email, consent=body.consent, resource_id=body.resource_id, note=body.note, honeypot=body.website)


from ziira.modules.bookings.api import routes_wave2  # noqa: E402  (the newer endpoints share this router's prefix)

router.include_router(routes_wave2.router)
public_router.include_router(routes_wave2.public_router)
