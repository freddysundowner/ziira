"""POS's figures for the Command Center: the day's sales, voids, returns, till differences and what customers owe."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import Figure, PulseSource
from ziira.sdk import Session

ZERO = Decimal(0)


class PosPulse(PulseSource):
    """Company-wide and per-branch figures from sales, returns, tills and invoices."""

    code = "pos.pulse"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        """Sales total, count and average, voids, refunds, till differences, overdue receivables and open tills."""
        c = {"c": str(company_id), "d": day}
        branches: list[UUID] = [r.branch_id for r in session.execute(text(
            "select distinct branch_id from pos.pos_device d join kernel.branch b on b.id = d.branch_id "
            "where b.company_id = :c"), c)]
        sales = _by_branch(session, """
            select branch_id, coalesce(sum(total) filter (where status = 'posted'), 0),
                   count(*) filter (where status = 'posted'), count(*) filter (where status = 'voided')
            from pos.sale where company_id = :c and business_date = :d group by branch_id""", c)
        refunds = _by_branch(session, """
            select branch_id, coalesce(sum(total), 0) from pos.sales_return where company_id = :c
              and status = 'posted' and coalesce(business_date, created_at::date) = :d group by branch_id""", c)
        variance = _by_branch(session, """
            select t.branch_id, coalesce(sum(t.variance), 0) from pos.till_session t
            join kernel.branch b on b.id = t.branch_id where b.company_id = :c and t.status = 'closed'
              and t.business_date = :d group by t.branch_id""", c)
        overdue = _by_branch(session, """
            select branch_id, coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice
            where company_id = :c and status in ('issued', 'part_paid') and due_date < :d group by branch_id""", c)
        open_tills = _by_branch(session, """
            select t.branch_id, count(*) from pos.till_session t join kernel.branch b on b.id = t.branch_id
            where b.company_id = :c and t.status = 'open' and t.business_date <= :d group by t.branch_id""", c)
        out: list[Figure] = []
        for branch in [None, *branches]:
            total, count, voids = (_pick(sales, i, branch) for i in range(3))
            out += [
                Figure("pos.sales_total", "Sales", "money", total, branch, True),
                Figure("pos.sales_count", "Number of sales", "count", count, branch, True),
                Figure("pos.average_sale", "Average sale", "money", total / count if count else ZERO, branch, True),
                Figure("pos.voids_count", "Voided sales", "count", voids, branch, False),
                Figure("pos.refunds_amount", "Refunds", "money", _pick(refunds, 0, branch), branch, False),
                Figure("pos.till_variance", "Cash difference of closed tills", "money", _pick(variance, 0, branch),
                       branch, None),
                Figure("pos.overdue_receivables", "Overdue customer balances", "money",
                       _pick(overdue, 0, branch), branch, False),
                Figure("pos.open_tills", "Tills open", "count", _pick(open_tills, 0, branch), branch, None),
            ]
        return out


def _by_branch(session: Session, sql: str, params: dict[str, object]) -> dict[UUID | None, tuple[Decimal, ...]]:
    return {r[0]: tuple(Decimal(v) for v in r[1:]) for r in session.execute(text(sql), params)}


def _pick(rows: dict[UUID | None, tuple[Decimal, ...]], index: int, branch: UUID | None) -> Decimal:
    """One branch's value, or (branch None) the company-wide sum over every branch and unassigned records."""
    if branch is None:
        return sum((values[index] for values in rows.values()), ZERO)
    return rows[branch][index] if branch in rows else ZERO
