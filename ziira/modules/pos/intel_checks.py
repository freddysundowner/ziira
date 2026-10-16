"""POS's checks for Ziira Intelligence: tills, sales controls, and what customers owe.

Every check reads this unit's own tables (and CRM through its public.py for names and credit limits), only inside a
look-back window, and only reports; it never writes. Findings are questions for a person, never accusations.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import (
    BaselineMetric,
    Candidate,
    CheckContext,
    IntelCheck,
    Record,
    Sample,
    fingerprint,
    is_unusual,
)
from ziira.modules.pos.domain.insights import paying_slower, rate, unusually_low
from ziira.modules.pos.services.common import unit_enabled
from ziira.sdk import Session

ZERO = Decimal(0)
BASELINE_MIN_DAY_SALES = 3        # a cashier's day with fewer sales than this says nothing about their habits


def money(amount: Decimal) -> str:
    """12345.5 -> '12,345.50'."""
    return f"{amount:,.2f}"


def currency(session: Session, company_id: UUID) -> str:
    """The company's base currency code."""
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def percent(value: Decimal) -> str:
    return f"{value * 100:.0f}%"


def customer_names(session: Session, company_id: UUID, ids: Sequence[UUID | None]) -> dict[UUID, str]:
    """Customer names from CRM when it is enabled; otherwise empty (the summaries then say 'a customer')."""
    wanted = {i for i in ids if i is not None}
    if not wanted or not unit_enabled(session, "crm"):
        return {}
    from ziira.modules.crm.public import find_customers

    return {cid: view.name for cid, view in find_customers(session, wanted).items()}


def _records(kind: str, word: str, ids: Sequence[UUID], numbers: Sequence[str]) -> tuple[Record, ...]:
    """The first five records of a group, labelled with their numbers."""
    return tuple(Record(kind, i, f"{word} {n}") for i, n in list(zip(ids, numbers, strict=True))[:5])


def who(names: dict[UUID, str], customer_id: UUID) -> str:
    return names.get(customer_id, "A customer")


# --------------------------------------------------------------------------------------------- tills
class TillCashVariance(IntelCheck):
    """A till was closed with the cash counted far from the cash expected."""

    code = "pos.till_cash_variance"

    value_kind = "money"
    title = "Till closed with a cash difference"
    area = "cash_sales"
    description = "A cashier closed their till and the cash counted was far from what the sales say it should be."
    default_severity = "medium"
    params: dict[str, Any] = {"limit": "500.00", "days": 14}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Closed tills in the window whose difference (either way) is beyond the limit."""
        limit = ctx.number("limit")
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select t.id, t.branch_id, t.business_date, t.variance, t.expected_cash, t.counted_cash, "
            "u.full_name as cashier, b.name as branch from pos.till_session t "
            "join kernel.branch b on b.id = t.branch_id join kernel.app_user u on u.id = t.cashier_id "
            "where b.company_id = :c and t.status = 'closed' and t.business_date >= :since "
            "and abs(t.variance) > :limit order by t.business_date"),
            {"c": str(ctx.company_id), "since": since, "limit": limit}).all()
        found = []
        for r in rows:
            variance = Decimal(r.variance)
            size = abs(variance)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="high" if size >= limit * 5 else "medium",
                summary=(f"{r.cashier}'s till at {r.branch} on {r.business_date} closed {cur} {money(size)} "
                         f"{'short' if variance < 0 else 'over'}: {cur} {money(Decimal(r.counted_cash))} counted "
                         f"against {cur} {money(Decimal(r.expected_cash))} expected."),
                recommended_action="Ask the cashier and the branch manager to explain the difference.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="pos.till_session", entity_id=r.id,
                period_start=r.business_date, period_end=r.business_date, value=variance, expected_value=ZERO,
                amount=size, records=(Record("pos.till_session", r.id, f"Till of {r.cashier}, {r.business_date}"),),
                figures={"expected_cash": money(Decimal(r.expected_cash)),
                         "counted_cash": money(Decimal(r.counted_cash)), "variance": money(variance)}))
        return found


# --------------------------------------------------------------------------------------------- cashier habits
@dataclass(frozen=True)
class CashierDay:
    """What one cashier did on one business day."""

    cashier_id: UUID
    day: date
    branch_id: UUID
    cashier: str
    sales: int
    voids: int
    void_total: Decimal
    posted_total: Decimal
    list_value: Decimal
    concession: Decimal       # price reductions and discounts given on the day's sales
    refunds: Decimal          # returns the person processed that day


def cashier_days(session: Session, company_id: UUID, date_from: date, date_to: date) -> list[CashierDay]:
    """Per cashier and day from `date_from` up to (not including) `date_to`."""
    params = {"c": str(company_id), "f": date_from, "t": date_to}
    sales = session.execute(text(
        "select s.cashier_id, s.business_date as day, u.full_name, "
        "(array_agg(s.branch_id order by s.sold_at desc))[1] as branch_id, "
        "count(*) as n, count(*) filter (where s.status = 'voided') as voids, "
        "coalesce(sum(s.total) filter (where s.status = 'voided'), 0) as void_total, "
        "coalesce(sum(s.total) filter (where s.status = 'posted'), 0) as posted_total "
        "from pos.sale s join kernel.app_user u on u.id = s.cashier_id "
        "where s.company_id = :c and s.business_date >= :f and s.business_date < :t "
        "group by s.cashier_id, s.business_date, u.full_name"), params).all()
    concessions = {(r.cashier_id, r.day): r for r in session.execute(text(
        "select s.cashier_id, s.business_date as day, "
        "sum(greatest(l.list_price - l.unit_price, 0) * l.quantity + l.discount_amount) as concession, "
        "sum(l.list_price * l.quantity) as list_value from pos.sale s join pos.sale_line l on l.sale_id = s.id "
        "where s.company_id = :c and s.status = 'posted' and s.business_date >= :f and s.business_date < :t "
        "group by s.cashier_id, s.business_date"), params)}
    refunds = {(r.created_by, r.day): Decimal(r.total) for r in session.execute(text(
        "select created_by, coalesce(business_date, created_at::date) as day, sum(total) as total "
        "from pos.sales_return where company_id = :c and status = 'posted' "
        "and coalesce(business_date, created_at::date) >= :f and coalesce(business_date, created_at::date) < :t "
        "group by created_by, coalesce(business_date, created_at::date)"), params)}
    out = []
    for r in sales:
        c = concessions.get((r.cashier_id, r.day))
        out.append(CashierDay(
            cashier_id=r.cashier_id, day=r.day, branch_id=r.branch_id, cashier=r.full_name, sales=r.n, voids=r.voids,
            void_total=Decimal(r.void_total), posted_total=Decimal(r.posted_total),
            list_value=Decimal(c.list_value) if c else ZERO, concession=Decimal(c.concession) if c else ZERO,
            refunds=refunds.get((r.cashier_id, r.day), ZERO)))
    return out


def void_rate(d: CashierDay) -> Decimal | None:
    """Share of the day's sales that were voided."""
    return rate(Decimal(d.voids), Decimal(d.sales))


def refund_rate(d: CashierDay) -> Decimal | None:
    """Value returned as a share of the value sold."""
    return rate(d.refunds, d.posted_total)


def discount_rate(d: CashierDay) -> Decimal | None:
    """Price reductions and discounts as a share of the list value of what was sold."""
    return rate(d.concession, d.list_value)


class _RateMetric(BaselineMetric):
    """A cashier's daily rate, per cashier: the base of the three baseline metrics."""

    def rate_of(self, day: CashierDay) -> Decimal | None:
        raise NotImplementedError

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        """One sample per cashier per day with enough sales."""
        out = []
        for d in cashier_days(session, company_id, date_from, date_to):
            value = self.rate_of(d)
            if d.sales >= BASELINE_MIN_DAY_SALES and value is not None:
                out.append(Sample(str(d.cashier_id), value))
        return out


class CashierVoidRateMetric(_RateMetric):
    """Share of a cashier's sales that are voided, per day."""

    code = "pos.cashier_void_rate"

    value_kind = "percent"
    title = "Cashier void rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return void_rate(day)


class CashierRefundRateMetric(_RateMetric):
    """Value a cashier returned as a share of what they sold, per day."""

    code = "pos.cashier_refund_rate"
    title = "Cashier refund rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return refund_rate(day)


class CashierDiscountRateMetric(_RateMetric):
    """Discounts and price overrides as a share of list value, per cashier per day."""

    code = "pos.cashier_discount_rate"
    title = "Cashier discount rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return discount_rate(day)


class BranchDailySalesMetric(BaselineMetric):
    """What a branch sells on a given weekday (key '<branch id>:dow<0=Monday>')."""

    code = "pos.branch_daily_sales"
    title = "Branch sales by weekday"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        """One sample per branch per day that had sales (finished days only)."""
        rows = session.execute(text(
            "select branch_id, business_date, sum(total) as total from pos.sale where company_id = :c "
            "and status = 'posted' and business_date >= :f and business_date < :t group by branch_id, business_date"),
            {"c": str(company_id), "f": date_from, "t": date_to})
        return [Sample(f"{r.branch_id}:dow{r.business_date.weekday()}", Decimal(r.total)) for r in rows]


class _CashierRateCheck(IntelCheck):
    """Shared shape of the void, refund and discount checks: yesterday (and the days before) against the cashier's own
    usual range."""

    metric: str
    what: str
    area = "controls"
    default_severity = "medium"
    params: dict[str, Any] = {"days": 2, "min_sales": 5, "min_rate": "0.05"}
    auto_resolves = False

    def rate_of(self, day: CashierDay) -> Decimal | None:
        raise NotImplementedError

    def amount_of(self, day: CashierDay) -> Decimal:
        raise NotImplementedError

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Finished days in the window where a cashier's rate is well above their own normal."""
        days = int(ctx.params["days"])
        cur = currency(session, ctx.company_id)
        found = []
        for d in cashier_days(session, ctx.company_id, ctx.today - timedelta(days=days), ctx.today):
            value = self.rate_of(d)
            baseline = ctx.baseline(self.metric, str(d.cashier_id))
            if value is None or d.sales < int(ctx.params["min_sales"]) or value < ctx.number("min_rate"):
                continue
            if baseline is None or not is_unusual(value, baseline):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, d.cashier_id, d.day), severity="medium",
                summary=(f"On {d.day} {d.cashier}'s {self.what} was {percent(value)} over {d.sales} sales "
                         f"({cur} {money(self.amount_of(d))}); their usual is about {percent(baseline.mean)}."),
                recommended_action=f"Ask {d.cashier} to explain.", company_id=ctx.company_id, branch_id=d.branch_id,
                entity_type="kernel.app_user", entity_id=d.cashier_id, period_start=d.day, period_end=d.day,
                value=value, expected_value=baseline.mean, amount=self.amount_of(d),
                records=(Record("kernel.app_user", d.cashier_id, d.cashier),),
                figures={"sales": str(d.sales), "rate": percent(value), "usual_rate": percent(baseline.mean)}))
        return found


class CashierVoidRate(_CashierRateCheck):
    code = "pos.cashier_void_rate"
    title = "A cashier voided more sales than usual"
    description = "A cashier cancelled a much bigger share of their sales than they normally do."
    metric = "pos.cashier_void_rate"
    what = "void rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return void_rate(day)

    def amount_of(self, day: CashierDay) -> Decimal:
        return day.void_total


class CashierRefundRate(_CashierRateCheck):
    code = "pos.cashier_refund_rate"
    title = "A cashier processed more refunds than usual"
    description = "A cashier returned a much bigger share of what they sold than they normally do."
    metric = "pos.cashier_refund_rate"
    what = "refund rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return refund_rate(day)

    def amount_of(self, day: CashierDay) -> Decimal:
        return day.refunds


class CashierDiscountRate(_CashierRateCheck):
    code = "pos.cashier_discount_rate"
    title = "A cashier gave more discounts than usual"
    description = "A cashier gave away a much bigger share of the list price in discounts and price changes than usual."
    metric = "pos.cashier_discount_rate"
    what = "discount and price-override rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return discount_rate(day)

    def amount_of(self, day: CashierDay) -> Decimal:
        return day.concession


class LargeExceptions(IntelCheck):
    """A single big void, refund or price override."""

    code = "pos.large_exception"
    title = "A large void, refund or price override"
    area = "controls"
    description = "One sale was voided, one return refunded, or one sale discounted for a large amount."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 7, "min_void": "2000.00", "min_refund": "2000.00", "min_override": "1000.00"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Voided sales, posted returns and discounted sales over their limits in the window."""
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        c = str(ctx.company_id)
        found = []
        voids = session.execute(text(
            "select s.id, s.number, s.branch_id, s.total, s.cashier_id, u.full_name as cashier, "
            "coalesce(v.full_name, u.full_name) as by_name, (s.voided_at at time zone :tz)::date as day "
            "from pos.sale s join kernel.app_user u on u.id = s.cashier_id "
            "left join kernel.app_user v on v.id = s.voided_by "
            "where s.company_id = :c and s.status = 'voided' and (s.voided_at at time zone :tz)::date >= :since "
            "and s.total >= :limit"), {"c": c, "tz": ctx.timezone, "since": since, "limit": ctx.number("min_void")})
        for r in voids:
            amount, limit = Decimal(r.total), ctx.number("min_void")
            found.append(self._candidate(
                ctx, "void", r.id, r.branch_id, r.day, amount, "high" if amount >= limit * 3 else "medium",
                f"Sale {r.number} for {cur} {money(amount)} by {r.cashier} was voided by {r.by_name} on {r.day}.",
                "Check the reason given for the void with the cashier.", Record("pos.sale", r.id, f"Sale {r.number}")))
        refunds = session.execute(text(
            "select r.id, r.number, r.branch_id, r.total, coalesce(r.business_date, r.created_at::date) as day, "
            "coalesce(u.full_name, 'someone') as by_name from pos.sales_return r "
            "left join kernel.app_user u on u.id = r.created_by where r.company_id = :c and r.status = 'posted' "
            "and coalesce(r.business_date, r.created_at::date) >= :since "
            "and r.total >= :limit"), {"c": c, "since": since, "limit": ctx.number("min_refund")})
        for r in refunds:
            amount, limit = Decimal(r.total), ctx.number("min_refund")
            found.append(self._candidate(
                ctx, "refund", r.id, r.branch_id, r.day, amount, "high" if amount >= limit * 3 else "medium",
                f"Return {r.number} refunded {cur} {money(amount)} on {r.day}, processed by {r.by_name}.",
                "Confirm the goods came back and the reason is genuine.",
                Record("pos.sales_return", r.id, f"Return {r.number}")))
        overrides = session.execute(text(
            "select s.id, s.number, s.branch_id, s.business_date as day, u.full_name as cashier, "
            "sum(greatest(l.list_price - l.unit_price, 0) * l.quantity + l.discount_amount) as given "
            "from pos.sale s join pos.sale_line l on l.sale_id = s.id join kernel.app_user u on u.id = s.cashier_id "
            "where s.company_id = :c and s.status = 'posted' and s.business_date >= :since "
            "group by s.id, s.number, s.branch_id, s.business_date, u.full_name having "
            "sum(greatest(l.list_price - l.unit_price, 0) * l.quantity + l.discount_amount) >= :limit"),
            {"c": c, "since": since, "limit": ctx.number("min_override")})
        for r in overrides:
            amount, limit = Decimal(r.given), ctx.number("min_override")
            found.append(self._candidate(
                ctx, "override", r.id, r.branch_id, r.day, amount, "high" if amount >= limit * 3 else "medium",
                f"Sale {r.number} by {r.cashier} on {r.day} was discounted or re-priced by {cur} {money(amount)} "
                "against list price.", "Ask who approved it and why.", Record("pos.sale", r.id, f"Sale {r.number}")))
        return found

    def _candidate(self, ctx: CheckContext, kind: str, record_id: UUID, branch_id: UUID | None, day: date,
                   amount: Decimal, severity: str, summary: str, action: str, record: Record) -> Candidate:
        return Candidate(
            fingerprint=fingerprint(self.code, kind, record_id), severity=severity, summary=summary,
            recommended_action=action, company_id=ctx.company_id, branch_id=branch_id, entity_type=record.type,
            entity_id=record_id, period_start=day, period_end=day, amount=amount, records=(record,),
            figures={"kind": kind, "amount": money(amount)})


class OutOfHoursSales(IntelCheck):
    """Sales rung up when the branch is normally closed."""

    code = "pos.out_of_hours_sales"

    value_kind = "count"
    title = "Sales outside trading hours"
    area = "controls"
    description = "Sales were made at a branch before it normally opens or after it normally closes."
    default_severity = "low"
    params: dict[str, Any] = {"open_hour": 6, "close_hour": 22, "days": 7}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Per branch and local day, sales before `open_hour` or from `close_hour` on (hours in the company's zone)."""
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select s.branch_id, b.name as branch, (s.sold_at at time zone :tz)::date as day, count(*) as n, "
            "sum(s.total) as total, min((s.sold_at at time zone :tz)::time) as first_at, "
            "array_agg(s.id order by s.sold_at) as ids, array_agg(s.number order by s.sold_at) as numbers "
            "from pos.sale s join kernel.branch b on b.id = s.branch_id where s.company_id = :c "
            "and s.status = 'posted' and (s.sold_at at time zone :tz)::date >= :since "
            "and (extract(hour from s.sold_at at time zone :tz) < :open "
            "or extract(hour from s.sold_at at time zone :tz) >= :close) "
            "group by s.branch_id, b.name, (s.sold_at at time zone :tz)::date"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "since": since, "open": int(ctx.params["open_hour"]),
             "close": int(ctx.params["close_hour"])}).all()
        found = []
        for r in rows:
            total = Decimal(r.total)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.day), severity="medium" if r.n >= 5 else "low",
                summary=(f"{r.branch} made {r.n} sale{'s' if r.n != 1 else ''} worth {cur} {money(total)} on {r.day} "
                         f"outside {int(ctx.params['open_hour']):02d}:00-{int(ctx.params['close_hour']):02d}:00, "
                         f"the first at {r.first_at.strftime('%H:%M')}."),
                recommended_action="Ask the branch manager why the till was in use then.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="kernel.branch", entity_id=r.branch_id, period_start=r.day,
                period_end=r.day, value=Decimal(r.n), amount=total,
                records=_records("pos.sale", "Sale", r.ids, r.numbers),
                figures={"sales": str(r.n), "total": money(total)}))
        return found


class LateRecordedSales(IntelCheck):
    """Sales recorded days after the trading day they belong to."""

    code = "pos.late_recorded_sales"

    value_kind = "count"
    title = "Sales recorded long after their business date"
    area = "controls"
    description = "A sale was entered, or synced from an offline till, days after the day it is dated."
    default_severity = "low"
    params: dict[str, Any] = {"days": 14, "min_days_late": 2, "high_days_late": 7}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Sales created in the window whose business date is `min_days_late` or more before the day they were saved."""
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select s.id, s.number, s.branch_id, s.total, s.business_date, s.synced_offline, u.full_name as cashier, "
            "(s.created_at at time zone :tz)::date as saved_on, "
            "(s.created_at at time zone :tz)::date - s.business_date as late from pos.sale s "
            "join kernel.app_user u on u.id = s.cashier_id where s.company_id = :c and s.status = 'posted' "
            "and (s.created_at at time zone :tz)::date >= :since "
            "and (s.created_at at time zone :tz)::date - s.business_date >= :late"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "since": since,
             "late": int(ctx.params["min_days_late"])}).all()
        found = []
        for r in rows:
            how = "synced from an offline till" if r.synced_offline else "entered"
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="medium" if r.late >= int(ctx.params["high_days_late"]) else "low",
                summary=(f"Sale {r.number} by {r.cashier} for {cur} {money(Decimal(r.total))} is dated "
                         f"{r.business_date} but was {how} on {r.saved_on}, {r.late} days later."),
                recommended_action="Check why the sale was recorded late.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="pos.sale", entity_id=r.id, period_start=r.business_date,
                period_end=r.saved_on, value=Decimal(r.late), amount=Decimal(r.total),
                records=(Record("pos.sale", r.id, f"Sale {r.number}"),),
                figures={"days_late": str(r.late), "offline": "yes" if r.synced_offline else "no"}))
        return found


class BranchSalesLow(IntelCheck):
    """A branch sold far less yesterday than it normally does on that weekday."""

    code = "pos.branch_sales_low"

    value_kind = "money"
    title = "A branch sold far less than usual"
    area = "cash_sales"
    description = "A branch's sales yesterday were far below what it normally sells on that day of the week."
    default_severity = "medium"
    params: dict[str, Any] = {"drop_percent": 50, "deviations": "2.0", "min_history": 6}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Yesterday's sales per branch against the branch's learned range for that weekday."""
        day = ctx.today - timedelta(days=1)
        totals = {r.branch_id: Decimal(r.total) for r in session.execute(text(
            "select branch_id, sum(total) as total from pos.sale where company_id = :c and status = 'posted' "
            "and business_date = :d group by branch_id"), {"c": str(ctx.company_id), "d": day})}
        branches = session.execute(text("select id, name from kernel.branch where company_id = :c"),
                                   {"c": str(ctx.company_id)}).all()
        cur = currency(session, ctx.company_id)
        found = []
        for b in branches:
            baseline = ctx.baseline("pos.branch_daily_sales", f"{b.id}:dow{day.weekday()}")
            value = totals.get(b.id, ZERO)
            if baseline is None or not unusually_low(
                    value, baseline.mean, baseline.stddev, baseline.sample_size,
                    drop_percent=int(ctx.params["drop_percent"]), deviations=ctx.number("deviations"),
                    min_history=int(ctx.params["min_history"])):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, b.id, day),
                severity="high" if value <= baseline.mean / 4 else "medium",
                summary=(f"{b.name} {'recorded no sales' if value == 0 else f'sold {cur} {money(value)}'} on {day} "
                         f"({day.strftime('%A')}); it usually sells about {cur} {money(baseline.mean)} on that day."),
                recommended_action="Ask the branch manager what happened that day.", company_id=ctx.company_id,
                branch_id=b.id, entity_type="kernel.branch", entity_id=b.id, period_start=day, period_end=day,
                value=value, expected_value=baseline.mean, amount=baseline.mean - value,
                records=(Record("kernel.branch", b.id, b.name),),
                figures={"sales": money(value), "usual": money(baseline.mean), "weekday": day.strftime("%A")}))
        return found


# --------------------------------------------------------------------------------------------- customers
OPEN = "('issued', 'part_paid')"


class OverdueCustomers(IntelCheck):
    """Customers with invoices that are well past their due date."""

    code = "pos.customer_overdue"

    value_kind = "days"
    title = "A customer is overdue"
    area = "customers"
    description = "A customer has an invoice that is more than the set number of days past its due date."
    default_severity = "medium"
    params: dict[str, Any] = {"min_days_overdue": 30, "high_days_overdue": 90}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """One finding per customer; the amount is everything they owe past due."""
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            f"select i.customer_id, count(*) as n, sum(i.total - i.amount_paid - i.credited) as owed, "
            f"min(i.due_date) as oldest, array_agg(i.id order by i.due_date) as ids, "
            f"array_agg(i.number order by i.due_date) as numbers, count(distinct i.branch_id) as branches, "
            f"min(i.branch_id::text) as branch from pos.sales_invoice i where i.company_id = :c "
            f"and i.status in {OPEN} and i.due_date < :today group by i.customer_id "
            f"having sum(i.total - i.amount_paid - i.credited) > 0 and min(i.due_date) < :cutoff"),
            {"c": str(ctx.company_id), "today": ctx.today,
             "cutoff": ctx.today - timedelta(days=int(ctx.params["min_days_overdue"]))}).all()
        names = customer_names(session, ctx.company_id, [r.customer_id for r in rows])
        found = []
        for r in rows:
            owed, days = Decimal(r.owed), (ctx.today - r.oldest).days
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.customer_id),
                severity="high" if days >= int(ctx.params["high_days_overdue"]) else "medium",
                summary=(f"{who(names, r.customer_id)} owes {cur} {money(owed)} past due on {r.n} "
                         f"invoice{'s' if r.n != 1 else ''}; the oldest is {days} days overdue."),
                recommended_action="Contact the customer to collect payment.", company_id=ctx.company_id,
                branch_id=UUID(r.branch) if r.branches == 1 and r.branch else None, entity_type="crm.customer",
                entity_id=r.customer_id, period_end=ctx.today, value=Decimal(days), amount=owed,
                records=_records("pos.sales_invoice", "Invoice", r.ids, r.numbers),
                figures={"overdue_balance": money(owed), "invoices": str(r.n), "oldest_days_overdue": str(days)}))
        return found


class SlowerPayers(IntelCheck):
    """Customers who now take noticeably longer to pay than they used to."""

    code = "pos.customer_paying_slower"

    value_kind = "days"
    title = "A customer is paying slower"
    area = "customers"
    description = "A customer takes much longer to pay their invoices than they did in the period before."
    default_severity = "low"
    params: dict[str, Any] = {"window_days": 90, "increase_percent": 50, "min_increase_days": 5, "min_invoices": 3}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Average days from issue to final payment on invoices paid in the last window, against the window before."""
        window = int(ctx.params["window_days"])
        mid, start = ctx.today - timedelta(days=window), ctx.today - timedelta(days=2 * window)
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "with paid as (select i.customer_id, i.id, i.issue_date, max(r.received_on) as paid_on "
            "from pos.sales_invoice i join pos.customer_receipt_allocation a on a.invoice_id = i.id "
            "join pos.customer_receipt r on r.id = a.receipt_id and r.status = 'posted' "
            "where i.company_id = :c and i.status = 'paid' group by i.id, i.customer_id, i.issue_date) "
            "select p.customer_id, count(*) filter (where p.paid_on > :mid) as n_recent, "
            "avg(p.paid_on - p.issue_date) filter (where p.paid_on > :mid) as recent, "
            "count(*) filter (where p.paid_on <= :mid) as n_prior, "
            "avg(p.paid_on - p.issue_date) filter (where p.paid_on <= :mid) as prior, "
            "(select coalesce(sum(o.total - o.amount_paid - o.credited), 0) from pos.sales_invoice o "
            f"where o.customer_id = p.customer_id and o.status in {OPEN}) as open_balance "
            "from paid p where p.paid_on > :start and p.paid_on <= :today group by p.customer_id"),
            {"c": str(ctx.company_id), "mid": mid, "start": start, "today": ctx.today}).all()
        names = customer_names(session, ctx.company_id, [r.customer_id for r in rows])
        found = []
        for r in rows:
            if r.recent is None or r.prior is None:
                continue
            recent, prior = Decimal(r.recent), Decimal(r.prior)
            if not paying_slower(recent, prior, r.n_recent, r.n_prior,
                                 increase_percent=int(ctx.params["increase_percent"]),
                                 min_increase_days=int(ctx.params["min_increase_days"]),
                                 min_invoices=int(ctx.params["min_invoices"])):
                continue
            owed = Decimal(r.open_balance)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.customer_id),
                severity="medium" if recent >= prior * 2 else "low",
                summary=(f"{who(names, r.customer_id)} now takes {recent:.0f} days on average to pay, up from "
                         f"{prior:.0f} days in the {window} days before"
                         f"{f'; they currently owe {cur} {money(owed)}' if owed > 0 else ''}."),
                recommended_action="Review the customer's terms and credit limit before giving more credit.",
                company_id=ctx.company_id, entity_type="crm.customer", entity_id=r.customer_id,
                period_start=mid, period_end=ctx.today, value=recent, expected_value=prior, amount=owed or None,
                figures={"recent_days": f"{recent:.1f}", "earlier_days": f"{prior:.1f}",
                         "recent_invoices": str(r.n_recent), "earlier_invoices": str(r.n_prior)}))
        return found


class CreditToOverdueCustomer(IntelCheck):
    """New credit given to a customer who was already behind."""

    code = "pos.credit_to_overdue_customer"

    value_kind = "money"
    title = "Credit given to a customer who was overdue"
    area = "customers"
    description = "A new invoice or credit sale was made to a customer who already had an overdue invoice unpaid."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 7, "grace_days": 0, "high_days_overdue": 60}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Invoices issued in the window where the customer still owes an older invoice that was due before it."""
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select i.id, i.number, i.customer_id, i.branch_id, i.total, i.issue_date, o.owed, o.oldest, o.n "
            "from pos.sales_invoice i cross join lateral (select sum(x.total - x.amount_paid - x.credited) as owed, "
            "max(i.issue_date - x.due_date) as oldest, count(*) as n from pos.sales_invoice x "
            f"where x.customer_id = i.customer_id and x.id <> i.id and x.status in {OPEN} "
            "and x.created_at < i.created_at and x.due_date < i.issue_date - :grace) o "
            "where i.company_id = :c and i.status <> 'cancelled' and i.issue_date >= :since and o.owed > 0"),
            {"c": str(ctx.company_id), "since": since, "grace": int(ctx.params["grace_days"])}).all()
        names = customer_names(session, ctx.company_id, [r.customer_id for r in rows])
        found = []
        for r in rows:
            owed = Decimal(r.owed)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="high" if r.oldest >= int(ctx.params["high_days_overdue"]) else "medium",
                summary=(f"Invoice {r.number} for {cur} {money(Decimal(r.total))} was issued on {r.issue_date} to "
                         f"{names.get(r.customer_id, 'a customer')}, "
                         f"who still owes {cur} {money(owed)} on {r.n} older invoice{'s' if r.n != 1 else ''} that "
                         f"were already overdue (the oldest by {r.oldest} days)."),
                recommended_action="Check who approved more credit, and collect the overdue balance first.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="pos.sales_invoice", entity_id=r.id,
                period_start=r.issue_date, period_end=r.issue_date, value=Decimal(r.total), amount=Decimal(r.total),
                records=(Record("pos.sales_invoice", r.id, f"Invoice {r.number}"),),
                figures={"overdue_before": money(owed), "oldest_days_overdue": str(r.oldest)}))
        return found


class OverCreditLimit(IntelCheck):
    """Customers who owe more than their credit limit."""

    code = "pos.customer_over_credit_limit"

    value_kind = "money"
    title = "A customer is over their credit limit"
    area = "customers"
    description = "A customer owes more than the credit limit set for them."
    default_severity = "medium"
    params: dict[str, Any] = {"tolerance_percent": 0, "high_percent": 150}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """What each customer owes (unpaid invoices less money held for them) against their limit in CRM. Needs CRM."""
        if not unit_enabled(session, "crm"):
            return []
        from ziira.modules.crm.public import find_customers

        owed_rows = session.execute(text(
            f"select i.customer_id, sum(i.total - i.amount_paid - i.credited) as owed, "
            f"(select coalesce(sum(r.unallocated), 0) from pos.customer_receipt r where r.customer_id = i.customer_id "
            f"and r.status = 'posted') as held, count(*) as n, min(i.branch_id::text) as branch, "
            f"count(distinct i.branch_id) as branches from pos.sales_invoice i where i.company_id = :c "
            f"and i.status in {OPEN} group by i.customer_id"), {"c": str(ctx.company_id)}).all()
        views = find_customers(session, {r.customer_id for r in owed_rows})
        cur = currency(session, ctx.company_id)
        tolerance = Decimal(int(ctx.params["tolerance_percent"]))
        found = []
        for r in owed_rows:
            view = views.get(r.customer_id)
            owed = Decimal(r.owed) - Decimal(r.held)
            if view is None or view.credit_limit <= 0 or owed <= view.credit_limit * (100 + tolerance) / 100:
                continue
            over = owed - view.credit_limit
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.customer_id),
                severity="high" if owed * 100 >= view.credit_limit * int(ctx.params["high_percent"]) else "medium",
                summary=(f"{view.name} owes {cur} {money(owed)}, which is {cur} {money(over)} over their credit limit "
                         f"of {cur} {money(view.credit_limit)}."),
                recommended_action="Hold further credit until the customer has paid down their balance.",
                company_id=ctx.company_id, branch_id=UUID(r.branch) if r.branches == 1 and r.branch else None,
                entity_type="crm.customer", entity_id=r.customer_id, value=owed, expected_value=view.credit_limit,
                amount=over, figures={"owed": money(owed), "credit_limit": money(view.credit_limit)}))
        return found

