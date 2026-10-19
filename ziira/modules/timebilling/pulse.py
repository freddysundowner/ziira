"""Time and Billing's figures for the Command Center."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import Figure, PulseSource
from ziira.modules.timebilling.domain.timesheet import week_start
from ziira.sdk import Session


class TimeBillingPulse(PulseSource):
    """Unbilled work, billable hours, waiting timesheets and how busy people are."""

    code = "timebilling"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        setting = session.execute(text(
            "select week_starts_on, capacity_minutes_week from timebilling.setting where company_id = :c"),
            {"c": company_id}).first()
        starts_on, capacity = (setting.week_starts_on, setting.capacity_minutes_week) if setting else (1, 2400)
        start = week_start(day, starts_on)
        unbilled = session.execute(text(
            "select p.branch_id, coalesce(sum(round((e.minutes - e.retainer_minutes) * coalesce(e.bill_rate, 0) / 60, "
            "2)), 0) as value from timebilling.entry e join timebilling.project p on p.id = e.project_id "
            "where e.company_id = :c and p.billing_mode <> 'fixed_fee' and e.status = 'approved' and e.billable "
            "and e.invoice_id is null and not e.written_off group by p.branch_id"), {"c": company_id}).all()
        today = session.execute(text(
            "select branch_id, coalesce(sum(minutes) filter (where billable), 0) as billable, "
            "coalesce(sum(minutes), 0) as logged from timebilling.entry where company_id = :c and work_date = :d "
            "group by branch_id"), {"c": company_id, "d": day}).all()
        week = session.execute(text(
            "select coalesce(sum(minutes) filter (where billable), 0) as billable, count(distinct user_id) as people "
            "from timebilling.entry where company_id = :c and work_date >= :s and work_date <= :d"),
            {"c": company_id, "s": start, "d": day}).one()
        waiting = session.execute(text(
            "select count(*) from timebilling.week where company_id = :c and status = 'submitted'"),
            {"c": company_id}).scalar_one()
        days_in = (day - start).days + 1
        figures = [
            Figure("timebilling.unbilled_value", "Unbilled work", "money",
                   sum((Decimal(r.value) for r in unbilled), Decimal(0)), None, None),
            Figure("timebilling.billable_hours_today", "Billable hours today", "count",
                   (Decimal(sum(r.billable for r in today)) / 60).quantize(Decimal("0.1")), None, True),
            Figure("timebilling.timesheets_waiting", "Timesheets waiting for approval", "count", Decimal(waiting),
                   None, False),
        ]
        figures += [Figure("timebilling.unbilled_value", "Unbilled work", "money", Decimal(r.value), r.branch_id, None)
                    for r in unbilled if r.branch_id is not None]
        figures += [Figure("timebilling.billable_hours_today", "Billable hours today", "count",
                           (Decimal(r.billable) / 60).quantize(Decimal("0.1")), r.branch_id, True)
                    for r in today if r.branch_id is not None]
        people = int(week.people)
        if people and capacity:
            expected = Decimal(capacity) * people * min(days_in, 7) / 7
            figures.append(Figure("timebilling.utilisation_week", "Billable share of capacity this week", "percent",
                                  (Decimal(week.billable) * 100 / expected).quantize(Decimal("0.1")), None, True))
        return figures

