"""Checks on the books themselves: unusual expenses, reconciliations left open, gross margin."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.finance.intel_checks.common import currency, ids, money, since
from ziira.modules.intel.public import (
    INTEL_BASELINE_METRIC,
    INTEL_CHECK,
    BaselineMetric,
    Candidate,
    CheckContext,
    IntelCheck,
    Record,
    Sample,
    fingerprint,
    is_unusual,
)
from ziira.sdk import Session, provides

EXPENSE_METRIC = "finance.expense_per_account"
COUNTED = "x.status in ('approved', 'posted')"


def expense_key(branch_id: UUID | None, account_id: UUID) -> str:
    """The baseline dimension of an expense account at a branch."""
    return f"{branch_id or 'none'}:{account_id}"


@provides(INTEL_BASELINE_METRIC)
class ExpensePerAccount(BaselineMetric):
    """What a branch spends on an expense account in a day (days with spending only)."""

    code = EXPENSE_METRIC
    title = "Expense amount per account per day"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        rows = session.execute(text(
            f"select x.branch_id, x.account_id, sum(x.amount) as total from finance.expense x "
            f"where x.company_id = :c and {COUNTED} and x.expense_date between :a and :b "
            f"group by x.branch_id, x.account_id, x.expense_date"),
            {"c": str(company_id), "a": date_from, "b": date_to}).all()
        return [Sample(expense_key(ids(r.branch_id), r.account_id), r.total) for r in rows]


@provides(INTEL_CHECK)
class UnusualExpense(IntelCheck):
    """A day's spending on an expense account far above what that branch normally spends on it."""

    code = "finance.unusual_expense"
    title = "Unusually large expense"
    area = "books"
    description = "A branch spent far more on one kind of expense in a day than it normally does."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 7, "min_amount": "500.00", "min_ratio": "2.0", "min_samples": 14}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        min_amount, min_ratio = ctx.number("min_amount"), ctx.number("min_ratio")
        rows = session.execute(text(
            f"select x.branch_id, x.account_id, x.expense_date, sum(x.amount) as total, a.code, a.name, "
            f"array_agg(x.id order by x.number) as ids, array_agg(x.number order by x.number) as numbers "
            f"from finance.expense x join finance.account a on a.id = x.account_id "
            f"where x.company_id = :c and {COUNTED} and x.expense_date >= :floor and x.expense_date <= :today "
            f"group by x.branch_id, x.account_id, x.expense_date, a.code, a.name order by x.expense_date"),
            {"c": str(ctx.company_id), "floor": since(ctx.today, ctx.number("days")), "today": ctx.today}).all()
        unit = currency(session, ctx.company_id)
        found = []
        for r in rows:
            baseline = ctx.baseline(EXPENSE_METRIC, expense_key(ids(r.branch_id), r.account_id))
            if (baseline is None or r.total < min_amount or r.total < min_ratio * baseline.mean
                    or not is_unusual(r.total, baseline, min_samples=int(ctx.number("min_samples")))):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.account_id, r.expense_date),
                severity=self.default_severity, company_id=ctx.company_id, branch_id=ids(r.branch_id),
                entity_type="finance.account", entity_id=r.account_id, period_start=r.expense_date,
                period_end=r.expense_date, value=r.total, expected_value=baseline.mean, amount=r.total - baseline.mean,
                summary=(f"Expenses on {r.code} {r.name} came to {unit} {money(r.total)} on {r.expense_date}, "
                         f"against a usual {unit} {money(baseline.mean)} on days with spending there."),
                recommended_action="Check the receipts for these expenses.",
                records=tuple(Record("finance.expense", ids(i), f"Expense {n}")
                              for i, n in zip(r.ids, r.numbers, strict=True)),
                figures={"account": f"{r.code} {r.name}", "usual": f"{baseline.mean:.2f}", "p95": f"{baseline.p95:.2f}",
                         "days_observed": str(baseline.sample_size)}))
        return found


@provides(INTEL_CHECK)
class StaleReconciliation(IntelCheck):
    """A bank reconciliation started and never finished."""

    code = "finance.stale_reconciliation"
    title = "Bank reconciliation left open"
    area = "books"
    description = "A bank reconciliation was started a while ago and has not been completed."
    default_severity = "low"
    params: dict[str, Any] = {"days_open": 30}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        limit = int(ctx.number("days_open"))
        rows = session.execute(text(
            "select r.id, r.statement_date, (r.created_at at time zone :tz)::date as started, a.code, a.name "
            "from finance.bank_reconciliation r join finance.account a on a.id = r.account_id "
            "where r.company_id = :c and r.status = 'in_progress' "
            "and (r.created_at at time zone :tz)::date <= :cutoff order by r.created_at"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "cutoff": since(ctx.today, limit)}).all()
        found = []
        for r in rows:
            age = (ctx.today - r.started).days
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium" if age >= 2 * limit else "low",
                company_id=ctx.company_id, entity_type="finance.bank_reconciliation", entity_id=r.id,
                period_end=r.statement_date, value=Decimal(age), expected_value=Decimal(limit),
                summary=(f"The reconciliation of {r.code} {r.name} to the statement of {r.statement_date} was "
                         f"started on {r.started} and is still not complete after {age} days."),
                recommended_action="Finish the reconciliation or cancel it and start again.",
                records=(Record("finance.bank_reconciliation", r.id, f"Reconciliation of {r.code} {r.name}"),),
                figures={"started": str(r.started), "days_open": str(age)}))
        return found


@provides(INTEL_CHECK)
class UnreconciledBankLines(IntelCheck):
    """Money movements on a bank account that never reached a reconciliation."""

    code = "finance.unreconciled_bank_lines"
    title = "Old unreconciled bank lines"
    area = "books"
    description = "Entries on a bank account are older than the limit and still not matched to a bank statement."
    default_severity = "low"
    params: dict[str, Any] = {"age_days": 45, "days": 180}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        age = int(ctx.number("age_days"))
        rows = session.execute(text(
            "select a.id, a.code, a.name, count(*) as n, sum(l.debit - l.credit) as net, "
            "sum(l.debit + l.credit) as gross, min(e.entry_date) as oldest "
            "from finance.account a join finance.journal_line l on l.account_id = a.id "
            "join finance.journal_entry e on e.id = l.entry_id "
            "left join finance.reconciliation_line rl on rl.journal_line_id = l.id "
            "where a.company_id = :c and rl.id is null "
            "and a.subtype in ('bank', 'mobile_money_clearing', 'card_clearing') "
            "and e.entry_date <= :cutoff and e.entry_date >= :floor "
            "and exists (select 1 from finance.bank_reconciliation r where r.account_id = a.id "
            "and r.status = 'completed') group by a.id, a.code, a.name order by a.code"),
            {"c": str(ctx.company_id), "cutoff": since(ctx.today, age),
             "floor": since(ctx.today, ctx.number("days"))}).all()
        unit = currency(session, ctx.company_id)
        found = []
        for r in rows:
            oldest_age = (ctx.today - r.oldest).days
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium" if oldest_age >= 2 * age else "low",
                company_id=ctx.company_id, entity_type="finance.account", entity_id=r.id,
                period_start=r.oldest, value=Decimal(r.n), amount=abs(r.net),
                summary=(f"{r.n} entries on {r.code} {r.name} (net {unit} {money(r.net)}) are more than {age} days old "
                         f"and not matched to any bank statement. The oldest is from {r.oldest}."),
                recommended_action="Reconcile the account to its latest statement and look into what does not match.",
                records=(Record("finance.account", r.id, f"{r.code} {r.name}"),),
                figures={"lines": str(r.n), "net": f"{r.net:.2f}", "oldest": str(r.oldest)}))
        return found


@provides(INTEL_CHECK)
class LowGrossMargin(IntelCheck):
    """The month so far earns a much lower gross margin than the previous three months."""

    code = "finance.low_gross_margin"
    title = "Gross margin well below normal"
    area = "books"
    description = "The share of sales kept after the cost of what was sold is far below the last three months."
    default_severity = "medium"
    params: dict[str, Any] = {"drop_points": "10.0", "min_income": "1000.00", "min_day": 5, "min_months": 2}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        if ctx.today.day < int(ctx.number("min_day")):
            return []
        month = ctx.today.replace(day=1)
        start = _months_back(month, 3)
        rows = session.execute(text(
            "select date_trunc('month', e.entry_date)::date as month, "
            "coalesce(sum(case when a.type = 'income' then l.credit - l.debit end), 0) as income, "
            "coalesce(sum(case when a.type = 'expense' and a.subtype = 'cogs' then l.debit - l.credit end), 0) as cost "
            "from finance.journal_line l join finance.journal_entry e on e.id = l.entry_id "
            "join finance.account a on a.id = l.account_id "
            "where l.company_id = :c and a.type in ('income', 'expense') and e.entry_date >= :start "
            "and e.entry_date <= :today group by 1"),
            {"c": str(ctx.company_id), "start": start, "today": ctx.today}).all()
        now = next((r for r in rows if r.month == month), None)
        before = [r for r in rows if r.month < month and r.income > 0]
        min_income = ctx.number("min_income")
        if now is None or now.income < min_income or len(before) < int(ctx.number("min_months")):
            return []
        before_income = sum((r.income for r in before), Decimal(0))
        if before_income < min_income:
            return []
        usual = (before_income - sum((r.cost for r in before), Decimal(0))) / before_income * 100
        current = (now.income - now.cost) / now.income * 100
        drop, limit = usual - current, ctx.number("drop_points")
        if drop <= limit:
            return []
        unit = currency(session, ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, month), severity="high" if drop >= 2 * limit else "medium",
            company_id=ctx.company_id, entity_type="finance.company", entity_id=ctx.company_id,
            period_start=month, period_end=ctx.today, value=current.quantize(Decimal("0.1")),
            expected_value=usual.quantize(Decimal("0.1")), amount=now.income * drop / 100,
            summary=(f"The gross margin so far this month is {current:.1f}% on sales of {unit} {money(now.income)}, "
                     f"against {usual:.1f}% over the previous {len(before)} months."),
            recommended_action="Check selling prices, discounts, returns and recent purchase costs.",
            figures={"margin_now": f"{current:.1f}", "margin_before": f"{usual:.1f}",
                     "sales_now": f"{now.income:.2f}", "cost_now": f"{now.cost:.2f}"})]


def _months_back(month_start: date, months: int) -> date:
    """The first day of the month `months` before the given first day of a month."""
    index = month_start.year * 12 + month_start.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)
