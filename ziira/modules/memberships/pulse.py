"""Memberships' figures for the Command Center."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, FigureKind, PulseSource
from ziira.sdk import Session, provides


@provides(COMMAND_PULSE_SOURCE)
class MembershipsPulse(PulseSource):
    """Active members, income they bring in each month, renewals and packages coming up, and invoices that failed."""

    code = "memberships"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        members = session.execute(text(
            "select branch_id, count(*) filter (where status = 'active') as active, "
            "coalesce(sum(price / (case billing_interval when 'month' then 1 when 'quarter' then 3 else 12 end)) "
            "  filter (where status = 'active'), 0) as monthly, "
            "count(*) filter (where status = 'active' and cancel_at is null and next_renewal_date between :d and :w) "
            "  as renewing "
            "from memberships.member where company_id = :c group by branch_id"),
            {"c": str(company_id), "d": day, "w": day + timedelta(days=7)}).all()
        packages = session.execute(text(
            "select branch_id, count(*) as n from memberships.sold_package where company_id = :c "
            "and status = 'active' and expires_on between :d and :m group by branch_id"),
            {"c": str(company_id), "d": day, "m": day + timedelta(days=30)}).all()
        failed = session.execute(text(
            "select branch_id, count(*) as n from memberships.invoice_run where company_id = :c "
            "and status = 'failed' group by branch_id"), {"c": str(company_id)}).all()

        late = session.execute(text(
            "select branch_id, count(*) as n from memberships.member where company_id = :c and arrears > 0 "
            "and past_due_since < :d and status in ('active', 'frozen') group by branch_id"),
            {"c": str(company_id), "d": day}).all()
        visits = session.execute(text(
            "select branch_id, count(*) as n from memberships.checkin where company_id = :c and business_date = :d "
            "and counted group by branch_id"), {"c": str(company_id), "d": day}).all()

        def build(metric: str, label: str, kind: FigureKind, rows: Sequence[Row[Any]], column: str,
                  better: bool | None) -> list[Figure]:
            total = sum((Decimal(getattr(r, column)) for r in rows), Decimal(0))
            made = [Figure(metric, label, kind, total, None, better)]
            made += [Figure(metric, label, kind, Decimal(getattr(r, column)), r.branch_id, better) for r in rows
                     if r.branch_id is not None]
            return made

        return [
            *build("memberships.active_members", "Active members", "count", members, "active", True),
            *build("memberships.monthly_income", "Membership income per month", "money", members, "monthly", True),
            *build("memberships.renewals_due_7_days", "Renewals in the next 7 days", "count", members, "renewing",
                   None),
            *build("memberships.packages_expiring_30_days", "Packages expiring in 30 days", "count", packages, "n",
                   None),
            *build("memberships.failed_recurring_invoices", "Recurring invoices that failed", "count", failed, "n",
                   False),
            *build("memberships.members_late", "Members who owe fees", "count", late, "n", False),
            *build("memberships.visits_today", "Visits today", "count", visits, "n", True),
        ]
