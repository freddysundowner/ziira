"""CSV for reports and for the accountant's software. Pure rules: rows in, text out.

Every text cell is made safe for spreadsheets (see ziira.sdk `to_csv`: nothing in a file can run as a formula).

The QuickBooks and Sage layouts were written from those products' public import documentation and have not been tried
in the real software: have the accountant import a small file first.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ziira.modules.finance.domain import statements
from ziira.sdk import safe, to_csv

FORMATS = ("generic", "quickbooks", "sage")
__all__ = ["FORMATS", "JournalRow", "balance_sheet_csv", "cash_flow_csv", "journal_csv", "pnl_csv", "safe", "to_csv",
           "vat_csv"]


@dataclass(frozen=True)
class JournalRow:
    """One journal line, with what the entry says about it."""

    entry_number: str
    entry_date: date
    source_type: str | None
    description: str | None
    account_code: str
    account_name: str
    branch: str | None
    debit: Decimal
    credit: Decimal
    external_code: str | None = None      # the account's code in the accountant's software
    external_name: str | None = None      # and its name there


def _dmy(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def journal_csv(rows: list[JournalRow], fmt: str) -> str:
    """The journal lines in a layout an accounting package can import. `fmt` is generic, quickbooks or sage."""
    if fmt == "quickbooks":
        # QuickBooks Online "journal entries" import: one row per line, rows of an entry share the journal number.
        return to_csv(
            ["*JournalNo", "*JournalDate", "*AccountName", "*Debits", "*Credits", "Description", "Name", "Location"],
            [[r.entry_number, _dmy(r.entry_date), r.external_name or f"{r.account_code} {r.account_name}",
              r.debit if r.debit else "", r.credit if r.credit else "", r.description or "", "", r.branch or ""]
             for r in rows])
    if fmt == "sage":
        # Sage 50 journal import (audit trail): JD is a debit, JC a credit; no tax is added to a journal line.
        return to_csv(
            ["Type", "Account Reference", "Nominal A/C Ref", "Department", "Date", "Reference", "Details",
             "Net Amount", "Tax Code", "Tax Amount"],
            [["JD" if r.debit else "JC", "", r.external_code or r.account_code, "", _dmy(r.entry_date),
              r.entry_number, r.description or r.account_name, r.debit or r.credit, "T9", Decimal("0.00")]
             for r in rows])
    if fmt == "generic":
        return to_csv(
            ["Entry", "Date", "Source", "Account code", "Account name", "Branch", "Description", "Debit", "Credit"],
            [[r.entry_number, r.entry_date, r.source_type or "manual", r.account_code, r.account_name, r.branch or "",
              r.description or "", r.debit, r.credit] for r in rows])
    raise ValueError(f"Unknown format '{fmt}'")


# --------------------------------------------------------------------------- statements as CSV
def pnl_csv(pnl: statements.ProfitAndLoss) -> str:
    rows: list[list[object]] = []
    for section, lines, total in (("Income", pnl.income, pnl.total_income),
                                  ("Cost of sales", pnl.cost_of_sales, pnl.total_cost_of_sales),
                                  ("Expenses", pnl.expenses, pnl.total_expenses)):
        rows += [[section, x.code, x.name, x.amount] for x in lines]
        rows.append([section, "", f"Total {section.lower()}", total])
        if section == "Cost of sales":
            rows.append(["", "", "Gross profit", pnl.gross_profit])
    rows.append(["", "", "Net profit", pnl.net_profit])
    return to_csv(["Section", "Code", "Account", "Amount"], rows)


def balance_sheet_csv(sheet: statements.BalanceSheet) -> str:
    rows: list[list[object]] = []
    for section, lines, total in (("Assets", sheet.assets, sheet.total_assets),
                                  ("Liabilities", sheet.liabilities, sheet.total_liabilities),
                                  ("Equity", sheet.equity, sheet.total_equity)):
        rows += [[section, x.code, x.name, x.amount] for x in lines]
        rows.append([section, "", f"Total {section.lower()}", total])
    rows += [["Equity", "", "Profit not yet closed to equity", sheet.accumulated_profit],
             ["", "", "Total liabilities and equity", sheet.total_liabilities_and_equity]]
    return to_csv(["Section", "Code", "Account", "Amount"], rows)


def cash_flow_csv(flow: statements.CashFlow) -> str:
    rows: list[list[object]] = [["Opening balance", flow.opening]]
    rows += [[label, amount] for label, amount in flow.movements]
    rows += [["Net movement", flow.net_movement], ["Closing balance", flow.closing]]
    return to_csv(["Line", "Amount"], rows)


def vat_csv(vat: statements.VatSummary) -> str:
    rows: list[list[object]] = [["Sales before VAT (net of returns)", vat.sales_net],
                                ["VAT charged (output)", vat.output_vat]]
    rows += [[f"  from {label}", amount] for label, amount in vat.output_by_source]
    rows.append(["VAT paid (input)", vat.input_vat])
    rows += [[f"  from {label}", amount] for label, amount in vat.input_by_source]
    rows.append(["VAT payable (refundable if negative)", vat.net_payable])
    return to_csv(["Line", "Amount"], rows)
