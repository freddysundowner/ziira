"""People's figures for the Command Center: headcount, leave waiting, overtime this month, payroll runs not yet paid."""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, FigureKind, PulseSource
from ziira.sdk import Session, provides


def _with_branches(metric: str, label: str, kind: FigureKind, total: Decimal, by_branch: dict[UUID, Decimal],
                   branches: list[UUID], better: bool | None) -> list[Figure]:
    """A company-wide figure and one per branch (zero for a branch with nothing)."""
    figures = [Figure(metric, label, kind, total, None, better)]
    figures += [Figure(metric, label, kind, by_branch.get(b, Decimal(0)), b, better) for b in branches]
    return figures


@provides(COMMAND_PULSE_SOURCE)
class PeoplePulse(PulseSource):
    """Staff and payroll numbers for a company and a day."""

    code = "people"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        params = {"c": str(company_id), "d": day, "m": day.replace(day=1)}
        branches = list(session.execute(text("select id from kernel.branch where company_id = :c order by code"),
                                        params).scalars())
        headcount = session.execute(text(
            "select branch_id, count(*) as n from people.employee where company_id = :c and hire_date <= :d "
            "and ((termination_date is null and status <> 'terminated') or termination_date >= :d) "
            "group by branch_id"), params).all()
        leave = session.execute(text(
            "select e.branch_id, count(*) as n from people.leave_request l "
            "join people.employee e on e.id = l.employee_id "
            "where e.company_id = :c and l.status = 'pending' group by e.branch_id"), params).all()
        overtime = session.execute(text(
            "select a.branch_id, coalesce(sum(a.overtime_hours), 0) as n from people.attendance a "
            "join people.employee e on e.id = a.employee_id where e.company_id = :c "
            "and a.work_date between :m and :d group by a.branch_id"), params).all()
        unpaid = session.execute(text(
            "select count(*) from people.payroll_run where company_id = :c "
            "and status not in ('paid', 'cancelled') and pay_date >= :since"),
            {**params, "since": day - timedelta(days=365)}).scalar_one()

        def split(rows: Sequence[Row[Any]]) -> tuple[Decimal, dict[UUID, Decimal]]:
            by_branch = {r.branch_id: Decimal(r.n) for r in rows if r.branch_id is not None}
            return sum((Decimal(r.n) for r in rows), Decimal(0)), by_branch

        figures: list[Figure] = []
        specs: list[tuple[str, str, Sequence[Row[Any]], bool | None]] = [
            ("people.headcount", "Employees", headcount, None),
            ("people.leave_waiting", "Leave requests awaiting approval", leave, False),
            ("people.overtime_hours_month", "Overtime hours this month", overtime, False)]
        for metric, label, rows, better in specs:
            total, by_branch = split(rows)
            figures += _with_branches(metric, label, "count", total, by_branch, branches, better)
        figures.append(Figure("people.payroll_runs_unpaid", "Payroll runs not yet paid", "count",
                              Decimal(unpaid), None, False))
        return figures
