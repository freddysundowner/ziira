"""Standalone checks: the questions Ziira Intelligence asks of a business that keeps its current system.

They answer the same questions as the Core units' checks, but from the canonical copy of the other system's data
(`connect.src_*`, filled by connectors and file uploads), so ONE set of checks serves every source: an ERP, a POS
export, a bank or mobile-money statement. They look only at `connect.src_*`, never at a Core unit's tables, so a
business that also runs Core units gets each unit's own checks AND these, about different data, without doubling up.

Rules (docs/intelligence.md, "Writing a check"):
- A check runs only where connections exist and only when the entities it needs are supplied (`requires`): otherwise it
  stays silent, and the Command Center's coverage note says what to connect to switch it on.
- A day is judged only when the connection's data is complete for it (`data_through`): a connection that has not been
  read lately never makes a quiet day look like a bad one.
- Checks read only, inside a look-back window; every limit is a `param` a business can change; findings are scoped by
  the mapped branch (`branch_id`; unmapped records are company level); summaries name the company currency.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.connect.domain.rules import (
    ZERO,
    is_round,
    money,
    outside_hours,
    paying_slower,
    percent,
    plain,
    price_rise_percent,
    rate,
    signed,
    unusually_low,
)
from ziira.modules.connect.services import overlap
from ziira.modules.connect.services.coverage import Supply, supplied
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
from ziira.sdk import Session, company_setting

BASELINE_MIN_DAY_SALES = 3
LIST_SIZE = 5
CAP = 200                         # a check never reports more than this many findings in one run


# --------------------------------------------------------------------------------------------- shared helpers
def currency(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def local_day(column: str) -> str:
    """SQL for the calendar day of a timestamp column in the company's time zone (bind :tz)."""
    return f"(({column}) at time zone :tz)::date"


def local_hour(column: str) -> str:
    return f"extract(hour from ({column}) at time zone :tz)"


def start_of(day: date, zone: str) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(zone))


def last_complete_day(ctx: CheckContext, through: datetime | None) -> date:
    """The latest day whose data is complete: the day before today, or before the day the data runs up to."""
    latest = ctx.today - timedelta(days=1)
    if through is None:
        return latest
    return min(latest, through.astimezone(ZoneInfo(ctx.timezone)).date() - timedelta(days=1))


def branch_names(session: Session, ids: Sequence[UUID | None]) -> dict[UUID, str]:
    wanted = [str(i) for i in {i for i in ids if i is not None}]
    if not wanted:
        return {}
    return {r.id: r.name for r in session.execute(text("select id, name from kernel.branch where id = any(cast(:i as "
                                                       "uuid[]))"),
                                                  {"i": wanted})}


def where_name(names: dict[UUID, str], branch_id: UUID | None, fallback: str | None = None) -> str:
    if branch_id is not None and branch_id in names:
        return names[branch_id]
    return fallback or "the business"


def lead(sentence: str) -> str:
    """A sentence that may start with 'the business' starts with a capital."""
    return sentence[:1].upper() + sentence[1:]


def user_names(session: Session, conns: Sequence[str], refs: Sequence[tuple[UUID, str | None]]) -> dict[tuple[UUID,
    str], str]:
    """Names of source users by (connection, ref), when the users were read; else the caller falls back to the ref."""
    wanted = sorted({r for _, r in refs if r})
    if not wanted or not conns:
        return {}
    return {(r.connection_id, r.ref): r.name for r in session.execute(text(
        "select connection_id, ref, name from connect.src_user where connection_id = any(cast(:c as uuid[])) "
        "and ref = any(:r)"), {"c": list(conns), "r": wanted})}


def person(names: dict[tuple[UUID, str], str], conn: UUID, ref: str | None, fallback: str = "A user") -> str:
    if not ref:
        return fallback
    return names.get((conn, ref), ref)


def party_names(session: Session, conns: Sequence[str], refs: Sequence[tuple[UUID, str | None]]) -> dict[tuple[UUID,
    str], str]:
    wanted = sorted({r for _, r in refs if r})
    if not wanted or not conns:
        return {}
    return {(r.connection_id, r.ref): r.name for r in session.execute(text(
        "select connection_id, ref, name from connect.src_party where connection_id = any(cast(:c as uuid[])) "
        "and ref = any(:r)"), {"c": list(conns), "r": wanted})}


def product_names(session: Session, conns: Sequence[str], refs: Sequence[str | None]) -> dict[tuple[UUID, str], str]:
    wanted = sorted({r for r in refs if r})
    if not wanted or not conns:
        return {}
    return {(r.connection_id, r.ref): r.name for r in session.execute(text(
        "select connection_id, ref, name from connect.src_product where connection_id = any(cast(:c as uuid[])) "
        "and ref = any(:r)"), {"c": list(conns), "r": wanted})}


def sale_records(rows: Sequence[Row[Any]], limit: int = LIST_SIZE) -> tuple[Record, ...]:
    return tuple(Record("connect.src_sale", r.id, f"Sale {r.number or r.ref}") for r in rows[:limit])


class StandaloneCheck(IntelCheck):
    """A check over `connect.src_*`. `requires` names the entities it needs; without them it says nothing."""

    requires: tuple[str, ...] = ()
    core_areas: tuple[str, ...] = ()    # business areas (OVERLAP_AREAS) in which Core's own checks take over, see below
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        supply = supplied(session, ctx.company_id)
        if not supply.has(*self.requires):
            return []
        found = self.scan(session, ctx, supply)
        # Where a Core unit now runs the same area at the same branch, its own checks look at the live data: this copy
        # of the old system would only say the same thing again, late. Unless the business chose to keep both.
        covered = overlap.covered_by_core(session, ctx.company_id, self.core_areas)
        if covered is not None:
            found = [c for c in found if not any(covered.covers(area, c.branch_id) for area in self.core_areas)]
        return found[:CAP]

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        raise NotImplementedError


# --------------------------------------------------------------------------------------------- cash and sales
class SaleWithoutPayment(StandaloneCheck):
    """Mobile-money or bank sales that no statement line backs up."""

    code = "standalone.sale_without_payment"

    value_kind = "count"
    title = "Sales paid electronically with no payment to show for it"
    area = "cash_sales"
    description = ("Sales recorded as paid by mobile money or bank transfer where no payment of the same code, or the "
                   "same amount at about the same time, appears in the statements you connected.")
    default_severity = "medium"
    requires = ("sales", "payments")
    core_areas = ("sales",)
    params: dict[str, Any] = {"days": 7, "grace_hours": 24, "window_minutes": 120, "min_amount": "1.00",
                              "methods": "mobile_money,bank", "high_count": 5}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        horizon = start_of(ctx.today + timedelta(days=1), ctx.timezone)
        until = horizon - timedelta(hours=int(ctx.params["grace_hours"]))
        covered = supply.complete_until("payments")
        if covered is not None:
            until = min(until, covered)
        since = start_of(ctx.today - timedelta(days=int(ctx.params["days"])), ctx.timezone)
        methods = [m.strip() for m in str(ctx.params["methods"]).split(",") if m.strip()]
        rows = session.execute(text(
            f"select s.id, s.ref, s.number, s.branch_id, s.occurred_at, {local_day('s.occurred_at')} as day, "
            "sp.amount, sp.reference from connect.src_sale s join connect.src_sale_payment sp on sp.sale_id = s.id "
            "where s.company_id = :c and s.connection_id = any(cast(:sc as uuid[])) and s.status = 'posted' "
            "and sp.method = any(:methods) and sp.amount >= :min and s.occurred_at >= :since and s.occurred_at < "
            ":until "
            "and not exists (select 1 from connect.src_payment p where p.company_id = :c "
            "and p.connection_id = any(cast(:pc as uuid[])) and p.direction = 'in' and "
            "((sp.reference is not null and p.reference is not null and lower(p.reference) = lower(sp.reference)) or "
            "(p.amount = sp.amount and abs(extract(epoch from p.occurred_at - s.occurred_at)) <= :win))) "
            "order by s.occurred_at"),
            {"c": str(ctx.company_id), "sc": supply.ids("sales"), "pc": supply.ids("payments"), "tz": ctx.timezone,
             "methods": methods, "min": ctx.number("min_amount"), "since": since, "until": until,
             "win": int(ctx.params["window_minutes"]) * 60}).all()
        groups: dict[tuple[UUID | None, date], list[Row[Any]]] = {}
        for r in rows:
            groups.setdefault((r.branch_id, r.day), []).append(r)
        names = branch_names(session, [b for b, _ in groups])
        cur = currency(session, ctx.company_id)
        found = []
        for (branch_id, day), items in groups.items():
            total = sum((Decimal(r.amount) for r in items), ZERO)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, branch_id, day),
                severity="high" if len(items) >= int(ctx.params["high_count"]) else "medium",
                summary=(f"{len(items)} sale{'s' if len(items) != 1 else ''} at {where_name(names,
                    branch_id)} on {day} "
                         f"worth {cur} {money(total)} {'were' if len(items) != 1 else 'was'} recorded as paid by "
                         "mobile money or bank, but no matching payment appears in the statements."),
                recommended_action="Compare these sales with the statement and ask the cashier how they were paid.",
                company_id=ctx.company_id, branch_id=branch_id, entity_type="connect.src_sale", entity_id=items[0].id,
                period_start=day, period_end=day, value=Decimal(len(items)), amount=total,
                records=sale_records(items), figures={"sales": str(len(items)), "total": money(total)}))
        return found


class CashDepositGap(StandaloneCheck):
    """Cash taken at the till but not banked."""

    code = "standalone.cash_deposit_gap"
    title = "Cash sales not matched by cash deposits"
    area = "cash_sales"
    description = ("Cash sales over the last days are well above the cash deposits on the bank statement "
                   "(compared per branch when deposits say which branch, else for the whole business).")
    default_severity = "medium"
    requires = ("sales", "payments")
    core_areas = ("sales",)
    params: dict[str, Any] = {"days": 7, "grace_days": 2, "tolerance_percent": 10, "min_gap": "100.00"}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        last = ctx.today - timedelta(days=1 + int(ctx.params["grace_days"]))
        first = last - timedelta(days=int(ctx.params["days"]) - 1)
        covered = supply.complete_until("payments")
        if covered is not None and covered.astimezone(ZoneInfo(ctx.timezone)).date() <= last + timedelta(
                days=int(ctx.params["grace_days"])):
            return []                                       # the statement does not yet reach the days deposits are due
        p = {"c": str(ctx.company_id), "sc": supply.ids("sales"), "pc": supply.ids("payments"), "tz": ctx.timezone,
             "first": first, "last": last, "today": ctx.today}
        cash = {r.branch_id: Decimal(r.total) for r in session.execute(text(
            "select s.branch_id, sum(sp.amount) as total from connect.src_sale s "
            "join connect.src_sale_payment sp on sp.sale_id = s.id where s.company_id = :c "
            f"and s.connection_id = any(cast(:sc as uuid[])) and s.status = 'posted' and sp.method = 'cash' "
            f"and {local_day('s.occurred_at')} between :first and :last group by s.branch_id"), p)}
        deposits = {r.branch_id: Decimal(r.total) for r in session.execute(text(
            "select branch_id, sum(amount) as total from connect.src_payment where company_id = :c "
            "and connection_id = any(cast(:pc as uuid[])) and direction = 'in' and method = 'cash' "
            f"and {local_day('occurred_at')} between :first and :today group by branch_id"), p)}
        if not cash:
            return []
        if any(b is not None for b in deposits):            # deposits say which branch: compare branch by branch
            pairs = [(b, cash[b], deposits.get(b, ZERO)) for b in cash]
        else:
            pairs = [(None, sum(cash.values(), ZERO), sum(deposits.values(), ZERO))]
        names = branch_names(session, [b for b, _, _ in pairs])
        cur = currency(session, ctx.company_id)
        tolerance = Decimal(int(ctx.params["tolerance_percent"]))
        found = []
        for branch_id, taken, banked in pairs:
            gap = taken - banked
            if gap <= ctx.number("min_gap") or gap * 100 <= taken * tolerance:
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, branch_id),
                severity="high" if banked * 2 < taken else "medium",
                summary=lead(f"{where_name(names,
                    branch_id)} took {cur} {money(taken)} in cash from {first} to {last} but "
                             f"the bank statement shows cash deposits of only {cur} {money(banked)}: "
                             f"{cur} {money(gap)} is not accounted for."),
                recommended_action="Ask who banks the cash, and compare the deposit slips with the daily cash sales.",
                company_id=ctx.company_id, branch_id=branch_id, entity_type="kernel.branch", entity_id=branch_id,
                period_start=first, period_end=last, value=banked, expected_value=taken, amount=gap,
                figures={"cash_sales": money(taken), "deposits": money(banked), "gap": money(gap)}))
        return found


class BranchSalesLow(StandaloneCheck):
    """A branch sold far less yesterday than it normally does on that weekday."""

    code = "standalone.branch_sales_low"
    title = "A branch sold far less than usual"
    area = "cash_sales"
    description = "A branch's sales yesterday were far below what it normally sells on that day of the week."
    default_severity = "medium"
    requires = ("sales",)
    core_areas = ("sales",)
    params: dict[str, Any] = {"drop_percent": 50, "deviations": "2.0", "min_history": 6}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        day = ctx.today - timedelta(days=1)
        if last_complete_day(ctx, supply.complete_until("sales")) < day:
            return []                                       # yesterday is not fully read yet
        p = {"c": str(ctx.company_id), "sc": supply.ids("sales"), "tz": ctx.timezone, "d": day,
             "since": ctx.today - timedelta(days=90)}
        seen = session.execute(text(
            "select distinct connection_id, branch_id, branch_ref from connect.src_sale where company_id = :c "
            f"and connection_id = any(cast(:sc as uuid[])) and status = 'posted' and {local_day('occurred_at')} >= "
            f":since"), p).all()
        totals = {(r.connection_id, r.branch_id, r.branch_ref): Decimal(r.total) for r in session.execute(text(
            "select connection_id, branch_id, branch_ref, sum(total) as total from connect.src_sale where company_id "
            "= :c "
            f"and connection_id = any(cast(:sc as uuid[])) and status = 'posted' and {local_day('occurred_at')} = :d "
            "group by connection_id, branch_id, branch_ref"), p)}
        names = branch_names(session, [r.branch_id for r in seen])
        cur = currency(session, ctx.company_id)
        found = []
        for r in seen:
            baseline = ctx.baseline("standalone.branch_daily_sales", sales_key(r.connection_id, r.branch_id,
                r.branch_ref,
                                                                              day.weekday()))
            value = totals.get((r.connection_id, r.branch_id, r.branch_ref), ZERO)
            if baseline is None or not unusually_low(
                    value, baseline.mean, baseline.stddev, baseline.sample_size,
                    drop_percent=int(ctx.params["drop_percent"]), deviations=ctx.number("deviations"),
                    min_history=int(ctx.params["min_history"])):
                continue
            label = where_name(names, r.branch_id, r.branch_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.connection_id, r.branch_id, r.branch_ref, day),
                severity="high" if value <= baseline.mean / 4 else "medium",
                summary=lead(f"{label} {'recorded no sales' if value == 0 else f'sold {cur} {money(value)}'} on {day} "
                             f"({day.strftime('%A')}); it usually sells about {cur} {money(baseline.mean)} "
                             "on that day."),
                recommended_action="Ask the branch manager what happened that day.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="kernel.branch", entity_id=r.branch_id, period_start=day,
                period_end=day, value=value, expected_value=baseline.mean, amount=baseline.mean - value,
                figures={"sales": money(value), "usual": money(baseline.mean), "weekday": day.strftime("%A")}))
        return found


def sales_key(connection_id: UUID, branch_id: UUID | None, branch_ref: str | None, weekday: int) -> str:
    """The baseline key of a branch's sales on a weekday (a mapped branch is one branch whichever system it is in)."""
    who = str(branch_id) if branch_id is not None else f"{connection_id}:{branch_ref or ''}"
    return f"{who}:dow{weekday}"


class OutOfHoursSales(StandaloneCheck):
    """Sales rung up before opening or after closing."""

    code = "standalone.out_of_hours_sales"
    title = "Sales outside trading hours"
    area = "controls"
    description = "Sales were made at a branch before it normally opens or after it normally closes."
    default_severity = "low"
    requires = ("sales",)
    core_areas = ("sales",)
    params: dict[str, Any] = {"open_hour": 6, "close_hour": 22, "days": 7}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            f"select s.branch_id, s.branch_ref, {local_day('s.occurred_at')} as day, count(*) as n, sum(s.total) as "
            f"total, "
            "min((s.occurred_at at time zone :tz)::time) as first_at, array_agg(s.id order by s.occurred_at) as ids, "
            "array_agg(coalesce(s.number, s.ref) order by s.occurred_at) as numbers from connect.src_sale s "
            "where s.company_id = :c and s.connection_id = any(cast(:sc as uuid[])) and s.status = 'posted' "
            f"and {local_day('s.occurred_at')} >= :since and "
            f"({local_hour('s.occurred_at')} < :open or {local_hour('s.occurred_at')} >= :close) "
            f"group by s.branch_id, s.branch_ref, {local_day('s.occurred_at')}"),
            {"c": str(ctx.company_id), "sc": supply.ids("sales"), "tz": ctx.timezone, "since": since,
             "open": int(ctx.params["open_hour"]), "close": int(ctx.params["close_hour"])}).all()
        names = branch_names(session, [r.branch_id for r in rows])
        found = []
        for r in rows:
            total = Decimal(r.total)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.branch_ref, r.day),
                severity="medium" if r.n >= 5 else "low",
                summary=lead(f"{where_name(names, r.branch_id,
                    r.branch_ref)} made {r.n} sale{'s' if r.n != 1 else ''} worth "
                             f"{cur} {money(total)} on {r.day} outside {int(ctx.params['open_hour']):02d}:00-"
                             f"{int(ctx.params['close_hour']):02d}:00, the first at {r.first_at.strftime('%H:%M')}."),
                recommended_action="Ask the branch manager why the till was in use then.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="kernel.branch", entity_id=r.branch_id, period_start=r.day,
                period_end=r.day, value=Decimal(r.n), amount=total,
                records=tuple(Record("connect.src_sale", i, f"Sale {n}") for i, n in zip(r.ids, r.numbers,
                    strict=True))[:LIST_SIZE],
                figures={"sales": str(r.n), "total": money(total)}))
        return found


class LateEnteredSales(StandaloneCheck):
    """Sales typed in days after they are dated (needs a source that records when each sale was entered)."""

    code = "standalone.late_entered_sales"
    title = "Sales entered long after their date"
    area = "controls"
    description = "A sale was entered into the system days after the day it is dated."
    default_severity = "low"
    requires = ("sales",)
    core_areas = ("sales",)
    params: dict[str, Any] = {"days": 14, "min_days_late": 2, "high_days_late": 7}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            f"select s.id, s.ref, s.number, s.branch_id, s.connection_id, s.cashier_ref, s.total, "
            f"{local_day('s.occurred_at')} as sold_on, {local_day('s.entered_at')} as entered_on, "
            f"{local_day('s.entered_at')} - {local_day('s.occurred_at')} as late from connect.src_sale s "
            "where s.company_id = :c and s.connection_id = any(cast(:sc as uuid[])) and s.status = 'posted' "
            f"and s.entered_at is not null and {local_day('s.entered_at')} >= :since "
            f"and {local_day('s.entered_at')} - {local_day('s.occurred_at')} >= :late order by late desc"),
            {"c": str(ctx.company_id), "sc": supply.ids("sales"), "tz": ctx.timezone, "since": since,
             "late": int(ctx.params["min_days_late"])}).all()
        who = user_names(session, supply.ids("users"), [(r.connection_id, r.cashier_ref) for r in rows])
        found = []
        for r in rows:
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="medium" if r.late >= int(ctx.params["high_days_late"]) else "low",
                summary=(f"Sale {r.number or r.ref} by {person(who, r.connection_id, r.cashier_ref, 'a cashier')} for "
                         f"{cur} {money(Decimal(r.total))} is dated {r.sold_on} but was entered on {r.entered_on}, "
                         f"{r.late} days later."),
                recommended_action="Check why the sale was recorded late.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="connect.src_sale", entity_id=r.id, period_start=r.sold_on,
                period_end=r.entered_on, value=Decimal(r.late), amount=Decimal(r.total),
                records=(Record("connect.src_sale", r.id, f"Sale {r.number or r.ref}"),),
                figures={"days_late": str(r.late)}))
        return found


# --------------------------------------------------------------------------------------------- cashier habits
@dataclass(frozen=True)
class CashierDay:
    """What one cashier did on one day (in one connected system)."""

    connection_id: UUID
    cashier_ref: str
    day: date
    branch_id: UUID | None
    sales: int
    voids: int
    void_total: Decimal
    posted_total: Decimal
    list_value: Decimal
    concession: Decimal
    refunds: Decimal


def cashier_days(session: Session, company_id: UUID, conns: Sequence[str], tz: str, date_from: date,
                 date_to: date) -> list[CashierDay]:
    """Per cashier and day from `date_from` up to (not including) `date_to`."""
    p = {"c": str(company_id), "sc": list(conns), "tz": tz, "f": date_from, "t": date_to}
    rows = session.execute(text(
        f"select s.connection_id, s.cashier_ref, {local_day('s.occurred_at')} as day, "
        "(array_agg(s.branch_id order by s.occurred_at desc))[1] as branch_id, count(*) as n, "
        "count(*) filter (where s.status = 'voided') as voids, "
        "coalesce(sum(s.total) filter (where s.status = 'voided'), 0) as void_total, "
        "coalesce(sum(s.total) filter (where s.status = 'posted'), 0) as posted_total, "
        "coalesce(sum(s.total) filter (where s.status = 'refunded'), 0) as refunds from connect.src_sale s "
        "where s.company_id = :c and s.connection_id = any(cast(:sc as uuid[])) and s.cashier_ref is not null "
        f"and {local_day('s.occurred_at')} >= :f and {local_day('s.occurred_at')} < :t "
        f"group by s.connection_id, s.cashier_ref, {local_day('s.occurred_at')}"), p).all()
    # price reductions and discounts on the day's posted sales: line discounts and prices below the list price; a sale
    # with no lines counts its sale-level discount against its total plus discount
    concessions = {(r.connection_id, r.cashier_ref, r.day): r for r in session.execute(text(
        f"select s.connection_id, s.cashier_ref, {local_day('s.occurred_at')} as day, "
        "sum(case when l.id is null then s.discount_total else "
        "greatest(coalesce(l.list_price, l.unit_price) - l.unit_price, 0) * l.quantity + l.discount end) as "
        "concession, "
        "sum(case when l.id is null then s.total + s.discount_total else "
        "coalesce(l.list_price, l.unit_price) * l.quantity end) as list_value "
        "from connect.src_sale s left join connect.src_sale_line l on l.sale_id = s.id "
        "where s.company_id = :c and s.connection_id = any(cast(:sc as uuid[])) and s.status = 'posted' "
        f"and s.cashier_ref is not null and {local_day('s.occurred_at')} >= :f and {local_day('s.occurred_at')} < :t "
        f"group by s.connection_id, s.cashier_ref, {local_day('s.occurred_at')}"), p)}
    out = []
    for r in rows:
        c = concessions.get((r.connection_id, r.cashier_ref, r.day))
        out.append(CashierDay(
            r.connection_id, r.cashier_ref, r.day, r.branch_id, r.n, r.voids, Decimal(r.void_total),
            Decimal(r.posted_total), Decimal(c.list_value) if c else ZERO, Decimal(c.concession) if c else ZERO,
            Decimal(r.refunds)))
    return out


def cashier_key(d: CashierDay) -> str:
    return f"{d.connection_id}:{d.cashier_ref}"


def void_rate(d: CashierDay) -> Decimal | None:
    return rate(Decimal(d.voids), Decimal(d.sales))


def refund_rate(d: CashierDay) -> Decimal | None:
    return rate(d.refunds, d.posted_total)


def discount_rate(d: CashierDay) -> Decimal | None:
    return rate(d.concession, d.list_value)


class _RateMetric(BaselineMetric):
    def rate_of(self, day: CashierDay) -> Decimal | None:
        raise NotImplementedError

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        """One sample per cashier per day with enough sales."""
        supply = supplied(session, company_id)
        if not supply.has("sales"):
            return []
        zone = str(company_setting(session, company_id, "timezone"))
        out = []
        for d in cashier_days(session, company_id, supply.ids("sales"), zone, date_from, date_to):
            value = self.rate_of(d)
            if d.sales >= BASELINE_MIN_DAY_SALES and value is not None:
                out.append(Sample(cashier_key(d), value))
        return out


class CashierVoidRateMetric(_RateMetric):
    code = "standalone.cashier_void_rate"
    title = "Cashier void rate (connected system)"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return void_rate(day)


class CashierRefundRateMetric(_RateMetric):
    code = "standalone.cashier_refund_rate"
    title = "Cashier refund rate (connected system)"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return refund_rate(day)


class CashierDiscountRateMetric(_RateMetric):
    code = "standalone.cashier_discount_rate"
    title = "Cashier discount rate (connected system)"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return discount_rate(day)


class BranchDailySalesMetric(BaselineMetric):
    """What a branch sells on a given weekday (key '<branch>:dow<0=Monday>')."""

    code = "standalone.branch_daily_sales"
    title = "Branch sales by weekday (connected system)"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        supply = supplied(session, company_id)
        if not supply.has("sales"):
            return []
        zone = str(company_setting(session, company_id, "timezone"))
        rows = session.execute(text(
            f"select connection_id, branch_id, branch_ref, {local_day('occurred_at')} as day, sum(total) as total "
            "from connect.src_sale where company_id = :c and connection_id = any(cast(:sc as uuid[])) "
            f"and status = 'posted' and {local_day('occurred_at')} >= :f and {local_day('occurred_at')} < :t "
            f"group by connection_id, branch_id, branch_ref, {local_day('occurred_at')}"),
            {"c": str(company_id), "sc": supply.ids("sales"), "tz": zone, "f": date_from, "t": date_to})
        return [Sample(sales_key(r.connection_id, r.branch_id, r.branch_ref, r.day.weekday()), Decimal(r.total))
                for r in rows]


class _CashierRateCheck(StandaloneCheck):
    metric: str
    what: str
    area = "controls"
    default_severity = "medium"
    requires = ("sales",)
    core_areas = ("sales",)
    params: dict[str, Any] = {"days": 2, "min_sales": 5, "min_rate": "0.05"}

    def rate_of(self, day: CashierDay) -> Decimal | None:
        raise NotImplementedError

    def amount_of(self, day: CashierDay) -> Decimal:
        raise NotImplementedError

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        days = int(ctx.params["days"])
        last = last_complete_day(ctx, supply.complete_until("sales"))
        cur = currency(session, ctx.company_id)
        rows = cashier_days(session, ctx.company_id, supply.ids("sales"), ctx.timezone,
                            ctx.today - timedelta(days=days), last + timedelta(days=1))
        who = user_names(session, supply.ids("users"), [(d.connection_id, d.cashier_ref) for d in rows])
        found = []
        for d in rows:
            value = self.rate_of(d)
            baseline = ctx.baseline(self.metric, cashier_key(d))
            if value is None or d.sales < int(ctx.params["min_sales"]) or value < ctx.number("min_rate"):
                continue
            if baseline is None or not is_unusual(value, baseline):
                continue
            name = person(who, d.connection_id, d.cashier_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, d.connection_id, d.cashier_ref, d.day), severity="medium",
                summary=(f"On {d.day} {name}'s {self.what} was {percent(value)} over {d.sales} sales "
                         f"({cur} {money(self.amount_of(d))}); their usual is about {percent(baseline.mean)}."),
                recommended_action=f"Ask {name} to explain.", company_id=ctx.company_id, branch_id=d.branch_id,
                period_start=d.day, period_end=d.day, value=value, expected_value=baseline.mean,
                amount=self.amount_of(d),
                figures={"sales": str(d.sales), "rate": percent(value), "usual_rate": percent(baseline.mean)}))
        return found


class CashierVoidRate(_CashierRateCheck):
    code = "standalone.cashier_void_rate"
    title = "A cashier voided more sales than usual"
    description = "A cashier cancelled a much bigger share of their sales than they normally do."
    metric = "standalone.cashier_void_rate"
    what = "void rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return void_rate(day)

    def amount_of(self, day: CashierDay) -> Decimal:
        return day.void_total


class CashierRefundRate(_CashierRateCheck):
    code = "standalone.cashier_refund_rate"
    title = "A cashier processed more refunds than usual"
    description = "A cashier refunded a much bigger share of what they sold than they normally do."
    metric = "standalone.cashier_refund_rate"
    what = "refund rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return refund_rate(day)

    def amount_of(self, day: CashierDay) -> Decimal:
        return day.refunds


class CashierDiscountRate(_CashierRateCheck):
    code = "standalone.cashier_discount_rate"
    title = "A cashier gave more discounts than usual"
    description = "A cashier gave away a much bigger share of the list price in discounts and price changes than usual."
    metric = "standalone.cashier_discount_rate"
    what = "discount and price-override rate"

    def rate_of(self, day: CashierDay) -> Decimal | None:
        return discount_rate(day)

    def amount_of(self, day: CashierDay) -> Decimal:
        return day.concession


class LargeExceptions(StandaloneCheck):
    """A single big void, refund or discount."""

    code = "standalone.large_exception"
    title = "A large void, refund or discount"
    area = "controls"
    description = "One sale was voided, one refunded, or one sale discounted for a large amount."
    default_severity = "medium"
    requires = ("sales",)
    core_areas = ("sales",)
    params: dict[str, Any] = {"days": 7, "min_void": "2000.00", "min_refund": "2000.00", "min_discount": "1000.00"}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select s.id, s.ref, s.number, s.connection_id, s.branch_id, s.status, s.total, s.cashier_ref, "
            f"s.voided_by_ref, {local_day('s.occurred_at')} as day, "
            "coalesce((select sum(case when l.id is null then 0 else "
            "greatest(coalesce(l.list_price, l.unit_price) - l.unit_price, 0) * l.quantity + l.discount end) "
            "from connect.src_sale_line l where l.sale_id = s.id), 0) + s.discount_total as concession "
            "from connect.src_sale s where s.company_id = :c and s.connection_id = any(cast(:sc as uuid[])) "
            f"and {local_day('s.occurred_at')} >= :since order by s.occurred_at"),
            {"c": str(ctx.company_id), "sc": supply.ids("sales"), "tz": ctx.timezone, "since": since}).all()
        who = user_names(session, supply.ids("users"), [(r.connection_id,
            r.voided_by_ref or r.cashier_ref) for r in rows])
        found = []
        for r in rows:
            total, concession = Decimal(r.total), Decimal(r.concession)
            by = person(who, r.connection_id, r.voided_by_ref or r.cashier_ref, "someone")
            label = r.number or r.ref
            record = (Record("connect.src_sale", r.id, f"Sale {label}"),)
            if r.status == "voided" and total >= ctx.number("min_void"):
                found.append(self._candidate(ctx, r, "void", total, record,
                                             f"Sale {label} for {cur} {money(total)} was voided by {by} on {r.day}.",
                                             "Check why the sale was cancelled and that the goods stayed in stock."))
            elif r.status == "refunded" and total >= ctx.number("min_refund"):
                found.append(self._candidate(ctx, r, "refund", total, record,
                                             f"Sale {label} for {cur} {money(total)} was refunded on {r.day} "
                                             f"(cashier {person(who, r.connection_id, r.cashier_ref, 'unknown')}).",
                                             "Check the refund against the customer's return and who approved it."))
            if r.status == "posted" and concession >= ctx.number("min_discount"):
                found.append(self._candidate(ctx, r, "discount", concession, record,
                                             f"Sale {label} on {r.day} was discounted by {cur} {money(concession)} "
                                             f"(cashier {person(who, r.connection_id, r.cashier_ref, 'unknown')}).",
                                             "Check who allowed the discount and why."))
        return found

    def _candidate(self, ctx: CheckContext, r: Row[Any], kind: str, amount: Decimal, records: tuple[Record, ...],
                   summary: str, action: str) -> Candidate:
        return Candidate(
            fingerprint=fingerprint(self.code, kind, r.id), severity="medium", summary=summary,
            recommended_action=action, company_id=ctx.company_id, branch_id=r.branch_id,
            entity_type="connect.src_sale", entity_id=r.id, period_start=r.day, period_end=r.day, value=amount,
            amount=amount, records=records, figures={"kind": kind, "amount": money(amount)})


# --------------------------------------------------------------------------------------------- customers
class OverdueCustomers(StandaloneCheck):
    """Customers with invoices well past their due date."""

    code = "standalone.customer_overdue"
    title = "A customer is overdue"
    area = "customers"
    description = "A customer has an invoice that is more than the set number of days past its due date."
    default_severity = "medium"
    requires = ("invoices",)
    core_areas = ("receivables",)
    params: dict[str, Any] = {"min_days_overdue": 30, "high_days_overdue": 90}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select i.connection_id, i.party_ref, count(*) as n, sum(i.total - i.paid) as owed, min(i.due_date) as "
            "oldest, "
            "array_agg(i.id order by i.due_date) as ids, array_agg(coalesce(i.number, i.ref) order by i.due_date) as "
            "numbers, "
            "count(distinct i.branch_id) as branches, min(i.branch_id::text) as branch from connect.src_invoice i "
            "where i.company_id = :c and i.connection_id = any(cast(:ic as uuid[])) and i.kind = 'customer' "
            "and i.status = 'open' and i.due_date < :today group by i.connection_id, i.party_ref "
            "having sum(i.total - i.paid) > 0 and min(i.due_date) < :cutoff"),
            {"c": str(ctx.company_id), "ic": supply.ids("invoices"), "today": ctx.today,
             "cutoff": ctx.today - timedelta(days=int(ctx.params["min_days_overdue"]))}).all()
        names = party_names(session, supply.ids("parties"), [(r.connection_id, r.party_ref) for r in rows])
        found = []
        for r in rows:
            owed, days = Decimal(r.owed), (ctx.today - r.oldest).days
            who = names.get((r.connection_id, r.party_ref or ""), r.party_ref or "A customer")
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.connection_id, r.party_ref),
                severity="high" if days >= int(ctx.params["high_days_overdue"]) else "medium",
                summary=(f"{who} owes {cur} {money(owed)} past due on {r.n} invoice{'s' if r.n != 1 else ''}; the "
                         f"oldest "
                         f"is {days} days overdue."),
                recommended_action="Contact the customer to collect payment.", company_id=ctx.company_id,
                branch_id=UUID(r.branch) if r.branches == 1 and r.branch else None, entity_type="connect.src_party",
                period_end=ctx.today, value=Decimal(days), amount=owed,
                records=tuple(Record("connect.src_invoice", i, f"Invoice {n}") for i, n in zip(r.ids, r.numbers,
                    strict=True))[:LIST_SIZE],
                figures={"overdue_balance": money(owed), "invoices": str(r.n), "oldest_days_overdue": str(days)}))
        return found


class SlowerPayers(StandaloneCheck):
    """Customers who now take noticeably longer to pay."""

    code = "standalone.customer_paying_slower"
    title = "A customer is paying slower"
    area = "customers"
    description = "A customer takes much longer to pay their invoices than they did in the period before."
    default_severity = "low"
    requires = ("invoices", "payments")
    core_areas = ("receivables",)
    params: dict[str, Any] = {"window_days": 90, "increase_percent": 50, "min_increase_days": 5, "min_invoices": 3}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        window = int(ctx.params["window_days"])
        mid, start = ctx.today - timedelta(days=window), ctx.today - timedelta(days=2 * window)
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "with paid as (select i.connection_id, i.party_ref, i.id, i.issue_date, "
            f"max({local_day('p.occurred_at')}) as paid_on from connect.src_invoice i "
            "join connect.src_payment p on p.invoice_ref = i.ref and p.direction = 'in' "
            "and p.connection_id = any(cast(:pc as uuid[])) where i.company_id = :c "
            "and i.connection_id = any(cast(:ic as uuid[])) and i.kind = 'customer' and i.status = 'paid' "
            "and i.party_ref is not null group by i.id, i.connection_id, i.party_ref, i.issue_date) "
            "select p.connection_id, p.party_ref, count(*) filter (where p.paid_on > :mid) as n_recent, "
            "avg(p.paid_on - p.issue_date) filter (where p.paid_on > :mid) as recent, "
            "count(*) filter (where p.paid_on <= :mid) as n_prior, "
            "avg(p.paid_on - p.issue_date) filter (where p.paid_on <= :mid) as prior, "
            "(select coalesce(sum(o.total - o.paid), 0) from connect.src_invoice o where o.connection_id = "
            "p.connection_id "
            "and o.party_ref = p.party_ref and o.kind = 'customer' and o.status = 'open') as open_balance "
            "from paid p where p.paid_on > :start and p.paid_on <= :today group by p.connection_id, p.party_ref"),
            {"c": str(ctx.company_id), "ic": supply.ids("invoices"), "pc": supply.ids("payments"), "tz": ctx.timezone,
             "mid": mid, "start": start, "today": ctx.today}).all()
        names = party_names(session, supply.ids("parties"), [(r.connection_id, r.party_ref) for r in rows])
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
            who = names.get((r.connection_id, r.party_ref), r.party_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.connection_id, r.party_ref),
                severity="medium" if recent >= prior * 2 else "low",
                summary=(f"{who} now takes {recent:.0f} days on average to pay, up from {prior:.0f} days in the "
                         f"{window} days before{f'; they currently owe {cur} {money(owed)}' if owed > 0 else ''}."),
                recommended_action="Review the customer's terms and credit limit before giving more credit.",
                company_id=ctx.company_id, entity_type="connect.src_party", period_start=mid, period_end=ctx.today,
                value=recent, expected_value=prior, amount=owed or None,
                figures={"recent_days": f"{recent:.1f}", "earlier_days": f"{prior:.1f}",
                         "recent_invoices": str(r.n_recent), "earlier_invoices": str(r.n_prior)}))
        return found


class CreditToOverdueCustomer(StandaloneCheck):
    """New credit given to a customer who was already behind."""

    code = "standalone.credit_to_overdue_customer"
    title = "Credit given to a customer who was overdue"
    area = "customers"
    description = "A new invoice was made out to a customer who already had an overdue invoice unpaid."
    default_severity = "medium"
    requires = ("invoices",)
    core_areas = ("receivables",)
    params: dict[str, Any] = {"days": 7, "grace_days": 0, "high_days_overdue": 60}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select i.id, coalesce(i.number, i.ref) as number, i.connection_id, i.party_ref, i.branch_id, i.total, "
            "i.issue_date, o.owed, o.oldest, o.n from connect.src_invoice i "
            "cross join lateral (select sum(x.total - x.paid) as owed, max(i.issue_date - x.due_date) as oldest, "
            "count(*) as n from connect.src_invoice x where x.connection_id = i.connection_id "
            "and x.party_ref = i.party_ref and x.kind = 'customer' and x.id <> i.id and x.status = 'open' "
            "and x.issue_date < i.issue_date and x.due_date < i.issue_date - :grace) o "
            "where i.company_id = :c and i.connection_id = any(cast(:ic as uuid[])) and i.kind = 'customer' "
            "and i.status in ('open', 'paid') and i.party_ref is not null and i.issue_date >= :since and o.owed > 0"),
            {"c": str(ctx.company_id), "ic": supply.ids("invoices"), "since": since,
             "grace": int(ctx.params["grace_days"])}).all()
        names = party_names(session, supply.ids("parties"), [(r.connection_id, r.party_ref) for r in rows])
        found = []
        for r in rows:
            owed = Decimal(r.owed)
            who = names.get((r.connection_id, r.party_ref), r.party_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="high" if r.oldest >= int(ctx.params["high_days_overdue"]) else "medium",
                summary=(f"Invoice {r.number} for {cur} {money(Decimal(r.total))} was issued on {r.issue_date} to "
                         f"{who}, "
                         f"who still owes {cur} {money(owed)} on {r.n} older invoice{'s' if r.n != 1 else ''} that "
                         f"{'were' if r.n != 1 else 'was'} already overdue (the oldest by {r.oldest} days)."),
                recommended_action="Check who approved more credit, and collect the overdue balance first.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="connect.src_invoice", entity_id=r.id,
                period_start=r.issue_date, period_end=r.issue_date, value=Decimal(r.total), amount=Decimal(r.total),
                records=(Record("connect.src_invoice", r.id, f"Invoice {r.number}"),),
                figures={"overdue_before": money(owed), "oldest_days_overdue": str(r.oldest)}))
        return found


# --------------------------------------------------------------------------------------------- suppliers
class SupplierPriceRise(StandaloneCheck):
    """A product's latest purchase cost is well above what was paid before."""

    code = "standalone.supplier_price_rise"
    title = "A product costs more than it used to"
    area = "suppliers"
    description = "The latest purchase of a product was at a price well above the average of earlier purchases."
    default_severity = "medium"
    requires = ("stock_movements",)
    core_areas = ("stock",)
    params: dict[str, Any] = {"days": 30, "history_days": 180, "rise_percent": 10, "min_earlier": 2}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        history = ctx.today - timedelta(days=int(ctx.params["history_days"]))
        rows = session.execute(text(
            "with buys as (select connection_id, product_ref, unit_cost, occurred_at, "
            f"{local_day('occurred_at')} as day from connect.src_stock_movement where company_id = :c "
            "and connection_id = any(cast(:mc as uuid[])) and kind = 'purchase' and unit_cost > 0 and quantity > 0 "
            "and occurred_at >= :hist), latest as (select distinct on (connection_id, product_ref) connection_id, "
            "product_ref, unit_cost, day, occurred_at from buys order by connection_id, product_ref, occurred_at desc) "
            "select l.connection_id, l.product_ref, l.unit_cost as latest, l.day, avg(b.unit_cost) as earlier, "
            "count(b.*) as n from latest l join buys b on b.connection_id = l.connection_id "
            "and b.product_ref = l.product_ref and b.occurred_at < l.occurred_at where l.day >= :since "
            "group by l.connection_id, l.product_ref, l.unit_cost, l.day"),
            {"c": str(ctx.company_id), "mc": supply.ids("stock_movements"), "tz": ctx.timezone, "hist": start_of(
                history, ctx.timezone), "since": since}).all()
        names = product_names(session, supply.ids("products"), [r.product_ref for r in rows])
        found = []
        for r in rows:
            latest, earlier = Decimal(r.latest), Decimal(r.earlier)
            rise = price_rise_percent(earlier, latest)
            if r.n < int(ctx.params["min_earlier"]) or rise is None or rise < Decimal(int(ctx.params["rise_percent"])):
                continue
            name = names.get((r.connection_id, r.product_ref), r.product_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.connection_id, r.product_ref, r.day),
                severity="high" if rise >= 2 * Decimal(int(ctx.params["rise_percent"])) else "medium",
                summary=(f"{name} was last bought on {r.day} at {cur} {money(latest)} a unit, {rise:.0f}% above the "
                         f"{cur} {money(earlier)} it cost on average before."),
                recommended_action="Ask the supplier or buyer why the price went up, and compare other suppliers.",
                company_id=ctx.company_id, entity_type="connect.src_product", period_start=r.day, period_end=r.day,
                value=latest, expected_value=earlier, amount=latest - earlier,
                figures={"latest": money(latest), "earlier_average": money(earlier), "rise_percent": f"{rise:.0f}"}))
        return found


class DuplicateSupplierInvoices(StandaloneCheck):
    """The same bill entered twice."""

    code = "standalone.duplicate_supplier_invoice"
    title = "A supplier invoice may have been entered twice"
    area = "suppliers"
    description = "Two supplier invoices for the same supplier and amount have the same number or nearly the same date."
    default_severity = "medium"
    requires = ("invoices",)
    core_areas = ("payables",)
    params: dict[str, Any] = {"lookback_days": 90, "days_apart": 3, "min_amount": "1.00"}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select a.id as a_id, b.id as b_id, a.connection_id, a.party_ref, a.total, a.branch_id, "
            "coalesce(a.number, a.ref) as a_number, coalesce(b.number, b.ref) as b_number, a.issue_date as a_date, "
            "b.issue_date as b_date from connect.src_invoice a join connect.src_invoice b "
            "on b.connection_id = a.connection_id and b.party_ref = a.party_ref and b.total = a.total and b.ref > "
            "a.ref "
            "where a.company_id = :c and a.connection_id = any(cast(:ic as uuid[])) and a.kind = 'supplier' "
            "and b.kind = 'supplier' and a.status in ('open', 'paid') and b.status in ('open', 'paid') "
            "and a.party_ref is not null and a.total >= :min and a.issue_date >= :since "
            "and (lower(coalesce(a.number, a.ref)) = lower(coalesce(b.number, b.ref)) "
            "or abs(a.issue_date - b.issue_date) <= :apart) order by a.issue_date"),
            {"c": str(ctx.company_id), "ic": supply.ids("invoices"), "min": ctx.number("min_amount"),
             "since": ctx.today - timedelta(days=int(ctx.params["lookback_days"])),
             "apart": int(ctx.params["days_apart"])}).all()
        names = party_names(session, supply.ids("parties"), [(r.connection_id, r.party_ref) for r in rows])
        found = []
        for r in rows:
            who = names.get((r.connection_id, r.party_ref), r.party_ref)
            total = Decimal(r.total)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.a_id, r.b_id), severity="medium",
                summary=(f"Invoices {r.a_number} ({r.a_date}) and {r.b_number} ({r.b_date}) from {who} are both for "
                         f"{cur} {money(total)}: one may be a duplicate."),
                recommended_action="Check the two invoices against the supplier's statement and pay only one.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="connect.src_invoice", entity_id=r.a_id,
                period_start=r.a_date, period_end=r.b_date, value=total, amount=total,
                records=(Record("connect.src_invoice", r.a_id, f"Invoice {r.a_number}"),
                         Record("connect.src_invoice", r.b_id, f"Invoice {r.b_number}")),
                figures={"amount": money(total)}))
        return found


class DuplicatePayments(StandaloneCheck):
    """The same payment made twice."""

    code = "standalone.duplicate_payment"
    title = "A payment may have been made twice"
    area = "suppliers"
    description = "Two payments out of the same amount to the same payee within a short time."
    default_severity = "medium"
    requires = ("payments",)
    core_areas = ("payments",)
    params: dict[str, Any] = {"days": 14, "hours_apart": 48, "min_amount": "1.00"}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        since = start_of(ctx.today - timedelta(days=int(ctx.params["days"])), ctx.timezone)
        rows = session.execute(text(
            "select a.id as a_id, b.id as b_id, a.amount, a.branch_id, a.occurred_at as a_at, b.occurred_at as b_at, "
            "coalesce(a.party_name, a.party_ref) as who from connect.src_payment a join connect.src_payment b "
            "on b.connection_id = a.connection_id and b.ref > a.ref and b.direction = 'out' and b.amount = a.amount "
            "and coalesce(lower(b.account), '') = coalesce(lower(a.account), '') "
            "and ((a.party_ref is not null and b.party_ref = a.party_ref) or "
            "(a.party_ref is null and a.party_name is not null and lower(b.party_name) = lower(a.party_name))) "
            "and coalesce(b.invoice_ref, '') = coalesce(a.invoice_ref, '') "
            "and abs(extract(epoch from b.occurred_at - a.occurred_at)) <= :gap "
            "and (a.reference is null or b.reference is null or lower(a.reference) <> lower(b.reference)) "
            "where a.company_id = :c and a.connection_id = any(cast(:pc as uuid[])) and a.direction = 'out' "
            "and a.amount >= :min and a.occurred_at >= :since order by a.occurred_at"),
            {"c": str(ctx.company_id), "pc": supply.ids("payments"), "min": ctx.number("min_amount"), "since": since,
             "gap": int(ctx.params["hours_apart"]) * 3600}).all()
        found = []
        for r in rows:
            amount = Decimal(r.amount)
            first = r.a_at.astimezone(ZoneInfo(ctx.timezone))
            second = r.b_at.astimezone(ZoneInfo(ctx.timezone))
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.a_id, r.b_id), severity="medium",
                summary=(f"Two payments of {cur} {money(amount)} went to {r.who or 'the same payee'}, on "
                         f"{first:%Y-%m-%d %H:%M} and {second:%Y-%m-%d %H:%M}: one may be a duplicate."),
                recommended_action="Check whether both were owed; if not, ask for a refund.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="connect.src_payment", entity_id=r.a_id,
                period_start=first.date(), period_end=second.date(), value=amount, amount=amount,
                records=(Record("connect.src_payment", r.a_id, f"Payment of {money(amount)} on {first:%Y-%m-%d}"),
                         Record("connect.src_payment", r.b_id, f"Payment of {money(amount)} on {second:%Y-%m-%d}")),
                figures={"amount": money(amount)}))
        return found


# --------------------------------------------------------------------------------------------- stock
class StockAdjustments(StandaloneCheck):
    """Stock adjusted by a lot, at odd hours, or dated back."""

    code = "standalone.stock_adjustment"
    title = "A stock adjustment worth a look"
    area = "stock"
    description = "Stock was written off or adjusted for a large value, at odd hours, or entered days after its date."
    default_severity = "medium"
    requires = ("stock_movements",)
    core_areas = ("stock",)
    params: dict[str, Any] = {"days": 14, "min_value": "5000.00", "min_quantity": "100", "open_hour": 6,
                              "close_hour": 22, "backdate_days": 3}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select m.id, m.ref, m.connection_id, m.branch_id, m.product_ref, m.quantity, m.user_ref, m.reason, "
            "m.occurred_at, m.entered_at, coalesce(m.unit_cost, p.unit_cost) as cost, "
            f"{local_day('m.occurred_at')} as day, {local_hour('coalesce(m.entered_at, m.occurred_at)')} as hour, "
            f"case when m.entered_at is null then 0 else {local_day('m.entered_at')} - {local_day('m.occurred_at')} "
            f"end "
            "as late from connect.src_stock_movement m left join connect.src_product p "
            "on p.connection_id = m.connection_id and p.ref = m.product_ref where m.company_id = :c "
            "and m.connection_id = any(cast(:mc as uuid[])) and m.kind in ('adjustment', 'count') "
            f"and {local_day('m.occurred_at')} >= :since order by m.occurred_at"),
            {"c": str(ctx.company_id), "mc": supply.ids("stock_movements"), "tz": ctx.timezone,
             "since": ctx.today - timedelta(days=int(ctx.params["days"]))}).all()
        products = product_names(session, supply.ids("products"), [r.product_ref for r in rows])
        who = user_names(session, supply.ids("users"), [(r.connection_id, r.user_ref) for r in rows])
        found = []
        for r in rows:
            qty = Decimal(r.quantity)
            cost = Decimal(r.cost) if r.cost is not None else None
            value = abs(qty) * cost if cost is not None else None
            reasons = []
            if value is not None and value >= ctx.number("min_value"):
                reasons.append(f"worth {cur} {money(value)}")
            elif value is None and abs(qty) >= ctx.number("min_quantity"):
                reasons.append(f"{plain(abs(qty))} units")
            if outside_hours(int(r.hour), int(ctx.params["open_hour"]), int(ctx.params["close_hour"])):
                reasons.append(f"entered at {int(r.hour):02d}:00, outside trading hours")
            if r.late >= int(ctx.params["backdate_days"]):
                reasons.append(f"entered {r.late} days after its date")
            if not reasons:
                continue
            name = products.get((r.connection_id, r.product_ref), r.product_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="high" if len(reasons) >= 2 else "medium",
                summary=(f"{person(who, r.connection_id, r.user_ref, 'Someone')} adjusted {name} by {signed(qty)} on "
                         f"{r.day}: {'; '.join(reasons)}." + (f" Reason given: {r.reason}." if r.reason else "")),
                recommended_action="Ask who made the adjustment and check the shelf.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="connect.src_stock_movement", entity_id=r.id, period_start=r.day,
                period_end=r.day, value=qty, amount=value,
                records=(Record("connect.src_stock_movement", r.id, f"Adjustment of {name} on {r.day}"),),
                figures={"quantity": signed(qty), "why": "; ".join(reasons)}))
        return found


class ShrinkageByProduct(StandaloneCheck):
    """A product keeps being written off or counted short."""

    code = "standalone.shrinkage_by_product"
    title = "Stock is going missing"
    area = "stock"
    description = "A product has lost a lot of stock to write-offs and short counts over the last weeks."
    default_severity = "medium"
    requires = ("stock_movements",)
    core_areas = ("stock",)
    params: dict[str, Any] = {"days": 30, "min_loss": "5000.00", "min_units": "10"}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select m.connection_id, m.product_ref, m.branch_id, -sum(m.quantity) as units, "
            "-sum(m.quantity * coalesce(m.unit_cost, p.unit_cost, 0)) as loss, count(*) as n, "
            "array_agg(m.id order by m.occurred_at) as ids from connect.src_stock_movement m "
            "left join connect.src_product p on p.connection_id = m.connection_id and p.ref = m.product_ref "
            "where m.company_id = :c and m.connection_id = any(cast(:mc as uuid[])) "
            "and m.kind in ('adjustment', 'count') and m.quantity < 0 "
            f"and {local_day('m.occurred_at')} >= :since group by m.connection_id, m.product_ref, m.branch_id"),
            {"c": str(ctx.company_id), "mc": supply.ids("stock_movements"), "tz": ctx.timezone,
             "since": ctx.today - timedelta(days=int(ctx.params["days"]))}).all()
        products = product_names(session, supply.ids("products"), [r.product_ref for r in rows])
        names = branch_names(session, [r.branch_id for r in rows])
        found = []
        for r in rows:
            loss, units = Decimal(r.loss), Decimal(r.units)
            if loss < ctx.number("min_loss") and not (loss == 0 and units >= ctx.number("min_units")):
                continue
            name = products.get((r.connection_id, r.product_ref), r.product_ref)
            value_text = f" worth {cur} {money(loss)}" if loss > 0 else ""
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.connection_id, r.product_ref, r.branch_id),
                severity="high" if loss >= 5 * ctx.number("min_loss") else "medium",
                summary=(f"{plain(units)} units of {name} were written off or counted missing at "
                         f"{where_name(names, r.branch_id)} in {int(ctx.params['days'])} days{value_text}."),
                recommended_action="Count the product, and check where it is going.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="connect.src_product", value=units,
                amount=loss if loss > 0 else None,
                records=tuple(Record("connect.src_stock_movement", i,
                    f"Adjustment of {name}") for i in r.ids)[:LIST_SIZE],
                figures={"units": plain(units), "adjustments": str(r.n)}))
        return found


class NegativeStock(StandaloneCheck):
    """More has gone out than came in."""

    code = "standalone.negative_stock"
    title = "Negative stock"
    area = "stock"
    description = ("A product's movements add up to less than nothing: more went out than ever came in. "
                   "Judged on the movements you connected, so it needs the history from the start (or an opening "
                   "count).")
    default_severity = "medium"
    requires = ("stock_movements",)
    core_areas = ("stock",)
    params: dict[str, Any] = {"min_units": "1"}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        rows = session.execute(text(
            "select m.connection_id, m.product_ref, m.branch_id, sum(m.quantity) as balance, "
            "max(m.occurred_at) as last_at from connect.src_stock_movement m where m.company_id = :c "
            "and m.connection_id = any(cast(:mc as uuid[])) group by m.connection_id, m.product_ref, m.branch_id "
            "having sum(m.quantity) <= -:min and bool_or(m.quantity > 0)"),
            {"c": str(ctx.company_id), "mc": supply.ids("stock_movements"), "min": ctx.number("min_units")}).all()
        products = product_names(session, supply.ids("products"), [r.product_ref for r in rows])
        names = branch_names(session, [r.branch_id for r in rows])
        found = []
        for r in rows:
            balance = Decimal(r.balance)
            name = products.get((r.connection_id, r.product_ref), r.product_ref)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.connection_id, r.product_ref, r.branch_id), severity="medium",
                summary=(f"{name} at {where_name(names,
                    r.branch_id)} has gone {plain(abs(balance))} units below zero: more "
                         "has been sold or moved out than was ever received."),
                recommended_action="Check for unrecorded deliveries, wrong units, or sales of goods that were not "
                                   "there.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="connect.src_product", value=balance,
                expected_value=ZERO, figures={"balance": plain(balance)}))
        return found


# --------------------------------------------------------------------------------------------- books
class ManualJournals(StandaloneCheck):
    """Manual journal entries with the usual signs of trouble."""

    code = "standalone.manual_journal"
    title = "A manual journal entry worth a look"
    area = "books"
    description = ("A journal entry made by hand is large, a round number, made at odd hours, dated back, or created "
                   "and approved by the same person.")
    default_severity = "medium"
    requires = ("journal_entries",)
    core_areas = ("journals",)
    params: dict[str, Any] = {"days": 14, "large_amount": "100000.00", "round_step": "10000", "round_min": "10000",
                              "open_hour": 6, "close_hour": 22, "backdate_days": 7}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            "select j.id, j.ref, j.connection_id, coalesce(j.number, j.ref) as number, j.entry_date, j.total_debit, "
            "j.created_by_ref, j.approved_by_ref, j.memo, "
            f"case when j.entered_at is null then null else {local_hour('j.entered_at')} end as hour, "
            f"case when j.entered_at is null then 0 else {local_day('j.entered_at')} - j.entry_date end as late "
            "from connect.src_journal_entry j where j.company_id = :c "
            "and j.connection_id = any(cast(:jc as uuid[])) and j.is_manual and "
            f"coalesce({local_day('j.entered_at')}, j.entry_date) >= :since order by j.entry_date"),
            {"c": str(ctx.company_id), "jc": supply.ids("journal_entries"), "tz": ctx.timezone,
             "since": ctx.today - timedelta(days=int(ctx.params["days"]))}).all()
        who = user_names(session, supply.ids("users"), [(r.connection_id, r.created_by_ref) for r in rows])
        found = []
        for r in rows:
            total = Decimal(r.total_debit)
            reasons = []
            if total >= ctx.number("large_amount"):
                reasons.append("a large amount")
            if is_round(total, ctx.number("round_step"), ctx.number("round_min")):
                reasons.append("an exactly round amount")
            if r.hour is not None and outside_hours(int(r.hour), int(ctx.params["open_hour"]),
                                                    int(ctx.params["close_hour"])):
                reasons.append(f"entered at {int(r.hour):02d}:00")
            if r.late >= int(ctx.params["backdate_days"]):
                reasons.append(f"dated {r.late} days before it was entered")
            same = bool(r.created_by_ref) and r.created_by_ref == r.approved_by_ref
            if same:
                reasons.append("created and approved by the same person")
            if not reasons:
                continue
            severity = "high" if len(reasons) >= 3 or (same and total >= ctx.number("large_amount")) else (
                "medium" if len(reasons) >= 2 or same else "low")
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity=severity,
                summary=(f"Manual journal {r.number} of {cur} {money(total)} dated {r.entry_date} "
                         f"(by {person(who, r.connection_id, r.created_by_ref,
                             'unknown')}) is " + ", ".join(reasons) + "."),
                recommended_action="Ask the person who made it for the reason and the supporting document.",
                company_id=ctx.company_id, entity_type="connect.src_journal_entry", entity_id=r.id,
                period_start=r.entry_date, period_end=r.entry_date, value=total, amount=total,
                records=(Record("connect.src_journal_entry", r.id, f"Journal {r.number}"),),
                figures={"amount": money(total), "why": ", ".join(reasons)}))
        return found


class ExpenseSamples(BaselineMetric):
    """What an expense category usually costs (key '<connection>:<category>')."""

    code = "standalone.expense_by_category"
    title = "Expense size by category (connected system)"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        supply = supplied(session, company_id)
        if not supply.has("expenses"):
            return []
        zone = str(company_setting(session, company_id, "timezone"))
        rows = session.execute(text(
            "select connection_id, coalesce(category, '') as category, amount from connect.src_expense "
            "where company_id = :c and connection_id = any(cast(:ec as uuid[])) and amount > 0 "
            f"and {local_day('occurred_at')} >= :f and {local_day('occurred_at')} < :t"),
            {"c": str(company_id), "ec": supply.ids("expenses"), "tz": zone, "f": date_from, "t": date_to})
        return [Sample(f"{r.connection_id}:{r.category}", Decimal(r.amount)) for r in rows]


class ExpenseFarAboveNormal(StandaloneCheck):
    """An expense far above what its category normally costs."""

    code = "standalone.expense_unusually_high"
    title = "An expense far above its category's normal"
    area = "books"
    description = "One expense is much larger than the usual expense in the same category."
    default_severity = "medium"
    requires = ("expenses",)
    core_areas = ("expenses",)
    params: dict[str, Any] = {"days": 7, "min_amount": "1000.00"}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        cur = currency(session, ctx.company_id)
        rows = session.execute(text(
            f"select e.id, e.ref, e.connection_id, e.branch_id, e.amount, coalesce(e.category, '') as category, "
            f"e.description, {local_day('e.occurred_at')} as day from connect.src_expense e where e.company_id = :c "
            "and e.connection_id = any(cast(:ec as uuid[])) and e.amount >= :min "
            f"and {local_day('e.occurred_at')} >= :since order by e.occurred_at"),
            {"c": str(ctx.company_id), "ec": supply.ids("expenses"), "tz": ctx.timezone,
                "min": ctx.number("min_amount"),
             "since": ctx.today - timedelta(days=int(ctx.params["days"]))}).all()
        found = []
        for r in rows:
            amount = Decimal(r.amount)
            baseline = ctx.baseline("standalone.expense_by_category", f"{r.connection_id}:{r.category}")
            if baseline is None or not is_unusual(amount, baseline):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium",
                summary=(f"An expense of {cur} {money(amount)}{f' ({r.description})' if r.description else ''} on "
                         f"{r.day} in '{r.category or 'no category'}' is far above the usual {cur} "
                         f"{money(baseline.mean)} "
                         "for that category."),
                recommended_action="Ask who approved it and check the receipt.", company_id=ctx.company_id,
                branch_id=r.branch_id, entity_type="connect.src_expense", entity_id=r.id, period_start=r.day,
                period_end=r.day, value=amount, expected_value=baseline.mean, amount=amount - baseline.mean,
                records=(Record("connect.src_expense", r.id, f"Expense of {money(amount)} on {r.day}"),),
                figures={"amount": money(amount), "usual": money(baseline.mean)}))
        return found


class UnmatchedReceipts(StandaloneCheck):
    """Money that arrived and matches no sale or invoice."""

    code = "standalone.unmatched_receipt"
    title = "Money received that matches nothing"
    area = "books"
    description = ("Payments received (mobile money, bank) that match no sale and no invoice by code, invoice or "
                   "amount. "
                   "Needs sales or invoices connected to compare with; cash deposits are left out.")
    default_severity = "low"
    requires = ("payments",)
    core_areas = ("payments", "sales", "receivables")
    params: dict[str, Any] = {"days": 14, "grace_days": 2, "window_minutes": 120, "min_amount": "1.00"}
    auto_resolves = True

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        if not supply.has("sales") and not supply.has("invoices"):
            return []                                       # nothing to compare the money with
        last = ctx.today - timedelta(days=int(ctx.params["grace_days"]))
        sales_conns, invoice_conns = supply.ids("sales"), supply.ids("invoices")
        compared_through = [t for t in (supply.complete_until("sales") if sales_conns else None,
                                        supply.complete_until("invoices") if invoice_conns else None) if t is not None]
        until = start_of(last, ctx.timezone)
        if compared_through:
            until = min(until, min(compared_through))
        rows = session.execute(text(
            f"select p.id, p.ref, p.branch_id, p.amount, p.reference, p.party_name, {local_day('p.occurred_at')} as "
            f"day "
            "from connect.src_payment p where p.company_id = :c and p.connection_id = any(cast(:pc as uuid[])) "
            "and p.direction = 'in' and p.method <> 'cash' and p.amount >= :min and p.occurred_at >= :since "
            "and p.occurred_at < :until "
            "and not exists (select 1 from connect.src_invoice i where i.connection_id = any(cast(:ic as uuid[])) "
            "and i.kind = 'customer' and i.status <> 'cancelled' and "
            "(p.invoice_ref is not null and i.ref = p.invoice_ref or "
            "(p.reference is not null and lower(i.number) = lower(p.reference)) or "
            "i.total = p.amount or i.total - i.paid = p.amount)) "
            "and not exists (select 1 from connect.src_sale s join connect.src_sale_payment sp on sp.sale_id = s.id "
            "where s.connection_id = any(cast(:sc as uuid[])) and s.status = 'posted' and "
            "((sp.reference is not null and p.reference is not null and lower(sp.reference) = lower(p.reference)) or "
            "(sp.amount = p.amount and abs(extract(epoch from p.occurred_at - s.occurred_at)) <= :win))) "
            "order by p.occurred_at"),
            {"c": str(ctx.company_id), "pc": supply.ids("payments"), "ic": invoice_conns, "sc": sales_conns,
             "tz": ctx.timezone, "min": ctx.number("min_amount"), "win": int(ctx.params["window_minutes"]) * 60,
             "since": start_of(ctx.today - timedelta(days=int(ctx.params["days"])), ctx.timezone),
                 "until": until}).all()
        groups: dict[tuple[UUID | None, date], list[Row[Any]]] = {}
        for r in rows:
            groups.setdefault((r.branch_id, r.day), []).append(r)
        names = branch_names(session, [b for b, _ in groups])
        cur = currency(session, ctx.company_id)
        found = []
        for (branch_id, day), items in groups.items():
            total = sum((Decimal(r.amount) for r in items), ZERO)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, branch_id, day), severity="low",
                summary=(f"{len(items)} payment{'s' if len(items) != 1 else ''} received on {day}"
                         f"{'' if branch_id is None else ' at ' + where_name(names, branch_id)} worth {cur} "
                         f"{money(total)} {'match' if len(items) != 1 else 'matches'} no sale or invoice."),
                recommended_action="Find out what these payments are for and record them against the right customer.",
                company_id=ctx.company_id, branch_id=branch_id, entity_type="connect.src_payment",
                entity_id=items[0].id, period_start=day, period_end=day, value=Decimal(len(items)), amount=total,
                records=tuple(Record("connect.src_payment", r.id, f"Payment {r.reference or money(Decimal(r.amount))}")
                              for r in items)[:LIST_SIZE], figures={"payments": str(len(items)),
                                  "total": money(total)}))
        return found


# --------------------------------------------------------------------------------------------- people
class NewUsers(StandaloneCheck):
    """A new user appeared in the other system."""

    code = "standalone.new_user"
    title = "A new user in the connected system"
    area = "people"
    description = ("A user was added to the system you connected recently. Role and pay-type changes are not seen, "
                   "because the canonical record keeps only the current role.")
    default_severity = "low"
    requires = ("users",)
    params: dict[str, Any] = {"days": 14}

    def scan(self, session: Session, ctx: CheckContext, supply: Supply) -> list[Candidate]:
        rows = session.execute(text(
            f"select id, name, role, {local_day('source_created_at')} as day from connect.src_user where company_id = "
            f":c "
            "and connection_id = any(cast(:uc as uuid[])) and source_created_at is not null "
            f"and {local_day('source_created_at')} >= :since order by source_created_at"),
            {"c": str(ctx.company_id), "uc": supply.ids("users"), "tz": ctx.timezone,
             "since": ctx.today - timedelta(days=int(ctx.params["days"]))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="low",
            summary=f"{r.name} was added as a user{f' ({r.role})' if r.role else ''} on {r.day}.",
            recommended_action="Check that this person should have access.", company_id=ctx.company_id,
            entity_type="connect.src_user", entity_id=r.id, period_start=r.day, period_end=r.day,
            records=(Record("connect.src_user", r.id, r.name),), figures={"role": r.role or ""}) for r in rows]


CHECKS: tuple[type[StandaloneCheck], ...] = (
    SaleWithoutPayment, CashDepositGap, BranchSalesLow, OutOfHoursSales, LateEnteredSales, CashierVoidRate,
    CashierRefundRate, CashierDiscountRate, LargeExceptions, OverdueCustomers, SlowerPayers, CreditToOverdueCustomer,
    SupplierPriceRise, DuplicateSupplierInvoices, DuplicatePayments, StockAdjustments, ShrinkageByProduct,
    NegativeStock, ManualJournals, ExpenseFarAboveNormal, UnmatchedReceipts, NewUsers)
METRICS: tuple[type[BaselineMetric], ...] = (
    CashierVoidRateMetric, CashierRefundRateMetric, CashierDiscountRateMetric, BranchDailySalesMetric, ExpenseSamples)
