"""Public interface of the Point of Sale and Sales module.

Other units use these; they normally talk to POS through events (`sale.posted`, `sale.returned`, `till.closed`).
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session


def open_till_sessions(session: Session, branch_id: UUID, day: date) -> int:
    """How many till sessions of a branch and business date are still open (a day cannot be closed while any is)."""
    return int(session.execute(text(
        "select count(*) from pos.till_session where branch_id = :b and business_date = :d and status = 'open'"),
        {"b": str(branch_id), "d": day}).scalar_one())


def customer_balance(session: Session, customer_id: UUID) -> Decimal:
    """What a customer owes on invoices that are not paid or cancelled (for statements and credit decisions)."""
    return Decimal(session.execute(text(
        "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice where customer_id = :c "
        "and status in ('issued', 'part_paid')"), {"c": str(customer_id)}).scalar_one())
