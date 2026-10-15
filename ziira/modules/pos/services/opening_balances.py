"""Use cases: what customers owed (or were owed) when the business moved onto Ziira.

An **opening invoice** is an invoice with no lines, no tax and no stock (`kind = opening_balance`). It carries the
original invoice's date, due date and number, so ageing, statements and reminders work as they do for any invoice,
and it is paid by the ordinary customer receipts. A customer in credit at go-live becomes an **opening receipt**
(`method = opening`) with the whole amount unallocated: money held on their account, to be applied or refunded as
usual.

Nothing is posted here. Each document publishes `customer.opening_balance` and Finance makes the entry (Dr accounts
receivable for the customer, Cr opening balance equity) dated the go-live date, in the same transaction. An opening
document is not cancelled one by one: the whole import is reversed, which refuses while any of it has been paid.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.public import CustomerView
from ziira.modules.finance.public import opening_balance_posted, period_is_open
from ziira.modules.pos.permissions import RECEIVABLES_MANAGE
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import CustomerReceipt, SalesInvoice
from ziira.modules.pos.services import tills
from ziira.modules.pos.services.common import unit_enabled
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

OPENING_KIND = "opening_balance"
OPENING_METHOD = "opening"
CENT = Decimal("0.01")
SHOWN = 5


def check_can_open(session: Session, company_id: UUID, go_live_date: date) -> None:
    """Whether opening balances can be brought in now: the books are on, the go-live date is not in the future and its
    period is open, and the company's opening trial balance has not been posted yet (customers come first)."""
    if not unit_enabled(session, "finance"):
        raise ValidationFailed("Switch on Finance first: opening balances are posted to the books")
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Switch on CRM first: balances belong to customers")
    if go_live_date > tills.today(session, company_id):
        raise ValidationFailed(f"The go-live date {go_live_date} is in the future")
    if not period_is_open(session, company_id, go_live_date):
        raise ValidationFailed(f"The accounting period containing {go_live_date} is closed: choose a go-live date in "
                               "an open period")
    if opening_balance_posted(session, company_id):
        raise ValidationFailed("The opening trial balance has already been posted. Customer balances are brought in "
                               "before it: reverse the trial balance first, or enter this as a normal invoice")


def clean_reference(reference: str | None, fallback: str) -> str:
    return (reference or "").strip().upper()[:60] or fallback


def _prepare(session: Session, customer: CustomerView, amount: Decimal, go_live_date: date) -> None:
    ctx = current_context()
    check_company(session, customer.company_id)
    ctx.require(RECEIVABLES_MANAGE, company_id=customer.company_id)
    check_can_open(session, customer.company_id, go_live_date)
    if amount <= 0 or amount != amount.quantize(CENT):
        raise ValidationFailed("An opening balance is more than zero with at most 2 decimal places")


def _publish(session: Session, type_: str, aggregate: str, document_id: UUID, *, company_id: UUID, customer_id: UUID,
             number: str, balance: Decimal, day: date) -> None:
    publish(session, Event(type_, aggregate, document_id, {
        "company_id": company_id, "branch_id": None, "business_date": day, "customer_id": customer_id,
        "number": number, "balance": balance}))


def create_opening_invoice(session: Session, *, customer: CustomerView, reference: str, issue_date: date,
                           due_date: date, amount: Decimal, go_live_date: date) -> SalesInvoice:
    """What a customer owed on one invoice at go-live. `reference` is the invoice's number in the old system; the dates
    are the invoice's own, which is what ageing uses."""
    _prepare(session, customer, amount, go_live_date)
    if issue_date > go_live_date:
        raise ValidationFailed(f"The invoice date {issue_date} is after the go-live date {go_live_date}")
    if due_date < issue_date:
        raise ValidationFailed("The due date is before the invoice date")
    ctx = current_context()
    invoice = SalesInvoice(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=customer.company_id,
        number=next_document_number(session, company_id=customer.company_id, branch_id=None,
                                    doc_type="opening_invoice", prefix="OPN"),
        customer_id=customer.id, issue_date=issue_date, due_date=due_date, subtotal=amount, tax_total=Decimal(0),
        total=amount, kind=OPENING_KIND, external_ref=reference,
        notes=f"Opening balance brought forward from the previous system (invoice {reference})")
    pos_repo.add(session, invoice)
    audit_record(session, "open", "pos.sales_invoice", invoice.id,
                 {"number": invoice.number, "customer": customer.code, "reference": reference, "total": amount,
                  "go_live_date": go_live_date})
    _publish(session, "customer.opening_balance", "pos.sales_invoice", invoice.id, company_id=customer.company_id,
             customer_id=customer.id, number=invoice.number, balance=amount, day=go_live_date)
    return invoice


def create_opening_credit(session: Session, *, customer: CustomerView, reference: str, amount: Decimal,
                          go_live_date: date) -> CustomerReceipt:
    """Money a customer had paid in advance at go-live: held on their account, unallocated."""
    _prepare(session, customer, amount, go_live_date)
    ctx = current_context()
    receipt = CustomerReceipt(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=customer.company_id, branch_id=None,
        number=next_document_number(session, company_id=customer.company_id, branch_id=None,
                                    doc_type="opening_receipt", prefix="OPR"),
        customer_id=customer.id, method=OPENING_METHOD, amount=amount, received_on=go_live_date, reference=reference,
        unallocated=amount)
    pos_repo.add(session, receipt)
    audit_record(session, "open", "pos.customer_receipt", receipt.id,
                 {"number": receipt.number, "customer": customer.code, "reference": reference, "credit": amount,
                  "go_live_date": go_live_date})
    _publish(session, "customer.opening_balance", "pos.customer_receipt", receipt.id, company_id=customer.company_id,
             customer_id=customer.id, number=receipt.number, balance=-amount, day=go_live_date)
    return receipt


def opening_exists(session: Session, customer_id: UUID, reference: str, *, credit: bool) -> bool:
    """Whether this customer already has an opening invoice (or credit) with this reference."""
    if credit:
        return pos_repo.opening_receipt_by_reference(session, customer_id, reference) is not None
    return pos_repo.opening_invoice_by_reference(session, customer_id, reference) is not None


def reverse_opening_documents(session: Session, document_ids: list[UUID], reason: str) -> int:
    """Take opening invoices and credits out again, all together (the books follow through Finance). Refused, changing
    nothing, while any of them has been paid, credited, applied or refunded: reverse those receipts first."""
    invoices = [x for x in (pos_repo.get_invoice(session, i, lock=True) for i in document_ids)
                if x is not None and x.kind == OPENING_KIND and x.status != "cancelled"]
    receipts = [x for x in (pos_repo.get_receipt(session, i, lock=True) for i in document_ids)
                if x is not None and x.method == OPENING_METHOD and x.status == "posted"]
    touched = [f"{x.number} (paid {x.amount_paid}, credited {x.credited})" for x in invoices
               if x.amount_paid > 0 or x.credited > 0]
    touched += [f"{x.number} (credit used or refunded)" for x in receipts if x.unallocated != x.amount or x.refunded]
    if touched:
        shown = ", ".join(touched[:SHOWN]) + (f" and {len(touched) - SHOWN} more" if len(touched) > SHOWN else "")
        raise Conflict(f"These opening balances have been paid or used since they were imported: {shown}. Reverse "
                       "those payments first, then reverse the import")
    ctx = current_context()
    for invoice in invoices:
        company_id = invoice.company_id
        invoice.status, invoice.cancelled_at = "cancelled", datetime.now(UTC)
        invoice.cancelled_by, invoice.cancel_reason = ctx.user_id, reason
        session.flush()
        audit_record(session, "cancel", "pos.sales_invoice", invoice.id, {"number": invoice.number, "reason": reason})
        _publish(session, "customer.opening_balance_reversed", "pos.sales_invoice", invoice.id, company_id=company_id,
                 customer_id=invoice.customer_id, number=invoice.number, balance=invoice.total,
                 day=tills.today(session, company_id))
    for receipt in receipts:
        receipt.status, receipt.reversed_at, receipt.reverse_reason = "reversed", datetime.now(UTC), reason
        receipt.unallocated = Decimal(0)
        session.flush()
        audit_record(session, "reverse", "pos.customer_receipt", receipt.id, {"number": receipt.number,
                                                                                "reason": reason})
        _publish(session, "customer.opening_balance_reversed", "pos.customer_receipt", receipt.id,
                 company_id=receipt.company_id, customer_id=receipt.customer_id, number=receipt.number,
                 balance=-receipt.amount, day=tills.today(session, receipt.company_id))
    return len(invoices) + len(receipts)

