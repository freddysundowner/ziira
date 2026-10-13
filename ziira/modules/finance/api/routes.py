"""HTTP endpoints of the Finance module. Routes only convert HTTP to service calls."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ziira.modules.finance.api import schemas as sc
from ziira.modules.finance.permissions import (
    ACCOUNTS_MANAGE,
    JOURNAL_APPROVE,
    JOURNAL_POST_MANUAL,
    PERIOD_CLOSE,
    REPORTS_VIEW,
)
from ziira.modules.finance.services import (
    accounts,
    entries,
    manual_journals,
    periods,
    posting,
    posting_rules,
    reports,
)
from ziira.modules.finance.services.access import READERS
from ziira.sdk import Forbidden, RequestContext, Session, db_session, page_limit, page_offset, request_context

router = APIRouter()
NO_CONTENT = status.HTTP_204_NO_CONTENT


def any_of(*permissions: str) -> Callable[[RequestContext], RequestContext]:
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


READ = [Depends(any_of(*READERS))]
REPORT = [Depends(any_of(REPORTS_VIEW))]
MANAGE_CHART = [Depends(any_of(ACCOUNTS_MANAGE))]
MANUAL = [Depends(any_of(JOURNAL_POST_MANUAL))]
CLOSE = [Depends(any_of(PERIOD_CLOSE))]


# --------------------------------------------------------------------------- chart of accounts
@router.post("/companies/{company_id}/books", response_model=list[sc.AccountOut], dependencies=MANAGE_CHART)
def post_setup_books(company_id: UUID, session: Session = Depends(db_session)) -> object:
    """Create the company's chart of accounts, journals and default posting rules (harmless if they exist)."""
    return accounts.setup_books(session, company_id)


@router.get("/accounts", response_model=list[sc.AccountOut], dependencies=READ)
def get_accounts(company_id: UUID | None = None, include_inactive: bool = False,
                 session: Session = Depends(db_session)) -> object:
    return accounts.list_accounts(session, company_id, include_inactive)


@router.post("/accounts", response_model=sc.AccountOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE_CHART)
def post_account(body: sc.AccountIn, session: Session = Depends(db_session)) -> object:
    return accounts.create_account(session, company_id=body.company_id, code=body.code, name=body.name,
                                   type=body.type, subtype=body.subtype, parent_id=body.parent_id)


@router.patch("/accounts/{account_id}", response_model=sc.AccountOut, dependencies=MANAGE_CHART)
def patch_account(account_id: UUID, body: sc.AccountUpdateIn, session: Session = Depends(db_session)) -> object:
    return accounts.update_account(session, account_id, name=body.name, is_active=body.is_active)


# --------------------------------------------------------------------------- posting rules
@router.get("/posting-rules", response_model=list[sc.RuleOut], dependencies=READ)
def get_rules(company_id: UUID, session: Session = Depends(db_session)) -> object:
    return posting_rules.list_rules(session, company_id)


@router.post("/posting-rules", response_model=sc.RuleOut, status_code=status.HTTP_201_CREATED,
             dependencies=MANAGE_CHART)
def post_rule(body: sc.RuleIn, session: Session = Depends(db_session)) -> object:
    return posting_rules.create_rule(session, company_id=body.company_id, doc_type=body.doc_type,
                                     line_role=body.line_role, account_id=body.account_id, side=body.side,
                                     conditions=body.conditions, priority=body.priority)


@router.put("/posting-rules/{posting_rule_id}", response_model=sc.RuleOut, dependencies=MANAGE_CHART)
def put_rule(posting_rule_id: UUID, body: sc.RuleUpdateIn, session: Session = Depends(db_session)) -> object:
    return posting_rules.update_rule(session, posting_rule_id, account_id=body.account_id)


@router.delete("/posting-rules/{posting_rule_id}", status_code=NO_CONTENT, dependencies=MANAGE_CHART)
def delete_rule(posting_rule_id: UUID, session: Session = Depends(db_session)) -> Response:
    posting_rules.delete_rule(session, posting_rule_id)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- periods
@router.get("/periods", response_model=list[sc.PeriodOut], dependencies=READ)
def get_periods(company_id: UUID, session: Session = Depends(db_session)) -> object:
    return periods.list_periods(session, company_id)


@router.post("/periods", response_model=sc.PeriodOut, status_code=status.HTTP_201_CREATED, dependencies=CLOSE)
def post_period(body: sc.PeriodOpenIn, session: Session = Depends(db_session)) -> object:
    """Create the monthly period containing a date (periods are also created when something is first posted)."""
    return periods.open_period(session, body.company_id, body.day)


@router.get("/periods/{period_id}/checklist", response_model=sc.ChecklistOut, dependencies=CLOSE)
def get_checklist(period_id: UUID, session: Session = Depends(db_session)) -> object:
    """What stops this period from being closed."""
    problems = periods.period_checklist(session, period_id)
    return sc.ChecklistOut(ready=not problems, problems=problems)


@router.post("/periods/{period_id}/status", response_model=sc.PeriodOut, dependencies=CLOSE)
def post_period_status(period_id: UUID, body: sc.PeriodStatusIn, session: Session = Depends(db_session)) -> object:
    """Close (soft), lock or reopen a period. Closing checks the period-close checklist first."""
    return periods.change_status(session, period_id, body.status)


# --------------------------------------------------------------------------- journal entries
@router.get("/journal-entries", response_model=list[sc.EntrySummaryOut], dependencies=REPORT)
def get_entries(company_id: UUID | None = None, source_type: str | None = None, source_id: UUID | None = None,
                date_from: date | None = None, date_to: date | None = None, limit: int = page_limit(),
                offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return entries.list_entries(session, company_id=company_id, source_type=source_type, source_id=source_id,
                                date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/journal-entries/{entry_id}", response_model=sc.EntryOut, dependencies=REPORT)
def get_one_entry(entry_id: UUID, session: Session = Depends(db_session)) -> object:
    return _entry_out(entries.get_entry(session, entry_id))


@router.post("/journal-entries/{entry_id}/reverse", response_model=sc.EntryOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(any_of(JOURNAL_APPROVE))])
def post_reverse(entry_id: UUID, body: sc.ReverseIn, session: Session = Depends(db_session)) -> object:
    """Cancel an entry by posting its mirror image (once per entry; a reversal cannot be reversed)."""
    reversal = posting.reverse_entry(session, entry_id, entry_date=body.entry_date, reason=body.reason)
    return _entry_out(entries.get_entry(session, reversal.id))


# --------------------------------------------------------------------------- manual journals
@router.post("/manual-journals", response_model=sc.ManualJournalOut, status_code=status.HTTP_201_CREATED,
             dependencies=MANUAL)
def post_manual(body: sc.ManualJournalIn, session: Session = Depends(db_session)) -> object:
    """Write a draft manual journal. It changes nothing until it is submitted (and approved)."""
    return _manual_out(manual_journals.create_manual_journal(
        session, company_id=body.company_id, entry_date=body.entry_date, description=body.description,
        lines=[manual_journals.ManualLineIn(x.account_id, x.debit, x.credit, x.branch_id, x.description)
               for x in body.lines]))


@router.get("/manual-journals", response_model=list[sc.ManualJournalSummaryOut], dependencies=READ)
def get_manuals(status_: str | None = Query(default=None, alias="status"), limit: int = page_limit(),
                offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return manual_journals.list_manual_journals(session, status=status_, limit=limit, offset=offset)


@router.get("/manual-journals/{manual_id}", response_model=sc.ManualJournalOut, dependencies=READ)
def get_manual(manual_id: UUID, session: Session = Depends(db_session)) -> object:
    return _manual_out(manual_journals.get_manual_journal(session, manual_id))


@router.post("/manual-journals/{manual_id}/submit", response_model=sc.ManualJournalOut, dependencies=MANUAL)
def post_submit_manual(manual_id: UUID, session: Session = Depends(db_session)) -> object:
    """Send for approval; posts at once if no approval rule applies to its size."""
    return _manual_out(manual_journals.submit_manual_journal(session, manual_id))


# --------------------------------------------------------------------------- reports
@router.get("/reports/trial-balance", response_model=sc.TrialBalanceOut, dependencies=REPORT)
def get_trial_balance(company_id: UUID, as_of: date, branch_id: UUID | None = None, include_zero: bool = False,
                      session: Session = Depends(db_session)) -> object:
    """Debit and credit totals per account up to a date. Reproducible for any past date."""
    t = reports.trial_balance(session, company_id, as_of, branch_id=branch_id, include_zero=include_zero)
    return sc.TrialBalanceOut(
        company_id=t.company_id, as_of=t.as_of, branch_id=t.branch_id, total_debit=t.total_debit,
        total_credit=t.total_credit, balanced=t.balanced,
        lines=[sc.TrialBalanceLineOut(account_id=x.account_id, code=x.code, name=x.name, type=x.type, debit=x.debit,
                                      credit=x.credit, balance=x.balance) for x in t.lines])


@router.get("/reports/general-ledger", response_model=sc.GeneralLedgerOut, dependencies=REPORT)
def get_general_ledger(company_id: UUID, account_id: UUID, date_from: date, date_to: date,
                       branch_id: UUID | None = None, limit: int = page_limit(500),
                       offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    """The lines posted to an account between two dates, with a running balance."""
    g = reports.general_ledger(session, company_id, account_id, date_from, date_to, branch_id=branch_id,
                               limit=limit, offset=offset)
    return sc.GeneralLedgerOut(
        account_id=g.account_id, code=g.code, name=g.name, date_from=g.date_from, date_to=g.date_to,
        opening=g.opening, closing=g.closing,
        lines=[sc.LedgerLineOut(entry_id=x.entry_id, number=x.number, entry_date=x.entry_date,
                                description=x.description, source_type=x.source_type, branch_id=x.branch_id,
                                debit=x.debit, credit=x.credit, balance=running) for x, running in g.lines])


def _entry_out(detail: entries.EntryDetail) -> sc.EntryOut:
    e = detail.entry
    return sc.EntryOut(
        id=e.id, company_id=e.company_id, number=e.number, entry_date=e.entry_date, source_type=e.source_type,
        source_id=e.source_id, description=e.description, is_manual=e.is_manual, reversal_of_id=e.reversal_of_id,
        posted_at=e.posted_at, approved_by=e.approved_by, reversed_by=detail.reversed_by,
        lines=[sc.EntryLineOut.model_validate(x) for x in detail.lines])


def _manual_out(detail: manual_journals.ManualDetail) -> sc.ManualJournalOut:
    j = detail.journal
    return sc.ManualJournalOut(
        id=j.id, company_id=j.company_id, number=j.number, entry_date=j.entry_date, description=j.description,
        status=j.status, total=j.total, created_by=j.created_by, entry_id=j.entry_id, approved_by=j.approved_by,
        lines=[sc.ManualLineOut.model_validate(x) for x in detail.lines])
