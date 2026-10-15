"""Figures for the Command Center from the connected systems: the day's sales, money received, what customers owe past
due, expenses and stock adjustments, read from `connect.src_*`. Only the figures of entities that are connected
appear."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import Figure, PulseSource
from ziira.modules.connect.services.coverage import supplied
from ziira.sdk import Session, company_setting

ZERO = Decimal(0)


class ConnectPulse(PulseSource):
    """Company-wide figures (and per mapped branch for sales, expenses and adjustments)."""

    code = "connect.pulse"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        supply = supplied(session, company_id)
        zone = str(company_setting(session, company_id, "timezone"))
        out: list[Figure] = []

        def by_branch(sql: str, entity: str) -> dict[UUID | None, tuple[Decimal, ...]]:
            rows = session.execute(text(sql), {"c": str(company_id), "d": day, "tz": zone, "ids": supply.ids(entity)})
            return {r[0]: tuple(Decimal(v) for v in r[1:]) for r in rows}

        def spread(rows: dict[UUID | None, tuple[Decimal, ...]], index: int, branch: UUID | None) -> Decimal:
            if branch is None:
                return sum((v[index] for v in rows.values()), ZERO)
            return rows[branch][index] if branch in rows else ZERO

        day_of = "((occurred_at) at time zone :tz)::date"
        if supply.has("sales"):
            sales = by_branch(
                "select branch_id, coalesce(sum(total) filter (where status = 'posted'), 0), "
                f"count(*) filter (where status = 'posted') from connect.src_sale where company_id = :c and {day_of} "
                f"= :d "
                "and connection_id = any(cast(:ids as uuid[])) group by branch_id", "sales")
            for branch in [None, *[b for b in sales if b is not None]]:
                out += [Figure("connect.sales_total", "Sales", "money", spread(sales, 0, branch), branch, True),
                        Figure("connect.sales_count", "Number of sales", "count", spread(sales, 1, branch), branch,
                            True)]
        if supply.has("payments"):
            received = by_branch(
                "select null::uuid, coalesce(sum(amount), 0) from connect.src_payment where company_id = :c "
                f"and direction = 'in' and {day_of} = :d and connection_id = any(cast(:ids as uuid[]))", "payments")
            out.append(Figure("connect.payments_received", "Payments received", "money", spread(received, 0, None),
                              None, True))
        if supply.has("invoices"):
            overdue = by_branch(
                "select null::uuid, coalesce(sum(total - paid), 0) from connect.src_invoice where company_id = :c "
                "and kind = 'customer' and status = 'open' and due_date < :d "
                "and connection_id = any(cast(:ids as uuid[]))", "invoices")
            out.append(Figure("connect.overdue_receivables", "Overdue customer balances", "money",
                              spread(overdue, 0, None), None, False))
        if supply.has("expenses"):
            expenses = by_branch(
                f"select branch_id, coalesce(sum(amount), 0) from connect.src_expense where company_id = :c and "
                f"{day_of} = :d "
                "and connection_id = any(cast(:ids as uuid[])) group by branch_id", "expenses")
            for branch in [None, *[b for b in expenses if b is not None]]:
                out.append(Figure("connect.expenses_total", "Expenses", "money", spread(expenses, 0, branch), branch,
                    False))
        if supply.has("stock_movements"):
            adjustments = by_branch(
                f"select branch_id, count(*) from connect.src_stock_movement where company_id = :c and {day_of} = :d "
                "and kind in ('adjustment', 'count') and connection_id = any(cast(:ids as uuid[])) group by branch_id",
                "stock_movements")
            for branch in [None, *[b for b in adjustments if b is not None]]:
                out.append(Figure("connect.stock_adjustments", "Stock adjustments", "count",
                                  spread(adjustments, 0, branch), branch, None))
        return out
