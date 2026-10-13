"""Use cases: a customer pays what they owe.

A receipt is one payment shared over the customer's unpaid invoices - the ones named, or the oldest first. The money is
recorded through Payments (so M-Pesa and bank money can be matched like any other), the invoices are marked paid in part
or in full, and Finance moves it from "accounts receivable" to cash, M-Pesa or the bank (`customer.paid`). A payment
cannot be more than is owed: advance payments are not supported yet. If the payment is reversed (in Payments, or here),
the invoices are owed again and Finance puts the books back.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.public import find_customer
from ziira.modules.payments.public import account_for_method, record_payment, reverse_payment
from ziira.modules.pos.permissions import RECEIVABLES_MANAGE, RECEIVABLES_VIEW
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import CustomerReceipt, CustomerReceiptAllocation
from ziira.modules.pos.services import invoices, tills
from ziira.modules.pos.services.common import unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
    publish,
)

METHODS = ("cash", "mpesa", "bank", "card", "cheque", "other")


@dataclass
class ReceiptView:
    receipt: CustomerReceipt
    allocations: list[CustomerReceiptAllocation]


def _scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in (RECEIVABLES_VIEW, RECEIVABLES_MANAGE):
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found.update(scopes)
    return sorted(found, key=str)


def _can_see(receipt: CustomerReceipt) -> bool:
    scopes = _scopes()
    return scopes is None or any((c is None or c == receipt.company_id) and (b is None or b == receipt.branch_id)
                                 for c, b in scopes)


def get_receipt(session: Session, receipt_id: UUID) -> ReceiptView:
    receipt = pos_repo.get_receipt(session, receipt_id)
    if receipt is None or not _can_see(receipt):
        raise NotFound("Receipt not found")
    return ReceiptView(receipt, pos_repo.receipt_allocations(session, receipt.id))


def list_receipts(session: Session, *, customer_id: UUID | None = None, limit: int = 50,
                  offset: int = 0) -> list[CustomerReceipt]:
    return pos_repo.list_receipts(session, _scopes(), customer_id=customer_id, limit=min(limit, 200), offset=offset)


def receive_payment(session: Session, *, customer_id: UUID, amount: Decimal, method: str,
                    branch_id: UUID | None = None, payment_account_id: UUID | None = None,
                    external_ref: str | None = None, received_on: date | None = None,
                    allocations: list[tuple[UUID, Decimal]] | None = None,
                    till_session_id: UUID | None = None) -> ReceiptView:
    """Record a customer's payment against their invoices (the named ones, or the oldest first). Cash can be put
    through the cashier's open till so the drawer count includes it. Needs 'receivables.manage' at the branch."""
    ctx = current_context()
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Enable CRM to take payments from customers")
    customer = find_customer(session, customer_id)
    if customer is None:
        raise NotFound("Customer not found")
    company_id = customer.company_id
    if method not in METHODS:
        raise ValidationFailed(f"Method must be one of: {', '.join(METHODS)}")
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed("A payment is more than zero with at most 2 decimal places")

    till = None
    if till_session_id is not None:
        till = pos_repo.get_till(session, till_session_id, share=True)
        if till is None or till.cashier_id != ctx.user_id or till.status != "open":
            raise ValidationFailed("Use your own open till")
        if method != "cash":
            raise ValidationFailed("Only cash goes through the till")
        branch_id = till.branch_id
    if branch_id is None:
        raise ValidationFailed("Say which branch is taking the payment")
    check_company(session, company_id, branch_id)
    ctx.require(RECEIVABLES_MANAGE, company_id=company_id, branch_id=branch_id)

    open_invoices = pos_repo.open_invoices_of(session, customer.id, lock=True)
    by_id = {x.id: x for x in open_invoices}
    if allocations is None:
        plan, left = [], amount
        for invoice in open_invoices:
            if left <= 0:
                break
            part = min(left, invoices.outstanding(invoice))
            plan.append((invoice.id, part))
            left -= part
        if left > 0:
            raise ValidationFailed(f"{customer.name} owes {amount - left}: the payment ({amount}) is more than is owed")
    else:
        plan = list(allocations)
        if len({i for i, _ in plan}) != len(plan):
            raise ValidationFailed("An invoice appears once in a payment")
        if sum((a for _, a in plan), Decimal(0)) != amount:
            raise ValidationFailed("The amounts given to invoices must add up to the payment")
        for invoice_id, part in plan:
            named = by_id.get(invoice_id)
            if named is None:
                raise ValidationFailed("An invoice named is not an unpaid invoice of this customer")
            if part <= 0 or part != part.quantize(Decimal("0.01")) or part > invoices.outstanding(named):
                raise ValidationFailed(f"{named.number}: only {invoices.outstanding(named)} is owed")
    if not plan:
        raise ValidationFailed(f"{customer.name} has no unpaid invoices")

    day = received_on or tills.today()
    account_id = payment_account_id
    if account_id is None and method != "cash":
        account_id = account_for_method(session, company_id, branch_id, "bank" if method == "cheque" else method)
        if account_id is None:
            raise ValidationFailed(f"No {method} account is set up for this branch")
    receipt = CustomerReceipt(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="customer_receipt",
                                    prefix="RCT"), customer_id=customer.id, till_session_id=till.id if till else None,
        method=method, amount=amount, received_on=day, reference=(external_ref or "").strip().upper()[:60] or None)
    pos_repo.add(session, receipt)
    paid = record_payment(
        session, company_id=company_id, branch_id=branch_id, method="bank" if method == "cheque" else method,
        amount=amount, direction="in", payment_account_id=account_id, business_date=day, external_ref=external_ref,
        party_type="customer", party_id=customer.id, allocations=[("sales_invoice", i, a) for i, a in plan],
        till_session_id=till.id if till else None)
    receipt.payment_id = paid.id
    rows = []
    for invoice_id, part in plan:
        invoice = by_id[invoice_id]
        invoice.amount_paid += part
        invoices.settle_status(invoice)
        rows.append(CustomerReceiptAllocation(tenant_id=ctx.tenant_id, receipt_id=receipt.id, invoice_id=invoice_id,
                                              amount=part))
    session.add_all(rows)
    session.flush()
    audit_record(session, "receive", "pos.customer_receipt", receipt.id,
                 {"number": receipt.number, "customer": customer.code, "amount": amount, "method": method})
    publish(session, Event("customer.paid", "pos.customer_receipt", receipt.id, {
        "company_id": company_id, "branch_id": branch_id, "business_date": day, "amount": amount, "method": method,
        "customer_id": customer.id, "number": receipt.number}))
    return ReceiptView(receipt, rows)


def reverse_receipt(session: Session, receipt_id: UUID, reason: str) -> ReceiptView:
    """Cancel a customer's payment that was recorded wrongly or bounced: the invoices are owed again. Needs
    'receivables.manage'; a reason is required."""
    receipt = pos_repo.get_receipt(session, receipt_id, lock=True)
    if receipt is None or not _can_see(receipt):
        raise NotFound("Receipt not found")
    current_context().require(RECEIVABLES_MANAGE, company_id=receipt.company_id, branch_id=receipt.branch_id)
    if receipt.status != "posted":
        raise Conflict("This receipt is already reversed")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if receipt.payment_id is None:
        raise ValidationFailed("This receipt has no payment to reverse")
    reverse_payment(session, receipt.payment_id, reason.strip())     # the event below brings the invoices up to date
    session.refresh(receipt)
    return ReceiptView(receipt, pos_repo.receipt_allocations(session, receipt.id))


def apply_payment_reversal(session: Session, event: Event) -> None:
    """A payment was reversed in Payments (from `payment.reversed`): the invoices it paid are owed again."""
    payload = event.payload
    if payload.get("direction") != "in":
        return
    if not any(a.get("doc_type") == "sales_invoice" for a in payload.get("allocations") or []):
        return
    receipt = pos_repo.receipt_by_payment(session, event.aggregate_id, lock=True)
    if receipt is None or receipt.status != "posted":
        return
    for allocation in pos_repo.receipt_allocations(session, receipt.id):
        invoice = pos_repo.get_invoice(session, allocation.invoice_id, lock=True)
        if invoice is not None and invoice.status != "cancelled":
            invoice.amount_paid = max(invoice.amount_paid - allocation.amount, Decimal(0))
            invoices.settle_status(invoice)
    receipt.status, receipt.reversed_at, receipt.reverse_reason = "reversed", datetime.now(UTC), payload.get("reason")
    session.flush()
    audit_record(session, "reverse", "pos.customer_receipt", receipt.id, {"number": receipt.number})
    publish(session, Event("customer.payment_reversed", "pos.customer_receipt", receipt.id, {
        "company_id": receipt.company_id, "branch_id": receipt.branch_id, "business_date": tills.today(),
        "amount": receipt.amount, "method": receipt.method, "customer_id": receipt.customer_id,
        "number": receipt.number}))
