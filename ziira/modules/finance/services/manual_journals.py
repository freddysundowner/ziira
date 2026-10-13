"""Use cases: manual journals. A person writes one (draft), submits it, and once approved (when the approval matrix asks
for it) it posts as an immutable journal entry.

    draft --submit--> pending_approval --approved--> posted
      |                      '--rejected--> rejected
      '--submit (no approval rule applies)--> posted

Manual journals cannot touch control accounts (stock, customers, suppliers, mobile-money clearing): those are kept by
their own records.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.domain import entries
from ziira.modules.finance.domain.entries import Line
from ziira.modules.finance.permissions import JOURNAL_APPROVE, JOURNAL_POST_MANUAL
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import ManualJournal, ManualJournalLine
from ziira.modules.finance.services.access import visible_companies
from ziira.modules.finance.services.books import ensure_books
from ziira.modules.finance.services.posting import EntryRequest, post_entry
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
    submit_for_approval,
)

DOC_TYPE = "manual_journal"


@dataclass(frozen=True)
class ManualLineIn:
    account_id: UUID
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    branch_id: UUID | None = None
    description: str | None = None


@dataclass(frozen=True)
class ManualDetail:
    journal: ManualJournal
    lines: list[ManualJournalLine]


def _lines(lines: list[ManualLineIn]) -> list[Line]:
    return [Line(x.account_id, x.debit, x.credit, x.branch_id, description=x.description) for x in lines]


def _load(session: Session, manual_id: UUID, *, lock: bool = False) -> ManualDetail:
    journal = finance_repo.get_manual(session, manual_id, lock=lock)
    companies = visible_companies()
    if journal is None or (companies is not None and journal.company_id not in companies):
        raise NotFound("Manual journal not found")
    return ManualDetail(journal, finance_repo.manual_lines(session, manual_id))


def create_manual_journal(session: Session, *, company_id: UUID, entry_date: date, description: str,
                          lines: list[ManualLineIn]) -> ManualDetail:
    """Write a draft manual journal. It changes nothing until it is submitted. Needs 'journal.post_manual'."""
    ctx = current_context()
    check_company(session, company_id)
    ctx.require(JOURNAL_POST_MANUAL, company_id=company_id)
    description = description.strip()
    if not description or len(description) > 500:
        raise ValidationFailed("A description is required (at most 500 characters)")
    total, _ = entries.check_lines(_lines(lines))
    ensure_books(session, company_id)
    # Same checks the posting will make, so a bad line is found now rather than at approval
    accounts = finance_repo.accounts_by_ids(session, {x.account_id for x in lines})
    for x in lines:
        account = accounts.get(x.account_id)
        if account is None or account.company_id != company_id:
            raise ValidationFailed("Account not found in this company")
        if not account.is_active:
            raise ValidationFailed(f"Account {account.code} is not active")
        if account.is_control:
            raise ValidationFailed(f"Account {account.code} {account.name} is kept by its own records; "
                                   "it cannot be posted to by hand")
        if x.branch_id:
            check_company(session, company_id, x.branch_id)
    general = finance_repo.journal_by_code(session, company_id, "GEN")
    if general is None:
        raise ValidationFailed("The company's books are not set up")
    journal = ManualJournal(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, journal_id=general.id,
        number=next_document_number(session, company_id=company_id, branch_id=None, doc_type="manual_journal",
                                    prefix="MJ"),
        entry_date=entry_date, description=description, total=total)
    finance_repo.add(session, journal)
    saved = []
    for index, x in enumerate(lines, 1):
        row = ManualJournalLine(tenant_id=ctx.tenant_id, manual_journal_id=journal.id, line_no=index,
                                account_id=x.account_id, branch_id=x.branch_id, debit=x.debit, credit=x.credit,
                                description=x.description)
        finance_repo.add(session, row)
        saved.append(row)
    audit_record(session, "create", "finance.manual_journal", journal.id,
                 {"number": journal.number, "total": total, "lines": len(saved)})
    return ManualDetail(journal, saved)


def get_manual_journal(session: Session, manual_id: UUID) -> ManualDetail:
    """One manual journal with its lines (404 if the user may not see the company's books)."""
    return _load(session, manual_id)


def list_manual_journals(session: Session, *, status: str | None = None, limit: int = 100,
                         offset: int = 0) -> list[ManualJournal]:
    """Manual journals of the companies the user may see, newest first."""
    return finance_repo.list_manuals(session, visible_companies(), status=status, limit=min(limit, 500), offset=offset)


def submit_manual_journal(session: Session, manual_id: UUID) -> ManualDetail:
    """Send a draft for approval; it posts at once if no approval rule applies to its size. Needs
    'journal.post_manual'."""
    detail = _load(session, manual_id, lock=True)
    journal = detail.journal
    current_context().require(JOURNAL_POST_MANUAL, company_id=journal.company_id)
    if journal.status != "draft":
        raise Conflict(f"This journal is {journal.status.replace('_', ' ')}, so it cannot be submitted")
    audit_record(session, "submit", "finance.manual_journal", journal.id, {"total": journal.total})
    if submit_for_approval(session, company_id=journal.company_id, doc_type=DOC_TYPE, doc_id=journal.id,
                           amount=journal.total) == "approved":
        _post(session, detail, approved_by=None)
    else:
        journal.status = "pending_approval"
        session.flush()
    return detail


def apply_decision(session: Session, manual_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post or reject a manual journal once its approval has been decided (from `approval.decided`)."""
    journal = finance_repo.get_manual(session, manual_id, lock=True)
    if journal is None:
        return
    if journal.status != "pending_approval":
        raise Conflict(f"This journal is {journal.status.replace('_', ' ')}, so it cannot be decided")
    current_context().require(JOURNAL_APPROVE, company_id=journal.company_id)
    if approved:
        _post(session, ManualDetail(journal, finance_repo.manual_lines(session, journal.id)), approved_by=decided_by)
    else:
        journal.status = "rejected"
        session.flush()
        audit_record(session, "reject", "finance.manual_journal", journal.id, {"number": journal.number})


def _post(session: Session, detail: ManualDetail, *, approved_by: UUID | None) -> None:
    journal = detail.journal
    general = finance_repo.get_journal(session, journal.journal_id)
    entry = post_entry(session, EntryRequest(
        company_id=journal.company_id, entry_date=journal.entry_date, journal_code=general.code if general else "GEN",
        lines=[Line(x.account_id, x.debit, x.credit, x.branch_id, description=x.description) for x in detail.lines],
        description=f"{journal.number}: {journal.description}", source_type="manual_journal", source_id=journal.id,
        is_manual=True, approved_by=approved_by))
    journal.status = "posted"
    journal.entry_id = entry.id
    journal.approved_by = approved_by
    session.flush()
