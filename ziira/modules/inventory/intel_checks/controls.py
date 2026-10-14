"""Control checks: stock that disappeared by hand, shrinkage, count differences, odd-hour or back-dated stock moves."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.intel.public import (
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
from ziira.modules.inventory.intel_checks.common import MANUAL_OUT, currency, local_date, money, qty, query
from ziira.sdk import Session, provides

ADJUSTMENT_VALUE_BY_USER = "inventory.adjustment_value_by_user"
DOCUMENT_RECORD = {"stock_adjustment": "inventory.stock_adjustment", "stock_count": "inventory.stock_count",
                   "transfer": "inventory.transfer"}


def _severity(amount: Decimal, limit: Decimal) -> str:
    """High when far over the limit, medium otherwise."""
    return "high" if limit > 0 and amount >= 5 * limit else "medium"


@provides(INTEL_CHECK)
class LargeWriteDown(IntelCheck):
    """One adjustment or write-off took a large value of stock out of the books."""

    code = "inventory.large_write_down"
    title = "Large stock write-downs"
    area = "controls"
    description = "A manual stock adjustment or write-off removed stock worth more than the limit."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 14, "value_limit": "1000"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        limit = ctx.number("value_limit")
        rows = query(session, f"""
            select m.source_type, m.source_id, m.branch_id, br.name as branch_name, min(m.business_date) as day,
                   sum(-m.value) as removed, count(*) as lines,
                   coalesce(min(a.number), 'a write-off') as number, min(rc.label) as reason,
                   min(u.full_name) as user_name
            from inventory.stock_movement m
            join kernel.branch br on br.id = m.branch_id
            left join inventory.stock_adjustment a on a.id = m.source_id and m.source_type = 'stock_adjustment'
            left join kernel.reason_code rc on rc.id = m.reason_code_id
            left join kernel.app_user u on u.id = m.created_by
            where m.company_id = :company and m.business_date >= :since and m.business_date <= :today
              and {MANUAL_OUT} and m.value < 0
            group by m.source_type, m.source_id, m.branch_id, br.name
            having sum(-m.value) >= :limit
            order by sum(-m.value) desc""", company=ctx.company_id, today=ctx.today, limit=limit,
                     since=ctx.today - timedelta(days=int(ctx.params["days"])))
        out = []
        for r in rows:
            removed = r.removed.quantize(Decimal("0.01"))
            who = r.user_name or "Someone"
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.source_type, r.source_id),
                severity=_severity(removed, limit),
                summary=f"{who} took stock worth {money(removed, code)} out of {r.branch_name} on {local_date(r.day)} "
                        f"({r.number}, reason: {r.reason or 'none given'}).",
                recommended_action="Ask them to explain it and check that the stock was really lost.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type=DOCUMENT_RECORD.get(r.source_type),
                entity_id=r.source_id, period_start=r.day, period_end=r.day, value=removed, expected_value=limit,
                amount=removed,
                records=(Record(DOCUMENT_RECORD.get(r.source_type, "inventory.document"), r.source_id, r.number),),
                figures={"lines": str(r.lines), "reason": r.reason or "", "by": who, "branch": r.branch_name}))
        return out


@provides(INTEL_CHECK)
class ShrinkageRate(IntelCheck):
    """A product lost more through adjustments, write-offs and counts than a fair share of what moved."""

    code = "inventory.shrinkage_rate"
    title = "Stock lost against stock moved"
    area = "controls"
    description = ("At a branch, a product lost through adjustments, write-offs and counts is a large share of "
                   "what was sold and received.")
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30, "percent": "10.0", "min_loss_value": "100"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        percent = ctx.number("percent")
        rows = query(session, """
            select m.branch_id, br.name as branch_name, m.product_id, p.sku, p.name,
                   sum(case when m.quantity < 0 and (
                         (m.movement_type = 'adjustment' and m.source_type = 'stock_adjustment')
                         or m.movement_type in ('write_off', 'count_variance')) then -m.quantity else 0 end) as lost,
                   sum(case when m.quantity < 0 and (
                         (m.movement_type = 'adjustment' and m.source_type = 'stock_adjustment')
                         or m.movement_type in ('write_off', 'count_variance')) then -m.value else 0 end) as lost_value,
                   sum(case when m.movement_type = 'sale' then -m.quantity
                            when m.movement_type = 'receipt' then m.quantity else 0 end) as moved
            from inventory.stock_movement m
            join products.product p on p.id = m.product_id
            join kernel.branch br on br.id = m.branch_id
            where m.company_id = :company and m.branch_id is not null
              and m.business_date >= :since and m.business_date <= :today
            group by m.branch_id, br.name, m.product_id, p.sku, p.name
            having sum(case when m.quantity < 0 and m.movement_type in ('adjustment', 'write_off', 'count_variance')
                            then -m.quantity else 0 end) > 0
            order by br.name, p.name""", company=ctx.company_id,
                     since=ctx.today - timedelta(days=int(ctx.params["days"])), today=ctx.today)
        out = []
        for r in rows:
            if r.moved <= 0 or r.lost_value < ctx.number("min_loss_value"):
                continue
            share = (r.lost * 100 / r.moved).quantize(Decimal("0.1"))
            if share <= percent:
                continue
            lost_value = r.lost_value.quantize(Decimal("0.01"))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.product_id),
                severity="high" if share >= 2 * percent else "medium",
                summary=f"At {r.branch_name}, {qty(r.lost)} of {r.name} ({r.sku}), worth {money(lost_value, code)}, "
                        f"was taken out by adjustments, write-offs or counts in the last {ctx.params['days']} days: "
                        f"{share}% of the {qty(r.moved)} sold or received.",
                recommended_action="Look at the adjustments and counts for this product and ask what happened.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="products.product",
                entity_id=r.product_id, period_start=ctx.today - timedelta(days=int(ctx.params["days"])),
                period_end=ctx.today,
                value=share, expected_value=percent, amount=lost_value,
                records=(Record("products.product", r.product_id, f"{r.name} ({r.sku})"),),
                figures={"lost": qty(r.lost), "sold_or_received": qty(r.moved), "percent": str(share),
                         "branch": r.branch_name}))
        return out


@provides(INTEL_CHECK)
class CountVarianceAboveLimit(IntelCheck):
    """A posted stock count changed the books by a large value."""

    code = "inventory.count_variance"
    title = "Large stock count differences"
    area = "controls"
    description = "A stock count that was posted found stock worth more than the limit missing or extra."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30, "value_limit": "1000"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        limit = ctx.number("value_limit")
        rows = query(session, """
            select sc.id, sc.number, m.branch_id, br.name as branch_name, min(m.business_date) as day,
                   sum(abs(m.value)) as gross, sum(m.value) as net, count(*) as lines, min(u.full_name) as user_name
            from inventory.stock_movement m
            join inventory.stock_count sc on sc.id = m.source_id
            join kernel.branch br on br.id = m.branch_id
            left join kernel.app_user u on u.id = sc.created_by
            where m.company_id = :company and m.source_type = 'stock_count' and m.movement_type = 'count_variance'
              and m.business_date >= :since and m.business_date <= :today
            group by sc.id, sc.number, m.branch_id, br.name
            having sum(abs(m.value)) >= :limit
            order by sum(abs(m.value)) desc""", company=ctx.company_id,
                     since=ctx.today - timedelta(days=int(ctx.params["days"])), today=ctx.today, limit=limit)
        out = []
        for r in rows:
            gross, net = r.gross.quantize(Decimal("0.01")), r.net.quantize(Decimal("0.01"))
            direction = "short" if net < 0 else "over"
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity=_severity(gross, limit),
                summary=f"Stock count {r.number} at {r.branch_name} on {local_date(r.day)} changed the books on "
                        f"{r.lines} lines, by {money(gross, code)} in total "
                        f"({money(abs(net), code)} {direction} overall).",
                recommended_action="Review the lines with the person who counted and recount the largest ones.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="inventory.stock_count", entity_id=r.id,
                period_start=r.day, period_end=r.day, value=gross, expected_value=limit, amount=gross,
                records=(Record("inventory.stock_count", r.id, f"Stock count {r.number}"),),
                figures={"lines": str(r.lines), "net": str(net), "gross": str(gross), "counted_by": r.user_name or ""}))
        return out


@provides(INTEL_CHECK)
class UnusualStockMoves(IntelCheck):
    """Adjustments or transfers made in the middle of the night, or recorded for a day long past."""

    code = "inventory.unusual_stock_moves"
    title = "Stock moves at odd hours or back-dated"
    area = "controls"
    description = "A stock adjustment or transfer was made outside working hours or dated well before it was entered."
    default_severity = "low"
    params: dict[str, Any] = {"days": 14, "hours_from": 6, "hours_to": 21, "backdate_days": 3, "min_value": "100"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        hours_from, hours_to = int(ctx.params["hours_from"]), int(ctx.params["hours_to"])
        grace = int(ctx.params["backdate_days"])
        rows = query(session, """
            select m.source_type, m.source_id, m.branch_id, br.name as branch_name,
                   (m.created_at at time zone :tz) as entered, min(m.business_date) as dated,
                   sum(abs(m.value)) as worth, min(u.full_name) as user_name, count(*) as lines,
                   min(coalesce(a.number, t.number)) as number
            from inventory.stock_movement m
            join kernel.branch br on br.id = m.branch_id
            left join kernel.app_user u on u.id = m.created_by
            left join inventory.stock_adjustment a on a.id = m.source_id and m.source_type = 'stock_adjustment'
            left join inventory.transfer t on t.id = m.source_id and m.source_type = 'transfer'
            where m.company_id = :company and m.source_type in ('stock_adjustment', 'transfer')
              and m.branch_id is not null and m.created_at >= :since
            group by m.source_type, m.source_id, m.branch_id, br.name, m.created_at
            having sum(abs(m.value)) >= :min_value
            order by m.created_at""", company=ctx.company_id, tz=ctx.timezone,
                     since=_start_of(ctx.today - timedelta(days=int(ctx.params["days"]))),
                     min_value=ctx.number("min_value"))
        out = []
        for r in rows:
            worth = r.worth.quantize(Decimal("0.01"))
            kind = "adjustment" if r.source_type == "stock_adjustment" else "transfer"
            who = r.user_name or "Someone"
            record = (Record(DOCUMENT_RECORD[r.source_type], r.source_id, f"{kind.capitalize()} {r.number}"),)
            entered_on = r.entered.date()
            if r.entered.hour < hours_from or r.entered.hour >= hours_to:
                out.append(Candidate(
                    fingerprint=fingerprint(self.code, "hours", r.source_type, r.source_id, r.entered),
                    severity="low",
                    summary=f"{who} entered {kind} {r.number} worth {money(worth, code)} at {r.branch_name} at "
                            f"{r.entered:%H:%M} on {local_date(entered_on)}, outside the usual hours "
                            f"({hours_from:02d}:00 to {hours_to:02d}:00).",
                    recommended_action="Ask why it was done at that hour.",
                    company_id=ctx.company_id, branch_id=r.branch_id, entity_type=DOCUMENT_RECORD[r.source_type],
                    entity_id=r.source_id, period_start=entered_on, period_end=entered_on, amount=worth, records=record,
                    figures={"time": f"{r.entered:%H:%M}", "by": who, "branch": r.branch_name}))
            late = (entered_on - r.dated).days
            if late > grace:
                out.append(Candidate(
                    fingerprint=fingerprint(self.code, "backdated", r.source_type, r.source_id, r.entered),
                    severity="medium",
                    summary=f"{who} entered {kind} {r.number} worth {money(worth, code)} at {r.branch_name} on "
                            f"{local_date(entered_on)} but dated it {local_date(r.dated)}, {late} days earlier.",
                    recommended_action="Ask why it was dated back and check it against the records of that day.",
                    company_id=ctx.company_id, branch_id=r.branch_id, entity_type=DOCUMENT_RECORD[r.source_type],
                    entity_id=r.source_id, period_start=r.dated, period_end=entered_on, value=Decimal(late),
                    expected_value=Decimal(grace), amount=worth, records=record,
                    figures={"dated": local_date(r.dated), "entered": local_date(entered_on), "by": who,
                             "branch": r.branch_name}))
        return out


def _start_of(day: date) -> datetime:
    """A safe lower bound for a window starting on a local day: midnight UTC of the day before."""
    return datetime.combine(day - timedelta(days=1), time.min, tzinfo=UTC)


class AdjustmentValueByUser(BaselineMetric):
    """What each person takes out of stock by hand on a day they do it (value, in the company currency)."""

    code = ADJUSTMENT_VALUE_BY_USER
    title = "Value of stock removed by hand, per person per day"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        rows = query(session, f"""
            select m.created_by, m.business_date, sum(-m.value) as removed
            from inventory.stock_movement m
            where m.company_id = :company and m.created_by is not null and m.value < 0 and {MANUAL_OUT}
              and m.business_date >= :date_from and m.business_date < :date_to
            group by m.created_by, m.business_date""", company=company_id, date_from=date_from, date_to=date_to)
        return [Sample(str(r.created_by), r.removed) for r in rows]


@provides(INTEL_CHECK)
class AdjustmentSpike(IntelCheck):
    """Someone has taken far more stock out by hand today than they usually do."""

    code = "inventory.adjustment_spike"
    title = "Unusually large stock removals by one person"
    area = "controls"
    description = "A person has taken far more value of stock out by hand today than is normal for them."
    default_severity = "medium"
    params: dict[str, Any] = {"min_value": "500"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        rows = query(session, f"""
            select m.created_by, min(u.full_name) as user_name, sum(-m.value) as removed, count(*) as lines
            from inventory.stock_movement m
            left join kernel.app_user u on u.id = m.created_by
            where m.company_id = :company and m.created_by is not null and m.value < 0 and {MANUAL_OUT}
              and m.business_date = :today
            group by m.created_by""", company=ctx.company_id, today=ctx.today)
        out = []
        for r in rows:
            baseline = ctx.baseline(ADJUSTMENT_VALUE_BY_USER, str(r.created_by))
            if r.removed < ctx.number("min_value") or baseline is None or not is_unusual(r.removed, baseline):
                continue
            removed = r.removed.quantize(Decimal("0.01"))
            normal = baseline.mean.quantize(Decimal("0.01"))
            who = r.user_name or "Someone"
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.created_by, ctx.today), severity="medium",
                summary=f"{who} took stock worth {money(removed, code)} out by hand on {local_date(ctx.today)}; "
                        f"on days they do this it is usually about {money(normal, code)}.",
                recommended_action="Ask them what the stock was removed for.",
                company_id=ctx.company_id, entity_type="kernel.app_user", entity_id=r.created_by,
                period_start=ctx.today, period_end=ctx.today, value=removed, expected_value=normal, amount=removed,
                records=(Record("kernel.app_user", r.created_by, who),),
                figures={"lines": str(r.lines), "usual": str(normal)}))
        return out
