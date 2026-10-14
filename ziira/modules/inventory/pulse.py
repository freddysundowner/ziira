"""Inventory's figures for the Command Center: what stock is worth, what is running out, what was adjusted."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, PulseSource
from ziira.modules.inventory.intel_checks.common import ON_HAND_CTE, query
from ziira.sdk import Session, provides

SALES_LOOKBACK_DAYS = 60


@provides(COMMAND_PULSE_SOURCE)
class InventoryPulse(PulseSource):
    """Stock value, products low or out, adjustments of the day, transfers on the road."""

    code = "inventory.pulse"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        branches = [r.branch_id for r in query(session, """
            select distinct branch_id from inventory.location
            where company_id = :company and kind in ('store', 'warehouse') and branch_id is not null
            order by branch_id""", company=company_id)]
        value = self._stock_value(session, company_id, branches)
        low = self._product_counts(session, company_id, branches, "o.qty > 0 and o.qty <= p.reorder_level "
                                   "and p.reorder_level > 0")
        negative = self._product_counts(session, company_id, branches, "o.qty < 0")
        out = self._out_of_stock(session, company_id, branches, day)
        adjusted = self._adjustments(session, company_id, branches, day)
        transit = self._in_transit(session, company_id, branches)
        figures: list[Figure] = []
        for scope in [None, *branches]:
            figures += [
                Figure("inventory.stock_value", "Stock value", "money", value[scope], scope, None),
                Figure("inventory.below_reorder", "Products below reorder level", "count", Decimal(low[scope]), scope,
                       False),
                Figure("inventory.out_of_stock", "Products out of stock", "count", Decimal(out[scope]), scope, False),
                Figure("inventory.negative_stock", "Products with negative stock", "count", Decimal(negative[scope]),
                       scope, False),
                Figure("inventory.adjustments_value", "Value of stock adjustments", "money", adjusted[scope], scope,
                       False),
                Figure("inventory.transfers_in_transit", "Transfers in transit", "count", Decimal(transit[scope]),
                       scope, None),
            ]
        return figures

    @staticmethod
    def _stock_value(session: Session, company_id: UUID, branches: list[UUID]) -> dict[UUID | None, Decimal]:
        """Stock worth: the company figure is the ledger's (with stock in transit), a branch's is what it holds."""
        total = query(session, "select coalesce(sum(value), 0) as v from inventory.product_cost where company_id = :c",
                      c=company_id)[0].v
        rows = query(session, f"""
            with {ON_HAND_CTE}
            select o.branch_id, sum(o.qty * coalesce(pc.average_cost, 0)) as v
            from onhand o
            left join inventory.product_cost pc on pc.company_id = :company and pc.product_id = o.product_id
            group by o.branch_id""", company=company_id)
        by_branch = {r.branch_id: Decimal(r.v).quantize(Decimal("0.01")) for r in rows}
        return {None: Decimal(total), **{b: by_branch.get(b, Decimal(0)) for b in branches}}

    @staticmethod
    def _product_counts(session: Session, company_id: UUID, branches: list[UUID],
                        condition: str) -> dict[UUID | None, int]:
        """How many products meet a condition on their on-hand figure (a product counts once company-wide)."""
        rows = query(session, f"""
            with {ON_HAND_CTE}
            select o.branch_id, o.product_id
            from onhand o join products.product p on p.id = o.product_id
            where p.is_active and p.product_type = 'stock' and {condition}""", company=company_id)
        return _counts(rows, branches)

    @staticmethod
    def _out_of_stock(session: Session, company_id: UUID, branches: list[UUID], day: date) -> dict[UUID | None, int]:
        """Products sold (or given a reorder level) at a branch recently that have none there now."""
        rows = query(session, f"""
            with active as (
              select m.branch_id, m.product_id, bool_or(m.movement_type = 'sale') as sold
              from inventory.stock_movement m
              where m.company_id = :company and m.branch_id is not null
                and m.business_date >= :since and m.business_date <= :day
              group by m.branch_id, m.product_id),
            {ON_HAND_CTE}
            select a.branch_id, a.product_id
            from active a join products.product p on p.id = a.product_id
            left join onhand o on o.branch_id = a.branch_id and o.product_id = a.product_id
            where p.is_active and p.product_type = 'stock' and coalesce(o.qty, 0) = 0
              and (a.sold or coalesce(p.reorder_level, 0) > 0)""", company=company_id, day=day,
                     since=day - timedelta(days=SALES_LOOKBACK_DAYS))
        return _counts(rows, branches)

    @staticmethod
    def _adjustments(session: Session, company_id: UUID, branches: list[UUID], day: date) -> dict[UUID | None, Decimal]:
        """The value moved by hand in the day (adjustments, write-offs and count differences), in either direction."""
        rows = query(session, """
            select m.branch_id, sum(abs(m.value)) as v
            from inventory.stock_movement m
            where m.company_id = :company and m.business_date = :day
              and m.movement_type in ('adjustment', 'write_off', 'count_variance')
              and (m.movement_type <> 'adjustment' or m.source_type = 'stock_adjustment')
            group by m.branch_id""", company=company_id, day=day)
        by_branch = {r.branch_id: Decimal(r.v) for r in rows}
        return {None: sum(by_branch.values(), Decimal(0)), **{b: by_branch.get(b, Decimal(0)) for b in branches}}

    @staticmethod
    def _in_transit(session: Session, company_id: UUID, branches: list[UUID]) -> dict[UUID | None, int]:
        """Transfers sent and not yet received, counted at the branch they are going to."""
        rows = query(session, """
            select dst.branch_id, count(*) as n
            from inventory.transfer t join inventory.location dst on dst.id = t.to_location_id
            where t.company_id = :company and t.status = 'dispatched'
            group by dst.branch_id""", company=company_id)
        by_branch = {r.branch_id: int(r.n) for r in rows}
        return {None: sum(by_branch.values()), **{b: by_branch.get(b, 0) for b in branches}}


def _counts(rows: list[Row[Any]], branches: list[UUID]) -> dict[UUID | None, int]:
    """Per branch the number of products, and company-wide the number of different products."""
    per_branch: dict[UUID, set[UUID]] = {b: set() for b in branches}
    for r in rows:
        per_branch.setdefault(r.branch_id, set()).add(r.product_id)
    everything: set[UUID] = set().union(*per_branch.values()) if per_branch else set()
    return {None: len(everything), **{b: len(per_branch[b]) for b in branches}}
