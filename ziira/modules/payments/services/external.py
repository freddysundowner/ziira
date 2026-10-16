"""Use cases: money the provider says moved (external transactions): provider callbacks, statements, manual entries."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ziira.modules.payments.domain import mobile_money, statements
from ziira.modules.payments.permissions import PAYMENTS_RECORD
from ziira.modules.payments.public import STATEMENT_EXTENSION
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import ExternalTransaction, PaymentAccount
from ziira.modules.payments.services import accounts
from ziira.modules.payments.services.access import can_view, view_scopes
from ziira.modules.payments.services.accounts import provider_for
from ziira.modules.payments.services.payments import request_matching
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_setting,
    current_context,
    flag_for_review,
    implementations,
)

PERSONAL_FIELD = re.compile(r"name|phone|msisdn|mobile|payer|customer", re.IGNORECASE)
SOURCE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")      # a provider names its own sources (see PaymentProvider.c2b_source)
MAX_STATEMENT_CHARS = 5_000_000


def record_external(session: Session, account: PaymentAccount, *, source: str, external_ref: str, txn_time: datetime,
                    direction: str, amount: Decimal, fee: Decimal = Decimal(0), bill_ref: str | None = None,
                    payer_name: str | None = None, payer_phone: str | None = None, raw: dict[str, Any] | None = None,
                    request_match: bool = True) -> tuple[ExternalTransaction, bool]:
    """Record a transaction the provider reported. Returns (transaction, created). Reporting the same reference again
    (provider retries, a statement uploaded twice) returns the first one; a *different amount* for a known reference
    is flagged for review, since one of the two reports is wrong."""
    if not SOURCE.match(source):
        raise ValidationFailed("A source is 3-40 lower-case letters, digits or '_'")
    if direction not in ("in", "out"):
        raise ValidationFailed("Direction must be 'in' or 'out'")
    ref = external_ref.strip().upper()
    if not ref or len(ref) > 60:
        raise ValidationFailed("A reference of 1-60 characters is required")
    amount = mobile_money.parse_amount(amount)
    earlier = payments_repo.external_by_ref(session, account.id, ref)
    if earlier is not None:
        if earlier.amount != amount:
            flag_for_review(session, unit="payments", kind="transaction_conflict", severity="high",
                            company_id=account.company_id, branch_id=account.branch_id, ref_type="external_transaction",
                            ref_id=earlier.id, amount=amount, dedupe_key=f"txn_conflict:{earlier.id}:{amount}",
                            message=f"{ref} was reported as {earlier.amount} and again as {amount} ({source})")
        return earlier, False
    ctx = current_context()
    txn = ExternalTransaction(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, payment_account_id=account.id, source=source, external_ref=ref,
        txn_time=txn_time, direction=direction, amount=amount, fee=fee,
        bill_ref=(bill_ref or "").strip().upper() or None,
        counterparty_name=(payer_name or "").strip()[:200] or None,
        counterparty_phone_masked=mobile_money.mask_phone(payer_phone) if payer_phone else None,
        phone_hash=mobile_money.phone_fingerprint(payer_phone) if payer_phone and _usable_phone(payer_phone) else None,
        raw=_scrub(raw or {}))
    payments_repo.add(session, txn)
    if request_match:
        request_matching(session, account.id)
    return txn, True


def _usable_phone(value: str) -> bool:
    try:
        mobile_money.phone_fingerprint(value)
    except ValidationFailed:
        return False
    return True


def _scrub(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep the provider's payload for audit, without the payer's phone number or name in the clear (any field whose
    name suggests a person)."""
    return {k: ("***" if v and PERSONAL_FIELD.search(k) else v) for k, v in raw.items()}


def process_c2b(session: Session, account: PaymentAccount, payload: dict[str, Any]) -> dict[str, Any]:
    """A provider's report of a customer paying one of our tills or paybills. A report for another shortcode is flagged
    and ignored. Returns the reply the provider expects."""
    provider = provider_for(session, account.provider)
    parsed = provider.parse_c2b(payload)
    if account.shortcode and parsed.shortcode and parsed.shortcode != account.shortcode:
        flag_for_review(session, unit="payments", kind="callback_misrouted", severity="high",
                        company_id=account.company_id, branch_id=account.branch_id, ref_type="payment_account",
                        ref_id=account.id, dedupe_key=f"misrouted:{account.id}:{parsed.ref}",
                        message=f"A confirmation for shortcode {parsed.shortcode} reached {account.name} "
                                f"({account.shortcode})")
        return dict(provider.callback_reply)
    record_external(session, account, source=provider.c2b_source, external_ref=parsed.ref, txn_time=parsed.time,
                             direction="in", amount=parsed.amount, bill_ref=parsed.bill_ref,
                             payer_name=parsed.payer_name, payer_phone=parsed.msisdn, raw=payload)
    return dict(provider.callback_reply)


@dataclass
class ImportResult:
    created: int = 0
    duplicates: int = 0
    skipped: list[str] = field(default_factory=list)


def import_statement(session: Session, account_id: UUID, content: str, *, fmt: str,
                     options: dict[str, str] | None = None) -> ImportResult:
    """Read an uploaded statement (`bank` CSV, or a format a provider plugin reads) into external transactions.
    Uploading it twice adds nothing. Needs 'payments.record' for the account."""
    account = payments_repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Payment account not found")
    current_context().require(PAYMENTS_RECORD, company_id=account.company_id, branch_id=account.branch_id)
    accounts.check_active(account)
    if len(content) > MAX_STATEMENT_CHARS:
        raise ValidationFailed("The statement is too large")
    if fmt == "bank":
        zone = ZoneInfo(str(company_setting(session, account.company_id, "timezone")))
        parsed, source = statements.parse_bank_statement(content, tz=zone, **(options or {})), "bank_statement"
    else:
        readers = implementations(session, STATEMENT_EXTENSION)
        chosen = next((r for r in readers if r.name == fmt), None)
        if chosen is None:
            raise ValidationFailed(f"Format must be one of: {', '.join(['bank', *sorted(r.name for r in readers)])}")
        parsed, source = chosen.parse(content), chosen.source
    result = ImportResult(skipped=list(parsed.skipped))
    for row in parsed.rows:
        _, created = record_external(session, account, source=source, external_ref=row.ref, txn_time=row.time,
                                     direction=row.direction, amount=row.amount, bill_ref=row.bill_ref,
                                     payer_name=row.payer_name, payer_phone=row.payer_phone,
                                     raw={"details": row.description}, request_match=False)
        result.created += created
        result.duplicates += not created
    if result.created:
        request_matching(session, account.id)
    audit_record(session, "import_statement", "payments.payment_account", account.id,
                 {"format": fmt, "created": result.created, "duplicates": result.duplicates,
                  "skipped": len(result.skipped)})
    return result


def get_external(session: Session, txn_id: UUID) -> ExternalTransaction:
    txn = payments_repo.get_external(session, txn_id)
    account = payments_repo.get_account(session, txn.payment_account_id) if txn else None
    if txn is None or account is None or not can_view(account.company_id, account.branch_id):
        raise NotFound("Transaction not found")
    return txn


def list_external(session: Session, *, account_id: UUID | None = None, match_status: str | None = None,
                  date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 100,
                  offset: int = 0) -> list[ExternalTransaction]:
    return payments_repo.list_external(session, view_scopes(), account_id=account_id, match_status=match_status,
                                       date_from=date_from, date_to=date_to, limit=min(limit, 500), offset=offset)


def set_ignored(session: Session, txn_id: UUID, ignored: bool, reason: str) -> ExternalTransaction:
    """Mark a transaction as not belonging to the business's sales (or bring it back). Needs 'recon.match'."""
    from ziira.modules.payments.permissions import RECON_MATCH

    txn = payments_repo.get_external(session, txn_id, lock=True)
    account = payments_repo.get_account(session, txn.payment_account_id) if txn else None
    if txn is None or account is None:
        raise NotFound("Transaction not found")
    current_context().require(RECON_MATCH, company_id=account.company_id, branch_id=account.branch_id)
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if ignored:
        if payments_repo.matched_amount_for_txn(session, txn.id) > 0:
            raise ValidationFailed("This transaction is matched: undo its matches first")
        txn.match_status = "ignored"
    elif txn.match_status == "ignored":
        txn.match_status = "unmatched"
    session.flush()
    audit_record(session, "ignore" if ignored else "unignore", "payments.external_transaction", txn.id,
                 {"reason": reason.strip()})
    if not ignored:
        request_matching(session, txn.payment_account_id)
    return txn
