"""Matching money that arrived (external transactions) to the payments people recorded. Pure Python.

Three stages, each running only on what the previous one left (specification section 10):
 1. exact reference   the mobile money receipt code (or bank reference) on the payment equals the transaction's;
 2. account number    the paybill account number the customer typed equals the payment's number;
 3. rules             same account and amount, close in time, scored; applied when confident enough, else proposed.
What nothing matches becomes an exception for a person. Amounts are tracked as what is still unmatched, so one
transaction can cover several payments and one payment can be covered by several transactions.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

EXACT, ACCOUNT_NUMBER, RULE = "exact_reference", "account_number", "rule"
APPLY_THRESHOLD = Decimal("0.9")
DEFAULT_WINDOW = timedelta(minutes=30)
CLOSE_IN_TIME = timedelta(minutes=5)


@dataclass(frozen=True)
class Txn:
    """Money that arrived (or left) according to the provider, with what is still unmatched."""

    id: UUID
    account_id: UUID
    ref: str
    unmatched: Decimal
    time: datetime
    bill_ref: str | None = None
    phone_hash: str | None = None
    direction: str = "in"


@dataclass(frozen=True)
class Pay:
    """A payment someone recorded, with what is still unmatched."""

    id: UUID
    account_id: UUID
    unmatched: Decimal
    time: datetime
    external_ref: str | None = None
    number: str | None = None
    phone_hash: str | None = None
    direction: str = "in"


@dataclass(frozen=True)
class Proposal:
    txn_id: UUID
    pay_id: UUID
    amount: Decimal
    stage: str
    rule_code: str | None
    confidence: Decimal
    apply: bool


def _norm(value: str | None) -> str | None:
    cleaned = (value or "").strip().upper()
    return cleaned or None


def match_all(txns: list[Txn], pays: list[Pay], *, window: timedelta = DEFAULT_WINDOW,
              threshold: Decimal = APPLY_THRESHOLD) -> list[Proposal]:
    """Propose matches between transactions and payments, stage by stage."""
    txn_left = {t.id: t.unmatched for t in txns}
    pay_left = {p.id: p.unmatched for p in pays}
    out: list[Proposal] = []

    def take(txn: Txn, pay: Pay, stage: str, rule: str | None, confidence: Decimal, apply: bool) -> None:
        amount = min(txn_left[txn.id], pay_left[pay.id])
        if amount <= 0:
            return
        out.append(Proposal(txn.id, pay.id, amount, stage, rule, confidence, apply))
        if apply:                                         # only applied matches use up the amounts
            txn_left[txn.id] -= amount
            pay_left[pay.id] -= amount

    ordered_txns = sorted(txns, key=lambda t: (t.time, str(t.id)))
    ordered_pays = sorted(pays, key=lambda p: (p.time, str(p.id)))

    # 1. exact reference
    for txn in ordered_txns:
        ref = _norm(txn.ref)
        for pay in ordered_pays:
            if ref and _norm(pay.external_ref) == ref and pay.account_id == txn.account_id \
                    and pay.direction == txn.direction and txn_left[txn.id] > 0 and pay_left[pay.id] > 0:
                take(txn, pay, EXACT, None, Decimal("1"), True)

    # 2. account number (the paybill account the customer typed)
    for txn in ordered_txns:
        bill = _norm(txn.bill_ref)
        for pay in ordered_pays:
            if bill and _norm(pay.number) == bill and pay.account_id == txn.account_id \
                    and pay.direction == txn.direction and txn_left[txn.id] > 0 and pay_left[pay.id] > 0:
                take(txn, pay, ACCOUNT_NUMBER, None, Decimal("0.98"), True)

    # 3. rules: same account and amount, close in time, scored
    claimed: set[UUID] = set()
    for txn in ordered_txns:
        if txn_left[txn.id] <= 0:
            continue
        scored: list[tuple[Decimal, Pay]] = []
        for pay in ordered_pays:
            if (pay.id in claimed or pay_left[pay.id] <= 0 or pay.account_id != txn.account_id
                    or pay.direction != txn.direction or pay_left[pay.id] != txn_left[txn.id]):
                continue
            gap = abs(pay.time - txn.time)
            if gap > window:
                continue
            score = Decimal("0.6")
            if txn.phone_hash and pay.phone_hash:
                if txn.phone_hash == pay.phone_hash:
                    score += Decimal("0.3")
                else:
                    continue                              # a different payer: not this payment
            if gap <= CLOSE_IN_TIME:
                score += Decimal("0.1")
            scored.append((score, pay))
        if not scored:
            continue
        scored.sort(key=lambda sp: (-sp[0], sp[1].time, str(sp[1].id)))
        best_score, best = scored[0]
        if len(scored) > 1 and scored[1][0] == best_score:
            continue                                      # two equally good candidates: leave it to a person
        apply = best_score >= threshold
        take(txn, best, RULE, "amount_account_time" if best_score < Decimal("0.9") else "amount_account_phone_time",
             best_score, apply)
        if not apply:
            claimed.add(best.id)                          # proposed to this transaction; do not propose it twice
    return out
