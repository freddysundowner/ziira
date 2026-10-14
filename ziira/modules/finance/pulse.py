"""Finance's figures for the Command Center: cash, profit, margin, expenses and journals waiting."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, PulseSource
from ziira.sdk import Session, provides


@provides(COMMAND_PULSE_SOURCE)
class FinancePulse(PulseSource):
    """Cash and bank balance, month-to-date profit and margin, the day's expenses, and journals waiting."""

    code = "finance"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        c = str(company_id)
        cash = session.execute(text(
            "select coalesce(sum(l.debit - l.credit), 0) from finance.journal_line l "
            "join finance.journal_entry e on e.id = l.entry_id join finance.account a on a.id = l.account_id "
            "where l.company_id = :c and a.type = 'asset' and a.subtype in ('cash', 'bank') and e.entry_date <= :d"),
            {"c": c, "d": day}).scalar_one()
        out = [Figure("finance.cash_and_bank", "Cash and bank balance", "money", Decimal(cash), higher_is_better=True)]

        # Income, cost of sales and all expenses from the month's first day, per branch of the line
        rows = session.execute(text(
            "select l.branch_id, "
            "coalesce(sum(case when a.type = 'income' then l.credit - l.debit end), 0) as income, "
            "coalesce(sum(case when a.type = 'expense' and a.subtype = 'cogs' then l.debit - l.credit end), 0) "
            "as cost, "
            "coalesce(sum(case when a.type = 'expense' then l.debit - l.credit end), 0) as costs "
            "from finance.journal_line l join finance.journal_entry e on e.id = l.entry_id "
            "join finance.account a on a.id = l.account_id "
            "where l.company_id = :c and a.type in ('income', 'expense') and e.entry_date >= :start "
            "and e.entry_date <= :d group by l.branch_id"),
            {"c": c, "start": day.replace(day=1), "d": day}).all()
        income = sum((Decimal(r.income) for r in rows), Decimal(0))
        cost = sum((Decimal(r.cost) for r in rows), Decimal(0))
        costs = sum((Decimal(r.costs) for r in rows), Decimal(0))
        out.append(Figure("finance.net_profit_mtd", "Net profit this month", "money", income - costs,
                          higher_is_better=True))
        if income > 0:
            out.append(Figure("finance.gross_margin_mtd", "Gross margin this month", "percent",
                              ((income - cost) / income * 100).quantize(Decimal("0.1")), higher_is_better=True))
        for r in rows:
            if r.branch_id is None:
                continue
            out.append(Figure("finance.net_profit_mtd", "Net profit this month", "money", Decimal(r.income - r.costs),
                              branch_id=UUID(str(r.branch_id)), higher_is_better=True))
            if r.income > 0:
                out.append(Figure("finance.gross_margin_mtd", "Gross margin this month", "percent",
                                  ((r.income - r.cost) / r.income * 100).quantize(Decimal("0.1")),
                                  branch_id=UUID(str(r.branch_id)), higher_is_better=True))

        spent = session.execute(text(
            "select x.branch_id, sum(x.amount) as total from finance.expense x where x.company_id = :c "
            "and x.status in ('approved', 'posted') and x.expense_date = :d group by x.branch_id"),
            {"c": c, "d": day}).all()
        out.append(Figure("finance.expenses_day", "Expenses today", "money",
                          sum((Decimal(r.total) for r in spent), Decimal(0)), higher_is_better=False))
        out.extend(Figure("finance.expenses_day", "Expenses today", "money", Decimal(r.total),
                          branch_id=UUID(str(r.branch_id)), higher_is_better=False) for r in spent if r.branch_id)

        waiting = session.execute(text(
            "select count(*) from finance.manual_journal where company_id = :c and status = 'pending_approval'"),
            {"c": c}).scalar_one()
        out.append(Figure("finance.manual_journals_waiting", "Manual journals waiting for approval", "count",
                          Decimal(waiting), higher_is_better=False))
        return out
