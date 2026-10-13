"""The posting engine: every journal entry is made here (specification section 07).

`post_entry` checks the lines (balanced, real accounts of the company, no hand-posting to control accounts), finds the
accounting period, applies the closed-period policy, numbers the entry, saves it with its lines (immutable; the
database also checks it balances at commit) and publishes `journal.posted`. Operational units never call it: they
publish documents, and finance's event handlers turn them into entries through `post_from_recipe`.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.finance.domain import entries, periods, rules
from ziira.modules.finance.domain.entries import Line
from ziira.modules.finance.domain.recipes import RecipeLine
from ziira.modules.finance.permissions import JOURNAL_APPROVE, PERIOD_CLOSE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import JournalEntry, JournalLine
from ziira.modules.finance.services.books import ensure_books, get_or_create_period
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_setting,
    current_context,
    next_document_number,
    publish,
)

NAIROBI = timezone(timedelta(hours=3))        # Kenya has no daylight saving time


def today() -> date:
    """Today's date in Kenya."""
    return datetime.now(UTC).astimezone(NAIROBI).date()


@dataclass(frozen=True)
class EntryRequest:
    """An entry to post."""

    company_id: UUID
    entry_date: date
    journal_code: str
    lines: list[Line]
    description: str | None = None
    source_type: str | None = None
    source_id: UUID | None = None
    is_manual: bool = False
    reversal_of_id: UUID | None = None
    approved_by: UUID | None = None
    automatic: bool = False           # made by the system from a document (may be redirected out of a closed period)
    allow_control: bool = False       # reversals may touch control accounts


def _check_accounts(session: Session, request: EntryRequest) -> None:
    ids = {line.account_id for line in request.lines}
    found = finance_repo.accounts_by_ids(session, ids)
    for account_id in ids:
        account = found.get(account_id)
        if account is None or account.company_id != request.company_id:
            raise ValidationFailed("Account not found in this company")
        if not account.is_active:
            raise ValidationFailed(f"Account {account.code} {account.name} is not active")
        if account.is_control and not request.automatic and not request.allow_control:
            raise ValidationFailed(f"Account {account.code} {account.name} is kept by its own records; "
                                   "it cannot be posted to by hand")
    for branch_id in {line.branch_id for line in request.lines if line.branch_id}:
        check_company(session, request.company_id, branch_id)


def post_entry(session: Session, request: EntryRequest) -> JournalEntry:
    """Post one journal entry. Raises ValidationFailed (unbalanced, closed period, bad account) or Conflict."""
    ctx = current_context()
    entries.check_lines(request.lines)
    ensure_books(session, request.company_id)
    _check_accounts(session, request)
    if request.source_type and request.source_id and not request.reversal_of_id and \
            finance_repo.entry_by_source(session, request.company_id, request.source_type, request.source_id):
        raise Conflict(f"This {request.source_type.replace('_', ' ')} has already been posted to the books")

    description, entry_date = request.description, request.entry_date
    period = get_or_create_period(session, request.company_id, entry_date)
    decision = periods.decide(period.status, automatic=request.automatic,
                              can_close=ctx.can(PERIOD_CLOSE, company_id=request.company_id),
                              policy=str(company_setting(session, request.company_id, "late_posting")))
    if decision == periods.REDIRECT:
        # A document dated in a closed month is booked in the current one, and says so
        original, entry_date = entry_date, today()
        period = get_or_create_period(session, request.company_id, entry_date)
        if period.status != periods.OPEN:
            raise ValidationFailed("There is no open accounting period to post into")
        description = f"{description or ''} (dated {original}, posted to the current period)".strip()

    journal = finance_repo.journal_by_code(session, request.company_id, request.journal_code)
    if journal is None:
        raise ValidationFailed(f"Journal '{request.journal_code}' not found")
    number = next_document_number(session, company_id=request.company_id, branch_id=None,
                                  doc_type=f"journal_{journal.code}", prefix=journal.code)
    entry = JournalEntry(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=request.company_id, journal_id=journal.id,
        period_id=period.id, number=number, entry_date=entry_date, source_type=request.source_type,
        source_id=request.source_id, description=description, is_manual=request.is_manual,
        reversal_of_id=request.reversal_of_id, approved_by=request.approved_by)
    finance_repo.add(session, entry)
    for line in request.lines:
        session.add(JournalLine(
            tenant_id=ctx.tenant_id, entry_id=entry.id, company_id=request.company_id, branch_id=line.branch_id,
            account_id=line.account_id, debit=line.debit, credit=line.credit, party_type=line.party_type,
            party_id=line.party_id, description=line.description))
    session.flush()
    total = sum((line.debit for line in request.lines), Decimal(0))
    if request.is_manual or request.reversal_of_id:
        audit_record(session, "reverse" if request.reversal_of_id else "post", "finance.journal_entry", entry.id,
                     {"number": number, "total": total, "reversal_of": request.reversal_of_id})
    publish(session, Event("journal.posted", "finance.journal_entry", entry.id, {
        "company_id": request.company_id, "number": number, "entry_date": entry_date, "total": total,
        "source_type": request.source_type, "source_id": request.source_id}))
    return entry


def post_from_recipe(session: Session, *, company_id: UUID, doc_type: str, journal_code: str, entry_date: date,
                     recipe: list[RecipeLine], context: dict[str, Any], branch_id: UUID | None,
                     source_type: str, source_id: UUID, description: str | None = None) -> JournalEntry | None:
    """Turn a document's recipe lines into an entry using the company's posting rules. Posts nothing for an empty
    recipe (a free sale, a worthless movement)."""
    if not recipe:
        return None
    ensure_books(session, company_id)
    posting_rules = [rules.PostingRule(r.doc_type, r.line_role, r.account_id, dict(r.conditions or {}), r.priority)
                     for r in finance_repo.list_rules(session, company_id)]
    lines = []
    for item in recipe:
        account_id = item.account_id or rules.resolve_account(posting_rules, doc_type, item.role, context)
        lines.append(Line(account_id=account_id, debit=item.amount if item.side == "debit" else Decimal(0),
                          credit=item.amount if item.side == "credit" else Decimal(0), branch_id=branch_id,
                          party_type=item.party_type, party_id=item.party_id,
                          description=item.description or description))
    return post_entry(session, EntryRequest(
        company_id=company_id, entry_date=entry_date, journal_code=journal_code, lines=lines,
        description=description, source_type=source_type, source_id=source_id, automatic=True))


def reverse_entry(session: Session, entry_id: UUID, *, entry_date: date | None, reason: str) -> JournalEntry:
    """Cancel a posted entry by posting its mirror image. Needs 'journal.approve' for the company.

    Only manual entries can be reversed this way. An entry made from a sale or a stock movement is corrected in its
    source document (a return, an adjustment), which posts its own correcting entry and keeps the books and the stock
    in step. An entry can be reversed once, and a reversal cannot itself be reversed (post a new entry instead).
    """
    original = finance_repo.get_entry(session, entry_id)
    if original is None:
        raise NotFound("Journal entry not found")
    current_context().require(JOURNAL_APPROVE, company_id=original.company_id)
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if original.reversal_of_id is not None:
        raise ValidationFailed("A reversal cannot be reversed; post a new entry instead")
    if not original.is_manual:
        raise ValidationFailed("This entry was made from a sale or a stock movement: correct that document "
                               "(a return or an adjustment) instead of reversing the entry")
    if finance_repo.reversal_of(session, entry_id) is not None:
        raise Conflict("This entry has already been reversed")
    lines = finance_repo.entry_lines(session, entry_id)
    mirrored = entries.mirror([Line(x.account_id, x.debit, x.credit, x.branch_id, x.party_type, x.party_id,
                                    x.description) for x in lines])
    journal = finance_repo.get_journal(session, original.journal_id)
    code = journal.code if journal else "GEN"
    return post_entry(session, EntryRequest(
        company_id=original.company_id, entry_date=entry_date or today(), journal_code=code, lines=mirrored,
        description=f"Reversal of {original.number}: {reason.strip()}", source_type=original.source_type,
        source_id=original.source_id, is_manual=True, reversal_of_id=original.id,
        approved_by=current_context().user_id, allow_control=True))
