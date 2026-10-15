"""Use cases: what the business owed suppliers when it moved onto Ziira.

An **opening bill** is a posted bill with no lines, no goods, no tax and nothing to match (`kind = opening_balance`).
It carries the supplier's invoice number and the original dates, so payables ageing is right, and it is paid by the
ordinary bill payments. Nothing is posted here: the bill publishes `supplier.opening_balance` and Finance makes the
entry (Dr opening balance equity, Cr accounts payable for the supplier) dated the go-live date, in the same
transaction. An opening bill is not cancelled one by one: the whole import is reversed, which refuses while any of it
has been paid.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.public import opening_balance_posted, period_is_open
from ziira.modules.purchasing.permissions import BILLS_MANAGE
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import Supplier, SupplierBill
from ziira.modules.purchasing.services.common import unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_today,
    current_context,
    next_document_number,
    publish,
)

OPENING_KIND = "opening_balance"
CENT = Decimal("0.01")
SHOWN = 5


def check_can_open(session: Session, company_id: UUID, go_live_date: date) -> None:
    """Whether opening balances can be brought in now: the books are on, the go-live date is not in the future and its
    period is open, and the company's opening trial balance has not been posted yet (suppliers come first)."""
    if not unit_enabled(session, "finance"):
        raise ValidationFailed("Switch on Finance first: opening balances are posted to the books")
    if go_live_date > company_today(session, company_id):
        raise ValidationFailed(f"The go-live date {go_live_date} is in the future")
    if not period_is_open(session, company_id, go_live_date):
        raise ValidationFailed(f"The accounting period containing {go_live_date} is closed: choose a go-live date in "
                               "an open period")
    if opening_balance_posted(session, company_id):
        raise ValidationFailed("The opening trial balance has already been posted. Supplier balances are brought in "
                               "before it: reverse the trial balance first, or enter this as a normal bill")


def clean_reference(reference: str | None, fallback: str) -> str:
    return (reference or "").strip()[:60] or fallback


def create_opening_bill(session: Session, *, supplier: Supplier, reference: str, bill_date: date, due_date: date,
                        amount: Decimal, go_live_date: date) -> SupplierBill:
    """What the business owed a supplier on one invoice at go-live. `reference` is the supplier's invoice number; the
    dates are the invoice's own, which is what ageing uses."""
    ctx = current_context()
    company_id = supplier.company_id
    check_company(session, company_id)
    ctx.require(BILLS_MANAGE, company_id=company_id)
    check_can_open(session, company_id, go_live_date)
    if amount <= 0 or amount != amount.quantize(CENT):
        raise ValidationFailed("An opening balance is more than zero with at most 2 decimal places")
    if bill_date > go_live_date:
        raise ValidationFailed(f"The bill date {bill_date} is after the go-live date {go_live_date}")
    if due_date < bill_date:
        raise ValidationFailed("The due date is before the bill date")
    if repo.bill_by_invoice(session, supplier.id, reference) is not None:
        raise Conflict(f"{supplier.name}'s invoice {reference} has already been entered")
    bill = SupplierBill(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=None,
        number=next_document_number(session, company_id=company_id, branch_id=None, doc_type="opening_bill",
                                    prefix="OBL"),
        supplier_id=supplier.id, supplier_invoice_no=reference, bill_date=bill_date, due_date=due_date,
        subtotal=amount, tax_total=Decimal(0), total=amount, match_status="not_required", status="posted",
        kind=OPENING_KIND, posted_at=datetime.now(UTC))
    repo.add(session, bill)
    audit_record(session, "open", "purchasing.supplier_bill", bill.id,
                 {"number": bill.number, "supplier": supplier.code, "invoice": reference, "total": amount,
                  "go_live_date": go_live_date})
    publish(session, Event("supplier.opening_balance", "purchasing.supplier_bill", bill.id, {
        "company_id": company_id, "branch_id": None, "business_date": go_live_date, "supplier_id": supplier.id,
        "number": bill.number, "balance": amount}))
    return bill


def reverse_opening_bills(session: Session, bill_ids: list[UUID], reason: str) -> int:
    """Take opening bills out again, all together (the books follow through Finance). Refused, changing nothing, while
    any of them has been paid, credited or refunded: reverse those payments first."""
    bills = [b for b in (repo.get_bill(session, i, lock=True) for i in bill_ids)
             if b is not None and b.kind == OPENING_KIND and b.status != "reversed"]
    touched = [f"{b.number} (paid {b.amount_paid}, credited {b.credited})" for b in bills
               if b.amount_paid > 0 or b.credited > 0 or b.refunded > 0]
    if touched:
        shown = ", ".join(touched[:SHOWN]) + (f" and {len(touched) - SHOWN} more" if len(touched) > SHOWN else "")
        raise Conflict(f"These opening bills have been paid or credited since they were imported: {shown}. Reverse "
                       "those payments first, then reverse the import")
    ctx = current_context()
    for bill in bills:
        bill.status, bill.reversed_at, bill.reversed_by = "reversed", datetime.now(UTC), ctx.user_id
        bill.reverse_reason = reason
        session.flush()
        audit_record(session, "reverse", "purchasing.supplier_bill", bill.id,
                     {"number": bill.number, "reason": reason})
        publish(session, Event("supplier.opening_balance_reversed", "purchasing.supplier_bill", bill.id, {
            "company_id": bill.company_id, "branch_id": None, "business_date": company_today(session, bill.company_id),
            "supplier_id": bill.supplier_id, "number": bill.number, "balance": bill.total}))
    return len(bills)
