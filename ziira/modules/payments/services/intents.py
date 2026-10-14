"""Use cases: asking a customer to pay by M-Pesa (STK push) and learning the outcome.

    pending --callback or status check--> succeeded | failed | cancelled | timeout

`start_stk_push` records the intent and queues the call to Safaricom (done by the worker, never inside the cashier's
request). Safaricom answers by calling back; if the callback never comes, a status check settles it. Either way the
outcome is applied once, and success records the transaction (the M-Pesa receipt) for matching.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.payments.domain import mpesa
from ziira.modules.payments.permissions import PAYMENTS_COLLECT
from ziira.modules.payments.public import PROVIDER_EXTENSION, PaymentProvider, StkQuery, StkRequest
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import PaymentIntent
from ziira.modules.payments.services import accounts, external
from ziira.modules.payments.services.access import can_view, view_scopes
from ziira.sdk import (
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    decrypt_text,
    encrypt_text,
    enqueue,
    flag_for_review,
    implementations,
    publish,
    settings_public_base_url,
    sign_value,
    verify_value,
)

PROMPT_LIFETIME = timedelta(minutes=3)
FINAL = ("succeeded", "failed", "cancelled", "timeout")


def callback_url(tenant_id: UUID, intent_id: UUID) -> str:
    """Where Safaricom reports this prompt's outcome: the address carries a signature, so only we can make it."""
    return (f"{settings_public_base_url().rstrip('/')}/api/v1/payments/callbacks/stk/"
            f"{tenant_id.hex}/{intent_id}/{sign_value(f'stk:{intent_id}')}")


def check_callback(tenant_id: UUID, intent_id: UUID, signature: str) -> bool:
    return verify_value(f"stk:{intent_id}", signature) and tenant_id is not None


def start_stk_push(session: Session, *, account_id: UUID, amount: Decimal, phone: str, doc_type: str | None = None,
                   doc_id: UUID | None = None, account_reference: str | None = None) -> PaymentIntent:
    """Ask the customer on `phone` to pay `amount` to the M-Pesa till or paybill. Needs 'payments.collect' for the
    account's branch."""
    ctx = current_context()
    account = payments_repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Payment account not found")
    check_company(session, account.company_id, account.branch_id)
    ctx.require(PAYMENTS_COLLECT, company_id=account.company_id, branch_id=account.branch_id)
    accounts.check_active(account)
    if account.kind != "mobile_money":
        raise ValidationFailed("Only an M-Pesa account can send a payment prompt")
    if account.credential_id is None:
        raise ValidationFailed(f"{account.name} has no M-Pesa credentials yet")
    limit = Decimal(str(account.config.get("stk_max", mpesa.MAX_STK_AMOUNT)))
    amount = mpesa.check_stk_amount(mpesa.parse_amount(amount), limit)
    msisdn = mpesa.normalize_phone(phone)
    intent = PaymentIntent(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, payment_account_id=account.id, kind="stk_push", amount=amount,
        phone_masked=mpesa.mask_phone(msisdn), phone_hash=mpesa.phone_fingerprint(msisdn), doc_type=doc_type,
        doc_id=doc_id, account_reference=(account_reference or "").strip()[:12] or None,
        expires_at=datetime.now(UTC) + PROMPT_LIFETIME, company_id=account.company_id, branch_id=account.branch_id)
    payments_repo.add(session, intent)
    enqueue(session, "payments.send_stk", {"intent_id": str(intent.id), "phone": encrypt_text(msisdn)},
            dedupe_key=f"send_stk:{intent.id}")
    audit_record(session, "stk_push", "payments.payment_intent", intent.id,
                 {"amount": amount, "phone": intent.phone_masked, "doc_type": doc_type})
    return intent


def provider_for(session: Session, name: str) -> PaymentProvider:
    for provider in implementations(session, PROVIDER_EXTENSION):
        if provider.name == name:
            return provider  # type: ignore[no-any-return]
    raise ValidationFailed(f"No payment provider called '{name}' is enabled")


def send(session: Session, intent_id: UUID, encrypted_phone: str) -> None:
    """The worker's step: tell the provider to send the prompt. Raises (to be retried) when it is unreachable."""
    intent = payments_repo.get_intent(session, intent_id, lock=True)
    if intent is None or intent.status != "pending" or intent.provider_request_id is not None:
        return                                           # already sent, settled or gone
    account = payments_repo.get_account(session, intent.payment_account_id)
    assert account is not None
    if intent.expires_at and datetime.now(UTC) > intent.expires_at:
        _finish(session, intent, "timeout", "expired", "The prompt expired before it could be sent")
        return
    response = provider_for(session, account.provider).stk_push(StkRequest(
        shortcode=account.shortcode or "", till_type=str(account.config.get("till_type", "paybill")),
        amount=intent.amount, msisdn=decrypt_text(encrypted_phone),
        callback_url=callback_url(session_tenant(), intent.id),
        account_reference=intent.account_reference or "Payment", description="Payment",
        credentials=accounts.credentials_of(session, account),
        environment=str(account.config.get("environment", "sandbox")), party_b=account.config.get("party_b")))
    if response.accepted:
        intent.provider_request_id = response.provider_request_id
        session.flush()
        enqueue(session, "payments.check_stk", {"intent_id": str(intent.id)}, delay_seconds=45,
                dedupe_key=f"check_stk:{intent.id}:0")
    elif response.permanent_failure:
        _finish(session, intent, "failed", "refused", response.message)
        flag_for_review(session, unit="payments", kind="stk_refused", severity="medium", company_id=intent.company_id,
                        branch_id=intent.branch_id, ref_type="payment_intent", ref_id=intent.id, amount=intent.amount,
                        dedupe_key=f"stk_refused:{intent.id}",
                        message=f"The M-Pesa prompt was refused: {response.message}")
    else:
        raise RuntimeError(response.message or "The provider could not be reached")


def session_tenant() -> UUID:
    return current_context().tenant_id


def check(session: Session, intent_id: UUID, attempt: int = 0) -> None:
    """The worker's step: ask Safaricom what became of a prompt whose callback has not come."""
    intent = payments_repo.get_intent(session, intent_id, lock=True)
    if intent is None or intent.status != "pending" or intent.provider_request_id is None:
        return
    account = payments_repo.get_account(session, intent.payment_account_id)
    assert account is not None
    result = provider_for(session, account.provider).query_stk(StkQuery(
        shortcode=account.shortcode or "", provider_request_id=intent.provider_request_id,
        credentials=accounts.credentials_of(session, account),
        environment=str(account.config.get("environment", "sandbox"))))
    if result.result_code >= 0 and (result.succeeded or result.result_code != 1037):
        apply_result(session, intent, result, {"source": "status_query"})
    elif intent.expires_at and datetime.now(UTC) > intent.expires_at + timedelta(minutes=2):
        _finish(session, intent, "timeout", "timeout", "No answer from the customer or Safaricom")
    else:
        enqueue(session, "payments.check_stk", {"intent_id": str(intent.id), "attempt": attempt + 1},
                delay_seconds=30, dedupe_key=f"check_stk:{intent.id}:{attempt + 1}")


def handle_callback(session: Session, intent_id: UUID, payload: dict[str, Any]) -> None:
    """Safaricom's callback for a prompt. Applying it twice does nothing the second time."""
    result = mpesa.parse_stk_callback(payload)
    intent = payments_repo.get_intent(session, intent_id, lock=True)
    if intent is None or (intent.provider_request_id and intent.provider_request_id != result.checkout_request_id):
        raise NotFound("Payment prompt not found")
    if intent.provider_request_id is None:
        intent.provider_request_id = result.checkout_request_id      # the callback beat our own bookkeeping
    apply_result(session, intent, result, payload)


def apply_result(session: Session, intent: PaymentIntent, result: mpesa.StkResult, raw: dict[str, Any]) -> None:
    if intent.status in FINAL:
        return
    if not result.succeeded:
        _finish(session, intent, "cancelled" if result.cancelled else "failed", str(result.result_code),
                result.description)
        return
    account = payments_repo.get_account(session, intent.payment_account_id)
    assert account is not None
    if not result.receipt:
        raise ValidationFailed("A successful result must carry the M-Pesa receipt")
    paid = result.amount or intent.amount
    txn, _ = external.record_external(
        session, account, source="daraja_stk", external_ref=result.receipt, txn_time=result.time or datetime.now(UTC),
        direction="in", amount=paid, bill_ref=intent.account_reference, payer_phone=result.phone, raw=raw)
    if result.phone and mpesa.phone_fingerprint(result.phone) != intent.phone_hash:
        flag_for_review(session, unit="payments", kind="stk_other_payer", severity="low", company_id=intent.company_id,
                        branch_id=intent.branch_id, ref_type="payment_intent", ref_id=intent.id, amount=paid,
                        dedupe_key=f"stk_other_payer:{intent.id}",
                        message=f"{result.receipt} was paid from a different phone than the prompt was sent to")
    if paid != intent.amount:
        flag_for_review(session, unit="payments", kind="stk_amount_differs", severity="medium",
                        company_id=intent.company_id, branch_id=intent.branch_id, ref_type="payment_intent",
                        ref_id=intent.id, amount=paid, dedupe_key=f"stk_amount:{intent.id}",
                        message=f"The prompt was for {intent.amount} but {paid} was paid ({result.receipt})")
    intent.external_transaction_id = txn.id
    _finish(session, intent, "succeeded", str(result.result_code), result.description, receipt=result.receipt)


def _finish(session: Session, intent: PaymentIntent, status: str, code: str, message: str,
            receipt: str | None = None) -> None:
    intent.status, intent.result_code = status, code[:50]
    session.flush()
    audit_record(session, f"stk_{status}", "payments.payment_intent", intent.id, {"message": message[:200]})
    publish(session, Event("stk.completed", "payments.payment_intent", intent.id, {
        "company_id": intent.company_id, "branch_id": intent.branch_id, "status": status, "amount": intent.amount,
        "receipt": receipt, "doc_type": intent.doc_type, "doc_id": intent.doc_id, "message": message[:200]}))


def get_intent(session: Session, intent_id: UUID) -> PaymentIntent:
    intent = payments_repo.get_intent(session, intent_id)
    if intent is None or intent.company_id is None or not can_view(intent.company_id, intent.branch_id):
        raise NotFound("Payment prompt not found")
    return intent


def list_intents(session: Session, *, status: str | None = None, doc_id: UUID | None = None, limit: int = 100,
                 offset: int = 0) -> list[PaymentIntent]:
    return payments_repo.list_intents(session, view_scopes(), status=status, doc_id=doc_id, limit=min(limit, 500),
                                      offset=offset)


def receipt_of(session: Session, intent: PaymentIntent) -> str | None:
    """The M-Pesa receipt of a successful prompt."""
    if intent.external_transaction_id is None:
        return None
    txn = payments_repo.get_external(session, intent.external_transaction_id)
    return txn.external_ref if txn else None
