"""Public interface of the Point of Sale and Sales module.

Other units use these; they normally talk to POS through events (`sale.posted`, `sale.returned`, `till.closed`).
"""

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session

RECEIPT_EXTRAS = "pos.receipt_extras"


class ReceiptExtra(ABC):
    """Contract of the "pos.receipt_extras" extension point: lines a plugin adds to the foot of a printed document
    (a tax-authority control code, a QR code's text, ...). `kind` is "sale", "invoice" or "receipt"."""

    @abstractmethod
    def lines(self, session: Session, kind: str, document_id: UUID) -> list[str]:
        """Extra lines for the document, or none."""


def open_till_sessions(session: Session, branch_id: UUID, day: date) -> int:
    """How many till sessions of a branch and business date are still open (a day cannot be closed while any is)."""
    return int(session.execute(text(
        "select count(*) from pos.till_session where branch_id = :b and business_date = :d and status = 'open'"),
        {"b": str(branch_id), "d": day}).scalar_one())


def customer_balance(session: Session, customer_id: UUID) -> Decimal:
    """What a customer owes on invoices that are not paid or cancelled, less money they hold on account in advance
    (negative: they are in credit). For statements and credit decisions."""
    owed = Decimal(session.execute(text(
        "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice where customer_id = :c "
        "and status in ('issued', 'part_paid')"), {"c": str(customer_id)}).scalar_one())
    held = Decimal(session.execute(text(
        "select coalesce(sum(unallocated), 0) from pos.customer_receipt where customer_id = :c and status = 'posted'"),
        {"c": str(customer_id)}).scalar_one())
    return owed - held
