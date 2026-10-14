"""Database access for the payments schema. Row-level security scopes every query to the tenant."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, false, func, or_, select, true
from sqlalchemy.orm import Session

from ziira.modules.payments.repository.models import (
    DailyClose,
    ExternalTransaction,
    Match,
    Payment,
    PaymentAccount,
    PaymentAllocation,
    PaymentIntent,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None


def add(session: Session, record: object) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def in_scope(scopes: Scopes, company_col: Any, branch_col: Any) -> ColumnElement[bool]:
    """Rows of the companies and branches the user may see (a null branch is company-level: company-wide only)."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(company_col == c, true() if b is None else branch_col == b) for c, b in scopes))


# --------------------------------------------------------------------------- accounts
def get_account(session: Session, account_id: UUID) -> PaymentAccount | None:
    return session.get(PaymentAccount, account_id)


def list_accounts(session: Session, scopes: Scopes, *, company_id: UUID | None = None, branch_id: UUID | None = None,
                  kind: str | None = None, include_inactive: bool = False) -> list[PaymentAccount]:
    query = (select(PaymentAccount).where(in_scope(scopes, PaymentAccount.company_id, PaymentAccount.branch_id))
             .order_by(PaymentAccount.company_id, PaymentAccount.name))
    if company_id:
        query = query.where(PaymentAccount.company_id == company_id)
    if branch_id:
        query = query.where(PaymentAccount.branch_id == branch_id)
    if kind:
        query = query.where(PaymentAccount.kind == kind)
    if not include_inactive:
        query = query.where(PaymentAccount.is_active)
    return list(session.scalars(query))


def find_cash_account(session: Session, company_id: UUID, branch_id: UUID) -> PaymentAccount | None:
    return session.scalar(select(PaymentAccount).where(
        PaymentAccount.company_id == company_id, PaymentAccount.branch_id == branch_id,
        PaymentAccount.kind == "cash", PaymentAccount.is_active).order_by(PaymentAccount.created_at).limit(1))


def account_by_callback_hash(session: Session, token_hash: str) -> PaymentAccount | None:
    return session.scalar(select(PaymentAccount).where(PaymentAccount.callback_token_hash == token_hash))


def account_by_shortcode(session: Session, shortcode: str) -> list[PaymentAccount]:
    return list(session.scalars(select(PaymentAccount).where(PaymentAccount.shortcode == shortcode,
                                                             PaymentAccount.is_active)))


# --------------------------------------------------------------------------- external transactions
def get_external(session: Session, txn_id: UUID, *, lock: bool = False) -> ExternalTransaction | None:
    if lock:
        return session.scalars(select(ExternalTransaction).where(ExternalTransaction.id == txn_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(ExternalTransaction, txn_id)


def external_by_ref(session: Session, account_id: UUID, ref: str) -> ExternalTransaction | None:
    return session.scalar(select(ExternalTransaction).where(ExternalTransaction.payment_account_id == account_id,
                                                            ExternalTransaction.external_ref == ref))


def list_external(session: Session, scopes: Scopes, *, account_id: UUID | None = None, match_status: str | None = None,
                  date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 100,
                  offset: int = 0) -> list[ExternalTransaction]:
    query = (select(ExternalTransaction).join(PaymentAccount,
                                              PaymentAccount.id == ExternalTransaction.payment_account_id)
             .where(in_scope(scopes, PaymentAccount.company_id, PaymentAccount.branch_id))
             .order_by(ExternalTransaction.txn_time.desc(), ExternalTransaction.id).limit(limit).offset(offset))
    if account_id:
        query = query.where(ExternalTransaction.payment_account_id == account_id)
    if match_status:
        query = query.where(ExternalTransaction.match_status == match_status)
    if date_from:
        query = query.where(ExternalTransaction.txn_time >= date_from)
    if date_to:
        query = query.where(ExternalTransaction.txn_time <= date_to)
    return list(session.scalars(query))


def matched_amount_for_txn(session: Session, txn_id: UUID) -> Decimal:
    return Decimal(session.scalar(select(func.coalesce(func.sum(Match.amount), 0)).where(
        Match.external_transaction_id == txn_id, Match.status == "applied")) or 0)


def matched_amount_for_payment(session: Session, payment_id: UUID) -> Decimal:
    return Decimal(session.scalar(select(func.coalesce(func.sum(Match.amount), 0)).where(
        Match.payment_id == payment_id, Match.status == "applied")) or 0)


@dataclass(frozen=True)
class OpenTxn:
    txn: ExternalTransaction
    unmatched: Decimal


def open_transactions(session: Session, account_id: UUID | None, limit: int = 2000) -> list[OpenTxn]:
    """Transactions with money still unmatched, with how much."""
    applied = (select(Match.external_transaction_id, func.sum(Match.amount).label("m"))
               .where(Match.status == "applied").group_by(Match.external_transaction_id).subquery())
    query = (select(ExternalTransaction, ExternalTransaction.amount - func.coalesce(applied.c.m, 0))
             .outerjoin(applied, applied.c.external_transaction_id == ExternalTransaction.id)
             .where(ExternalTransaction.match_status.in_(("unmatched", "proposed")),
                    ExternalTransaction.amount - func.coalesce(applied.c.m, 0) > 0)
             .order_by(ExternalTransaction.txn_time).limit(limit))
    if account_id:
        query = query.where(ExternalTransaction.payment_account_id == account_id)
    return [OpenTxn(row[0], Decimal(row[1])) for row in session.execute(query)]


# --------------------------------------------------------------------------- payments
def get_payment(session: Session, payment_id: UUID, *, lock: bool = False) -> Payment | None:
    if lock:
        return session.scalars(select(Payment).where(Payment.id == payment_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(Payment, payment_id)


def allocations(session: Session, payment_id: UUID) -> list[PaymentAllocation]:
    return list(session.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment_id)))


def list_payments(session: Session, scopes: Scopes, *, branch_id: UUID | None = None, method: str | None = None,
                  business_date: date | None = None, external_ref: str | None = None, doc_id: UUID | None = None,
                  limit: int = 100, offset: int = 0) -> list[Payment]:
    query = (select(Payment).where(in_scope(scopes, Payment.company_id, Payment.branch_id))
             .order_by(Payment.business_date.desc(), Payment.created_at.desc(), Payment.id).limit(limit).offset(offset))
    if branch_id:
        query = query.where(Payment.branch_id == branch_id)
    if method:
        query = query.where(Payment.method == method)
    if business_date:
        query = query.where(Payment.business_date == business_date)
    if external_ref:
        query = query.where(Payment.external_ref == external_ref)
    if doc_id:
        query = query.where(Payment.id.in_(select(PaymentAllocation.payment_id).where(
            PaymentAllocation.doc_id == doc_id)))
    return list(session.scalars(query))


@dataclass(frozen=True)
class OpenPayment:
    payment: Payment
    unmatched: Decimal


def open_payments(session: Session, account_id: UUID | None, limit: int = 2000) -> list[OpenPayment]:
    """Money-in payments (card, M-Pesa, bank) that external transactions have not fully covered."""
    applied = (select(Match.payment_id, func.sum(Match.amount).label("m")).where(Match.status == "applied")
               .group_by(Match.payment_id).subquery())
    query = (select(Payment, Payment.amount - func.coalesce(applied.c.m, 0))
             .outerjoin(applied, applied.c.payment_id == Payment.id)
             .where(Payment.status == "posted", Payment.method.in_(("mobile_money", "card", "bank")),
                    Payment.amount - func.coalesce(applied.c.m, 0) > 0)
             .order_by(Payment.created_at).limit(limit))
    if account_id:
        query = query.where(Payment.payment_account_id == account_id)
    return [OpenPayment(row[0], Decimal(row[1])) for row in session.execute(query)]


def payment_totals(session: Session, branch_id: UUID, day: date) -> dict[tuple[str, str], Decimal]:
    """Posted payments of a branch and day: total by (direction, method)."""
    rows = session.execute(select(Payment.direction, Payment.method, func.sum(Payment.amount)).where(
        Payment.branch_id == branch_id, Payment.business_date == day, Payment.status == "posted")
        .group_by(Payment.direction, Payment.method))
    return {(r[0], r[1]): Decimal(r[2]) for r in rows}


def matched_total_for_branch(session: Session, branch_id: UUID, day: date, method: str) -> Decimal:
    """How much of a branch's payments of a method that day external transactions have covered."""
    return Decimal(session.scalar(
        select(func.coalesce(func.sum(Match.amount), 0)).join(Payment, Payment.id == Match.payment_id)
        .where(Payment.branch_id == branch_id, Payment.business_date == day, Payment.method == method,
               Payment.status == "posted", Match.status == "applied")) or 0)


# --------------------------------------------------------------------------- intents
def get_intent(session: Session, intent_id: UUID, *, lock: bool = False) -> PaymentIntent | None:
    if lock:
        return session.scalars(select(PaymentIntent).where(PaymentIntent.id == intent_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(PaymentIntent, intent_id)


def intent_by_request(session: Session, provider_request_id: str, *, lock: bool = False) -> PaymentIntent | None:
    query = select(PaymentIntent).where(PaymentIntent.provider_request_id == provider_request_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def list_intents(session: Session, scopes: Scopes, *, status: str | None = None, doc_id: UUID | None = None,
                 limit: int = 100, offset: int = 0) -> list[PaymentIntent]:
    query = (select(PaymentIntent).where(in_scope(scopes, PaymentIntent.company_id, PaymentIntent.branch_id))
             .order_by(PaymentIntent.created_at.desc(), PaymentIntent.id).limit(limit).offset(offset))
    if status:
        query = query.where(PaymentIntent.status == status)
    if doc_id:
        query = query.where(PaymentIntent.doc_id == doc_id)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- matches
def get_match(session: Session, match_id: UUID, *, lock: bool = False) -> Match | None:
    if lock:
        return session.scalars(select(Match).where(Match.id == match_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(Match, match_id)


def live_match(session: Session, txn_id: UUID, payment_id: UUID) -> Match | None:
    return session.scalar(select(Match).where(Match.external_transaction_id == txn_id, Match.payment_id == payment_id,
                                              Match.status != "undone"))


def list_matches(session: Session, *, txn_id: UUID | None = None, payment_id: UUID | None = None,
                 status: str | None = None, limit: int = 200) -> list[Match]:
    query = select(Match).order_by(Match.created_at.desc(), Match.id).limit(limit)
    if txn_id:
        query = query.where(Match.external_transaction_id == txn_id)
    if payment_id:
        query = query.where(Match.payment_id == payment_id)
    if status:
        query = query.where(Match.status == status)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- daily close
def get_close(session: Session, branch_id: UUID, day: date, *, lock: bool = False) -> DailyClose | None:
    query = select(DailyClose).where(DailyClose.branch_id == branch_id, DailyClose.business_date == day)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def get_close_by_id(session: Session, close_id: UUID, *, lock: bool = False) -> DailyClose | None:
    if lock:
        return session.scalars(select(DailyClose).where(DailyClose.id == close_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(DailyClose, close_id)


def list_closes(session: Session, scopes: Scopes, *, branch_id: UUID | None = None, status: str | None = None,
                limit: int = 100, offset: int = 0) -> list[DailyClose]:
    query = (select(DailyClose).where(in_scope(scopes, DailyClose.company_id, DailyClose.branch_id))
             .order_by(DailyClose.business_date.desc(), DailyClose.id).limit(limit).offset(offset))
    if branch_id:
        query = query.where(DailyClose.branch_id == branch_id)
    if status:
        query = query.where(DailyClose.status == status)
    return list(session.scalars(query))


def find_account_by_kinds(session: Session, company_id: UUID, branch_id: UUID | None,
                          kinds: tuple[str, ...]) -> PaymentAccount | None:
    """The active account of one of the kinds that serves the branch: the branch's own first, then the company's."""
    rows = list(session.scalars(select(PaymentAccount).where(
        PaymentAccount.company_id == company_id, PaymentAccount.kind.in_(kinds), PaymentAccount.is_active,
        (PaymentAccount.branch_id == branch_id) | PaymentAccount.branch_id.is_(None)).order_by(PaymentAccount.name)))
    rows.sort(key=lambda a: a.branch_id is None)
    return rows[0] if rows else None


def cash_in_session(session: Session, till_session_id: UUID) -> Decimal:
    """Cash taken (in) less cash paid out in a till session, from its posted payments."""
    value = session.scalar(select(func.coalesce(func.sum(
        case((Payment.direction == "in", Payment.amount), else_=-Payment.amount)), 0)).where(
        Payment.till_session_id == till_session_id, Payment.method == "cash", Payment.status == "posted"))
    return Decimal(value or 0)


def payments_for_document(session: Session, doc_type: str, doc_id: UUID) -> list[tuple[PaymentAllocation, Payment]]:
    rows = session.execute(select(PaymentAllocation, Payment).join(Payment, Payment.id == PaymentAllocation.payment_id)
                           .where(PaymentAllocation.doc_type == doc_type, PaymentAllocation.doc_id == doc_id)
                           .order_by(Payment.created_at, Payment.id))
    return [(a, p) for a, p in rows]
