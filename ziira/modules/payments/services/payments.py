"""Use cases: recording money received or paid, in the one payments model (specification section 10)."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from ziira.modules.payments.domain import mpesa
from ziira.modules.payments.permissions import PAYMENTS_RECORD
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import Payment, PaymentAllocation
from ziira.modules.payments.services import accounts, closing
from ziira.modules.payments.services.access import can_view, view_scopes
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    enqueue,
    next_document_number,
    publish,
)

METHODS = ("cash", "mpesa", "bank", "card", "cheque", "other")
KIND_FOR_METHOD = {"cash": ("cash",), "mpesa": ("mpesa_till", "mpesa_paybill"), "bank": ("bank",), "card": ("card",),
                   "cheque": ("bank", "cash"), "other": ("bank", "cash", "card", "mpesa_till", "mpesa_paybill")}
PARTY_TYPES = ("customer", "supplier", "employee", "other")
NAIROBI = timezone(timedelta(hours=3))


def today() -> date:
    return datetime.now(UTC).astimezone(NAIROBI).date()


def record_payment(session: Session, *, company_id: UUID, branch_id: UUID | None, method: str, amount: Decimal,
                   direction: str = "in", payment_account_id: UUID | None = None, business_date: date | None = None,
                   external_ref: str | None = None, phone: str | None = None, party_type: str | None = None,
                   party_id: UUID | None = None, allocations: list[tuple[str, UUID, Decimal]] | None = None,
                   till_session_id: UUID | None = None, paid_at: datetime | None = None) -> Payment:
    """Record money received (direction 'in') or paid ('out'), allocate it to documents, and ask for it to be matched.

    Called by other units (a sale's payments) and by people (`POST /payments`, which checks 'payments.record').
    `allocations` are (document type, document id, amount); they may add up to less than the payment (the rest is on
    account) but never more. A day whose close is locked cannot be changed.
    """
    ctx = current_context()
    check_company(session, company_id, branch_id)
    if method not in METHODS:
        raise ValidationFailed(f"Method must be one of: {', '.join(METHODS)}")
    if direction not in ("in", "out"):
        raise ValidationFailed("Direction must be 'in' or 'out'")
    amount = mpesa.parse_amount(amount, "Payment amount")
    if party_type is not None and party_type not in PARTY_TYPES:
        raise ValidationFailed(f"Party type must be one of: {', '.join(PARTY_TYPES)}")
    day = business_date or today()
    closing.check_day_open(session, branch_id, day)

    if payment_account_id is None:
        if method != "cash" or branch_id is None:
            raise ValidationFailed("Choose the payment account the money went through")
        account = accounts.cash_account_for_branch(session, company_id, branch_id)
    else:
        account = accounts.check_active(payments_repo.get_account(session, payment_account_id), company_id)
    if account.kind not in KIND_FOR_METHOD[method]:
        raise ValidationFailed(f"A {method} payment cannot go through a {account.kind.replace('_', ' ')} account")

    reference = external_ref.strip().upper() if external_ref and external_ref.strip() else None
    if reference and len(reference) > 60:
        raise ValidationFailed("The reference is too long")
    if reference and method in ("mpesa", "card", "bank"):
        for earlier in payments_repo.list_payments(session, None, external_ref=reference, limit=50):
            if earlier.payment_account_id == account.id and earlier.status == "posted" \
                    and earlier.amount == amount and earlier.direction == direction:
                raise Conflict(f"{reference} has already been recorded for {amount}")
    fingerprint = mpesa.phone_fingerprint(phone) if phone else None

    allocated = Decimal(0)
    for doc_type, _, part in allocations or []:
        if not doc_type or part <= 0:
            raise ValidationFailed("Each allocation needs a document type and a positive amount")
        allocated += part
    if allocated > amount:
        raise ValidationFailed(f"The allocations ({allocated}) are more than the payment ({amount})")

    payment = Payment(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="payment",
                                    prefix="PAY"),
        direction=direction, method=method, payment_account_id=account.id, amount=amount, business_date=day,
        party_type=party_type, party_id=party_id, external_ref=reference, phone_hash=fingerprint,
        till_session_id=till_session_id)
    if paid_at is not None:
        payment.created_at = paid_at                       # an offline sale: the payment happened when it was taken
    payments_repo.add(session, payment)
    for doc_type, doc_id, part in allocations or []:
        session.add(PaymentAllocation(tenant_id=ctx.tenant_id, payment_id=payment.id, doc_type=doc_type,
                                      doc_id=doc_id, amount=part))
    session.flush()
    audit_record(session, "record", "payments.payment", payment.id,
                 {"number": payment.number, "method": method, "amount": amount, "direction": direction})
    publish(session, Event("payment.received" if direction == "in" else "payment.made", "payments.payment",
                           payment.id, {
        "company_id": company_id, "branch_id": branch_id, "number": payment.number, "method": method,
        "amount": amount, "business_date": day, "party_type": party_type, "party_id": party_id,
        "payment_account_id": account.id}))
    if method in ("mpesa", "card", "bank"):
        request_matching(session, account.id)
    return payment


def request_matching(session: Session, account_id: UUID) -> None:
    """Ask the worker to match this account's money soon. Matching is safe to repeat, so every request simply queues a
    job (a bulk import asks once, at the end)."""
    enqueue(session, "payments.match", {"account_id": str(account_id)}, delay_seconds=2)


def get_payment(session: Session, payment_id: UUID) -> Payment:
    payment = payments_repo.get_payment(session, payment_id)
    if payment is None or not can_view(payment.company_id, payment.branch_id):
        raise NotFound("Payment not found")
    return payment


def list_payments(session: Session, *, branch_id: UUID | None = None, method: str | None = None,
                  business_date: date | None = None, external_ref: str | None = None, doc_id: UUID | None = None,
                  limit: int = 100, offset: int = 0) -> list[Payment]:
    """Payments the user may see, newest first."""
    return payments_repo.list_payments(session, view_scopes(), branch_id=branch_id, method=method,
                                       business_date=business_date,
                                       external_ref=external_ref.strip().upper() if external_ref else None,
                                       doc_id=doc_id, limit=min(limit, 500), offset=offset)


def reverse_payment(session: Session, payment_id: UUID, reason: str) -> Payment:
    """Cancel a payment that was recorded by mistake (it stays on record as reversed). Needs 'payments.record'."""
    payment = payments_repo.get_payment(session, payment_id, lock=True)
    if payment is None:
        raise NotFound("Payment not found")
    current_context().require(PAYMENTS_RECORD, company_id=payment.company_id, branch_id=payment.branch_id)
    if payment.status != "posted":
        raise Conflict(f"This payment is already {payment.status}")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    closing.check_day_open(session, payment.branch_id, payment.business_date)
    if payments_repo.matched_amount_for_payment(session, payment.id) > 0:
        raise ValidationFailed("This payment is matched to money that arrived: undo the match first")
    payment.status = "reversed"
    session.flush()
    audit_record(session, "reverse", "payments.payment", payment.id, {"reason": reason.strip()})
    return payment
