"""Stock-level checks: out of stock, low, negative, expiring and expired batches, slow stock, transfers not received."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.modules.inventory.intel_checks.common import ON_HAND_CTE, currency, local_date, money, qty, query
from ziira.sdk import Session, provides

PRODUCT = "products.product"


@provides(INTEL_CHECK)
class OutOfStock(IntelCheck):
    """A product that is sold here, or has a reorder level, has none left at a branch."""

    code = "inventory.out_of_stock"
    title = "Products out of stock"
    area = "stock"
    description = "A product you normally stock or sell at a branch has run out there."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 60}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.params["days"]))
        rows = query(session, f"""
            with active as (
              select m.branch_id, m.product_id, bool_or(m.movement_type = 'sale') as sold,
                     max(m.business_date) as last_seen
              from inventory.stock_movement m
              where m.company_id = :company and m.branch_id is not null
                and m.business_date >= :since and m.business_date <= :today
              group by m.branch_id, m.product_id),
            {ON_HAND_CTE}
            select a.branch_id, br.name as branch_name, a.product_id, p.sku, p.name, p.reorder_level, a.last_seen
            from active a
            join products.product p on p.id = a.product_id
            join kernel.branch br on br.id = a.branch_id
            left join onhand o on o.branch_id = a.branch_id and o.product_id = a.product_id
            where p.is_active and p.product_type = 'stock' and coalesce(o.qty, 0) = 0
              and (a.sold or coalesce(p.reorder_level, 0) > 0)
            order by br.name, p.name""", company=ctx.company_id, since=since, today=ctx.today)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.branch_id, r.product_id), severity="medium",
            summary=f"{r.name} ({r.sku}) is out of stock at {r.branch_name}; it last moved there on "
                    f"{local_date(r.last_seen)}.",
            recommended_action="Reorder it or move stock in from another branch.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type=PRODUCT, entity_id=r.product_id,
            period_start=r.last_seen, value=Decimal(0),
            expected_value=r.reorder_level if r.reorder_level else None,
            records=(Record(PRODUCT, r.product_id, f"{r.name} ({r.sku})"),),
            figures={"on_hand": "0", "branch": r.branch_name}) for r in rows]


@provides(INTEL_CHECK)
class LowStock(IntelCheck):
    """A product is at or under the reorder level set for it."""

    code = "inventory.low_stock"
    title = "Products below their reorder level"
    area = "stock"
    description = "A product's stock at a branch has fallen to its reorder level or under."
    default_severity = "low"
    params: dict[str, Any] = {}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = query(session, f"""
            with {ON_HAND_CTE}
            select o.branch_id, br.name as branch_name, o.product_id, p.sku, p.name, p.reorder_level, o.qty
            from onhand o
            join products.product p on p.id = o.product_id
            join kernel.branch br on br.id = o.branch_id
            where p.is_active and p.product_type = 'stock' and p.reorder_level > 0
              and o.qty > 0 and o.qty <= p.reorder_level
            order by br.name, p.name""", company=ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.branch_id, r.product_id), severity="low",
            summary=f"{r.name} ({r.sku}) is down to {qty(r.qty)} at {r.branch_name}; "
                    f"its reorder level is {qty(r.reorder_level)}.",
            recommended_action="Reorder it before it runs out.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type=PRODUCT, entity_id=r.product_id,
            value=r.qty, expected_value=r.reorder_level,
            records=(Record(PRODUCT, r.product_id, f"{r.name} ({r.sku})"),),
            figures={"on_hand": qty(r.qty), "reorder_level": qty(r.reorder_level), "branch": r.branch_name})
            for r in rows]


@provides(INTEL_CHECK)
class NegativeStock(IntelCheck):
    """The books say a branch holds less than nothing of a product."""

    code = "inventory.negative_stock"
    title = "Negative stock"
    area = "stock"
    description = "A branch shows less than zero of a product, so a delivery or a transfer was probably not recorded."
    default_severity = "medium"
    params: dict[str, Any] = {}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        rows = query(session, f"""
            with {ON_HAND_CTE}
            select o.branch_id, br.name as branch_name, o.product_id, p.sku, p.name, o.qty,
                   coalesce(pc.average_cost, 0) as cost
            from onhand o
            join products.product p on p.id = o.product_id
            join kernel.branch br on br.id = o.branch_id
            left join inventory.product_cost pc on pc.company_id = :company and pc.product_id = o.product_id
            where p.product_type = 'stock' and o.qty < 0
            order by br.name, p.name""", company=ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.branch_id, r.product_id), severity="medium",
            summary=f"{r.name} ({r.sku}) shows {qty(r.qty)} at {r.branch_name}, less than none; "
                    f"that is about {money(-r.qty * r.cost, code)} sold or moved without being recorded as received.",
            recommended_action="Find the missing receipt or transfer and record it, or count the stock.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type=PRODUCT, entity_id=r.product_id,
            value=r.qty, expected_value=Decimal(0), amount=(-r.qty * r.cost).quantize(Decimal("0.01")),
            records=(Record(PRODUCT, r.product_id, f"{r.name} ({r.sku})"),),
            figures={"on_hand": qty(r.qty), "branch": r.branch_name}) for r in rows]


def _expiry_rows(session: Session, ctx: CheckContext, low: date, high: date) -> list[Any]:
    return query(session, """
        select l.branch_id, br.name as branch_name, ba.id as batch_id, ba.batch_no, ba.expiry_date, ba.product_id,
               p.sku, p.name, sum(b.quantity) as qty, coalesce(pc.average_cost, 0) as cost
        from inventory.batch ba
        join inventory.stock_balance b on b.batch_id = ba.id
        join inventory.location l on l.id = b.location_id
        join kernel.branch br on br.id = l.branch_id
        join products.product p on p.id = ba.product_id
        left join inventory.product_cost pc on pc.company_id = :company and pc.product_id = ba.product_id
        where l.company_id = :company and l.kind in ('store', 'warehouse') and l.branch_id is not null
          and ba.expiry_date >= :low and ba.expiry_date <= :high
        group by l.branch_id, br.name, ba.id, ba.batch_no, ba.expiry_date, ba.product_id, p.sku, p.name, pc.average_cost
        having sum(b.quantity) > 0
        order by ba.expiry_date, p.name""", company=ctx.company_id, low=low, high=high)


@provides(INTEL_CHECK)
class BatchExpiringSoon(IntelCheck):
    """A batch still on the shelf expires within the next few weeks."""

    code = "inventory.batch_expiring"
    title = "Batches expiring soon"
    area = "stock"
    description = "A batch with stock still on hand will expire within the next few weeks."
    default_severity = "medium"
    params: dict[str, Any] = {"days_ahead": 30, "urgent_days": 7}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        urgent = int(ctx.params["urgent_days"])
        out = []
        for r in _expiry_rows(session, ctx, ctx.today, ctx.today + timedelta(days=int(ctx.params["days_ahead"]))):
            left = (r.expiry_date - ctx.today).days
            worth = (r.qty * r.cost).quantize(Decimal("0.01"))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.batch_id),
                severity="high" if left <= urgent else "medium",
                summary=f"Batch {r.batch_no} of {r.name} ({r.sku}) expires on {local_date(r.expiry_date)} "
                        f"({left} days); {qty(r.qty)} is still at {r.branch_name}, worth about {money(worth, code)}.",
                recommended_action="Sell it first, discount it, or return it to the supplier before it expires.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="inventory.batch", entity_id=r.batch_id,
                period_end=r.expiry_date, value=r.qty, amount=worth,
                records=(Record("inventory.batch", r.batch_id, f"Batch {r.batch_no}"),
                         Record(PRODUCT, r.product_id, f"{r.name} ({r.sku})")),
                figures={"days_left": str(left), "on_hand": qty(r.qty), "branch": r.branch_name}))
        return out


@provides(INTEL_CHECK)
class ExpiredStock(IntelCheck):
    """A batch that has already expired is still counted as stock."""

    code = "inventory.batch_expired"
    title = "Expired stock on hand"
    area = "stock"
    description = "A batch past its expiry date is still held as stock."
    default_severity = "high"
    params: dict[str, Any] = {"days_back": 365}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        out = []
        rows = _expiry_rows(session, ctx, ctx.today - timedelta(days=int(ctx.params["days_back"])),
                            ctx.today - timedelta(days=1))
        for r in rows:
            worth = (r.qty * r.cost).quantize(Decimal("0.01"))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.batch_id), severity="high",
                summary=f"Batch {r.batch_no} of {r.name} ({r.sku}) expired on {local_date(r.expiry_date)}; "
                        f"{qty(r.qty)} is still held at {r.branch_name}, worth about {money(worth, code)}.",
                recommended_action="Take it off the shelf and write it off with the reason 'expired'.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="inventory.batch", entity_id=r.batch_id,
                period_end=r.expiry_date, value=r.qty, amount=worth,
                records=(Record("inventory.batch", r.batch_id, f"Batch {r.batch_no}"),
                         Record(PRODUCT, r.product_id, f"{r.name} ({r.sku})")),
                figures={"expired_on": local_date(r.expiry_date), "on_hand": qty(r.qty), "branch": r.branch_name}))
        return out


@provides(INTEL_CHECK)
class SlowStock(IntelCheck):
    """Money tied up in stock that has not gone out for a long time."""

    code = "inventory.slow_stock"
    title = "Slow or dead stock"
    area = "stock"
    description = "A branch holds stock of real value that has not been sold or moved out for months."
    default_severity = "low"
    params: dict[str, Any] = {"days": 90, "min_value": "1000"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        days = int(ctx.params["days"])
        cutoff = ctx.today - timedelta(days=days)
        rows = query(session, f"""
            with {ON_HAND_CTE},
            held as (
              select o.branch_id, o.product_id, o.qty, o.qty * coalesce(pc.average_cost, 0) as worth
              from onhand o
              left join inventory.product_cost pc on pc.company_id = :company and pc.product_id = o.product_id
              where o.qty > 0 and o.qty * coalesce(pc.average_cost, 0) >= :min_value)
            select h.branch_id, br.name as branch_name, h.product_id, p.sku, p.name, h.qty, h.worth,
                   (select max(m.business_date) from inventory.stock_movement m
                      join inventory.location l on l.id = m.location_id
                     where l.branch_id = h.branch_id and m.product_id = h.product_id
                       and m.movement_type in ('sale', 'transfer_out', 'purchase_return')) as last_out,
                   (select min(m.business_date) from inventory.stock_movement m
                      join inventory.location l on l.id = m.location_id
                     where l.branch_id = h.branch_id and m.product_id = h.product_id) as first_seen
            from held h
            join products.product p on p.id = h.product_id
            join kernel.branch br on br.id = h.branch_id
            where p.is_active and p.product_type = 'stock'
            order by h.worth desc""", company=ctx.company_id, min_value=ctx.number("min_value"))
        out = []
        for r in rows:
            if r.first_seen is None or r.first_seen > cutoff or (r.last_out is not None and r.last_out >= cutoff):
                continue
            since = r.last_out or r.first_seen
            worth = r.worth.quantize(Decimal("0.01"))
            story = (f"nothing has gone out since {local_date(r.last_out)}" if r.last_out
                     else f"none has gone out since it arrived on {local_date(r.first_seen)}")
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, r.product_id), severity="low",
                summary=f"{qty(r.qty)} of {r.name} ({r.sku}) at {r.branch_name}, worth {money(worth, code)}: {story}.",
                recommended_action="Discount it, move it to a branch where it sells, or stop reordering it.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type=PRODUCT, entity_id=r.product_id,
                period_start=since, period_end=ctx.today, value=r.qty, amount=worth,
                records=(Record(PRODUCT, r.product_id, f"{r.name} ({r.sku})"),),
                figures={"on_hand": qty(r.qty), "days_without_outflow": str((ctx.today - since).days),
                         "branch": r.branch_name}))
        return out


@provides(INTEL_CHECK)
class TransferNotReceived(IntelCheck):
    """Stock was sent to another location and nobody has booked it in."""

    code = "inventory.transfer_not_received"
    title = "Transfers not received"
    area = "stock"
    description = "Stock sent between branches has been on the road for days without being received."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 3}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        code = currency(session, ctx.company_id)
        days = int(ctx.params["days"])
        rows = query(session, """
            select t.id, t.number, (t.dispatched_at at time zone :tz)::date as sent_on,
                   src.name as from_name, dst.name as to_name, dst.branch_id as to_branch,
                   coalesce(sum(tl.qty_sent * coalesce(pc.average_cost, 0)), 0) as worth, count(tl.id) as lines
            from inventory.transfer t
            join inventory.location src on src.id = t.from_location_id
            join inventory.location dst on dst.id = t.to_location_id
            join inventory.transfer_line tl on tl.transfer_id = t.id
            left join inventory.product_cost pc on pc.company_id = t.company_id and pc.product_id = tl.product_id
            where t.company_id = :company and t.status = 'dispatched'
              and (t.dispatched_at at time zone :tz)::date <= :limit
            group by t.id, t.number, t.dispatched_at, src.name, dst.name, dst.branch_id
            order by t.dispatched_at""", company=ctx.company_id, tz=ctx.timezone,
                     limit=ctx.today - timedelta(days=days))
        out = []
        for r in rows:
            waiting = (ctx.today - r.sent_on).days
            worth = r.worth.quantize(Decimal("0.01"))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="high" if waiting >= 3 * days else "medium",
                summary=f"Transfer {r.number} from {r.from_name} to {r.to_name} was sent on {local_date(r.sent_on)} "
                        f"and has not been received after {waiting} days; it carries about "
                        f"{money(worth, code)} of stock.",
                recommended_action="Ask the receiving branch to check it in, or find out where the stock is.",
                company_id=ctx.company_id, branch_id=r.to_branch, entity_type="inventory.transfer", entity_id=r.id,
                period_start=r.sent_on, period_end=ctx.today, value=Decimal(waiting), expected_value=Decimal(days),
                amount=worth, records=(Record("inventory.transfer", r.id, f"Transfer {r.number}"),),
                figures={"days_waiting": str(waiting), "lines": str(r.lines)}))
        return out
