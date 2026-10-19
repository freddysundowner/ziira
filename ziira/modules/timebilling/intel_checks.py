"""Intelligence checks over billable work: what was done but not invoiced, projects going over budget, timesheets nobody
sent in, retainers running out and a falling billable share. None of them writes anything."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.modules.timebilling.domain.timesheet import hours
from ziira.sdk import Session

CENT = Decimal("0.01")


def money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount.quantize(CENT):,.2f}"


def _currency(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": company_id}).scalar() or "")


class UnbilledWorkAgeing(IntelCheck):
    """Approved work for a client that has waited too long to be invoiced."""

    code = "timebilling.unbilled_ageing"

    value_kind = "money"
    title = "Work done but not invoiced"
    area = "customers"
    description = "Approved time and expenses for a client that have been waiting a long while for an invoice."
    default_severity = "medium"
    params: dict[str, Any] = {"unbilled_days": 30, "min_amount": "1.00", "look_back_days": 365}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        age = int(ctx.number("unbilled_days"))
        cutoff = ctx.today - timedelta(days=age)
        floor = ctx.number("min_amount")
        since = ctx.today - timedelta(days=int(ctx.number("look_back_days")))
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            "select p.client_id, p.branch_id, min(e.work_date) as oldest, "
            "sum(round((e.minutes - e.retainer_minutes) * coalesce(e.bill_rate, 0) / 60, 2)) as value, "
            "sum(e.minutes - e.retainer_minutes) as minutes "
            "from timebilling.entry e join timebilling.project p on p.id = e.project_id "
            "where e.company_id = :c and p.billing_mode <> 'fixed_fee' and e.status = 'approved' and e.billable "
            "and e.invoice_id is null and not e.written_off and e.minutes > e.retainer_minutes "
            "and e.work_date >= :since "
            "group by p.client_id, p.branch_id having min(e.work_date) <= :cutoff"),
            {"c": ctx.company_id, "since": since, "cutoff": cutoff}).all()
        from ziira.modules.crm.public import find_customers

        names = find_customers(session, {r.client_id for r in rows})
        out = []
        for r in rows:
            value = Decimal(r.value)
            if value < floor:
                continue
            days = (ctx.today - r.oldest).days
            name = names[r.client_id].name if r.client_id in names else "A client"
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.client_id, r.branch_id),
                severity="high" if days >= age * 3 else "medium",
                summary=(f"{name} has {hours(int(r.minutes))} hours of approved work, worth {money(value, currency)}, "
                         f"that has not been invoiced. The oldest is {days} days old."),
                recommended_action="Open Unbilled work, review it and send the invoice.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="crm.customer", entity_id=r.client_id,
                period_end=r.oldest, value=Decimal(days), expected_value=Decimal(age), amount=value,
                records=(Record("crm.customer", r.client_id, name),),
                figures={"days": str(days), "hours": str(hours(int(r.minutes))), "currency": currency}))
        return out


class ProjectOverBudget(IntelCheck):
    """An active project that has used more of its budget than allowed."""

    code = "timebilling.project_over_budget"

    value_kind = "percent"
    title = "Project over budget"
    area = "customers"
    description = "A project has used more hours or money than its budget."
    default_severity = "medium"
    params: dict[str, Any] = {"over_percent": "100.0"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        limit = ctx.number("over_percent")
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            "select p.id, p.code, p.name, p.branch_id, p.budget_minutes, "
            "case when p.billing_mode = 'capped_fee' then coalesce(p.budget_amount, p.fee_cap) "
            "  else p.budget_amount end as budget_amount, p.billing_mode, "
            "coalesce((select sum(round(e.minutes * coalesce(e.bill_rate, 0) / 60, 2)) from timebilling.entry e "
            "  where e.project_id = p.id and e.status = 'approved' and e.billable "
            "  and e.minutes > e.retainer_minutes), 0) as worked, "
            "coalesce((select sum(minutes) from timebilling.entry where project_id = p.id), 0) as logged, "
            "coalesce((select sum(l.amount) from timebilling.invoice_batch_line l join timebilling.invoice_batch b "
            "  on b.id = l.batch_id where l.project_id = p.id and b.status = 'issued' "
            "  and l.kind <> 'retainer_topup'), 0) + "
            "coalesce((select sum(round((e.minutes - e.retainer_minutes) * coalesce(e.bill_rate, 0) / 60, 2)) "
            "  from timebilling.entry e where e.project_id = p.id and e.status = 'approved' and e.billable "
            "  and e.invoice_id is null and not e.written_off), 0) as worth "
            "from timebilling.project p where p.company_id = :c and p.status = 'active' "
            "and (p.budget_minutes is not null or p.budget_amount is not null or p.fee_cap is not null)"),
            {"c": ctx.company_id}).all()
        out = []
        for r in rows:
            by_hours = Decimal(r.logged) * 100 / r.budget_minutes if r.budget_minutes else None
            used_money = Decimal(r.worked) if r.billing_mode == "capped_fee" else Decimal(r.worth)
            by_money = used_money * 100 / r.budget_amount if r.budget_amount else None
            worst = max(x for x in (by_hours, by_money) if x is not None)
            if worst <= limit:
                continue
            if by_hours is not None and by_hours >= (by_money or Decimal(0)):
                what = f"{hours(int(r.logged))} of {hours(r.budget_minutes)} budgeted hours"
                extra = (Decimal(r.logged) - r.budget_minutes) / 60 * 1
            else:
                what = f"{money(used_money, currency)} of a {money(r.budget_amount, currency)} budget"
                extra = used_money - r.budget_amount
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="high" if worst >= limit + 25 else "medium",
                summary=f"Project {r.code} {r.name} has used {what}: {worst.quantize(Decimal('0.1'))}% of its budget.",
                recommended_action="Talk to the client about more budget, or agree what is left to do.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="timebilling.project", entity_id=r.id,
                value=worst.quantize(Decimal("0.1")), expected_value=limit,
                amount=extra.quantize(CENT) if by_money is not None and by_money >= (by_hours or 0) else None,
                records=(Record("timebilling.project", r.id, f"{r.code} {r.name}"),),
                figures={"percent": str(worst.quantize(Decimal("0.1"))), "currency": currency}))
        return out


class TimesheetsNotSubmitted(IntelCheck):
    """People who logged time and never sent the week in."""

    code = "timebilling.timesheets_not_submitted"

    value_kind = "days"
    title = "Timesheet not sent in"
    area = "people"
    description = "Someone logged time for a week that has ended and has not submitted it for approval."
    default_severity = "low"
    params: dict[str, Any] = {"grace_days": 3, "look_back_weeks": 8}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        from ziira.modules.timebilling.services import reports

        wait = int(ctx.number("grace_days"))
        floor = ctx.today - timedelta(weeks=int(ctx.number("look_back_weeks")))
        out = []
        for m in reports.unsubmitted_weeks(session, ctx.company_id, ctx.today, wait):
            if m.week_start < floor:
                continue
            late = (ctx.today - (m.week_start + timedelta(days=6))).days
            out.append(Candidate(
                fingerprint=fingerprint(self.code, m.user_id, m.week_start),
                severity="medium" if late > wait * 3 else "low",
                summary=(f"{m.name} logged {hours(m.minutes)} hours in the week of {m.week_start.isoformat()} and has "
                         f"not sent that week in. It ended {late} days ago."),
                recommended_action="Ask them to submit the week so it can be approved and invoiced.",
                company_id=ctx.company_id, entity_type="kernel.app_user", entity_id=m.user_id,
                period_start=m.week_start, period_end=m.week_start + timedelta(days=6), value=Decimal(late),
                expected_value=Decimal(wait), records=(Record("kernel.app_user", m.user_id, m.name),),
                figures={"days": str(late), "hours": str(hours(m.minutes))}))
        return out


class TimesheetWaitingForApproval(IntelCheck):
    """A submitted week that nobody has approved."""

    code = "timebilling.approval_waiting"

    value_kind = "days"
    title = "Timesheet waiting for approval"
    area = "people"
    description = "A submitted week has been waiting a long while for someone to approve it."
    default_severity = "low"
    params: dict[str, Any] = {"approval_days": 3, "look_back_days": 120}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        wait = int(ctx.number("approval_days"))
        rows = session.execute(text(
            "select w.id, w.user_id, w.week_start, w.minutes, w.submitted_at, u.full_name from timebilling.week w "
            "join kernel.app_user u on u.id = w.user_id where w.company_id = :c and w.status = 'submitted' "
            "and w.submitted_at >= cast(:since as date) and w.submitted_at < cast(:cut as date)"),
            {"c": ctx.company_id, "since": ctx.today - timedelta(days=int(ctx.number("look_back_days"))),
             "cut": ctx.today - timedelta(days=wait)}).all()
        out = []
        for r in rows:
            waiting = (ctx.today - r.submitted_at.date()).days
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="medium" if waiting > wait * 3 else "low",
                summary=(f"{r.full_name}'s week of {r.week_start.isoformat()} ({hours(r.minutes)} hours) has been "
                         f"waiting {waiting} days for approval."),
                recommended_action="Approve it or send it back, so the time can be invoiced.",
                company_id=ctx.company_id, entity_type="timebilling.week", entity_id=r.id, value=Decimal(waiting),
                expected_value=Decimal(wait), 
                records=(Record("timebilling.week", r.id, f"{r.full_name} {r.week_start}"),),
                figures={"days": str(waiting), "hours": str(hours(r.minutes))}))
        return out


class RetainerRunningOut(IntelCheck):
    """A prepaid-hours retainer that is nearly used up or about to expire with hours left."""

    code = "timebilling.retainer_nearly_used"

    value_kind = "percent"
    title = "Retainer nearly used up"
    area = "customers"
    description = "A client's prepaid hours are almost all used, or are about to expire unused."
    default_severity = "medium"
    params: dict[str, Any] = {"used_percent": "80.0", "expiry_days": 14}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        limit = ctx.number("used_percent")
        soon = ctx.today + timedelta(days=int(ctx.number("expiry_days")))
        rows = session.execute(text(
            "select r.id, r.balance_minutes, r.topped_up_minutes, r.expires_on, p.id as pid, p.code, p.name, "
            "p.branch_id from timebilling.retainer r join timebilling.project p on p.id = r.project_id "
            "where r.company_id = :c and r.kind = 'hours' and r.status = 'active' and r.topped_up_minutes > 0"),
            {"c": ctx.company_id}).all()
        out = []
        for r in rows:
            used = Decimal(r.topped_up_minutes - r.balance_minutes) * 100 / r.topped_up_minutes
            expiring = r.expires_on is not None and r.balance_minutes > 0 and ctx.today <= r.expires_on <= soon
            if used < limit and not expiring:
                continue
            left = f"{hours(r.balance_minutes)} hours left"
            reason = (f"its {left} expire on {r.expires_on.isoformat()}" if expiring and used < limit
                      else f"{used.quantize(Decimal('0.1'))}% of the prepaid hours are used, {left}")
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium",
                summary=f"The retainer on {r.code} {r.name}: {reason}.",
                recommended_action=("Offer the client a top-up before the work stops." if not expiring
                                    else "Remind the client to use the hours, or agree an extension."),
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="timebilling.retainer", entity_id=r.id,
                value=used.quantize(Decimal("0.1")), expected_value=limit,
                records=(Record("timebilling.project", r.pid, f"{r.code} {r.name}"),),
                figures={"percent": str(used.quantize(Decimal("0.1"))), "hours": str(hours(r.balance_minutes))}))
        return out


class BillableShareDrop(IntelCheck):
    """The share of logged time that is billable has fallen compared with the weeks before."""

    code = "timebilling.billable_ratio_drop"

    value_kind = "percent"
    title = "Less of the time is billable"
    area = "people"
    description = "The share of logged hours that can be billed has dropped well below the weeks before."
    default_severity = "low"
    params: dict[str, Any] = {
        "recent_days": 14, "compare_days": 56, "share_drop_points": "10.0", "min_logged_hours": 20,
    }
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        recent = int(ctx.number("recent_days"))
        compare = int(ctx.number("compare_days"))
        split: date = ctx.today - timedelta(days=recent)
        start: date = split - timedelta(days=compare)
        row = session.execute(text(
            "select coalesce(sum(minutes) filter (where work_date > :split), 0) as r_all, "
            "coalesce(sum(minutes) filter (where work_date > :split and billable), 0) as r_bill, "
            "coalesce(sum(minutes) filter (where work_date <= :split), 0) as b_all, "
            "coalesce(sum(minutes) filter (where work_date <= :split and billable), 0) as b_bill "
            "from timebilling.entry where company_id = :c and work_date > :start and work_date <= :today"),
            {"c": ctx.company_id, "split": split, "start": start, "today": ctx.today}).one()
        floor = int(ctx.number("min_logged_hours")) * 60
        if row.r_all < floor or row.b_all < floor:
            return []
        now = Decimal(row.r_bill) * 100 / row.r_all
        before = Decimal(row.b_bill) * 100 / row.b_all
        if before - now < ctx.number("share_drop_points"):
            return []
        return [Candidate(
            fingerprint=fingerprint(self.code, ctx.company_id, ctx.today.isocalendar()[:2]), severity="low",
            summary=(f"{now.quantize(Decimal('0.1'))}% of the time logged in the last {recent} days is billable, "
                     f"down from {before.quantize(Decimal('0.1'))}% in the {compare} days before."),
            recommended_action="Look at where the non-billable hours went: internal work, waiting or untracked jobs.",
            company_id=ctx.company_id, value=now.quantize(Decimal("0.1")),
            expected_value=before.quantize(Decimal("0.1")),
            figures={"percent": str(now.quantize(Decimal("0.1"))),
                     "usual_percent": str(before.quantize(Decimal("0.1")))})]


class EngagementWorkOverdue(IntelCheck):
    """Dated work for an engagement (a monthly close, an annual return) that is late and not done."""

    code = "timebilling.work_overdue"

    value_kind = "days"
    title = "Engagement work overdue"
    area = "customers"
    description = "A dated piece of work for a client is past its due date and is still open."
    default_severity = "medium"
    params: dict[str, Any] = {"grace_days": 0, "look_back_days": 180}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        grace = int(ctx.number("grace_days"))
        since = ctx.today - timedelta(days=int(ctx.number("look_back_days")))
        rows = session.execute(text(
            "select t.id, t.name, t.due_on, t.period, p.code, p.name as project, p.client_id, p.branch_id "
            "from timebilling.engagement_task t join timebilling.project p on p.id = t.project_id "
            "where t.company_id = :c and t.status = 'open' and t.due_on < :cut and t.due_on >= :since"),
            {"c": ctx.company_id, "cut": ctx.today - timedelta(days=grace), "since": since}).all()
        from ziira.modules.crm.public import find_customers

        names = find_customers(session, {r.client_id for r in rows})
        out = []
        for r in rows:
            late = (ctx.today - r.due_on).days
            who = names[r.client_id].name if r.client_id in names else r.project
            label = f"{r.name} ({r.period})" if r.period else r.name
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="high" if late >= 14 else "medium",
                summary=f"{label} for {who} was due on {r.due_on.isoformat()} and is {late} days late.",
                recommended_action="Finish it, or move its due date if the client agreed to wait.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="timebilling.task", entity_id=r.id,
                period_end=r.due_on, value=Decimal(late), expected_value=Decimal(grace),
                figures={"days": str(late)}))
        return out


class ReviewWaitingForPartner(IntelCheck):
    """An invoice review that a partner was asked to look at and has not."""

    code = "timebilling.review_waiting"

    value_kind = "days"
    title = "Invoice waiting for a partner"
    area = "customers"
    description = "An invoice review was sent to a partner a while ago and has not been approved or sent back."
    default_severity = "low"
    params: dict[str, Any] = {"waiting_days": 3, "look_back_days": 60}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        wait = int(ctx.number("waiting_days"))
        rows = session.execute(text(
            "select b.id, b.client_id, b.branch_id, b.review_requested_at, "
            "coalesce((select sum(amount) from timebilling.invoice_batch_line where batch_id = b.id), 0) as amount "
            "from timebilling.invoice_batch b where b.company_id = :c and b.status = 'draft' "
            "and b.review_status = 'requested' and b.review_requested_at >= cast(:since as date) "
            "and b.review_requested_at < cast(:cut as date)"),
            {"c": ctx.company_id, "since": ctx.today - timedelta(days=int(ctx.number("look_back_days"))),
             "cut": ctx.today - timedelta(days=wait)}).all()
        from ziira.modules.crm.public import find_customers

        names = find_customers(session, {r.client_id for r in rows})
        currency = _currency(session, ctx.company_id)
        out = []
        for r in rows:
            waiting = (ctx.today - r.review_requested_at.date()).days
            who = names[r.client_id].name if r.client_id in names else "A client"
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium" if waiting > wait * 3 else "low",
                summary=(f"The invoice for {who} ({money(Decimal(r.amount), currency)}) has been waiting {waiting} "
                         f"days for a partner to look at it."),
                recommended_action="Open the invoice review and approve it or send it back.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="timebilling.invoice_batch",
                entity_id=r.id, value=Decimal(waiting), expected_value=Decimal(wait), amount=Decimal(r.amount),
                figures={"days": str(waiting), "currency": currency}))
        return out


class LowRealisation(IntelCheck):
    """Too much of the work invoiced lately was written down or off."""

    code = "timebilling.realisation_low"

    value_kind = "percent"
    title = "Work billed for less than it is worth"
    area = "customers"
    description = "Of the work invoiced in recent weeks, the share billed (the rest written down or off) is low."
    default_severity = "medium"
    params: dict[str, Any] = {"min_percent": "85.0", "look_back_days": 90, "min_value": "1000.00"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("look_back_days")))
        row = session.execute(text(
            "select coalesce(sum(coalesce(l.list_amount, l.amount)), 0) as standard, "
            "coalesce(sum(l.amount), 0) as billed from timebilling.invoice_batch_line l "
            "join timebilling.invoice_batch b on b.id = l.batch_id where b.company_id = :c and b.status = 'issued' "
            "and l.kind in ('time', 'expense', 'milestone') and b.issued_at >= cast(:since as date)"),
            {"c": ctx.company_id, "since": since}).one()
        standard, billed = Decimal(row.standard), Decimal(row.billed)
        if standard < ctx.number("min_value") or standard == 0:
            return []
        pct = (billed * 100 / standard).quantize(Decimal("0.1"))
        if pct >= ctx.number("min_percent"):
            return []
        currency = _currency(session, ctx.company_id)
        lost = standard - billed
        return [Candidate(
            fingerprint=fingerprint(self.code, ctx.company_id, ctx.today.isocalendar()[:2]),
            severity="high" if pct < ctx.number("min_percent") - 15 else "medium",
            summary=(f"Only {pct}% of the work invoiced in the last {int(ctx.number('look_back_days'))} days was "
                     f"billed: {money(lost, currency)} of {money(standard, currency)} was written down or off."),
            recommended_action="Look at which clients and projects lost the most, and why: scope, estimates or rates.",
            company_id=ctx.company_id, value=pct, expected_value=ctx.number("min_percent"), amount=lost,
            figures={"percent": str(pct), "currency": currency})]


CHECKS = (UnbilledWorkAgeing, ProjectOverBudget, TimesheetsNotSubmitted, TimesheetWaitingForApproval,
          RetainerRunningOut, BillableShareDrop, EngagementWorkOverdue, ReviewWaitingForPartner, LowRealisation)
