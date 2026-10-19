"""Use cases: selling a session package, refunding what is unused, and expiring packages.

A package sold is its own credit holder with its own balance and expiry. Selling writes a 'purchase' entry, and the
sale is invoiced once (billing.py) when invoices are available."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from ziira.modules.memberships.permissions import CREDITS, MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import billing, common, credits, invoicing, profiles
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
    publish,
)

PACKAGE = credits.PACKAGE


def _event(session: Session, name: str, sold: repo.Row, **extra: Any) -> None:
    publish(session, Event(name, "memberships.sold_package", sold["id"], {
        "company_id": sold["company_id"], "branch_id": sold["branch_id"], "customer_id": sold["customer_id"],
        "sold_package_id": sold["id"], "package_id": sold["package_id"], "number": sold["number"], **extra}))


def with_balance(session: Session, rows: list[repo.Row]) -> list[repo.Row]:
    balance = repo.balances(session, [r["id"] for r in rows])
    return [{**r, "balance": balance[r["id"]]} for r in rows]


def sell(session: Session, *, package_id: UUID, customer_id: UUID, branch_id: UUID, purchased_on: date | None = None,
         price: Any = None, invoice: bool | None = None, notes: str | None = None,
         billing_customer_id: UUID | None = None, voucher_code: str | None = None) -> repo.Row:
    """Sell a package to a customer. The price defaults to the catalogue price. `invoice` None: invoice when the
    package has a service item and invoices are on; True insists. Needs 'memberships.manage' at the branch."""
    package = common.get_row(session, "package", package_id, "Package")
    company_id = package["company_id"]
    common.require(MANAGE, company_id, branch_id)
    check_company(session, company_id, branch_id)
    if package["status"] != "active":
        raise ValidationFailed("This package is retired and can no longer be sold")
    common.customer_of(session, company_id, customer_id)
    payer = billing_customer_id or profiles.billing_customer_of(session, customer_id)
    if payer is not None and payer != customer_id:
        common.customer_of(session, company_id, payer)
    else:
        payer = None
    amount = package["price"] if price is None else price
    if amount < 0:
        raise ValidationFailed("The price cannot be negative")
    day = purchased_on or common.today(session, company_id)
    can_bill = amount > 0 and package["product_id"] is not None and invoicing.available(session)
    if invoice and amount > 0 and not can_bill:
        raise ValidationFailed("The package cannot be invoiced: it needs a service item to invoice it as, and Point "
                               "of Sale and Invoices must be on")
    bill = can_bill if invoice is None else (invoice and can_bill)
    ctx = current_context()
    sold = repo.insert(session, "sold_package", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
        "number": next_document_number(session, company_id=company_id, branch_id=None, doc_type="package_sale",
                                       prefix="PKG"),
        "customer_id": customer_id, "package_id": package_id, "name": package["name"], "credits": package["credits"],
        "price": amount, "covered_services": package["covered_services"], "purchased_on": day,
        "expires_on": day + timedelta(days=package["expiry_days"]) if package["expiry_days"] else None,
        "notes": (notes or "").strip() or None, "billing_customer_id": payer})
    credits.add_unchecked(session, sold, PACKAGE, "purchase", package["credits"], day=day,
                          note=f"Bought {package['name']}")
    if bill:
        billing.bill_period(
            session, owner_type="package", owner_id=sold["id"], company_id=company_id, branch_id=branch_id,
            customer_id=payer or customer_id, period_start=day, period_end=None,
            lines=[{"product_id": str(package["product_id"]), "description": package["name"], "quantity": "1",
                    "unit_price": str(amount), "discount": "0"}], due_days=None, memo=f"Package {sold['number']}",
            raise_on_error=True, voucher_code=voucher_code)
    audit_record(session, "sell", "memberships.sold_package", sold["id"], {"package": package["code"],
                                                                           "customer": str(customer_id)})
    _event(session, "package.sold", sold, credits=package["credits"], price=amount, expires_on=sold["expires_on"])
    return with_balance(session, [sold])[0]


def get_sold(session: Session, sold_id: UUID) -> repo.Row:
    return with_balance(session, [common.get_row(session, "sold_package", sold_id, "Package")])[0]


def list_sold(session: Session, *, company_id: UUID | None = None, customer_id: UUID | None = None,
              status: str | None = None, expiring_before: date | None = None, limit: int = 50,
              offset: int = 0) -> list[repo.Row]:
    clause, params = repo.scope_sql(common.view_scopes())
    rows = repo.many(
        session,
        f"select * from memberships.sold_package where {clause} and (cast(:c as uuid) is null or company_id = :c) "
        "and (cast(:cu as uuid) is null or customer_id = :cu) and (cast(:s as text) is null or status = :s) "
        "and (cast(:e as date) is null or (expires_on is not null and expires_on <= :e)) "
        "order by status, expires_on nulls last, purchased_on desc limit :l offset :o",
        c=company_id, cu=customer_id, s=status, e=expiring_before, l=min(limit, 200), o=offset, **params)
    return with_balance(session, rows)


def refund(session: Session, sold_id: UUID, note: str) -> repo.Row:
    """Take back a package that was not used up: its remaining credits are removed and it is closed. The money goes
    back through a credit note in Sales, which this does not issue. Needs 'memberships.credits'."""
    sold = common.get_row(session, "sold_package", sold_id, "Package", lock=True)
    common.require(CREDITS, sold["company_id"], sold["branch_id"])
    if sold["status"] != "active":
        raise Conflict("Only an active package can be refunded")
    if not note.strip():
        raise ValidationFailed("Say why the package is refunded")
    left = repo.holder_balance(session, sold_id)
    if left > 0:
        credits.add_unchecked(session, sold, PACKAGE, "refund", -left, note=note.strip()[:300])
    saved = repo.update(session, "sold_package", sold_id, {"status": "refunded"})
    audit_record(session, "refund", "memberships.sold_package", sold_id, {"credits_removed": str(left)})
    return with_balance(session, [saved])[0]


# --------------------------------------------------------------------------- the recurring task's work
def expire_due(session: Session, company_id: UUID, today: date) -> int:
    """Close the packages whose expiry date has passed: unused credits are written off. Returns how many."""
    due = repo.many(session, "select * from memberships.sold_package where company_id = :c and status = 'active' "
                             "and expires_on is not null and expires_on < :d order by expires_on, id for update",
                    c=company_id, d=today)
    for sold in due:
        left = credits.expire_leftover(session, sold, PACKAGE, note="The package expired", day=sold["expires_on"])
        saved = repo.update(session, "sold_package", sold["id"], {"status": "expired"})
        audit_record(session, "expire", "memberships.sold_package", sold["id"], {"credits_written_off": str(left)})
        _event(session, "package.expired", saved, credits_written_off=left)
    return len(due)
