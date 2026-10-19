"""The client card: what the front desk wants to know about someone when they walk in.

History, who they usually see, what they are due for, fees and credit they have, a patch-test warning, and the fields
the business keeps (allergies note, formula, preferred staff). It holds no clinical record: a clinic's pack adds
administrative fields only.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import unit_enabled
from ziira.sdk import NotFound, Session, company_today, custom_fields

ENTITY = "bookings.client"
PATCH_KEY = "patch_test_date"


def patch_test_status(session: Session, company_id: UUID, customer_id: UUID | None, offer_needs: bool,
                      on: date | None = None) -> str | None:
    """A plain warning when a service needs a patch test and the client's last one is missing or too old (the validity
    is the business's setting; this is not medical advice). None: nothing to warn about."""
    if not offer_needs or customer_id is None:
        return None
    settings = repo.ensure_settings(session, company_id)
    values = custom_fields.read_values(session, ENTITY, customer_id)
    raw_date = values.get(PATCH_KEY)
    if not raw_date:
        return "No patch test on record for this client"
    try:
        tested = date.fromisoformat(str(raw_date))
    except ValueError:
        return "The patch test date on record is not a date"
    valid_days = settings.patch_test_valid_days
    today = on or company_today(session, company_id)
    if valid_days is not None and tested + timedelta(days=valid_days) < today:
        return f"The patch test of {tested.isoformat()} has expired"
    if tested > today:
        return "The patch test date is in the future"
    return None


def warnings_for(session: Session, appt: Appointment) -> list[str]:
    """Things the desk should see about an appointment: a missing or expired patch test, an unpaid fee, a deposit
    owed."""
    out: list[str] = []
    offer = repo.get_offer(session, appt.offer_id)
    if offer is not None and offer.needs_patch_test:
        msg = patch_test_status(session, appt.company_id, appt.customer_id, True)
        if msg:
            out.append(msg)
    if appt.status in ("requested", "confirmed") and appt.deposit_amount > appt.deposit_paid:
        out.append(f"Deposit of {appt.deposit_amount - appt.deposit_paid} not yet paid")
    if appt.customer_id is not None:
        owed = raw.one(session, "select count(*) as n, coalesce(sum(amount), 0) as total from bookings.client_fee "
                                "where customer_id = :c and status = 'open'", c=appt.customer_id)
        if owed and owed["n"]:
            out.append(f"Owes {owed['total']} in fees from earlier visits")
    return out


def client_card(session: Session, company_id: UUID, customer_id: UUID) -> dict[str, Any]:
    """Everything the desk shows on the client's card."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    history = repo.list_appointments(session, access.view_scopes(), customer_id=customer_id, order_desc=True, limit=30)
    history = [a for a in history if a.company_id == company_id]
    names = {o.id: o.name for o in repo.offers_by_ids(session, {a.offer_id for a in history}).values()}
    usual = raw.many(session, """
        select r.id as resource_id, r.name, count(*) as visits from bookings.appointment a
        join bookings.appointment_resource ar on ar.appointment_id = a.id and ar.part = 0
        join bookings.resource r on r.id = ar.resource_id
        where a.customer_id = :c and a.company_id = :co and a.status = 'completed' and r.kind = 'staff'
        group by r.id, r.name order by count(*) desc, r.name limit 3""", c=customer_id, co=company_id)
    fees = raw.many(session, "select * from bookings.client_fee where customer_id = :c and status = 'open' "
                             "order by created_at", c=customer_id)
    values = custom_fields.read_values(session, ENTITY, customer_id)
    card: dict[str, Any] = {
        "customer_id": customer_id, "values": values,
        "history": [{"appointment_id": a.id, "number": a.number, "service": names.get(a.offer_id, ""),
                     "status": a.status, "starts_at": a.starts_at, "price": a.price, "note": a.note} for a in history],
        "usual_staff": usual, "open_fees": fees,
        "patch_test": patch_test_status(session, company_id, customer_id, True),
        "visits": sum(1 for a in history if a.status == "completed"),
        "last_visit": next((a.starts_at for a in history if a.status == "completed"), None),
        "no_shows": sum(1 for a in history if a.status == "no_show"),
        "membership": None, "credit": None}
    if unit_enabled(session, "memberships"):
        import ziira.modules.memberships.public as memberships

        m = memberships.active_membership(session, customer_id)
        card["membership"] = None if m is None else {
            "plan": m.plan_name, "credits": m.credits_balance, "discount_percent": m.discount_percent,
            "renews": m.next_renewal_date}
        card["credit"] = memberships.member_credit_balance(session, customer_id)
    if unit_enabled(session, "pos"):
        import ziira.modules.pos.public as pos_public

        card["on_account"] = pos_public.customer_credit(session, customer_id)
    return card


def _manage_in_company(company_id: UUID) -> None:
    """The person may manage bookings somewhere in the company (a front desk at one branch keeps the whole client
    card)."""
    from ziira.modules.bookings.permissions import BOOKINGS_MANAGE
    from ziira.sdk import Forbidden, current_context

    companies = current_context().companies_with(BOOKINGS_MANAGE)
    if companies is not None and company_id not in companies:
        raise Forbidden(f"You do not have permission '{BOOKINGS_MANAGE}' here")


def field_definitions(session: Session, company_id: UUID) -> list[Any]:
    """The fields the business keeps on a client card."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return custom_fields.definitions_for(session, ENTITY, company_id)


def save_fields(session: Session, company_id: UUID, customer_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
    """Change some fields on a client card (only the keys sent). Any front desk of the company may; values may be
    personal data, so only the keys are audited."""
    from ziira.sdk import audit_record

    _manage_in_company(company_id)
    if not unit_enabled(session, "crm"):
        raise NotFound("Client not found")
    from ziira.modules.crm.public import find_customer

    found = find_customer(session, customer_id)
    if found is None or found.company_id != company_id:
        raise NotFound("Client not found")
    defs = custom_fields.definitions_for(session, ENTITY, company_id)
    existing = custom_fields.read_values(session, ENTITY, customer_id)
    clean = custom_fields.validate_values(defs, values, existing=existing)
    custom_fields.write_values(session, ENTITY, customer_id, clean, company_id=company_id)
    audit_record(session, "client_fields", "crm.customer", customer_id, {"keys": sorted(values)})
    return custom_fields.read_values(session, ENTITY, customer_id)
