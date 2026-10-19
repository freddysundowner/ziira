"""Use cases: booking, moving, cancelling and serving appointments.

An appointment holds each of its resources from `start - buffer_before` to `end + buffer_after`. The database has the
last word on double booking (an exclusion constraint per resource), so two people booking the same time at once cannot
both succeed: the loser gets a clear "already taken" answer and the attempt is noted for Intelligence.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ziira.modules.bookings.domain import availability as av
from ziira.modules.bookings.domain import checkout as money_rules
from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.domain import rules
from ziira.modules.bookings.domain.recurrence import occurrence_dates
from ziira.modules.bookings.permissions import BOOKINGS_MANAGE
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import (
    Appointment,
    AppointmentAttendee,
    BookingRefusal,
    BookingSettings,
    Resource,
    ServiceOffer,
)
from ziira.modules.bookings.services import access, fees, notify, pricing, scheduling
from ziira.modules.bookings.services.common import now, require_aware, unit_enabled, user_id, zone
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    check_reason,
    current_context,
    next_document_number,
    publish,
    tenant_transaction,
)

SOURCES = ("staff", "online", "walk_in", "waitlist", "recurring")


# --------------------------------------------------------------------------- reading
def _visible(session: Session, appointment_id: UUID, *, lock: bool = False) -> Appointment:
    appt = repo.get_appointment(session, appointment_id, lock=lock)
    if appt is None or not access.can_view(appt.company_id, appt.branch_id):
        raise NotFound("Appointment not found")
    return appt


def get_appointment(session: Session, appointment_id: UUID) -> Appointment:
    return _visible(session, appointment_id)


def _manage(appt: Appointment) -> None:
    current_context().require(BOOKINGS_MANAGE, company_id=appt.company_id, branch_id=appt.branch_id)


def list_appointments(session: Session, **filters: Any) -> list[Appointment]:
    filters["limit"] = min(int(filters.get("limit") or 100), 500)
    return repo.list_appointments(session, access.view_scopes(), **filters)


def resources_of(session: Session, appointment_ids: set[UUID]) -> dict[UUID, list[UUID]]:
    return repo.appointment_resources(session, appointment_ids)


# --------------------------------------------------------------------------- making
def _refuse(company_id: UUID, branch_id: UUID | None, resource_id: UUID | None, start: datetime, source: str) -> None:
    """Note a refused booking (in its own transaction, because the request that refused it will roll back)."""
    ctx = current_context()
    try:
        with tenant_transaction(ctx.tenant_id) as other:
            repo.add(other, BookingRefusal(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                           branch_id=branch_id, resource_id=resource_id, attempted_start=start,
                                           source=source))
    except Exception:       # noqa: BLE001 - keeping the note is best effort, the refusal itself must still be reported
        pass


def _customer_details(session: Session, company_id: UUID, customer_id: UUID | None, name: str | None,
                      phone: str | None, email: str | None) -> tuple[str | None, str | None, str | None]:
    if customer_id is not None:
        if not unit_enabled(session, "crm"):
            raise ValidationFailed("Customers are not switched on for this business")
        from ziira.modules.crm.public import find_customer

        found = find_customer(session, customer_id)
        if found is None or found.company_id != company_id:
            raise ValidationFailed("The customer was not found in this company")
        name = name or found.name
        phone = phone or found.phone
        email = email or found.email
    return (rules.check_name(name, "The client's name") if name else None,
            (phone or "").strip() or None, rules.check_email(email))


def _choose_resources(session: Session, offer: ServiceOffer, settings: BookingSettings, branch_id: UUID | None,
                      start: datetime, requested: list[UUID] | None, *, for_client: bool, allow_outside_hours: bool,
                      source: str, exclude: UUID | None = None) -> tuple[UUID, list[Resource]]:
    """The branch and the resources that will serve the booking, or an explanation why none can."""
    if requested:
        known = repo.resources_by_ids(session, set(requested))
        if len(known) != len(set(requested)):
            raise ValidationFailed("A resource was not found")
        branch_id = branch_id or next(iter(known.values())).branch_id
    linked = scheduling.usable_resources(session, offer, None, branch_id)
    if branch_id is None:
        branches = {r.branch_id for r in linked}
        if len(branches) != 1:
            raise ValidationFailed("Choose the branch" if branches else "No one is set up to do this service")
        branch_id = next(iter(branches))
        linked = [r for r in linked if r.branch_id == branch_id]
    if not linked:
        raise ValidationFailed("No one is set up to do this service at this branch")
    if not for_client:
        current_context().require(BOOKINGS_MANAGE, company_id=offer.company_id, branch_id=branch_id)
    if offer.resource_mode == "all":
        every = repo.offer_resource_ids(session, {offer.id}).get(offer.id, [])
        if len(linked) != len(every):
            raise ValidationFailed("Everyone this service needs must be active and in the same branch")
        candidates = [linked]
    else:
        pool = [r for r in linked if not requested or r.id in requested]
        if not pool:
            raise ValidationFailed("That resource does not do this service")
        candidates = [[r] for r in pool]
    last: list[str] = []
    for group in candidates:
        last = scheduling.check_fits(session, offer, settings, start, [r.id for r in group], for_client=for_client,
                                     exclude_appointment=exclude, allow_outside_hours=allow_outside_hours)
        if not last:
            return branch_id, group
    if av.CONFLICT in last:
        _refuse(offer.company_id, branch_id, candidates[0][0].id, start, source)
        raise Conflict(scheduling.explain(last))
    raise ValidationFailed(scheduling.explain(last))


def _hold(session: Session, appt: Appointment, offer: ServiceOffer, resources: list[Resource]) -> None:
    """Insert the resource rows (one per stretch when the service has processing time). The exclusion constraint
    refuses a time already held."""
    for part, held in enumerate(av.blocked_intervals(appt.starts_at, scheduling.shape_of(offer))):
        for r in resources:
            session.execute(text(
                "insert into bookings.appointment_resource (tenant_id, created_by, appointment_id, resource_id, "
                "blocked, part) values (kernel.current_tenant(), :u, :a, :r, tstzrange(:s, :e, '[)'), :p)"),
                {"u": str(user_id()) if user_id() else None, "a": str(appt.id), "r": str(r.id), "s": held.start,
                 "e": held.end, "p": part})


def _insert(session: Session, offer: ServiceOffer, settings: BookingSettings, branch_id: UUID,
            resources: list[Resource], start: datetime, *, source: str, status: str, customer_id: UUID | None,
            name: str | None, phone: str | None, email: str | None, note: str | None, local_id: str | None,
            series_id: UUID | None = None, series_index: int | None = None,
            consent_at: datetime | None = None, price: Decimal | None = None, variant: str | None = None,
            visit_id: UUID | None = None, payer: dict[str, Any] | None = None) -> Appointment:
    ctx = current_context()
    payer = payer or {}
    end = start + timedelta(minutes=offer.duration_minutes)
    try:
        with session.begin_nested():
            appt = Appointment(
                tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=offer.company_id, branch_id=branch_id,
                number=next_document_number(session, company_id=offer.company_id, branch_id=branch_id,
                                            doc_type="appointment", prefix="APT"),
                offer_id=offer.id, kind=offer.kind, capacity=offer.capacity if offer.kind == "class" else 1,
                status=status, source=source, starts_at=start, ends_at=end, customer_id=customer_id,
                client_name=name, client_phone=phone, client_email=email,
                price=offer.price if price is None else price, price_variant=variant,
                deposit_amount=money_rules.deposit_due(offer.price if price is None else price,
                                                       offer.deposit_amount, offer.deposit_percent),
                note=(note or "").strip() or None, series_id=series_id, series_index=series_index,
                local_id=local_id, consent_given_at=consent_at, visit_id=visit_id,
                payer_customer_id=payer.get("payer_customer_id"), payer_member_no=payer.get("payer_member_no"),
                preauth_ref=payer.get("preauth_ref"), copay_amount=payer.get("copay_amount"),
                checked_in_at=now() if status == life.CHECKED_IN else None)
            repo.add(session, appt)
            _hold(session, appt, offer, resources)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23P01":
            _refuse(offer.company_id, branch_id, resources[0].id, start, source)
            raise Conflict("That time is already taken") from None
        raise
    return appt


def create_appointment(session: Session, *, offer_id: UUID, starts_at: datetime, branch_id: UUID | None = None,
                       resource_ids: list[UUID] | None = None, customer_id: UUID | None = None,
                       client_name: str | None = None, client_phone: str | None = None,
                       client_email: str | None = None, note: str | None = None, source: str = "staff",
                       local_id: str | None = None, allow_outside_hours: bool = False,
                       status: str | None = None, series_id: UUID | None = None, series_index: int | None = None,
                       consent_at: datetime | None = None, for_client: bool = False,
                       notify_client: bool = True, price_variant: str | None = None, visit_id: UUID | None = None,
                       payer: dict[str, Any] | None = None) -> Appointment:
    """Book a service. `resource_ids` picks who; left out, the first free resource that does the service takes it.
    Staff (needs 'bookings.manage' at the branch) may book at short notice and, with `allow_outside_hours`, outside
    working hours; a time that is already taken is always refused. A repeated `local_id` returns the first booking."""
    require_aware(starts_at)
    if source not in SOURCES:
        raise ValidationFailed(f"Source must be one of: {', '.join(SOURCES)}")
    offer = repo.get_offer(session, offer_id)
    if offer is None or not access.can_see_company(offer.company_id):
        raise NotFound("Service not found")
    if not offer.is_active:
        raise ValidationFailed(f"{offer.name} is not offered any more")
    check_company(session, offer.company_id)
    settings = repo.ensure_settings(session, offer.company_id)
    if local_id:
        again = repo.by_local_id(session, offer.company_id, local_id)
        if again is not None:
            return again
    branch_id, resources = _choose_resources(
        session, offer, settings, branch_id, starts_at, resource_ids, for_client=for_client,
        allow_outside_hours=allow_outside_hours, source=source)
    name, phone, email = _customer_details(session, offer.company_id, customer_id, client_name, client_phone,
                                           client_email)
    if offer.kind == "appointment" and not (name or customer_id):
        raise ValidationFailed("Say who the appointment is for")
    price, variant = pricing.price_for(session, offer, resources, price_variant)
    if status is None:
        deposit_first = source == "online" and money_rules.deposit_due(price, offer.deposit_amount,
                                                                       offer.deposit_percent) > 0
        status = (life.CHECKED_IN if source == "walk_in"
                  else life.CONFIRMED if source != "online" or (settings.auto_confirm and not deposit_first)
                  else life.REQUESTED)
    appt = _insert(session, offer, settings, branch_id, resources, starts_at, source=source, status=status,
                   customer_id=customer_id, name=name, phone=phone, email=email, note=note,
                   local_id=local_id, series_id=series_id, series_index=series_index, consent_at=consent_at,
                   price=price, variant=variant, visit_id=visit_id, payer=payer)
    audit_record(session, "create", "bookings.appointment", appt.id,
                 {"number": appt.number, "start": starts_at.isoformat(), "source": source})
    publish(session, Event("appointment.created", "bookings.appointment", appt.id, _payload(appt, resources)))
    if appt.status == life.CONFIRMED:
        publish(session, Event("appointment.confirmed", "bookings.appointment", appt.id, _payload(appt, resources)))
    if notify_client and source != "walk_in":
        notify.confirmation(session, appt)
    return appt


def _payload(appt: Appointment, resources: list[Resource] | list[UUID]) -> dict[str, Any]:
    ids = [r.id if isinstance(r, Resource) else r for r in resources]
    return {"company_id": appt.company_id, "branch_id": appt.branch_id, "appointment_id": appt.id,
            "number": appt.number, "offer_id": appt.offer_id, "customer_id": appt.customer_id,
            "resource_ids": ids, "status": appt.status, "starts_at": appt.starts_at.isoformat(),
            "source": appt.source}


def create_walk_in(session: Session, *, offer_id: UUID, branch_id: UUID | None = None,
                   resource_ids: list[UUID] | None = None, customer_id: UUID | None = None,
                   client_name: str | None = None, client_phone: str | None = None, note: str | None = None,
                   local_id: str | None = None) -> Appointment:
    """A client who walked in: a booking that starts now (to the minute) and is already checked in. Working hours may be
    ignored (the person is here), but a resource already busy is not."""
    moment = now().replace(second=0, microsecond=0)
    return create_appointment(session, offer_id=offer_id, starts_at=moment, branch_id=branch_id,
                              resource_ids=resource_ids, customer_id=customer_id, client_name=client_name or "Walk-in",
                              client_phone=client_phone, note=note, source="walk_in", local_id=local_id,
                              allow_outside_hours=True)


def create_series(session: Session, *, offer_id: UUID, starts_at: datetime, frequency: str, count: int | None = None,
                  until: Any = None, **booking: Any) -> dict[str, Any]:
    """Book the same service on a repeating pattern. Each occurrence is a real appointment at the same local time of
    day. An occurrence that does not fit is skipped and reported, with the reason; the rest are booked."""
    require_aware(starts_at)
    offer = repo.get_offer(session, offer_id)
    if offer is None or not access.can_see_company(offer.company_id):
        raise NotFound("Service not found")
    zn = zone(session, offer.company_id)
    first_local = starts_at.astimezone(zn)
    days = occurrence_dates(first_local.date(), frequency, count=count, until=until)
    series_id = uuid4()
    created: list[Appointment] = []
    conflicts: list[dict[str, Any]] = []
    for index, day in enumerate(days):
        moment = datetime.combine(day, first_local.time(), tzinfo=zn)
        try:
            with session.begin_nested():
                created.append(create_appointment(
                    session, offer_id=offer_id, starts_at=moment, series_id=series_id, series_index=index,
                    source="recurring" if booking.get("source") in (None, "staff") else booking["source"],
                    **{k: v for k, v in booking.items() if k not in ("source", "local_id")}))
        except (Conflict, ValidationFailed) as exc:
            conflicts.append({"index": index, "starts_at": moment, "problem": str(exc)})
    if not created and conflicts:
        raise Conflict("None of the times fit: " + conflicts[0]["problem"])
    return {"series_id": series_id, "created": created, "conflicts": conflicts}


# --------------------------------------------------------------------------- changing
def reschedule(session: Session, appointment_id: UUID, *, starts_at: datetime, resource_ids: list[UUID] | None = None,
               reason_code_id: UUID | None = None, note: str | None = None,
               allow_outside_hours: bool = False) -> Appointment:
    """Move an appointment that has not started to another time (and, if asked, other resources). Needs a reason from
    the 'appointment_reschedule' list. The client is told again and a new reminder is due."""
    require_aware(starts_at)
    appt = _visible(session, appointment_id, lock=True)
    _manage(appt)
    if appt.status not in life.MOVABLE:
        raise ValidationFailed(f"An appointment that is {appt.status.replace('_', ' ')} cannot be moved")
    check_reason(session, "appointment_reschedule", reason_code_id, note)
    offer = repo.get_offer(session, appt.offer_id)
    assert offer is not None
    settings = repo.ensure_settings(session, appt.company_id)
    previous = repo.appointment_resources(session, {appt.id}).get(appt.id, [])
    wanted = resource_ids or (previous if offer.resource_mode == "all" else previous[:1])
    _, resources = _choose_resources(session, offer, settings, appt.branch_id, starts_at, wanted, for_client=False,
                                     allow_outside_hours=allow_outside_hours, source="staff", exclude=appt.id)
    before = appt.starts_at
    try:
        with session.begin_nested():
            session.execute(text("delete from bookings.appointment_resource where appointment_id = :a"),
                            {"a": str(appt.id)})
            appt.starts_at, appt.ends_at = starts_at, starts_at + timedelta(minutes=offer.duration_minutes)
            session.flush()
            _hold(session, appt, offer, resources)
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23P01":
            _refuse(appt.company_id, appt.branch_id, resources[0].id, starts_at, "staff")
            raise Conflict("That time is already taken") from None
        raise
    appt.updated_by, appt.updated_at = user_id(), now()
    session.flush()
    audit_record(session, "reschedule", "bookings.appointment", appt.id,
                 {"from": before.isoformat(), "to": starts_at.isoformat(), "reason": note or ""})
    publish(session, Event("appointment.rescheduled", "bookings.appointment", appt.id,
                           {**_payload(appt, resources), "previous_starts_at": before.isoformat()}))
    notify.forget(session, appt.id, "confirmation", "reminder")
    notify.confirmation(session, appt)
    return appt


def _client_reason(session: Session, reason_code_id: UUID | None, by_client: bool) -> bool:
    """True when the client cancelled (a fee may apply); a cancellation by the business never carries a fee."""
    if by_client:
        return True
    if reason_code_id is None:
        return False
    found = session.execute(text("select code from kernel.reason_code where id = :i"),
                            {"i": str(reason_code_id)}).first()
    return bool(found and found.code == "CLIENT")


def _release(session: Session, appt: Appointment) -> None:
    session.execute(text("update bookings.appointment_resource set holds = false, updated_at = now() "
                         "where appointment_id = :a"), {"a": str(appt.id)})


def cancel(session: Session, appointment_id: UUID, *, reason_code_id: UUID | None, note: str | None = None,
           by_client: bool = False) -> Appointment:
    """Cancel an appointment that has not been served. A reason from the 'appointment_cancel' list is required. A
    cancellation inside the company's cancellation window is marked late. The resource is freed and the client told."""
    appt = _visible(session, appointment_id, lock=True)
    _manage(appt)
    life.check_move(appt.status, life.CANCELLED)
    check_reason(session, "appointment_cancel", reason_code_id, note)
    settings = repo.ensure_settings(session, appt.company_id)
    moment = now()
    appt.status = life.CANCELLED
    appt.cancel_reason_id, appt.cancel_note = reason_code_id, (note or "").strip() or None
    appt.cancelled_at, appt.cancelled_by = moment, user_id()
    appt.late_cancellation = life.is_late_cancellation(appt.starts_at, moment, settings.cancel_window_hours)
    appt.updated_by, appt.updated_at = user_id(), moment
    _release(session, appt)
    session.execute(text("update bookings.appointment_attendee set status = 'cancelled' where appointment_id = :a"),
                    {"a": str(appt.id)})
    session.flush()
    if appt.late_cancellation and appt.kind == "appointment" and _client_reason(session, reason_code_id, by_client):
        fees.charge_for_appointment(session, appt, settings, late=True, no_show=False)
    audit_record(session, "cancel", "bookings.appointment", appt.id,
                 {"late": appt.late_cancellation, "by_client": by_client, "note": appt.cancel_note or ""})
    publish(session, Event("appointment.cancelled", "bookings.appointment", appt.id,
                           {**_payload(appt, repo.appointment_resources(session, {appt.id}).get(appt.id, [])),
                            "late": appt.late_cancellation}))
    notify.cancelled(session, appt)
    return appt


def _simple_move(session: Session, appointment_id: UUID, target: str) -> Appointment:
    appt = _visible(session, appointment_id, lock=True)
    _manage(appt)
    life.check_move(appt.status, target)
    appt.status = target
    appt.updated_by, appt.updated_at = user_id(), now()
    return appt


def confirm(session: Session, appointment_id: UUID) -> Appointment:
    """Accept a booking request. The client is told it is confirmed."""
    appt = _simple_move(session, appointment_id, life.CONFIRMED)
    notify.forget(session, appt.id, "confirmation")
    session.flush()
    audit_record(session, "confirm", "bookings.appointment", appt.id, {})
    resources = repo.appointment_resources(session, {appt.id}).get(appt.id, [])
    publish(session, Event("appointment.confirmed", "bookings.appointment", appt.id, _payload(appt, resources)))
    notify.confirmation(session, appt)
    return appt


def check_in(session: Session, appointment_id: UUID) -> Appointment:
    """The client has arrived."""
    appt = _simple_move(session, appointment_id, life.CHECKED_IN)
    appt.checked_in_at = now()
    session.flush()
    audit_record(session, "check_in", "bookings.appointment", appt.id, {})
    publish(session, Event("appointment.checked_in", "bookings.appointment", appt.id,
                           _payload(appt, repo.appointment_resources(session, {appt.id}).get(appt.id, []))))
    return appt


def start_service(session: Session, appointment_id: UUID) -> Appointment:
    """The service begins."""
    appt = _simple_move(session, appointment_id, life.IN_SERVICE)
    appt.started_at = now()
    session.flush()
    audit_record(session, "start", "bookings.appointment", appt.id, {})
    return appt


def mark_no_show(session: Session, appointment_id: UUID, *, reason_code_id: UUID | None = None,
                 note: str | None = None) -> Appointment:
    """The client did not come. Only once the start time has passed. The resource is freed."""
    appt = _simple_move(session, appointment_id, life.NO_SHOW)
    if appt.starts_at > now():
        raise ValidationFailed("It has not started yet: cancel it instead")
    if reason_code_id is None:
        found = session.execute(text(
            "select id from kernel.reason_code where category = 'appointment_cancel' and code = 'NO_SHOW'")).first()
        reason_code_id = found.id if found else None
    if reason_code_id is not None:
        check_reason(session, "appointment_cancel", reason_code_id, note)
    appt.cancel_reason_id, appt.cancel_note = reason_code_id, (note or "").strip() or None
    appt.cancelled_at, appt.cancelled_by = now(), user_id()
    _release(session, appt)
    session.flush()
    if appt.kind == "appointment":
        fees.charge_for_appointment(session, appt, repo.ensure_settings(session, appt.company_id), late=False,
                                    no_show=True)
    audit_record(session, "no_show", "bookings.appointment", appt.id, {})
    publish(session, Event("appointment.no_show", "bookings.appointment", appt.id,
                           _payload(appt, repo.appointment_resources(session, {appt.id}).get(appt.id, []))))
    return appt


def finish_service(session: Session, appointment_id: UUID, *, invoice: bool = True) -> Appointment:
    """The service is done. Publishes `appointment.completed` (what was done, by whom, how long, the price lines) so
    billing can follow, and invoices straight away when the business asked for that (`invoice=False`: a checkout bills
    it)."""
    from ziira.modules.bookings.services import invoicing

    appt = _simple_move(session, appointment_id, life.COMPLETED)
    moment = now()
    appt.completed_at = moment
    started = appt.started_at or appt.checked_in_at or appt.starts_at
    appt.minutes_worked = max(int((moment - started).total_seconds() // 60), 0)
    session.flush()
    resources = repo.appointment_resources(session, {appt.id}).get(appt.id, [])
    offer = repo.get_offer(session, appt.offer_id)
    assert offer is not None
    audit_record(session, "finish", "bookings.appointment", appt.id, {"minutes": appt.minutes_worked})
    publish(session, Event("appointment.completed", "bookings.appointment", appt.id, {
        **_payload(appt, resources), "minutes": appt.minutes_worked, "service": offer.name,
        "product_id": offer.product_id,
        "lines": [{"product_id": offer.product_id, "description": offer.name, "quantity": "1",
                   "unit_price": str(appt.price)}]}))
    if invoice and repo.ensure_settings(session, appt.company_id).invoice_on_completion:
        invoicing.try_invoice(session, appt)
    return appt


def finish_for_checkout(session: Session, appt: Appointment, invoice: Any | None) -> Appointment:
    """A checkout bills this appointment: finish it if it is not finished, and tie the invoice to it."""
    if appt.status == life.CHECKED_IN:
        start_service(session, appt.id)
    if appt.status == life.IN_SERVICE:
        finish_service(session, appt.id, invoice=False)
    if appt.status != life.COMPLETED:
        raise ValidationFailed(f"{appt.number} is {appt.status.replace('_', ' ')} and cannot be billed")
    if invoice is not None:
        appt.invoice_id, appt.invoice_number = invoice.id, invoice.number
        session.flush()
        publish(session, Event("appointment.invoiced", "bookings.appointment", appt.id, {
            "company_id": appt.company_id, "branch_id": appt.branch_id, "appointment_id": appt.id,
            "invoice_id": invoice.id, "invoice_number": invoice.number}))
    return appt


# --------------------------------------------------------------------------- classes
def _class(session: Session, appointment_id: UUID, *, lock: bool = False) -> Appointment:
    appt = _visible(session, appointment_id, lock=lock)
    if appt.kind != "class":
        raise ValidationFailed("Only a class has attendees")
    return appt


def attendees(session: Session, appointment_id: UUID) -> list[AppointmentAttendee]:
    _class(session, appointment_id)
    return repo.attendees_of(session, appointment_id)


def add_attendee(session: Session, appointment_id: UUID, *, customer_id: UUID | None = None, name: str | None = None,
                 phone: str | None = None, email: str | None = None) -> AppointmentAttendee:
    """Book a person on a class while there is room. Needs 'bookings.manage'."""
    appt = _class(session, appointment_id, lock=True)
    _manage(appt)
    if appt.status not in (life.REQUESTED, life.CONFIRMED, life.CHECKED_IN):
        raise ValidationFailed("This class can no longer take people")
    who, phone, email = _customer_details(session, appt.company_id, customer_id, name, phone, email)
    if not who:
        raise ValidationFailed("Say who is joining")
    current = repo.attendees_of(session, appt.id)
    live = [a for a in current if a.status != "cancelled"]
    if len(live) >= appt.capacity:
        raise Conflict("The class is full: add the person to the waitlist")
    if customer_id is not None and any(a.customer_id == customer_id for a in live):
        raise Conflict("That person is already on this class")
    ctx = current_context()
    row = AppointmentAttendee(tenant_id=ctx.tenant_id, created_by=ctx.user_id, appointment_id=appt.id,
                              customer_id=customer_id, name=who, phone=phone, email=email)
    repo.add(session, row)
    audit_record(session, "add_attendee", "bookings.appointment", appt.id, {"name": who})
    return row


def update_attendee(session: Session, attendee_id: UUID, status: str) -> AppointmentAttendee:
    """Mark a person on a class as attended, a no-show or cancelled."""
    if status not in ("booked", "attended", "no_show", "cancelled"):
        raise ValidationFailed("Status must be booked, attended, no_show or cancelled")
    row = repo.get_attendee(session, attendee_id)
    if row is None:
        raise NotFound("Attendee not found")
    appt = _class(session, row.appointment_id, lock=True)
    _manage(appt)
    row.status = status
    row.updated_by, row.updated_at = user_id(), now()
    session.flush()
    audit_record(session, "attendee", "bookings.appointment", appt.id, {"status": status})
    return row


def calendar_day_count(session: Session, branch_id: UUID, start: datetime, end: datetime) -> Decimal:
    """How many live appointments a branch has in a stretch of time."""
    return Decimal(len(repo.list_appointments(session, access.view_scopes(), branch_id=branch_id,
                                              status=sorted(life.LIVE), start=start, end=end, limit=500)))
