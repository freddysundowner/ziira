"""Use cases: profit and loss, balance sheet, cash flow summary and VAT summary.

They read the journal lines, so each can be produced for any past date and always reconciles to the books. A user with a
branch grant sees only that branch's lines. All need 'reports.view'.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.domain import statements as st
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.finance_repo import TotalRow
from ziira.modules.finance.services.reports import _scopes
from ziira.sdk import Session, ValidationFailed, check_company


def _totals(rows: list[TotalRow]) -> list[st.AccountTotal]:
    return [st.AccountTotal(r.account_id, r.code, r.name, r.type, r.subtype, r.debit, r.credit) for r in rows]


def _span(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValidationFailed("The end date is before the start date")


@dataclass(frozen=True)
class BranchProfit:
    branch_id: UUID | None
    branch_name: str
    statement: st.ProfitAndLoss


@dataclass(frozen=True)
class ProfitReport:
    company_id: UUID
    date_from: date
    date_to: date
    branch_id: UUID | None
    consolidated: st.ProfitAndLoss
    branches: list[BranchProfit]              # filled when asked for a split by branch


def profit_and_loss(session: Session, company_id: UUID, date_from: date, date_to: date, *,
                    branch_id: UUID | None = None, by_branch: bool = False) -> ProfitReport:
    """Income, cost of sales and expenses between two dates; consolidated, for one branch, or split by branch."""
    _span(date_from, date_to)
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    rows = finance_repo.account_totals(session, scopes, company_id, date_to, date_from=date_from, branch_id=branch_id,
                                       group_branch=by_branch)
    pnl_types = [r for r in rows if r.type in ("income", "expense")]
    consolidated_rows: dict[UUID, TotalRow] = {}
    for r in pnl_types:                                    # one row per account across every branch
        old = consolidated_rows.get(r.account_id)
        consolidated_rows[r.account_id] = r if old is None else TotalRow(
            r.account_id, r.code, r.name, r.type, r.subtype, None, old.debit + r.debit, old.credit + r.credit)
    branches: list[BranchProfit] = []
    if by_branch:
        names = finance_repo.branch_names(session, company_id)
        for key in sorted({r.branch_id for r in pnl_types}, key=lambda b: names.get(b, "") if b else "~"):
            branches.append(BranchProfit(key, names.get(key, "Not tied to a branch") if key else "Not tied to a branch",
                                         st.profit_and_loss(_totals([r for r in pnl_types if r.branch_id == key]))))
    return ProfitReport(company_id, date_from, date_to, branch_id,
                        st.profit_and_loss(_totals(list(consolidated_rows.values()))), branches)


@dataclass(frozen=True)
class BalanceSheetReport:
    company_id: UUID
    as_of: date
    branch_id: UUID | None
    sheet: st.BalanceSheet


def balance_sheet(session: Session, company_id: UUID, as_of: date, *,
                  branch_id: UUID | None = None) -> BalanceSheetReport:
    """Assets, liabilities and equity up to a date, with profit not yet closed to equity on its own line."""
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    rows = finance_repo.account_totals(session, scopes, company_id, as_of, branch_id=branch_id)
    return BalanceSheetReport(company_id, as_of, branch_id, st.balance_sheet(_totals(rows)))


@dataclass(frozen=True)
class CashFlowReport:
    company_id: UUID
    date_from: date
    date_to: date
    branch_id: UUID | None
    flow: st.CashFlow


def cash_flow(session: Session, company_id: UUID, date_from: date, date_to: date, *,
              branch_id: UUID | None = None) -> CashFlowReport:
    """Cash, bank, mobile money and card accounts: the balance at the start, what moved them, the balance at the end."""
    _span(date_from, date_to)
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    from datetime import timedelta

    def balance(day: date) -> Decimal:
        rows = finance_repo.account_totals(session, scopes, company_id, day, branch_id=branch_id,
                                           subtypes=st.CASH_SUBTYPES)
        return sum((r.debit - r.credit for r in rows), Decimal(0))

    moves = finance_repo.totals_by_source(session, scopes, company_id, date_from, date_to,
                                          subtypes=st.CASH_SUBTYPES, branch_id=branch_id)
    return CashFlowReport(company_id, date_from, date_to, branch_id,
                          st.cash_flow(balance(date_from - timedelta(days=1)), balance(date_to), moves))


@dataclass(frozen=True)
class VatReport:
    company_id: UUID
    date_from: date
    date_to: date
    branch_id: UUID | None
    summary: st.VatSummary


def vat_summary(session: Session, company_id: UUID, date_from: date, date_to: date, *,
                branch_id: UUID | None = None) -> VatReport:
    """VAT charged on sales less VAT paid on purchases and expenses between two dates (the figure for the VAT return),
    from the VAT accounts. Rates come from the tax codes chosen on each product, entered by hand."""
    _span(date_from, date_to)
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    rows = finance_repo.account_totals(session, scopes, company_id, date_to, date_from=date_from, branch_id=branch_id,
                                       subtypes=("sales", "sales_returns", "vat_output", "vat_input"))
    output = finance_repo.totals_by_source(session, scopes, company_id, date_from, date_to, subtypes=("vat_output",),
                                           branch_id=branch_id)
    inbound = finance_repo.totals_by_source(session, scopes, company_id, date_from, date_to, subtypes=("vat_input",),
                                            branch_id=branch_id)
    return VatReport(company_id, date_from, date_to, branch_id,
                     st.vat_summary(_totals(rows), {k: -v for k, v in output.items()}, inbound))
