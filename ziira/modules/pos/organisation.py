"""POS's part of "kernel.branch_usage": the devices of a branch, what keeps it open (a till, documents not yet posted)
and the sales that fix a company's currency."""

from uuid import UUID

from sqlalchemy import text

from ziira.sdk import BranchUsageProvider, Session, provides


@provides("kernel.branch_usage")
class PosBranchUsage(BranchUsageProvider):
    name = "pos"

    def branch_counts(self, session: Session, branch_ids: list[UUID]) -> dict[str, dict[UUID, int]]:
        rows = session.execute(text(
            "select branch_id, count(*) as n from pos.pos_device where branch_id = any(cast(:b as uuid[])) "
            "group by branch_id"), {"b": [str(b) for b in branch_ids]})
        return {"devices": {r.branch_id: r.n for r in rows}}

    def branch_blockers(self, session: Session, branch_id: UUID) -> list[str]:
        found = session.execute(text(
            "select (select count(*) from pos.till_session where branch_id = :b and status = 'open') as tills, "
            "(select count(*) from pos.sales_document where branch_id = :b "
            "  and status in ('draft', 'pending_approval')) as documents, "
            "(select count(*) from pos.sales_invoice where branch_id = :b and status = 'draft') as invoices, "
            "(select count(*) from pos.sales_return where branch_id = :b "
            "  and status in ('draft', 'pending_approval')) as returns"), {"b": str(branch_id)}).one()
        reasons = []
        if found.tills:
            reasons.append(f"{found.tills} till{'s are' if found.tills != 1 else ' is'} still open (close "
                           f"{'them' if found.tills != 1 else 'it'} first)")
        unposted = found.documents + found.invoices + found.returns
        if unposted:
            reasons.append(f"{unposted} sales document{'s are' if unposted != 1 else ' is'} not finished (quotations, "
                           "orders, invoices or returns that are still drafts or waiting for approval)")
        return reasons

    def currency_locks(self, session: Session, company_id: UUID) -> list[str]:
        has_sales = session.execute(text(
            "select 1 from pos.sale where company_id = :c union all "
            "select 1 from pos.sales_invoice where company_id = :c and status <> 'draft' limit 1"),
            {"c": str(company_id)}).first()
        return ["sales recorded"] if has_sales else []
