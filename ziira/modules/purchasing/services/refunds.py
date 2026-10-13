"""Use cases: money a supplier gives back.

When goods are sent back and credited *after* the bill was paid, the supplier owes the business the difference: the bill
has been paid and credited for more than it was worth. The refund is recorded when that money arrives (through
Payments, so bank and M-Pesa money can be matched like any other), and Finance clears what the supplier owed
(`supplier.refunded`). A refund can be reversed (in Payments or here); a payment that a refund relied on cannot be
reversed until the refund is.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.payments.public import account_for_method, record_payment, reverse_payment
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import BILLS_PAY
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import SupplierBill, SupplierRefund
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import today, unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    next_document_number,
    publish,
)

METHODS = ("cash", "mpesa", "bank", "cheque", "other")


@dataclass
class RefundView:
    refund: SupplierRefund


def due_on(bill: SupplierBill) -> Decimal:
    """What the supplier still owes back on the bill."""
    return rules.refundable(bill.total, bill.amount_paid, bill.credited, bill.refunded)


def get_refund(session: Session, refund_id: UUID) -> RefundView:
    refund = repo.get_refund(session, refund_id)
    if refund is None or not access.can_view(refund.company_id, refund.branch_id):
        raise NotFound("Refund not found")
    return RefundView(refund)


def list_refunds(session: Session, *, supplier_id: UUID | None = None, limit: int = 50,
                 offset: int = 0) -> list[SupplierRefund]:
    return repo.list_refunds(session, access.view_scopes(), supplier_id=supplier_id, limit=min(limit, 200),
                             offset=offset)


def refunds_due(session: Session) -> list[tuple[SupplierBill, Decimal]]:
    """Bills the supplier has been overpaid on, and how much it owes back on each."""
    return [(bill, due_on(bill)) for bill in repo.overpaid_bills(session, access.view_scopes())]


def record_refund(session: Session, bill_id: UUID, *, amount: Decimal, method: str,
                  payment_account_id: UUID | None = None, external_ref: str | None = None,
                  received_on: date | None = None) -> RefundView:
    """Record money a supplier paid back against an overpaid bill. Needs 'bills.pay'. It cannot be more than the
    supplier owes back on the bill."""
    ctx = current_context()
    bill = repo.get_bill(session, bill_id, lock=True)
    if bill is None or not access.can_view(bill.company_id, bill.branch_id):
        raise NotFound("Bill not found")
    ctx.require(BILLS_PAY, company_id=bill.company_id, branch_id=bill.branch_id)
    if not unit_enabled(session, "payments"):
        raise ValidationFailed("Enable Payments to record a refund")
    if method not in METHODS:
        raise ValidationFailed(f"Method must be one of: {', '.join(METHODS)}")
    if amount <= 0 or amount != amount.quantize(rules.CENT):
        raise ValidationFailed("A refund is more than zero with at most 2 decimal places")
    owed_back = due_on(bill)
    if owed_back <= 0:
        raise ValidationFailed("The supplier owes nothing back on this bill")
    if amount > owed_back:
        raise ValidationFailed(f"The supplier owes back {rules.plain(owed_back)} on this bill")
    pay_method = "bank" if method == "cheque" else method
    account_id = payment_account_id
    if account_id is None and pay_method != "cash":
        account_id = account_for_method(session, bill.company_id, bill.branch_id, pay_method)
        if account_id is None:
            raise ValidationFailed(f"No {method} account is set up")
    day = received_on or today()
    refund = SupplierRefund(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=bill.company_id, branch_id=bill.branch_id,
        number=next_document_number(session, company_id=bill.company_id, branch_id=bill.branch_id,
                                    doc_type="supplier_refund", prefix="SRF"), bill_id=bill.id,
        supplier_id=bill.supplier_id, method=method, amount=amount, received_on=day,
        reference=(external_ref or "").strip().upper()[:60] or None)
    repo.add(session, refund)
    paid = record_payment(
        session, company_id=bill.company_id, branch_id=bill.branch_id, method=pay_method, direction="in",
        amount=amount, payment_account_id=account_id, business_date=day, external_ref=external_ref,
        party_type="supplier", party_id=bill.supplier_id, allocations=[("supplier_refund", bill.id, amount)])
    refund.payment_id = paid.id
    bill.refunded += amount
    session.flush()
    audit_record(session, "refund", "purchasing.supplier_refund", refund.id,
                 {"number": refund.number, "bill": bill.number, "amount": amount})
    publish(session, Event("supplier.refunded", "purchasing.supplier_refund", refund.id, {
        "company_id": bill.company_id, "branch_id": bill.branch_id, "business_date": day, "amount": amount,
        "method": pay_method, "supplier_id": bill.supplier_id, "number": refund.number, "bill_id": bill.id}))
    return RefundView(refund)


def reverse_refund(session: Session, refund_id: UUID, reason: str) -> RefundView:
    """Cancel a refund that did not arrive (a bounced cheque, a wrong entry): the supplier owes it again."""
    refund = repo.get_refund(session, refund_id)
    if refund is None or not access.can_view(refund.company_id, refund.branch_id):
        raise NotFound("Refund not found")
    current_context().require(BILLS_PAY, company_id=refund.company_id, branch_id=refund.branch_id)
    if refund.status != "posted" or refund.payment_id is None:
        raise Conflict("This refund is already reversed")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    reverse_payment(session, refund.payment_id, reason.strip())          # the event below brings the bill up to date
    session.refresh(refund)
    return RefundView(refund)


def apply_payment_reversal(session: Session, event: Event) -> None:
    """A payment was reversed in Payments (from `payment.reversed`): a refund received from a supplier goes back to
    being owed."""
    payload = event.payload
    if payload.get("direction") != "in":
        return
    if not any(a.get("doc_type") == "supplier_refund" for a in payload.get("allocations") or []):
        return
    refund = repo.refund_by_payment(session, event.aggregate_id, lock=True)
    if refund is None or refund.status != "posted":
        return
    bill = repo.get_bill(session, refund.bill_id, lock=True)
    refund.status = "reversed"
    if bill is not None:
        bill.refunded = max(bill.refunded - refund.amount, Decimal(0))
    session.flush()
    audit_record(session, "reverse", "purchasing.supplier_refund", refund.id, {"number": refund.number})
    publish(session, Event("supplier.refund_reversed", "purchasing.supplier_refund", refund.id, {
        "company_id": refund.company_id, "branch_id": refund.branch_id, "business_date": today(),
        "amount": refund.amount, "method": "bank" if refund.method == "cheque" else refund.method,
        "supplier_id": refund.supplier_id, "number": refund.number, "bill_id": refund.bill_id,
        "at": datetime.now(UTC).isoformat()}))
