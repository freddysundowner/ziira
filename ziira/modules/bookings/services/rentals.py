"""Chair and room rental: a barber or stylist who rents a chair pays a fee every week or month, invoiced by itself.

The renter is a customer (their account is invoiced); the fee is a service item in Products. The worker invoices each
period exactly once (unique per rental and period), starting from the start date and catching up on missed periods one
at a time.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import unit_enabled, user_id
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_today,
    current_context,
    flag_for_review,
)

NAMESPACE = UUID("5f0d8c9e-4c77-4a53-9a70-0b6d4f7c1a11")


def add_period(day: date, every: str, steps: int = 1) -> date:
    """The start of the next period: a week later, or the same day next month (the last day when the month is
    shorter)."""
    if every == "week":
        return day + timedelta(weeks=steps)
    month = day.month - 1 + steps
    year, month = day.year + month // 12, month % 12 + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    return date(year, month, 28)


def list_rentals(session: Session, company_id: UUID, *, active_only: bool = False) -> list[dict[str, Any]]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return raw.many(session, "select * from bookings.chair_rental where company_id = :c "
                             f"{'and is_active ' if active_only else ''}order by created_at", c=company_id)


def create_rental(session: Session, *, company_id: UUID, branch_id: UUID, customer_id: UUID, product_id: UUID,
                  amount: Decimal, every: str, start_date: date, resource_id: UUID | None = None,
                  description: str | None = None, end_date: date | None = None) -> dict[str, Any]:
    """Rent a chair or room to a customer. Needs 'bookings.setup' at the branch. The fee is tax-inclusive like every
    price. The first invoice is made on the start date."""
    current_context().require(BOOKINGS_SETUP, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    if every not in ("week", "month"):
        raise ValidationFailed("Rent is charged every week or every month")
    if amount <= 0:
        raise ValidationFailed("The rent is more than zero")
    if end_date is not None and end_date < start_date:
        raise ValidationFailed("The end is before the start")
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Customers must be switched on: the renter is a customer")
    from ziira.modules.crm.public import find_customer
    from ziira.modules.products.public import find_product

    if (c := find_customer(session, customer_id)) is None or c.company_id != company_id:
        raise ValidationFailed("The renter was not found in this company")
    product = find_product(session, product_id)
    if product is None or product.company_id != company_id or product.product_type != "service":
        raise ValidationFailed("Pick a service item for the rent")
    if resource_id is not None:
        res = repo.get_resource(session, resource_id)
        if res is None or res.company_id != company_id:
            raise ValidationFailed("That chair or room was not found")
    made = raw.insert(session, "chair_rental", {
        "company_id": company_id, "branch_id": branch_id, "resource_id": resource_id, "customer_id": customer_id,
        "product_id": product_id, "description": (description or "").strip()[:200] or f"Chair rent: {product.name}",
        "amount": amount, "every": every, "start_date": start_date, "next_due": start_date, "end_date": end_date},
        user_id=user_id())
    audit_record(session, "create", "bookings.chair_rental", made["id"], {"amount": amount, "every": every})
    return made


def end_rental(session: Session, rental_id: UUID, end_date: date | None = None) -> dict[str, Any]:
    """Stop a rental (from a date, or now)."""
    row = raw.one(session, "select * from bookings.chair_rental where id = :i", i=rental_id)
    if row is None or not access.can_view(row["company_id"], row["branch_id"]):
        raise NotFound("Rental not found")
    current_context().require(BOOKINGS_SETUP, company_id=row["company_id"], branch_id=row["branch_id"])
    done = raw.update(session, "chair_rental", rental_id, {"is_active": False, "end_date": end_date or company_today(
        session, row["company_id"])}, user_id=user_id())
    audit_record(session, "end", "bookings.chair_rental", rental_id, {})
    return done


def run_due(session: Session) -> int:
    """Invoice every rental period that has started and is not yet invoiced. Safe to run again. A failure (the renter is
    over their limit) goes to the exceptions inbox and is tried again next run. Returns how many invoices were made."""
    import ziira.modules.pos.public as pos_public

    if not unit_enabled(session, "pos"):
        return 0
    made = 0
    for rental in raw.many(session, "select * from bookings.chair_rental where is_active order by created_at"):
        today = company_today(session, rental["company_id"])
        while rental["next_due"] <= today and (rental["end_date"] is None or rental["next_due"] <= rental["end_date"]):
            period = rental["next_due"]
            try:
                with session.begin_nested():
                    run = raw.one(session, "insert into bookings.chair_rental_run (tenant_id, rental_id, period_start) "
                                           "values (kernel.current_tenant(), :r, :p) "
                                           "on conflict do nothing returning *",
                                  r=rental["id"], p=period)
                    if run is not None:
                        ref = pos_public.issue_invoice_from_lines(
                            session, company_id=rental["company_id"], branch_id=rental["branch_id"],
                            customer_id=rental["customer_id"], lines=[pos_public.InvoiceLineIn(
                                product_id=rental["product_id"], description=f"{rental['description']} ({period})",
                                quantity=Decimal(1), unit_price=rental["amount"])],
                            source_type="bookings.chair_rental", source_id=uuid5(NAMESPACE, f"{rental['id']}:{period}"),
                            memo=f"Rent from {period}", issue_date=period)
                        raw.update(session, "chair_rental_run", run["id"], {"invoice_id": ref.id,
                                                                            "invoice_number": ref.number})
                        raw.update(session, "chair_rental", rental["id"], {"last_invoice_number": ref.number})
                        made += 1
                    rental = raw.update(session, "chair_rental", rental["id"],
                                        {"next_due": add_period(period, rental["every"])})
            except Exception as exc:  # noqa: BLE001 - one renter's problem must not stop the others
                flag_for_review(session, unit="bookings", kind="rental_invoice_failed", severity="medium",
                                message=(f"Chair rent for {rental['description']} ({period}) "
                                         f"could not be invoiced: {exc}"),
                                company_id=rental["company_id"], branch_id=rental["branch_id"],
                                ref_type="bookings.chair_rental", ref_id=rental["id"],
                                dedupe_key=f"bookings:rental:{rental['id']}:{period}")
                break
    return made
