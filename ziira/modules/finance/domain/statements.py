"""Financial statements built from account totals: profit and loss, balance sheet, cash flow and the VAT summary.

Pure rules: the services read the journal lines and hand the totals here. Every statement is arithmetic over the same
debit and credit totals, so it reconciles to the journal lines by construction; each result also carries the check that
proves it (`balanced`, `reconciles`).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from ziira.modules.finance.domain.entries import natural_balance

COST_OF_SALES = frozenset({"cogs", "shrinkage", "purchase_variance"})
CASH_SUBTYPES = ("cash", "bank", "mobile_money_clearing", "card_clearing")
ZERO = Decimal(0)


@dataclass(frozen=True)
class AccountTotal:
    """Debits and credits posted to one account over some span."""

    account_id: object
    code: str
    name: str
    type: str
    subtype: str | None
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class StatementLine:
    account_id: object
    code: str
    name: str
    amount: Decimal


def _lines(totals: list[AccountTotal]) -> list[StatementLine]:
    """Accounts with something in them, each at the amount it normally shows."""
    return [StatementLine(t.account_id, t.code, t.name, natural_balance(t.type, t.debit, t.credit))
            for t in sorted(totals, key=lambda x: x.code) if t.debit or t.credit]


def _sum(lines: list[StatementLine]) -> Decimal:
    return sum((x.amount for x in lines), ZERO)


@dataclass(frozen=True)
class ProfitAndLoss:
    income: list[StatementLine]
    total_income: Decimal
    cost_of_sales: list[StatementLine]
    total_cost_of_sales: Decimal
    gross_profit: Decimal
    expenses: list[StatementLine]
    total_expenses: Decimal
    net_profit: Decimal


def profit_and_loss(totals: list[AccountTotal]) -> ProfitAndLoss:
    """Income less cost of sales is the gross profit; less the other expenses is the net profit."""
    income = _lines([t for t in totals if t.type == "income"])
    cost = _lines([t for t in totals if t.type == "expense" and t.subtype in COST_OF_SALES])
    other = _lines([t for t in totals if t.type == "expense" and t.subtype not in COST_OF_SALES])
    gross = _sum(income) - _sum(cost)
    return ProfitAndLoss(income, _sum(income), cost, _sum(cost), gross, other, _sum(other), gross - _sum(other))


@dataclass(frozen=True)
class BalanceSheet:
    assets: list[StatementLine]
    total_assets: Decimal
    liabilities: list[StatementLine]
    total_liabilities: Decimal
    equity: list[StatementLine]
    total_equity: Decimal
    accumulated_profit: Decimal          # profit not yet closed into retained earnings (no year-end closing entries)
    total_liabilities_and_equity: Decimal

    @property
    def balanced(self) -> bool:
        return self.total_assets == self.total_liabilities_and_equity


def balance_sheet(totals: list[AccountTotal]) -> BalanceSheet:
    """What the business has, owes and is worth, from totals up to a date. Profit that has not been closed to equity
    is shown on its own line, so assets always equal liabilities plus equity."""
    assets = _lines([t for t in totals if t.type == "asset"])
    liabilities = _lines([t for t in totals if t.type == "liability"])
    equity = _lines([t for t in totals if t.type == "equity"])
    pl = profit_and_loss(totals)
    total_equity = _sum(equity) + pl.net_profit
    return BalanceSheet(assets, _sum(assets), liabilities, _sum(liabilities), equity, _sum(equity), pl.net_profit,
                        _sum(liabilities) + total_equity)


@dataclass(frozen=True)
class CashFlow:
    opening: Decimal
    movements: list[tuple[str, Decimal]]       # what caused the cash to move (sales, supplier payments ...), net
    closing: Decimal

    @property
    def net_movement(self) -> Decimal:
        return sum((m for _, m in self.movements), ZERO)

    @property
    def reconciles(self) -> bool:
        return self.opening + self.net_movement == self.closing


SOURCE_LABELS = {
    "sale": "Sales", "sale_return": "Sales returns", "customer_payment": "Customer payments",
    "customer_refund": "Customer refunds", "supplier_payment": "Supplier payments",
    "supplier_refund": "Supplier refunds", "expense": "Expenses", "settlement": "M-Pesa settlements",
    "cash_deposit": "Cash deposits", "till_variance": "Till differences", "manual": "Manual journals",
    "manual_journal": "Manual journals",
}


def cash_flow(opening: Decimal, closing: Decimal, by_source: dict[str | None, Decimal]) -> CashFlow:
    """Cash and bank accounts: where they started, what moved them (by the kind of document), where they ended."""
    rows = sorted(((SOURCE_LABELS.get(k or "manual", (k or "manual").replace("_", " ").capitalize()), v)
                   for k, v in by_source.items() if v != 0), key=lambda x: (-x[1], x[0]))
    return CashFlow(opening, rows, closing)


@dataclass(frozen=True)
class VatSummary:
    sales_net: Decimal                   # sales less returns, before VAT
    output_vat: Decimal                  # VAT charged to customers, less what was given back
    input_vat: Decimal                   # VAT paid to suppliers and on expenses
    net_payable: Decimal                 # output less input; negative means a refund is due
    output_by_source: list[tuple[str, Decimal]] = field(default_factory=list)
    input_by_source: list[tuple[str, Decimal]] = field(default_factory=list)


def vat_summary(totals: list[AccountTotal], output_by_source: dict[str | None, Decimal],
                input_by_source: dict[str | None, Decimal]) -> VatSummary:
    """VAT charged less VAT paid, from the VAT accounts, with the net sales it relates to."""
    sales = sum((natural_balance(t.type, t.debit, t.credit) for t in totals if t.subtype in ("sales", "sales_returns")),
                ZERO)
    output = sum((natural_balance(t.type, t.debit, t.credit) for t in totals if t.subtype == "vat_output"), ZERO)
    inbound = sum((natural_balance(t.type, t.debit, t.credit) for t in totals if t.subtype == "vat_input"), ZERO)

    def labelled(by: dict[str | None, Decimal]) -> list[tuple[str, Decimal]]:
        return sorted(((SOURCE_LABELS.get(k or "manual", (k or "manual").replace("_", " ").capitalize()), v)
                       for k, v in by.items() if v != 0), key=lambda x: (-x[1], x[0]))

    return VatSummary(sales, output, inbound, output - inbound, labelled(output_by_source), labelled(input_by_source))
