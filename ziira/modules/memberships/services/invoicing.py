"""The one place Memberships asks for an invoice. Invoices are made only by the sales unit's invoice service
(`pos.public.issue_invoice_from_lines`); when that unit is off, or does not offer the function, nothing here can issue
and callers record that clearly instead of failing silently."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.memberships.services import common
from ziira.sdk import Session, ValidationFailed

SOURCE_TYPE = "memberships.invoice_run"


class InvoicingUnavailable(ValidationFailed):
    """Raised when invoices cannot be made (the sales unit is off or too old)."""


@dataclass(frozen=True)
class IssuedInvoice:
    id: UUID
    number: str
    total: Decimal
    due_date: date | None = None


def available(session: Session) -> bool:
    """True when this business can have invoices issued for it."""
    if not common.unit_enabled(session, "pos"):
        return False
    import ziira.modules.pos.public as sales

    return hasattr(sales, "issue_invoice_from_lines")


def issue(session: Session, *, company_id: UUID, branch_id: UUID, customer_id: UUID, lines: list[dict[str, str]],
          run_id: UUID, due_days: int | None, memo: str | None, issue_date: date | None = None) -> IssuedInvoice:
    """Issue an invoice for the lines (each: product_id, description, quantity, unit_price, discount), once per run."""
    if not available(session):
        raise InvoicingUnavailable("Invoices cannot be issued: switch on Point of Sale and Invoices first")
    import ziira.modules.pos.public as sales

    made = sales.issue_invoice_from_lines(
        session, company_id=company_id, branch_id=branch_id, customer_id=customer_id,
        lines=[sales.InvoiceLineIn(product_id=UUID(str(x["product_id"])), description=x.get("description") or "",
                                   quantity=Decimal(x["quantity"]), unit_price=Decimal(x["unit_price"]),
                                   discount=Decimal(x.get("discount") or 0)) for x in lines],
        source_type=SOURCE_TYPE, source_id=run_id, due_days=due_days, memo=memo, issue_date=issue_date)
    return IssuedInvoice(made.id, made.number, made.total, made.due_date)
