"""HTTP endpoints of the Finance module. Routes only convert HTTP to service calls."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ziira.modules.finance.api import schemas as sc
from ziira.modules.finance.domain import exports as csv_export
from ziira.modules.finance.domain import reconciliation as recon_rules
from ziira.modules.finance.permissions import (
    ACCOUNTS_MANAGE,
    BANK_RECONCILE,
    EXPENSES_APPROVE,
    EXPENSES_SUBMIT,
    JOURNAL_APPROVE,
    JOURNAL_POST_MANUAL,
    PERIOD_CLOSE,
    REPORTS_VIEW,
)
from ziira.modules.finance.services import (
    accounts,
    bank_reconciliation,
    entries,
    expenses,
    manual_journals,
    opening_balances,
    periods,
    posting,
    posting_rules,
    reports,
)
from ziira.modules.finance.services import (
    exports as export_service,
)
from ziira.modules.finance.services import (
    statements as statement_service,
)
from ziira.modules.finance.services.access import READERS
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    RequestContext,
    Session,
    ValidationFailed,
    page_limit,
    page_offset,
    request_context,
)

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
RECON = [Depends(any_of(BANK_RECONCILE))]
EXPENSE_READ = [Depends(any_of(EXPENSES_SUBMIT, EXPENSES_APPROVE, REPORTS_VIEW))]
EXPENSE_WRITE = [Depends(any_of(EXPENSES_SUBMIT))]
EXPENSE_DECIDE = [Depends(any_of(EXPENSES_APPROVE))]


# --------------------------------------------------------------------------- chart of accounts
@router.post("/companies/{company_id}/books", response_model=list[sc.AccountOut], dependencies=MANAGE_CHART)
def post_setup_books(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Create the company's chart of accounts, journals and default posting rules (harmless if they exist)."""
    return accounts.setup_books(session, company_id)


@router.get("/accounts", response_model=list[sc.AccountOut], dependencies=READ)
def get_accounts(company_id: UUID | None = None, include_inactive: bool = False,
                 session: Session = DB_SESSION) -> object:
    return accounts.list_accounts(session, company_id, include_inactive)


@router.post("/accounts", response_model=sc.AccountOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE_CHART)
def post_account(body: sc.AccountIn, session: Session = DB_SESSION) -> object:
    return accounts.create_account(session, company_id=body.company_id, code=body.code, name=body.name,
                                   type=body.type, subtype=body.subtype, parent_id=body.parent_id)


@router.patch("/accounts/{account_id}", response_model=sc.AccountOut, dependencies=MANAGE_CHART)
def patch_account(account_id: UUID, body: sc.AccountUpdateIn, session: Session = DB_SESSION) -> object:
    return accounts.update_account(session, account_id, name=body.name, is_active=body.is_active)


# --------------------------------------------------------------------------- posting rules
@router.get("/posting-rules", response_model=list[sc.RuleOut], dependencies=READ)
def get_rules(company_id: UUID, session: Session = DB_SESSION) -> object:
    return posting_rules.list_rules(session, company_id)


@router.post("/posting-rules", response_model=sc.RuleOut, status_code=status.HTTP_201_CREATED,
             dependencies=MANAGE_CHART)
def post_rule(body: sc.RuleIn, session: Session = DB_SESSION) -> object:
    return posting_rules.create_rule(session, company_id=body.company_id, doc_type=body.doc_type,
                                     line_role=body.line_role, account_id=body.account_id, side=body.side,
                                     conditions=body.conditions, priority=body.priority)


@router.put("/posting-rules/{posting_rule_id}", response_model=sc.RuleOut, dependencies=MANAGE_CHART)
def put_rule(posting_rule_id: UUID, body: sc.RuleUpdateIn, session: Session = DB_SESSION) -> object:
    return posting_rules.update_rule(session, posting_rule_id, account_id=body.account_id)


@router.delete("/posting-rules/{posting_rule_id}", status_code=NO_CONTENT, dependencies=MANAGE_CHART)
def delete_rule(posting_rule_id: UUID, session: Session = DB_SESSION) -> Response:
    posting_rules.delete_rule(session, posting_rule_id)
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- periods
@router.get("/periods", response_model=list[sc.PeriodOut], dependencies=READ)
def get_periods(company_id: UUID, session: Session = DB_SESSION) -> object:
    return periods.list_periods(session, company_id)


@router.post("/periods", response_model=sc.PeriodOut, status_code=status.HTTP_201_CREATED, dependencies=CLOSE)
def post_period(body: sc.PeriodOpenIn, session: Session = DB_SESSION) -> object:
    """Create the monthly period containing a date (periods are also created when something is first posted)."""
    return periods.open_period(session, body.company_id, body.day)


@router.get("/periods/{period_id}/checklist", response_model=sc.ChecklistOut, dependencies=CLOSE)
def get_checklist(period_id: UUID, session: Session = DB_SESSION) -> object:
    """What stops this period from being closed."""
    problems = periods.period_checklist(session, period_id)
    return sc.ChecklistOut(ready=not problems, problems=problems)


@router.post("/periods/{period_id}/status", response_model=sc.PeriodOut, dependencies=CLOSE)
def post_period_status(period_id: UUID, body: sc.PeriodStatusIn, session: Session = DB_SESSION) -> object:
    """Close (soft), lock or reopen a period. Closing checks the period-close checklist first."""
    return periods.change_status(session, period_id, body.status)


# --------------------------------------------------------------------------- journal entries
@router.get("/journal-entries", response_model=list[sc.EntrySummaryOut], dependencies=REPORT)
def get_entries(company_id: UUID | None = None, source_type: str | None = None, source_id: UUID | None = None,
                date_from: date | None = None, date_to: date | None = None, limit: int = page_limit(),
                offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return entries.list_entries(session, company_id=company_id, source_type=source_type, source_id=source_id,
                                date_from=date_from, date_to=date_to, limit=limit, offset=offset)


@router.get("/journal-entries/{entry_id}", response_model=sc.EntryOut, dependencies=REPORT)
def get_one_entry(entry_id: UUID, session: Session = DB_SESSION) -> object:
    return _entry_out(entries.get_entry(session, entry_id))


@router.post("/journal-entries/{entry_id}/reverse", response_model=sc.EntryOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(any_of(JOURNAL_APPROVE))])
def post_reverse(entry_id: UUID, body: sc.ReverseIn, session: Session = DB_SESSION) -> object:
    """Cancel an entry by posting its mirror image (once per entry; a reversal cannot be reversed)."""
    reversal = posting.reverse_entry(session, entry_id, entry_date=body.entry_date, reason=body.reason)
    return _entry_out(entries.get_entry(session, reversal.id))


# --------------------------------------------------------------------------- opening balances
@router.get("/opening-balances", response_model=list[sc.OpeningBalanceOut], dependencies=READ)
def get_opening_balances(session: Session = DB_SESSION) -> object:
    """The opening balance entries of the companies you can see (posted by the opening trial balance import)."""
    return opening_balances.list_opening_balances(session)


@router.post("/opening-balances/{opening_id}/reverse", response_model=sc.OpeningBalanceOut,
             dependencies=[Depends(any_of(JOURNAL_APPROVE))])
def post_reverse_opening_balance(opening_id: UUID, body: sc.ReverseIn, session: Session = DB_SESSION) -> object:
    """Cancel a company's opening balance entry with a mirror entry, so a corrected one can be posted."""
    return opening_balances.reverse_opening_balance(session, opening_id, reason=body.reason, entry_date=body.entry_date)


# --------------------------------------------------------------------------- manual journals
@router.post("/manual-journals", response_model=sc.ManualJournalOut, status_code=status.HTTP_201_CREATED,
             dependencies=MANUAL)
def post_manual(body: sc.ManualJournalIn, session: Session = DB_SESSION) -> object:
    """Write a draft manual journal. It changes nothing until it is submitted (and approved)."""
    return _manual_out(manual_journals.create_manual_journal(
        session, company_id=body.company_id, entry_date=body.entry_date, description=body.description,
        lines=[manual_journals.ManualLineIn(x.account_id, x.debit, x.credit, x.branch_id, x.description)
               for x in body.lines]))


@router.get("/manual-journals", response_model=list[sc.ManualJournalSummaryOut], dependencies=READ)
def get_manuals(status_: str | None = Query(default=None, alias="status"), limit: int = page_limit(),
                offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return manual_journals.list_manual_journals(session, status=status_, limit=limit, offset=offset)


@router.get("/manual-journals/{manual_id}", response_model=sc.ManualJournalOut, dependencies=READ)
def get_manual(manual_id: UUID, session: Session = DB_SESSION) -> object:
    return _manual_out(manual_journals.get_manual_journal(session, manual_id))


@router.post("/manual-journals/{manual_id}/submit", response_model=sc.ManualJournalOut, dependencies=MANUAL)
def post_submit_manual(manual_id: UUID, session: Session = DB_SESSION) -> object:
    """Send for approval; posts at once if no approval rule applies to its size."""
    return _manual_out(manual_journals.submit_manual_journal(session, manual_id))


# --------------------------------------------------------------------------- reports
@router.get("/reports/trial-balance", response_model=sc.TrialBalanceOut, dependencies=REPORT)
def get_trial_balance(company_id: UUID, as_of: date, branch_id: UUID | None = None, include_zero: bool = False,
                      session: Session = DB_SESSION) -> object:
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
                       offset: int = page_offset(), session: Session = DB_SESSION) -> object:
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


# --------------------------------------------------------------------------- statements and exports
Format = Query(default="json", pattern="^(json|csv)$", description="json, or csv for a spreadsheet")


def _csv(text: str, name: str) -> Response:
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


def _pnl_out(p: object) -> sc.ProfitAndLossOut:
    return sc.ProfitAndLossOut.model_validate(p, from_attributes=True)


def _pairs(rows: list[tuple[str, Decimal]]) -> list[sc.LabelAmountOut]:
    return [sc.LabelAmountOut(label=a, amount=b) for a, b in rows]


@router.get("/reports/profit-and-loss", response_model=sc.ProfitReportOut,
            responses={200: {"content": {"text/csv": {}}}}, dependencies=REPORT)
def get_profit_and_loss(company_id: UUID, date_from: date, date_to: date, branch_id: UUID | None = None,
                        by_branch: bool = False, format: str = Format,
                        session: Session = DB_SESSION) -> object:
    """Income, cost of sales and expenses between two dates: consolidated, one branch, or split by branch."""
    r = statement_service.profit_and_loss(session, company_id, date_from, date_to, branch_id=branch_id,
                                          by_branch=by_branch)
    if format == "csv":
        return _csv(csv_export.pnl_csv(r.consolidated), f"profit-and-loss-{date_from}-{date_to}")
    return sc.ProfitReportOut(
        company_id=r.company_id, date_from=r.date_from, date_to=r.date_to, branch_id=r.branch_id,
        consolidated=_pnl_out(r.consolidated),
        branches=[sc.BranchProfitOut(branch_id=b.branch_id, branch_name=b.branch_name, statement=_pnl_out(b.statement))
                  for b in r.branches])


@router.get("/reports/balance-sheet", response_model=sc.BalanceSheetOut, responses={200: {"content": {"text/csv": {}}}},
            dependencies=REPORT)
def get_balance_sheet(company_id: UUID, as_of: date, branch_id: UUID | None = None, format: str = Format,
                      session: Session = DB_SESSION) -> object:
    """What the business has, owes and is worth at the end of a day."""
    r = statement_service.balance_sheet(session, company_id, as_of, branch_id=branch_id)
    if format == "csv":
        return _csv(csv_export.balance_sheet_csv(r.sheet), f"balance-sheet-{as_of}")
    return sc.BalanceSheetOut(
        company_id=r.company_id, as_of=r.as_of, branch_id=r.branch_id, balanced=r.sheet.balanced,
        **{k: getattr(r.sheet, k) for k in (
            "total_assets", "total_liabilities", "total_equity", "accumulated_profit",
            "total_liabilities_and_equity")},
        assets=[sc.StatementLineOut.model_validate(x, from_attributes=True) for x in r.sheet.assets],
        liabilities=[sc.StatementLineOut.model_validate(x, from_attributes=True) for x in r.sheet.liabilities],
        equity=[sc.StatementLineOut.model_validate(x, from_attributes=True) for x in r.sheet.equity])


@router.get("/reports/cash-flow", response_model=sc.CashFlowOut, responses={200: {"content": {"text/csv": {}}}},
            dependencies=REPORT)
def get_cash_flow(company_id: UUID, date_from: date, date_to: date, branch_id: UUID | None = None,
                  format: str = Format, session: Session = DB_SESSION) -> object:
    """Cash, bank, M-Pesa and card balances at the start and end, and what moved them."""
    r = statement_service.cash_flow(session, company_id, date_from, date_to, branch_id=branch_id)
    if format == "csv":
        return _csv(csv_export.cash_flow_csv(r.flow), f"cash-flow-{date_from}-{date_to}")
    return sc.CashFlowOut(company_id=r.company_id, date_from=r.date_from, date_to=r.date_to, branch_id=r.branch_id,
                          opening=r.flow.opening, movements=_pairs(r.flow.movements), net_movement=r.flow.net_movement,
                          closing=r.flow.closing, reconciles=r.flow.reconciles)


@router.get("/reports/vat-summary", response_model=sc.VatReportOut, responses={200: {"content": {"text/csv": {}}}},
            dependencies=REPORT)
def get_vat_summary(company_id: UUID, date_from: date, date_to: date, branch_id: UUID | None = None,
                    format: str = Format, session: Session = DB_SESSION) -> object:
    """VAT charged less VAT paid between two dates: the figure for the VAT return."""
    r = statement_service.vat_summary(session, company_id, date_from, date_to, branch_id=branch_id)
    if format == "csv":
        return _csv(csv_export.vat_csv(r.summary), f"vat-summary-{date_from}-{date_to}")
    v = r.summary
    return sc.VatReportOut(company_id=r.company_id, date_from=r.date_from, date_to=r.date_to, branch_id=r.branch_id,
                           sales_net=v.sales_net, output_vat=v.output_vat, input_vat=v.input_vat,
                           net_payable=v.net_payable, output_by_source=_pairs(v.output_by_source),
                           input_by_source=_pairs(v.input_by_source))


@router.get("/exports/journal", response_class=Response, responses={200: {"content": {"text/csv": {}}}},
            dependencies=REPORT)
def get_journal_export(company_id: UUID, date_from: date, date_to: date,
                       format: str = Query(default="generic", pattern="^(generic|quickbooks|sage)$"),
                       branch_id: UUID | None = None, session: Session = DB_SESSION) -> Response:
    """The journal lines of a period as CSV, for the accountant's software (generic, QuickBooks or Sage)."""
    text = export_service.journal_export(session, company_id, date_from, date_to, format, branch_id=branch_id)
    return _csv(text, f"journal-{format}-{date_from}-{date_to}")


@router.get("/account-mappings", response_model=list[sc.MappingOut], dependencies=READ)
def get_account_mappings(company_id: UUID, session: Session = DB_SESSION) -> object:
    """What the accountant calls each account in their own software."""
    return export_service.list_mappings(session, company_id)


@router.put("/account-mappings/{account_id}", response_model=sc.MappingOut, dependencies=MANAGE_CHART)
def put_account_mapping(account_id: UUID, company_id: UUID, body: sc.MappingIn,
                        session: Session = DB_SESSION) -> object:
    return export_service.set_mapping(session, company_id, account_id, external_code=body.external_code,
                                      external_name=body.external_name)


@router.delete("/account-mappings/{account_id}", status_code=NO_CONTENT, dependencies=MANAGE_CHART)
def delete_account_mapping(account_id: UUID, company_id: UUID, session: Session = DB_SESSION) -> None:
    export_service.clear_mapping(session, company_id, account_id)


# --------------------------------------------------------------------------- expenses
@router.post("/expenses", response_model=sc.ExpenseOut, status_code=status.HTTP_201_CREATED, dependencies=EXPENSE_WRITE)
def post_expense(body: sc.ExpenseIn, session: Session = DB_SESSION) -> object:
    """Write a draft expense: a cost paid at once from cash, bank, M-Pesa or card, with its receipt reference."""
    return expenses.create_expense(
        session, company_id=body.company_id, branch_id=body.branch_id, expense_date=body.expense_date,
        description=body.description, account_id=body.account_id, amount=body.amount, tax_amount=body.tax_amount,
        paid_from=body.paid_from, payee=body.payee, receipt_ref=body.receipt_ref)


@router.get("/expenses", response_model=list[sc.ExpenseOut], dependencies=EXPENSE_READ)
def get_expenses(company_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                 date_from: date | None = None, date_to: date | None = None, limit: int = page_limit(50),
                 offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return expenses.list_expenses(session, company_id=company_id, status=status_, date_from=date_from,
                                  date_to=date_to, limit=limit, offset=offset)


@router.get("/expenses/{expense_id}", response_model=sc.ExpenseOut, dependencies=EXPENSE_READ)
def get_expense(expense_id: UUID, session: Session = DB_SESSION) -> object:
    return expenses.get_expense(session, expense_id)


@router.post("/expenses/{expense_id}/submit", response_model=sc.ExpenseOut, dependencies=EXPENSE_WRITE)
def post_submit_expense(expense_id: UUID, session: Session = DB_SESSION) -> object:
    """Send the draft for approval; it posts at once when no approval rule applies to its size."""
    return expenses.submit_expense(session, expense_id)


@router.post("/expenses/{expense_id}/reverse", response_model=sc.ExpenseOut, dependencies=EXPENSE_DECIDE)
def post_reverse_expense(expense_id: UUID, body: sc.ExpenseReverseIn, session: Session = DB_SESSION) -> object:
    """Cancel a posted expense by posting its mirror image."""
    return expenses.reverse_expense(session, expense_id, body.reason)


# --------------------------------------------------------------------------- bank reconciliation
def _line(c: bank_reconciliation.LedgerCandidate, cleared: bool | None = None) -> sc.ReconLineOut:
    return sc.ReconLineOut(line_id=c.line_id, number=c.number, entry_date=c.entry_date, description=c.description,
                           debit=c.debit, credit=c.credit, amount=c.debit - c.credit,
                           cleared=c.cleared if cleared is None else cleared)


def _recon_out(d: bank_reconciliation.ReconciliationDetail) -> sc.ReconciliationOut:
    r = d.reconciliation
    assert r.account_id is not None
    return sc.ReconciliationOut(
        id=r.id, company_id=r.company_id, account_id=r.account_id, account_code=d.account_code,
        account_name=d.account_name, statement_date=r.statement_date, statement_balance=r.statement_balance,
        book_balance=d.book_balance, cleared_balance=r.cleared_balance, difference=r.difference,
        outstanding=d.outstanding, status=r.status, completed_by=r.completed_by, completed_at=r.completed_at,
        cleared=[_line(x) for x in d.cleared], uncleared=[_line(x) for x in d.uncleared])


@router.post("/bank-reconciliations", response_model=sc.ReconciliationOut, status_code=status.HTTP_201_CREATED,
             dependencies=RECON)
def post_reconciliation(body: sc.ReconcileStartIn, session: Session = DB_SESSION) -> object:
    """Start reconciling a bank, M-Pesa or card account to a statement (its date and closing balance)."""
    return _recon_out(bank_reconciliation.start_reconciliation(
        session, company_id=body.company_id, account_id=body.account_id, statement_date=body.statement_date,
        statement_balance=body.statement_balance))


@router.get("/bank-reconciliations", response_model=list[sc.ReconciliationSummaryOut], dependencies=RECON)
def get_reconciliations(company_id: UUID | None = None, account_id: UUID | None = None,
                        status_: str | None = Query(default=None, alias="status", pattern="^(in_progress|completed)$"),
                        limit: int = page_limit(50), offset: int = page_offset(),
                        session: Session = DB_SESSION) -> object:
    return bank_reconciliation.list_reconciliations(session, company_id=company_id, account_id=account_id,
                                                    status=status_, limit=limit, offset=offset)


@router.get("/bank-reconciliations/{recon_id}", response_model=sc.ReconciliationOut, dependencies=RECON)
def get_reconciliation(recon_id: UUID, session: Session = DB_SESSION) -> object:
    """The reconciliation with the lines cleared and the lines still waiting (the reconciling items)."""
    return _recon_out(bank_reconciliation.get_reconciliation(session, recon_id))


@router.post("/bank-reconciliations/{recon_id}/clear", response_model=sc.ReconciliationOut, dependencies=RECON)
def post_clear(recon_id: UUID, body: sc.ClearIn, session: Session = DB_SESSION) -> object:
    """Mark ledger lines as on the statement (or take the mark off): by id, or everything up to a date."""
    return _recon_out(bank_reconciliation.clear_lines(session, recon_id, line_ids=body.line_ids, until=body.until,
                                                      cleared=body.cleared))


@router.post("/bank-reconciliations/{recon_id}/suggestions", response_model=sc.SuggestResultOut, dependencies=RECON)
def post_suggestions(recon_id: UUID, body: sc.SuggestIn, session: Session = DB_SESSION) -> object:
    """Match statement lines (JSON, or CSV text) to ledger lines; `apply` clears the matches."""
    if (body.lines is None) == (body.csv is None):
        raise ValidationFailed("Send either lines or csv")
    items = ([recon_rules.item(x.date, x.reference, x.description, x.amount) for x in body.lines]
             if body.lines is not None else recon_rules.parse_csv(body.csv or ""))
    r = bank_reconciliation.suggest_matches(session, recon_id, items, apply=body.apply)

    def plain(x: recon_rules.StatementItem) -> sc.SuggestionLineOut:
        return sc.SuggestionLineOut(date=x.day, reference=x.reference, description=x.description, amount=x.amount)

    return sc.SuggestResultOut(
        suggestions=[sc.SuggestionOut(statement=plain(x.item), ledger=_line(x.line, cleared=r.applied), reason=x.reason)
                     for x in r.suggestions],
        unmatched=[plain(x) for x in r.unmatched], applied=r.applied, reconciliation=_recon_out(r.detail))


@router.post("/bank-reconciliations/{recon_id}/complete", response_model=sc.ReconciliationOut, dependencies=RECON)
def post_complete_reconciliation(recon_id: UUID, session: Session = DB_SESSION) -> object:
    """Finish the reconciliation: only when the cleared lines add up to the statement's balance. Final."""
    return _recon_out(bank_reconciliation.complete_reconciliation(session, recon_id))


@router.delete("/bank-reconciliations/{recon_id}", status_code=NO_CONTENT, dependencies=RECON)
def delete_reconciliation(recon_id: UUID, session: Session = DB_SESSION) -> None:
    """Throw away a reconciliation that is still in progress."""
    bank_reconciliation.cancel_reconciliation(session, recon_id)
