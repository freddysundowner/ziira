"""Use cases: reconciling a bank, M-Pesa or card account to its statement.

    start (statement date and balance) --> tick the ledger lines that appear on the statement --> complete

The cleared lines must add up to the statement's balance before the reconciliation can be completed; a completed one is
final and its lines are never cleared again. Statement lines can be uploaded to suggest which ledger lines they are.
What is on the statement but not in the books (bank charges, interest) is entered as a manual journal or an expense,
which then appears as a ledger line to clear.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.domain import reconciliation as rules
from ziira.modules.finance.permissions import BANK_RECONCILE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.finance_repo import LedgerCandidate as LedgerCandidate  # noqa: PLC0414
from ziira.modules.finance.repository.models import BankReconciliation, ReconciliationLine
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    publish,
)

ACCOUNT_SUBTYPES = ("bank", "mobile_money_clearing", "card_clearing")
MAX_LINES_SHOWN = 2000


@dataclass(frozen=True)
class ReconciliationDetail:
    reconciliation: BankReconciliation
    account_code: str
    account_name: str
    book_balance: Decimal             # what the books say now, up to the statement date
    cleared: list[LedgerCandidate]
    uncleared: list[LedgerCandidate]  # in the books, not (yet) on the statement: the reconciling items

    @property
    def outstanding(self) -> Decimal:
        return sum((x.debit - x.credit for x in self.uncleared), Decimal(0))


def _visible() -> set[UUID] | None:
    return current_context().companies_with(BANK_RECONCILE)


def _load(session: Session, recon_id: UUID, *, lock: bool = False) -> BankReconciliation:
    recon = finance_repo.get_reconciliation(session, recon_id, lock=lock)
    companies = _visible()
    if recon is None or recon.account_id is None or (companies is not None and recon.company_id not in companies):
        raise NotFound("Reconciliation not found")
    return recon


def _detail(session: Session, recon: BankReconciliation) -> ReconciliationDetail:
    assert recon.account_id is not None
    account = finance_repo.get_account(session, recon.account_id)
    candidates = finance_repo.ledger_candidates(session, recon.company_id, recon.account_id, recon.statement_date,
                                                recon.id)
    book = finance_repo.book_balance_until(session, recon.company_id, recon.account_id, recon.statement_date)
    return ReconciliationDetail(
        recon, account.code if account else "", account.name if account else "", book,
        [x for x in candidates if x.cleared][-MAX_LINES_SHOWN:],
        [x for x in candidates if not x.cleared][-MAX_LINES_SHOWN:])


def _refresh(session: Session, recon: BankReconciliation) -> None:
    assert recon.account_id is not None
    recon.cleared_balance = finance_repo.cleared_balance(session, recon.account_id, recon.id)
    recon.book_balance = finance_repo.book_balance_until(session, recon.company_id, recon.account_id,
                                                         recon.statement_date)
    recon.difference = rules.difference(recon.statement_balance, recon.cleared_balance)
    session.flush()


def start_reconciliation(session: Session, *, company_id: UUID, account_id: UUID, statement_date: date,
                         statement_balance: Decimal) -> ReconciliationDetail:
    """Begin reconciling an account to a statement (its date and closing balance). One at a time per account, and never
    to a date before the last one completed. Needs 'bank.reconcile' for the company."""
    ctx = current_context()
    check_company(session, company_id)
    ctx.require(BANK_RECONCILE, company_id=company_id)
    account = finance_repo.get_account(session, account_id)
    if account is None or account.company_id != company_id:
        raise ValidationFailed("Account not found in this company")
    if account.subtype not in ACCOUNT_SUBTYPES:
        raise ValidationFailed(f"Only bank, M-Pesa and card accounts are reconciled to a statement, not "
                               f"{account.code} {account.name}")
    if finance_repo.open_reconciliation(session, account_id) is not None:
        raise Conflict("This account already has a reconciliation in progress: complete or cancel it first")
    last = finance_repo.last_completed_date(session, account_id)
    if last is not None and statement_date <= last:
        raise ValidationFailed(f"This account was already reconciled up to {last}: use a later statement")
    if abs(statement_balance) > Decimal("1000000000000"):
        raise ValidationFailed("That balance is too large")
    recon = BankReconciliation(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, account_id=account_id,
        statement_date=statement_date, statement_balance=statement_balance, book_balance=Decimal(0),
        cleared_balance=Decimal(0), difference=Decimal(0))
    finance_repo.add(session, recon)
    _refresh(session, recon)
    audit_record(session, "start", "finance.bank_reconciliation", recon.id,
                 {"account": account.code, "statement_date": statement_date, "statement_balance": statement_balance})
    return _detail(session, recon)


def get_reconciliation(session: Session, recon_id: UUID) -> ReconciliationDetail:
    recon = _load(session, recon_id)
    if recon.status == "in_progress":
        _refresh(session, recon)
    return _detail(session, recon)


def list_reconciliations(session: Session, *, company_id: UUID | None = None, account_id: UUID | None = None,
                         status: str | None = None, limit: int = 50, offset: int = 0) -> list[BankReconciliation]:
    return finance_repo.list_reconciliations(session, _visible(), company_id=company_id, account_id=account_id,
                                             status=status, limit=min(limit, 200), offset=offset)


def _open(session: Session, recon_id: UUID) -> BankReconciliation:
    recon = _load(session, recon_id, lock=True)
    current_context().require(BANK_RECONCILE, company_id=recon.company_id)
    if recon.status != "in_progress":
        raise Conflict("This reconciliation is completed and cannot be changed")
    return recon


def clear_lines(session: Session, recon_id: UUID, *, line_ids: list[UUID] | None = None, until: date | None = None,
                cleared: bool = True) -> ReconciliationDetail:
    """Mark ledger lines as on the statement (or take the mark off). Name the lines, or give a date to clear every line
    dated up to it (for the lines already settled before the statement began). Needs 'bank.reconcile'."""
    recon = _open(session, recon_id)
    assert recon.account_id is not None
    if (not line_ids) == (until is None):
        raise ValidationFailed("Name the lines to clear, or give a date to clear everything up to it (not both)")
    ctx = current_context()
    candidates = {c.line_id: c for c in finance_repo.ledger_candidates(
        session, recon.company_id, recon.account_id, recon.statement_date, recon.id)}
    if until is not None:
        wanted = {c.line_id for c in candidates.values() if c.entry_date <= until}
    else:
        wanted = set(line_ids or [])
        unknown = wanted - set(candidates)
        if unknown:
            raise ValidationFailed(f"{len(unknown)} line(s) are not part of this account up to the statement date, or "
                                   "were cleared in an earlier reconciliation")
    already = finance_repo.cleared_line_ids(session, recon.id)
    if cleared:
        for line_id in sorted(wanted - already, key=str):
            finance_repo.add(session, ReconciliationLine(tenant_id=ctx.tenant_id, created_by=ctx.user_id,
                                                         reconciliation_id=recon.id, journal_line_id=line_id))
        changed = len(wanted - already)
    else:
        finance_repo.remove_cleared(session, recon.id, wanted & already)
        changed = len(wanted & already)
    session.flush()
    _refresh(session, recon)
    audit_record(session, "clear" if cleared else "unclear", "finance.bank_reconciliation", recon.id,
                 {"lines": changed, "cleared_balance": recon.cleared_balance})
    return _detail(session, recon)


@dataclass(frozen=True)
class SuggestionOut:
    item: rules.StatementItem
    line: LedgerCandidate
    reason: str


@dataclass(frozen=True)
class SuggestionResult:
    suggestions: list[SuggestionOut]
    unmatched: list[rules.StatementItem]      # on the statement, nothing in the books to match: enter them first
    applied: bool
    detail: ReconciliationDetail


def suggest_matches(session: Session, recon_id: UUID, items: list[rules.StatementItem], *,
                    apply: bool = False) -> SuggestionResult:
    """Match uploaded statement lines to the ledger lines not yet cleared (same amount; the same reference first, then
    the nearest date). With `apply` the matches are cleared at once; otherwise they are only proposed. Needs
    'bank.reconcile'."""
    if not items:
        raise ValidationFailed("Send the statement's lines")
    if len(items) > rules.MAX_LINES:
        raise ValidationFailed(f"A statement has at most {rules.MAX_LINES} lines")
    recon = _open(session, recon_id)
    assert recon.account_id is not None
    free = [c for c in finance_repo.ledger_candidates(session, recon.company_id, recon.account_id,
                                                      recon.statement_date, recon.id) if not c.cleared]
    by_id = {c.line_id: c for c in free}
    found = rules.suggest_matches(
        items, [rules.LedgerItem(c.line_id, c.entry_date, c.number, c.description or "", c.debit - c.credit)
                for c in free])
    matched_items = {s.item_index for s in found}
    result = [SuggestionOut(items[s.item_index], by_id[s.line_id], s.reason) for s in found]
    unmatched = [x for i, x in enumerate(items) if i not in matched_items]
    if apply and found:
        ctx = current_context()
        for s in found:
            finance_repo.add(session, ReconciliationLine(tenant_id=ctx.tenant_id, created_by=ctx.user_id,
                                                         reconciliation_id=recon.id, journal_line_id=s.line_id))
        session.flush()
        _refresh(session, recon)
        audit_record(session, "clear", "finance.bank_reconciliation", recon.id,
                     {"lines": len(found), "from": "statement", "cleared_balance": recon.cleared_balance})
    return SuggestionResult(result, unmatched, apply, _detail(session, recon))


def complete_reconciliation(session: Session, recon_id: UUID) -> ReconciliationDetail:
    """Finish: allowed only when the cleared lines add up to the statement's balance. Final. Needs 'bank.reconcile'."""
    recon = _open(session, recon_id)
    _refresh(session, recon)
    if recon.difference != 0:
        raise Conflict(f"The cleared lines are {abs(recon.difference)} "
                       f"{'short of' if recon.difference > 0 else 'over'} the statement's balance: clear the lines "
                       "that are on the statement, or enter what the books are missing")
    ctx = current_context()
    recon.status = "completed"
    recon.completed_by = ctx.user_id
    recon.completed_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "complete", "finance.bank_reconciliation", recon.id,
                 {"statement_balance": recon.statement_balance, "book_balance": recon.book_balance})
    publish(session, Event("reconciliation.completed", "finance.bank_reconciliation", recon.id, {
        "company_id": recon.company_id, "account_id": recon.account_id, "statement_date": recon.statement_date,
        "statement_balance": recon.statement_balance}))
    return _detail(session, recon)


def cancel_reconciliation(session: Session, recon_id: UUID) -> None:
    """Throw away a reconciliation in progress (its ticks go with it). A completed one stays. Needs 'bank.reconcile'."""
    recon = _open(session, recon_id)
    audit_record(session, "cancel", "finance.bank_reconciliation", recon.id,
                 {"statement_date": recon.statement_date})
    finance_repo.delete_reconciliation(session, recon)
