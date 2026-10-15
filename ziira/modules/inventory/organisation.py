"""Inventory's part of "kernel.branch_usage": the locations of a branch, what keeps it open (stock in transit, counts
and documents not yet posted) and the stock movements that fix a company's currency."""

from uuid import UUID

from sqlalchemy import text

from ziira.sdk import BranchUsageProvider, Session, provides


@provides("kernel.branch_usage")
class InventoryBranchUsage(BranchUsageProvider):
    name = "inventory"

    def branch_counts(self, session: Session, branch_ids: list[UUID]) -> dict[str, dict[UUID, int]]:
        rows = session.execute(text(
            "select branch_id, count(*) as n from inventory.location where branch_id = any(cast(:b as uuid[])) "
            "and is_active group by branch_id"), {"b": [str(b) for b in branch_ids]})
        return {"locations": {r.branch_id: r.n for r in rows}}

    def branch_blockers(self, session: Session, branch_id: UUID) -> list[str]:
        found = session.execute(text(
            "with here as (select id from inventory.location where branch_id = :b) "
            "select (select count(*) from inventory.transfer where status = 'dispatched' "
            "  and (from_location_id in (select id from here) or to_location_id in (select id from here))) as moving, "
            "(select count(*) from inventory.transfer where status in ('draft', 'pending_approval') "
            "  and (from_location_id in (select id from here) or to_location_id in (select id from here))) as drafts, "
            "(select count(*) from inventory.stock_adjustment where status in ('draft', 'pending_approval') "
            "  and location_id in (select id from here)) as adjustments, "
            "(select count(*) from inventory.stock_count where status in ('counting', 'review', 'pending_approval') "
            "  and location_id in (select id from here)) as counts"), {"b": str(branch_id)}).one()
        reasons = []
        if found.moving:
            reasons.append(f"{found.moving} stock transfer{'s are' if found.moving != 1 else ' is'} in transit "
                           "(receive or cancel them first)")
        unposted = found.drafts + found.adjustments
        if unposted:
            reasons.append(f"{unposted} stock transfer or adjustment{'s are' if unposted != 1 else ' is'} "
                           "not posted yet")
        if found.counts:
            reasons.append(f"{found.counts} stock count{'s are' if found.counts != 1 else ' is'} not finished")
        return reasons

    def currency_locks(self, session: Session, company_id: UUID) -> list[str]:
        has_stock = session.execute(text("select 1 from inventory.stock_movement where company_id = :c limit 1"),
                                    {"c": str(company_id)}).first()
        return ["stock movements recorded"] if has_stock else []
