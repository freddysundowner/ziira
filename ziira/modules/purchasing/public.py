"""Public interface of the Purchasing and Suppliers module.

Other units normally talk to Purchasing through events (`goods.received`, `bill.posted`, `supplier.paid`).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.purchasing.repository import purchasing_repo
from ziira.sdk import Session


def supplier_balance(session: Session, supplier_id: UUID) -> Decimal:
    """What the business owes a supplier on posted bills (negative: the supplier owes the business, for example a refund
    that is due)."""
    total = Decimal(0)
    for bill in purchasing_repo.list_bills(session, None, supplier_id=supplier_id, status=None, due_before=None,
                                           limit=500, offset=0):
        if bill.status in ("posted", "part_paid", "paid"):
            total += bill.total - bill.amount_paid - bill.credited + bill.refunded
    return total


@dataclass(frozen=True)
class SupplierView:
    """What other units need to know about a supplier."""

    id: UUID
    company_id: UUID
    code: str
    name: str
    payment_terms_days: int
    status: str


def find_supplier_by_code(session: Session, company_id: UUID, code: str) -> SupplierView | None:
    """A company's supplier by code (codes are upper case), or None."""
    found = purchasing_repo.supplier_by_code(session, company_id, code.strip().upper())
    if found is None:
        return None
    return SupplierView(found.id, found.company_id, found.code, found.name, found.payment_terms_days, found.status)


@dataclass(frozen=True)
class OrderView:
    """What other units need to know about a purchase order (a part ordered for a job)."""

    id: UUID
    company_id: UUID
    number: str
    supplier_id: UUID
    supplier_name: str
    status: str
    expected_date: date | None


def find_order_by_number(session: Session, company_id: UUID, number: str) -> OrderView | None:
    """A company's purchase order by its number (any case), or None. Read only; added for Jobs (parts ordered for a
    job)."""
    from sqlalchemy import text

    row = session.execute(text(
        "select o.id, o.company_id, o.number, o.supplier_id, s.name as supplier_name, o.status, o.expected_date "
        "from purchasing.purchase_order o join purchasing.supplier s on s.id = o.supplier_id "
        "where o.company_id = :c and upper(o.number) = upper(:n)"), {"c": str(company_id), "n": number.strip()}).first()
    if row is None:
        return None
    return OrderView(row.id, row.company_id, row.number, row.supplier_id, row.supplier_name, row.status,
                     row.expected_date)
