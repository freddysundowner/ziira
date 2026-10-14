"""Purchasing's figures for the Command Center."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.command.public import Figure, FigureKind, PulseSource
from ziira.sdk import Session, company_setting


class PurchasingPulse(PulseSource):
    """What is owed to suppliers, what falls due, what arrived today and which orders are open."""

    code = "purchasing"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        tz = str(company_setting(session, company_id, "timezone"))
        bills = session.execute(text(
            "select branch_id, "
            "coalesce(sum(total - amount_paid - credited), 0) as owed, "
            "coalesce(sum(total - amount_paid - credited) filter "
            "(where due_date >= :day and due_date <= :soon), 0) as soon, "
            "coalesce(sum(total - amount_paid - credited) filter (where due_date < :day), 0) as overdue "
            "from purchasing.supplier_bill where company_id = :c and status in ('posted', 'part_paid') "
            "group by branch_id"), {"c": company_id, "day": day, "soon": day + timedelta(days=7)}).all()
        received = session.execute(text(
            "select r.branch_id, coalesce(sum(l.quantity * l.unit_cost), 0) as value "
            "from purchasing.goods_receipt r join purchasing.goods_receipt_line l on l.receipt_id = r.id "
            "where r.company_id = :c and r.status = 'posted' and (r.received_at at time zone :tz)::date = :day "
            "group by r.branch_id"), {"c": company_id, "tz": tz, "day": day}).all()
        orders = session.execute(text(
            "select branch_id, count(*) as n from purchasing.purchase_order where company_id = :c "
            "and status in ('approved', 'sent', 'part_received') group by branch_id"), {"c": company_id}).all()

        def build(metric: str, label: str, kind: FigureKind, rows: Sequence[Row[Any]], column: str,
                  better: bool | None) -> list[Figure]:
            per_branch = {r.branch_id: Decimal(getattr(r, column)) for r in rows if r.branch_id is not None}
            total = sum((Decimal(getattr(r, column)) for r in rows), Decimal(0))
            made = [Figure(metric, label, kind, total, None, better)]
            made += [Figure(metric, label, kind, v, b, better) for b, v in per_branch.items()]
            return made

        return [
            *build("purchasing.payables_outstanding", "Owed to suppliers", "money", bills, "owed", False),
            *build("purchasing.bills_due_7_days", "Bills due in 7 days", "money", bills, "soon", None),
            *build("purchasing.bills_overdue", "Overdue supplier bills", "money", bills, "overdue", False),
            *build("purchasing.goods_received_value", "Goods received", "money", received, "value", None),
            *build("purchasing.open_purchase_orders", "Open purchase orders", "count", orders, "n", None),
        ]
