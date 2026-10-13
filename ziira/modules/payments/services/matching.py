"""Use cases: matching money that arrived to the payments people recorded (specification section 10).

`run_matching` applies the engine of domain/matching.py: exact reference, then account number, then rules. Confident
matches are applied; weaker ones are proposed for a person to accept. What stays unmatched for a while becomes an
exception.
Every match records the stage, the rule and who did it, and can be undone (the history is kept).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.payments.domain import matching
from ziira.modules.payments.permissions import RECON_MATCH
from ziira.modules.payments.repository import payments_repo
from ziira.modules.payments.repository.models import ExternalTransaction, Match, Payment
from ziira.modules.payments.services import closing
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    flag_for_review,
    publish,
)

UNMATCHED_GRACE = timedelta(hours=2)          # a transaction nobody has claimed after this long needs a person
NO_TRANSACTION_GRACE = timedelta(hours=24)    # a card/M-Pesa payment with no provider record after this long, too


@dataclass(frozen=True)
class MatchRun:
    applied: int
    proposed: int
    flagged: int


def _status_of(session: Session, txn: ExternalTransaction) -> str:
    if txn.match_status == "ignored":
        return "ignored"
    matched = payments_repo.matched_amount_for_txn(session, txn.id)
    if matched >= txn.amount:
        return "matched"
    proposed = payments_repo.list_matches(session, txn_id=txn.id, status="proposed", limit=1)
    return "proposed" if proposed else "unmatched"


def refresh_status(session: Session, txn_id: UUID) -> None:
    txn = payments_repo.get_external(session, txn_id, lock=True)
    if txn is not None:
        txn.match_status = _status_of(session, txn)
        session.flush()


def run_matching(session: Session, account_id: UUID | None = None, *, now: datetime | None = None) -> MatchRun:
    """Match what is unmatched (one account, or all). Safe to run as often as you like."""
    now = now or datetime.now(UTC)
    ctx = current_context()
    open_txns = payments_repo.open_transactions(session, account_id)
    open_pays = payments_repo.open_payments(session, account_id)
    by_txn = {o.txn.id: o.txn for o in open_txns}
    by_pay = {o.payment.id: o.payment for o in open_pays}
    txns = [matching.Txn(o.txn.id, o.txn.payment_account_id, o.txn.external_ref, o.unmatched, o.txn.txn_time,
                         o.txn.bill_ref, o.txn.phone_hash, o.txn.direction) for o in open_txns]
    pays = [matching.Pay(o.payment.id, o.payment.payment_account_id, o.unmatched, o.payment.created_at,
                         o.payment.external_ref, o.payment.number, o.payment.phone_hash, o.payment.direction)
            for o in open_pays]
    applied = proposed = 0
    touched: set[UUID] = set()
    for p in matching.match_all(txns, pays):
        if payments_repo.live_match(session, p.txn_id, p.pay_id) is not None:
            continue                                     # already proposed (or applied) on an earlier run
        payment = by_pay[p.pay_id]
        if p.apply:
            closing.check_day_open(session, payment.branch_id, payment.business_date)
        match = Match(tenant_id=ctx.tenant_id, created_by=ctx.user_id, external_transaction_id=p.txn_id,
                      payment_id=p.pay_id, amount=p.amount, stage=p.stage, rule_code=p.rule_code,
                      confidence=p.confidence, status="applied" if p.apply else "proposed")
        payments_repo.add(session, match)
        touched.add(p.txn_id)
        if p.apply:
            applied += 1
            audit_record(session, "match", "payments.match", match.id,
                         {"txn": p.txn_id, "payment": p.pay_id, "amount": p.amount, "stage": p.stage})
            publish(session, Event("payment.matched", "payments.match", match.id, {
                "company_id": payment.company_id, "branch_id": payment.branch_id, "payment_id": p.pay_id,
                "external_transaction_id": p.txn_id, "amount": p.amount, "stage": p.stage}))
        else:
            proposed += 1
    for txn_id in touched:
        refresh_status(session, txn_id)
    return MatchRun(applied, proposed, _flag_the_unclaimed(session, by_txn, by_pay, now))


def _flag_the_unclaimed(session: Session, by_txn: dict[UUID, ExternalTransaction], by_pay: dict[UUID, Payment],
                        now: datetime) -> int:
    flagged = 0
    for txn in by_txn.values():
        fresh = payments_repo.get_external(session, txn.id)
        if fresh is None or fresh.match_status == "matched" or now - fresh.txn_time < UNMATCHED_GRACE:
            continue
        account = payments_repo.get_account(session, fresh.payment_account_id)
        if account is None:
            continue
        item = flag_for_review(
            session, unit="payments", kind="unmatched_transaction", severity="medium", company_id=account.company_id,
            branch_id=account.branch_id, ref_type="external_transaction", ref_id=fresh.id, amount=fresh.amount,
            dedupe_key=f"unmatched_txn:{fresh.id}",
            message=f"{fresh.external_ref} for {fresh.amount} on {account.name} is not matched to any sale or payment")
        if item is not None:
            flagged += 1
            publish(session, Event("payment.unmatched", "payments.external_transaction", fresh.id, {
                "company_id": account.company_id, "branch_id": account.branch_id, "amount": fresh.amount,
                "external_ref": fresh.external_ref}))
    for payment in by_pay.values():
        if now - payment.created_at < NO_TRANSACTION_GRACE:
            continue
        item = flag_for_review(
            session, unit="payments", kind="payment_without_transaction", severity="medium",
            company_id=payment.company_id, branch_id=payment.branch_id, ref_type="payment", ref_id=payment.id,
            amount=payment.amount, dedupe_key=f"payment_no_txn:{payment.id}",
            message=f"{payment.number} ({payment.method}, {payment.amount}) has no matching record from the provider")
        flagged += item is not None
    return flagged


# --------------------------------------------------------------------------- people deciding
def _load(session: Session, txn_id: UUID, payment_id: UUID) -> tuple[ExternalTransaction, Payment]:
    txn = payments_repo.get_external(session, txn_id, lock=True)
    payment = payments_repo.get_payment(session, payment_id, lock=True)
    if txn is None or payment is None:
        raise NotFound("Transaction or payment not found")
    return txn, payment


def manual_match(session: Session, txn_id: UUID, payment_id: UUID, amount: Decimal | None = None) -> Match:
    """Match a transaction to a payment by hand (for the amount, or all that is still unmatched on both). Needs
    'recon.match' for the payment's branch."""
    txn, payment = _load(session, txn_id, payment_id)
    current_context().require(RECON_MATCH, company_id=payment.company_id, branch_id=payment.branch_id)
    if txn.match_status == "ignored":
        raise ValidationFailed("That transaction is ignored")
    if payment.status != "posted" or payment.direction != txn.direction:
        raise ValidationFailed("That payment cannot be matched to this transaction")
    if payment.payment_account_id != txn.payment_account_id:
        raise ValidationFailed("The transaction and the payment are on different accounts")
    closing.check_day_open(session, payment.branch_id, payment.business_date)
    live = payments_repo.live_match(session, txn_id, payment_id)
    if live is not None and live.status == "applied":
        raise Conflict("They are already matched")
    free_txn = txn.amount - payments_repo.matched_amount_for_txn(session, txn.id)
    free_pay = payment.amount - payments_repo.matched_amount_for_payment(session, payment.id)
    amount = amount if amount is not None else min(free_txn, free_pay)
    if amount <= 0 or amount > free_txn or amount > free_pay:
        raise ValidationFailed(f"Only {min(free_txn, free_pay)} is still unmatched on both")
    ctx = current_context()
    if live is not None:                                   # a proposal being confirmed by a person
        live.status, live.amount, live.stage, live.updated_by = "applied", amount, "manual", ctx.user_id
        match = live
        session.flush()
    else:
        match = Match(tenant_id=ctx.tenant_id, created_by=ctx.user_id, external_transaction_id=txn_id,
                      payment_id=payment_id, amount=amount, stage="manual", status="applied")
        payments_repo.add(session, match)
    audit_record(session, "match", "payments.match", match.id, {"txn": txn_id, "payment": payment_id, "amount": amount,
                                                                 "stage": "manual"})
    publish(session, Event("payment.matched", "payments.match", match.id, {
        "company_id": payment.company_id, "branch_id": payment.branch_id, "payment_id": payment_id,
        "external_transaction_id": txn_id, "amount": amount, "stage": "manual"}))
    refresh_status(session, txn_id)
    return match


def undo_match(session: Session, match_id: UUID, reason: str) -> Match:
    """Undo a match (it stays on record as undone). Needs 'recon.match' for the payment's branch."""
    match = payments_repo.get_match(session, match_id, lock=True)
    if match is None:
        raise NotFound("Match not found")
    payment = payments_repo.get_payment(session, match.payment_id)
    assert payment is not None
    ctx = current_context()
    ctx.require(RECON_MATCH, company_id=payment.company_id, branch_id=payment.branch_id)
    if match.status == "undone":
        raise Conflict("This match was already undone")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if match.status == "applied":
        closing.check_day_open(session, payment.branch_id, payment.business_date)
    match.status, match.undone_by, match.undone_at = "undone", ctx.user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "unmatch", "payments.match", match.id, {"reason": reason.strip()})
    refresh_status(session, match.external_transaction_id)
    return match


def list_matches(session: Session, *, txn_id: UUID | None = None, payment_id: UUID | None = None,
                 status: str | None = None) -> list[Match]:
    """Matches of a transaction or payment the user may see."""
    from ziira.modules.payments.services.access import can_view

    out = []
    for match in payments_repo.list_matches(session, txn_id=txn_id, payment_id=payment_id, status=status):
        payment = payments_repo.get_payment(session, match.payment_id)
        if payment is not None and can_view(payment.company_id, payment.branch_id):
            out.append(match)
    return out
