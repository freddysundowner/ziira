"""Database access for the finance schema. Row-level security scopes every query to the tenant."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, text, true
from sqlalchemy.orm import Session

from ziira.modules.finance.repository.models import (
    Account,
    AccountMapping,
    Expense,
    Journal,
    JournalEntry,
    JournalLine,
    ManualJournal,
    ManualJournalLine,
    Period,
    PostingRule,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None


def add(session: Session, record: object) -> None:
    """Insert a record and load its generated columns."""
    session.add(record)
    session.flush()
    session.refresh(record)


# --------------------------------------------------------------------------- books
def lock_books(session: Session, company_id: UUID) -> None:
    """Serialise setting up (and extending) a company's books until the transaction ends."""
    session.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"books:{company_id}"})


def has_accounts(session: Session, company_id: UUID) -> bool:
    return session.scalar(select(Account.id).where(Account.company_id == company_id).limit(1)) is not None


# --------------------------------------------------------------------------- accounts
def get_account(session: Session, account_id: UUID) -> Account | None:
    return session.get(Account, account_id)


def account_by_code(session: Session, company_id: UUID, code: str) -> Account | None:
    return session.scalar(select(Account).where(Account.company_id == company_id, Account.code == code))


def accounts_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Account]:
    if not ids:
        return {}
    return {a.id: a for a in session.scalars(select(Account).where(Account.id.in_(ids)))}


def list_accounts(session: Session, company_ids: set[UUID] | None, company_id: UUID | None = None,
                  include_inactive: bool = False) -> list[Account]:
    query = select(Account).order_by(Account.company_id, Account.code)
    if company_ids is not None:
        query = query.where(Account.company_id.in_(company_ids))
    if company_id:
        query = query.where(Account.company_id == company_id)
    if not include_inactive:
        query = query.where(Account.is_active)
    return list(session.scalars(query))


def account_in_rules(session: Session, account_id: UUID) -> bool:
    return session.scalar(select(PostingRule.id).where(PostingRule.account_id == account_id).limit(1)) is not None


def account_line_count(session: Session, account_id: UUID) -> int:
    return int(session.scalar(select(func.count()).select_from(JournalLine).where(
        JournalLine.account_id == account_id)) or 0)


def account_balance(session: Session, account_id: UUID) -> tuple[Decimal, Decimal]:
    """(total debits, total credits) ever posted to the account."""
    row = session.execute(select(func.coalesce(func.sum(JournalLine.debit), 0),
                                 func.coalesce(func.sum(JournalLine.credit), 0)).where(
        JournalLine.account_id == account_id)).one()
    return Decimal(row[0]), Decimal(row[1])


# --------------------------------------------------------------------------- periods and journals
def period_for(session: Session, company_id: UUID, day: date) -> Period | None:
    return session.scalar(select(Period).where(Period.company_id == company_id, Period.start_date <= day,
                                               Period.end_date >= day))


def get_period(session: Session, period_id: UUID, *, lock: bool = False) -> Period | None:
    if lock:
        return session.scalars(select(Period).where(Period.id == period_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(Period, period_id)


def list_periods(session: Session, company_id: UUID) -> list[Period]:
    return list(session.scalars(select(Period).where(Period.company_id == company_id).order_by(Period.start_date)))


def journal_by_code(session: Session, company_id: UUID, code: str) -> Journal | None:
    return session.scalar(select(Journal).where(Journal.company_id == company_id, Journal.code == code))


def get_journal(session: Session, journal_id: UUID) -> Journal | None:
    return session.get(Journal, journal_id)


def list_journals(session: Session, company_id: UUID) -> list[Journal]:
    return list(session.scalars(select(Journal).where(Journal.company_id == company_id).order_by(Journal.code)))


# --------------------------------------------------------------------------- posting rules
def list_rules(session: Session, company_id: UUID) -> list[PostingRule]:
    return list(session.scalars(select(PostingRule).where(PostingRule.company_id == company_id)
                                .order_by(PostingRule.doc_type, PostingRule.line_role, PostingRule.priority)))


def get_rule(session: Session, rule_id: UUID) -> PostingRule | None:
    return session.get(PostingRule, rule_id)


def delete_rule(session: Session, rule: PostingRule) -> None:
    session.delete(rule)
    session.flush()


# --------------------------------------------------------------------------- entries
def get_entry(session: Session, entry_id: UUID) -> JournalEntry | None:
    return session.get(JournalEntry, entry_id)


def entry_by_source(session: Session, company_id: UUID, source_type: str, source_id: UUID) -> JournalEntry | None:
    return session.scalar(select(JournalEntry).where(
        JournalEntry.company_id == company_id, JournalEntry.source_type == source_type,
        JournalEntry.source_id == source_id, JournalEntry.reversal_of_id.is_(None)))


def reversal_of(session: Session, entry_id: UUID) -> JournalEntry | None:
    return session.scalar(select(JournalEntry).where(JournalEntry.reversal_of_id == entry_id))


def entry_lines(session: Session, entry_id: UUID) -> list[JournalLine]:
    return list(session.scalars(select(JournalLine).where(JournalLine.entry_id == entry_id)
                                .order_by(JournalLine.created_at, JournalLine.id)))


def list_entries(session: Session, company_ids: set[UUID] | None, *, company_id: UUID | None = None,
                 source_type: str | None = None, source_id: UUID | None = None, date_from: date | None = None,
                 date_to: date | None = None, limit: int = 100, offset: int = 0) -> list[JournalEntry]:
    query = select(JournalEntry).order_by(JournalEntry.entry_date.desc(), JournalEntry.posted_at.desc(),
                                          JournalEntry.id).limit(limit).offset(offset)
    if company_ids is not None:
        query = query.where(JournalEntry.company_id.in_(company_ids))
    for column, value in ((JournalEntry.company_id, company_id), (JournalEntry.source_type, source_type),
                          (JournalEntry.source_id, source_id)):
        if value is not None:
            query = query.where(column == value)
    if date_from:
        query = query.where(JournalEntry.entry_date >= date_from)
    if date_to:
        query = query.where(JournalEntry.entry_date <= date_to)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- manual journals
def get_manual(session: Session, manual_id: UUID, *, lock: bool = False) -> ManualJournal | None:
    if lock:
        return session.scalars(select(ManualJournal).where(ManualJournal.id == manual_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(ManualJournal, manual_id)


def manual_lines(session: Session, manual_id: UUID) -> list[ManualJournalLine]:
    return list(session.scalars(select(ManualJournalLine).where(ManualJournalLine.manual_journal_id == manual_id)
                                .order_by(ManualJournalLine.line_no)))


def list_manuals(session: Session, company_ids: set[UUID] | None, *, status: str | None = None,
                 limit: int = 100, offset: int = 0) -> list[ManualJournal]:
    query = (select(ManualJournal).order_by(ManualJournal.created_at.desc(), ManualJournal.id)
             .limit(limit).offset(offset))
    if company_ids is not None:
        query = query.where(ManualJournal.company_id.in_(company_ids))
    if status:
        query = query.where(ManualJournal.status == status)
    return list(session.scalars(query))


def pending_manuals_in(session: Session, company_id: UUID, start: date, end: date) -> int:
    return int(session.scalar(select(func.count()).select_from(ManualJournal).where(
        ManualJournal.company_id == company_id, ManualJournal.status == "pending_approval",
        ManualJournal.entry_date >= start, ManualJournal.entry_date <= end)) or 0)


# --------------------------------------------------------------------------- expenses
def get_expense(session: Session, expense_id: UUID, *, lock: bool = False) -> Expense | None:
    query = select(Expense).where(Expense.id == expense_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def list_expenses(session: Session, scopes: Scopes, *, company_id: UUID | None, status: str | None,
                  date_from: date | None, date_to: date | None, limit: int, offset: int) -> list[Expense]:
    query = select(Expense).order_by(Expense.expense_date.desc(), Expense.number.desc()).limit(limit).offset(offset)
    if scopes is not None:
        query = query.where(or_(false(), *(
            and_(Expense.company_id == c, true() if b is None else Expense.branch_id == b) for c, b in scopes)))
    if company_id:
        query = query.where(Expense.company_id == company_id)
    if status:
        query = query.where(Expense.status == status)
    if date_from:
        query = query.where(Expense.expense_date >= date_from)
    if date_to:
        query = query.where(Expense.expense_date <= date_to)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- reports
def _in_scope(scopes: Scopes) -> ColumnElement[bool]:
    """Journal lines the user may see: company-wide grants see the company's lines; a branch grant only its branch."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(JournalLine.company_id == c, true() if b is None else JournalLine.branch_id == b)
                          for c, b in scopes))


@dataclass(frozen=True)
class TrialBalanceRow:
    account_id: UUID
    code: str
    name: str
    type: str
    debit: Decimal
    credit: Decimal


def trial_balance(session: Session, scopes: Scopes, company_id: UUID, as_of: date,
                  branch_id: UUID | None = None, include_zero: bool = False) -> list[TrialBalanceRow]:
    """Debit and credit totals per account of the company up to (and including) a date."""
    lines = (select(JournalLine.account_id, func.sum(JournalLine.debit).label("d"),
                    func.sum(JournalLine.credit).label("c"))
             .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .where(JournalLine.company_id == company_id, JournalEntry.entry_date <= as_of, _in_scope(scopes))
             .group_by(JournalLine.account_id))
    if branch_id:
        lines = lines.where(JournalLine.branch_id == branch_id)
    sums = {r.account_id: (Decimal(r.d), Decimal(r.c)) for r in session.execute(lines)}
    rows = []
    for account in session.scalars(select(Account).where(Account.company_id == company_id).order_by(Account.code)):
        debit, credit = sums.get(account.id, (Decimal(0), Decimal(0)))
        if debit or credit or include_zero:
            rows.append(TrialBalanceRow(account.id, account.code, account.name, account.type, debit, credit))
    return rows


@dataclass(frozen=True)
class LedgerLine:
    entry_id: UUID
    number: str
    entry_date: date
    description: str | None
    source_type: str | None
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal


def ledger_before(session: Session, scopes: Scopes, company_id: UUID, account_id: UUID, day: date,
                  branch_id: UUID | None = None) -> tuple[Decimal, Decimal]:
    """Debits and credits posted to an account before a date (the opening position)."""
    query = (select(func.coalesce(func.sum(JournalLine.debit), 0), func.coalesce(func.sum(JournalLine.credit), 0))
             .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .where(JournalLine.company_id == company_id, JournalLine.account_id == account_id,
                    JournalEntry.entry_date < day, _in_scope(scopes)))
    if branch_id:
        query = query.where(JournalLine.branch_id == branch_id)
    row = session.execute(query).one()
    return Decimal(row[0]), Decimal(row[1])


def ledger_lines(session: Session, scopes: Scopes, company_id: UUID, account_id: UUID, date_from: date,
                 date_to: date, branch_id: UUID | None = None, limit: int = 1000, offset: int = 0) -> list[LedgerLine]:
    query = (select(JournalLine, JournalEntry).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .where(JournalLine.company_id == company_id, JournalLine.account_id == account_id,
                    JournalEntry.entry_date >= date_from, JournalEntry.entry_date <= date_to, _in_scope(scopes))
             .order_by(JournalEntry.entry_date, JournalEntry.posted_at, JournalLine.created_at, JournalLine.id)
             .limit(limit).offset(offset))
    if branch_id:
        query = query.where(JournalLine.branch_id == branch_id)
    return [LedgerLine(e.id, e.number, e.entry_date, line.description or e.description, e.source_type,
                       line.branch_id, line.debit, line.credit) for line, e in session.execute(query)]


@dataclass(frozen=True)
class TotalRow:
    account_id: UUID
    code: str
    name: str
    type: str
    subtype: str | None
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal


def account_totals(session: Session, scopes: Scopes, company_id: UUID, date_to: date, *,
                   date_from: date | None = None, branch_id: UUID | None = None,
                   subtypes: tuple[str, ...] | None = None, group_branch: bool = False) -> list[TotalRow]:
    """Debits and credits per account (and per branch when asked) over entries dated from `date_from` (or the
    beginning) to `date_to`, only for accounts that have lines."""
    columns = [Account.id, Account.code, Account.name, Account.type, Account.subtype,
               func.sum(JournalLine.debit).label("d"), func.sum(JournalLine.credit).label("c")]
    query = (select(*columns, *([JournalLine.branch_id] if group_branch else []))
             .join(JournalLine, JournalLine.account_id == Account.id)
             .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .where(JournalLine.company_id == company_id, JournalEntry.entry_date <= date_to, _in_scope(scopes))
             .group_by(Account.id, Account.code, Account.name, Account.type, Account.subtype,
                       *([JournalLine.branch_id] if group_branch else []))
             .order_by(Account.code))
    if date_from is not None:
        query = query.where(JournalEntry.entry_date >= date_from)
    if branch_id:
        query = query.where(JournalLine.branch_id == branch_id)
    if subtypes is not None:
        query = query.where(Account.subtype.in_(subtypes))
    return [TotalRow(r.id, r.code, r.name, r.type, r.subtype, r.branch_id if group_branch else None,
                     Decimal(r.d), Decimal(r.c)) for r in session.execute(query)]


def totals_by_source(session: Session, scopes: Scopes, company_id: UUID, date_from: date, date_to: date, *,
                     subtypes: tuple[str, ...], branch_id: UUID | None = None) -> dict[str | None, Decimal]:
    """Net debit (debits less credits) on accounts of these subtypes in a span, by the kind of document behind it."""
    query = (select(JournalEntry.source_type, func.sum(JournalLine.debit - JournalLine.credit))
             .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
             .join(Account, Account.id == JournalLine.account_id)
             .where(JournalLine.company_id == company_id, Account.subtype.in_(subtypes),
                    JournalEntry.entry_date >= date_from, JournalEntry.entry_date <= date_to, _in_scope(scopes))
             .group_by(JournalEntry.source_type))
    if branch_id:
        query = query.where(JournalLine.branch_id == branch_id)
    return {source: Decimal(total) for source, total in session.execute(query)}


@dataclass(frozen=True)
class JournalExportRow:
    entry_number: str
    entry_date: date
    source_type: str | None
    description: str | None
    account_id: UUID
    account_code: str
    account_name: str
    branch_id: UUID | None
    debit: Decimal
    credit: Decimal


def journal_rows(session: Session, scopes: Scopes, company_id: UUID, date_from: date, date_to: date,
                 branch_id: UUID | None = None, limit: int = 100000) -> list[JournalExportRow]:
    """Every journal line of the entries dated in a span, in entry order (for exports)."""
    query = (select(JournalEntry, JournalLine, Account)
             .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
             .join(Account, Account.id == JournalLine.account_id)
             .where(JournalEntry.company_id == company_id, JournalEntry.entry_date >= date_from,
                    JournalEntry.entry_date <= date_to, _in_scope(scopes))
             .order_by(JournalEntry.entry_date, JournalEntry.number, JournalLine.created_at, JournalLine.id)
             .limit(limit))
    if branch_id:
        query = query.where(JournalLine.branch_id == branch_id)
    return [JournalExportRow(e.number, e.entry_date, e.source_type, line.description or e.description, a.id, a.code,
                             a.name, line.branch_id, line.debit, line.credit) for e, line, a in session.execute(query)]


def branch_names(session: Session, company_id: UUID) -> dict[UUID, str]:
    return {r.id: r.name for r in session.execute(
        text("select id, name from kernel.branch where company_id = :c"), {"c": str(company_id)})}


def mappings(session: Session, company_id: UUID) -> dict[UUID, AccountMapping]:
    found = session.scalars(select(AccountMapping).where(AccountMapping.company_id == company_id))
    return {m.account_id: m for m in found}


def get_mapping(session: Session, company_id: UUID, account_id: UUID) -> AccountMapping | None:
    return session.scalars(select(AccountMapping).where(
        AccountMapping.company_id == company_id, AccountMapping.account_id == account_id)).first()


# --------------------------------------------------------------------------- checks
def unbalanced_entries(session: Session) -> list[tuple[UUID, Decimal, Decimal]]:
    rows = session.execute(text(
        "select entry_id, sum(debit) as d, sum(credit) as c from finance.journal_line group by entry_id "
        "having sum(debit) <> sum(credit)"))
    return [(r.entry_id, r.d, r.c) for r in rows]


def ledger_totals(session: Session) -> dict[UUID, tuple[Decimal, Decimal]]:
    """Total debits and credits per company, over every line."""
    rows = session.execute(text("select company_id, sum(debit) as d, sum(credit) as c from finance.journal_line "
                                "group by company_id"))
    return {r.company_id: (r.d, r.c) for r in rows}


def balances_by_subtype(session: Session, company_id: UUID, subtypes: list[str]) -> Decimal:
    """Net debit balance (debits minus credits) of the company's accounts with these subtypes."""
    value = session.scalar(
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.company_id == company_id, Account.subtype.in_(subtypes)))
    return Decimal(value or 0)


def balance_by_subtype_until(session: Session, company_id: UUID, subtypes: list[str], day: date) -> Decimal:
    """Net debit balance of the company's accounts with these subtypes, over entries dated up to a day."""
    value = session.scalar(
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalLine.company_id == company_id, Account.subtype.in_(subtypes), JournalEntry.entry_date <= day))
    return Decimal(value or 0)


def posted_sources(session: Session, source_type: str, ids: set[UUID]) -> set[UUID]:
    """Which of these source documents already have an entry."""
    if not ids:
        return set()
    return set(session.scalars(select(JournalEntry.source_id).where(
        JournalEntry.source_type == source_type, JournalEntry.source_id.in_(ids),
        JournalEntry.reversal_of_id.is_(None))))
