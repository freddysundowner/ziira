"""Payments figures for the Command Center: what came in, by which route, what is unexplained, and failed prompts."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import Figure, PulseSource
from ziira.sdk import Session, company_setting


class PaymentsPulse(PulseSource):
    """Money received on the day (all branches and per branch), by method, unlinked receipts and failed prompts."""

    code = "payments.pulse"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        """Company-wide figures plus one set per active branch."""
        tz = str(company_setting(session, company_id, "timezone"))
        branches = [r[0] for r in session.execute(
            text("select id from kernel.branch where company_id = :c and is_active"), {"c": company_id}).all()]
        received = session.execute(text("""
            select p.branch_id, p.method, count(*) filter (where p.party_id is null and not exists
                       (select 1 from payments.payment_allocation x where x.payment_id = p.id)) as unlinked_n,
                   coalesce(sum(p.amount), 0) as total,
                   coalesce(sum(p.amount) filter (where p.party_id is null and not exists
                       (select 1 from payments.payment_allocation x where x.payment_id = p.id)), 0) as unlinked
              from payments.payment p
             where p.company_id = :c and p.direction = 'in' and p.status = 'posted' and p.business_date = :d
               and not exists (select 1 from payments.payment_allocation x
                                where x.payment_id = p.id and x.doc_type in ('settlement', 'cash_deposit'))
             group by p.branch_id, p.method"""), {"c": company_id, "d": day}).all()
        failed = session.execute(text("""
            select branch_id, count(*) as n from payments.payment_intent
             where company_id = :c and status in ('failed', 'timeout') and (created_at at time zone :tz)::date = :d
             group by branch_id"""), {"c": company_id, "tz": tz, "d": day}).all()

        def build(branch: UUID | None) -> list[Figure]:
            rows = [r for r in received if branch is None or r.branch_id == branch]
            fails = sum((r.n for r in failed if branch is None or r.branch_id == branch), 0)
            by = {m: sum((r.total for r in rows if r.method == m), Decimal(0)) for m in ("mobile_money", "bank")}
            return [
                Figure("payments.received", "Payments received", "money", sum((r.total for r in rows), Decimal(0)),
                       branch, True),
                Figure("payments.received_mobile_money", "Received by mobile money", "money", by["mobile_money"],
                       branch, True),
                Figure("payments.received_bank", "Received by bank", "money", by["bank"], branch, True),
                Figure("payments.unmatched_amount", "Received but not linked to a sale or customer", "money",
                       sum((r.unlinked for r in rows), Decimal(0)), branch, False),
                Figure("payments.unmatched_count", "Payments not linked to a sale or customer", "count",
                       Decimal(sum((r.unlinked_n for r in rows), 0)), branch, False),
                Figure("payments.failed_prompts", "Failed payment prompts", "count", Decimal(fails), branch, False)]

        figures = build(None)
        for branch in branches:
            figures.extend(build(branch))
        return figures
