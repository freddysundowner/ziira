"""A believable week of sample data so a new business can see the screens working before it has real clients: a handful
of clients, a week of finished visits (some missed, one cancelled late), and the next few days booked, spread over the
staff the pack set up. It makes no invoices and takes no money. Every row it makes is noted in `bookings.sample_record`,
so it can be removed together; the clients stay in Customers (their names end with "(sample)") because Customers has no
delete."""

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import unit_enabled, zone
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_today,
    current_context,
    next_document_number,
)

CLIENTS = ["Amina Wanjiru", "Brian Otieno", "Carol Njeri", "David Kamau", "Esther Achieng", "Faith Mutua"]
PHONES = ["0700000101", "0700000102", "0700000103", "0700000104", "0700000105", "0700000106"]
MARK = " (sample)"


def status(session: Session, company_id: UUID) -> dict[str, int]:
    rows = raw.many(session, "select entity, count(*) as n from bookings.sample_record "
                    "where company_id = :c group by entity",
                    c=company_id)
    return {r["entity"]: int(r["n"]) for r in rows}


def create(session: Session, company_id: UUID, branch_id: UUID | None = None) -> dict[str, int]:
    """Make the sample week (once: asking again changes nothing). Needs 'bookings.setup' and Customers."""
    current_context().require(BOOKINGS_SETUP, company_id=company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Customers must be switched on to make sample clients")
    if status(session, company_id):
        return status(session, company_id)
    resources = [r for r in repo.list_resources(session, None, company_id=company_id, branch_id=branch_id,
                                                  active_only=True)
                 if r.kind in ("staff", "chair")]
    offers = [o for o in repo.list_offers(session, None, company_id=company_id, active_only=True)
              if o.kind == "appointment"]
    if not resources or not offers:
        raise ValidationFailed("Set up staff and services first (or switch on an industry pack)")
    from ziira.modules.crm.public import match_or_create_customer

    customers = []
    for name, phone in zip(CLIENTS, PHONES, strict=True):
        customer, created = match_or_create_customer(session, company_id, name=name + MARK, phone=phone)
        customers.append(customer)
        if created:
            _note(session, company_id, "customer", customer.id)
    zn = zone(session, company_id)
    today = company_today(session, company_id)
    plan: list[tuple[date, int, str]] = []
    for back in range(7, 0, -1):
        day = today - timedelta(days=back)
        if day.weekday() != 6:
            plan += [(day, 9, "completed"), (day, 11, "completed"), (day, 14, "completed")]
    plan[3] = (plan[3][0], plan[3][1], "no_show")
    plan[8] = (plan[8][0], plan[8][1], "late_cancel")
    for ahead in range(0, 4):
        day = today + timedelta(days=ahead)
        if day.weekday() != 6:
            plan += [(day, 10, "confirmed"), (day, 15, "confirmed")]
    made = 0
    for i, (day, hour, state) in enumerate(plan):
        resource = resources[i % len(resources)]
        offer = _offer_for(offers, resource, i)
        starts = datetime.combine(day, time(hour, 0), tzinfo=zn)
        if state == "confirmed" and starts <= datetime.now(zn):
            continue
        customer = customers[i % len(customers)]
        appt = _insert(session, company_id, resource, offer, starts, customer, state, i)
        _note(session, company_id, "appointment", appt.id)
        made += 1
    for i, (back, client_i) in enumerate([(52, 1), (49, 4)]):
        offer = offers[i % len(offers)]
        resource = resources[(i + 1) % len(resources)]
        starts = datetime.combine(today - timedelta(days=back), time(10, 0), tzinfo=zn)
        appt = _insert(session, company_id, resource, offer, starts, customers[client_i], "completed", 100 + i)
        _note(session, company_id, "appointment", appt.id)
        made += 1
    audit_record(session, "sample_data", "bookings.company", company_id, {"appointments": made})
    return status(session, company_id)


def _offer_for(offers: list[Any], resource: Any, i: int) -> Any:
    return offers[i % len(offers)]


def _insert(session: Session, company_id: UUID, resource: Any, offer: Any, starts: datetime, customer: Any, state: str,
            seed: int) -> Appointment:
    ctx = current_context()
    ends = starts + timedelta(minutes=offer.duration_minutes)
    appt_state = {"completed": "completed", "no_show": "no_show", "late_cancel": "cancelled",
                  "confirmed": "confirmed"}[state]
    appt = Appointment(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=resource.branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=resource.branch_id,
                                    doc_type="appointment", prefix="APT"),
        offer_id=offer.id, kind="appointment", status=appt_state, source="staff", starts_at=starts, ends_at=ends,
        customer_id=customer.id, client_name=customer.name, client_phone=customer.phone, price=offer.price,
        late_cancellation=state == "late_cancel",
        completed_at=ends if state == "completed" else None,
        minutes_worked=offer.duration_minutes if state == "completed" else None,
        cancelled_at=starts - timedelta(hours=3) if state == "late_cancel" else None)
    repo.add(session, appt)
    holds = state not in ("no_show", "late_cancel")
    session.execute(text(
        "insert into bookings.appointment_resource (tenant_id, appointment_id, resource_id, blocked, holds) "
        "values (kernel.current_tenant(), :a, :r, tstzrange(:s, :e, '[)'), :h)"),
        {"a": str(appt.id), "r": str(resource.id), "s": starts, "e": ends, "h": holds})
    return appt


def _note(session: Session, company_id: UUID, entity: str, entity_id: UUID) -> None:
    raw.insert(session, "sample_record", {"company_id": company_id, "entity": entity, "entity_id": entity_id,
                                          "pack": "sample"})


def remove(session: Session, company_id: UUID) -> dict[str, int]:
    """Remove the sample appointments (and nothing a person made). The sample clients stay in Customers."""
    current_context().require(BOOKINGS_SETUP, company_id=company_id)
    ids = [r["entity_id"] for r in raw.many(
        session, "select entity_id from bookings.sample_record where company_id = :c and entity = 'appointment'",
        c=company_id)]
    removed = 0
    for appt_id in ids:
        busy = raw.one(session, "select 1 as x from bookings.checkout_line where appointment_id = :a limit 1",
                       a=appt_id)
        if busy is not None:
            continue
        raw.run(session, "delete from bookings.appointment where id = :a", a=appt_id)
        removed += 1
    raw.run(session, "delete from bookings.sample_record where company_id = :c and entity = 'appointment'",
            c=company_id)
    kept = status(session, company_id).get("customer", 0)
    return {"appointments_removed": removed, "clients_kept": kept}
