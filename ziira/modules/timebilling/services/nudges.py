"""The reminders Time and Billing sends, decided here and queued through `notify.tell` (never sent in a request):

    missed time        the next morning, to a person who logged less than the company's minimum for a working day
    week not sent      after a week ends, to a person with time in it that was never submitted (and once more later)
    approval waiting   a submitted week nobody approved: first the person's own approver, then everyone who may
                       approve, then again every week; an away approver is skipped
    review waiting     an invoice review that a partner has not looked at
    work coming due    a dated task is near, or late, to whoever does it

Who is a fee-earner (and so reminded to log time)? Active people who hold 'time.log', have not switched reminders off
on their staff profile, and either have a weekly capacity set or logged time in the last eight weeks: an owner who
never logs time is never nagged.
"""

from datetime import date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text

from ziira.modules.timebilling.domain import nudges as rules
from ziira.modules.timebilling.domain.timesheet import hours, week_start
from ziira.modules.timebilling.permissions import TIME_APPROVE, TIME_LOG, TIME_PARTNER
from ziira.modules.timebilling.repository.models import EngagementTask, InvoiceBatch, Project, Staff, Week
from ziira.modules.timebilling.services import common, notify, reports
from ziira.sdk import Session, company_zone, format_day, recipients_with_permission

LOOK_BACK_WEEKS = 8


def _first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def _key(*parts: object) -> UUID:
    """A stable id for 'this person on this day' (reminders about a day have no row of their own)."""
    return uuid5(NAMESPACE_URL, ":".join(str(p) for p in parts))


def fee_earners(session: Session, company_id: UUID, today: date) -> list[Any]:
    """The people to remind to log time (see the module note)."""
    staff = {s.user_id: s for s in session.scalars(select(Staff).where(Staff.company_id == company_id))}
    since = today - timedelta(weeks=LOOK_BACK_WEEKS)
    logged = set(session.execute(text(
        "select distinct user_id from timebilling.entry where company_id = :c and work_date >= :s"),
        {"c": str(company_id), "s": since}).scalars())
    out = []
    for person in recipients_with_permission(session, TIME_LOG):
        row = staff.get(person.user_id)
        if not person.context.has_anywhere(TIME_LOG):
            continue
        if row is not None and (not row.active or not row.nudges):
            continue
        if (row is not None and row.weekly_capacity_minutes) or person.user_id in logged:
            out.append(person)
    return out


def missed_time(session: Session, company_id: UUID, today: date) -> int:
    """Remind people who logged less than the minimum on the last working day."""
    setting = common.settings(session, company_id)
    day = rules.previous_working_day(today, setting.work_days or [])
    if day is None or setting.nudge_minutes <= 0:
        return 0
    away = {s.user_id: s.away_until for s in session.scalars(select(Staff).where(Staff.company_id == company_id))}
    business = notify.business_name(session, company_id)
    told = 0
    for person in fee_earners(session, company_id, today):
        if (away.get(person.user_id) or date.min) >= day:
            continue
        got = int(session.execute(text(
            "select coalesce(sum(minutes), 0) from timebilling.entry where company_id = :c and user_id = :u "
            "and work_date = :d"), {"c": str(company_id), "u": str(person.user_id), "d": day}).scalar() or 0)
        running = session.execute(text("select 1 from timebilling.timer where user_id = :u"),
                                  {"u": str(person.user_id)}).first() is not None
        if running or not rules.short_of(got, setting.nudge_minutes):
            continue
        told += notify.tell(
            session, company_id=company_id, user_id=person.user_id, kind="alerts", template="time_missing",
            variables={"name": _first_name(person.full_name), "date": format_day(day), "logged": str(hours(got)),
                       "wanted": str(hours(setting.nudge_minutes)), "business": business},
            subject_id=_key("missed", person.user_id, day), day=today, ref_type="kernel.app_user")
    return told


def weeks_not_sent(session: Session, company_id: UUID, today: date) -> int:
    """Remind people whose finished week still has unsent time: once when it ends, once more a few days later."""
    setting = common.settings(session, company_id)
    business = notify.business_name(session, company_id)
    people = {p.user_id: p for p in fee_earners(session, company_id, today)}
    told = 0
    for m in reports.unsubmitted_weeks(session, company_id, today, 0):
        person = people.get(m.user_id)
        if person is None or m.week_start < today - timedelta(weeks=LOOK_BACK_WEEKS):
            continue
        late = (today - (m.week_start + timedelta(days=6))).days
        again = max(setting.unsubmitted_after_days, 2)
        for stage, due in ((0, late >= 1), (1, late >= again)):
            if not due:
                continue
            told += notify.tell(
                session, company_id=company_id, user_id=person.user_id, kind="alerts", template="time_submit",
                variables={"name": _first_name(person.full_name), "week": format_day(m.week_start),
                           "hours": str(hours(m.minutes)), "business": business},
                subject_id=_key("unsent", m.user_id, m.week_start), day=m.week_start + timedelta(days=stage),
                ref_type="kernel.app_user")
    return told


def approvals_waiting(session: Session, company_id: UUID, today: date, now: datetime) -> int:
    """Remind approvers of submitted weeks that wait: the person's own approver first, then everyone who may approve."""
    setting = common.settings(session, company_id)
    first_after, escalate_after = setting.approval_reminder_days, setting.approval_escalate_days
    if first_after <= 0 and escalate_after <= 0:
        return 0
    staff = {s.user_id: s for s in session.scalars(select(Staff).where(Staff.company_id == company_id))}
    business = notify.business_name(session, company_id)
    zone = company_zone(session, company_id)
    told = 0
    weeks = list(session.scalars(select(Week).where(
        Week.company_id == company_id, Week.status == "submitted", Week.approval_pending.is_(False))))
    for week in weeks:
        sent_on = (week.submitted_at or now).astimezone(zone).date()
        waiting = (today - sent_on).days
        author = week.user_id
        author_name = common.user_names(session, {author}).get(author, "")
        branches = set(session.scalars(text(
            "select distinct branch_id from timebilling.entry where week_id = :w").bindparams(w=week.id)))
        everyone = [p for p in notify.approvers_for(session, company_id, next(iter(branches), None), author)]
        profile = staff.get(author)
        chosen = profile.approver_id if profile else None
        own = [p for p in everyone if p.user_id == chosen and (staff.get(chosen) is None
                                                               or (staff[chosen].away_until or date.min) < today)]
        if escalate_after > 0 and waiting >= escalate_after:
            stage = (waiting - escalate_after) // 7
            targets, day = everyone, sent_on + timedelta(days=escalate_after + 7 * stage)
        elif first_after > 0 and waiting >= first_after:
            targets, day = (own or everyone), sent_on + timedelta(days=first_after)
        else:
            continue
        for person in targets:
            told += notify.tell(
                session, company_id=company_id, user_id=person.user_id, kind="approvals",
                template="approval_reminder",
                variables={"name": _first_name(person.full_name), "person": author_name,
                           "week": format_day(week.week_start), "hours": str(hours(week.minutes)),
                           "days": str(waiting), "business": business},
                subject_id=week.id, day=day, ref_type="timebilling.week")
    return told


def reviews_waiting(session: Session, company_id: UUID, today: date, now: datetime) -> int:
    """Remind partners of an invoice review they were asked to look at and have not."""
    setting = common.settings(session, company_id)
    if setting.approval_reminder_days <= 0:
        return 0
    business = notify.business_name(session, company_id)
    told = 0
    for batch in session.scalars(select(InvoiceBatch).where(
            InvoiceBatch.company_id == company_id, InvoiceBatch.status == "draft",
            InvoiceBatch.review_status == "requested")):
        asked = (batch.review_requested_at or now).astimezone(company_zone(session, company_id)).date()
        waiting = (today - asked).days
        if waiting < setting.approval_reminder_days:
            continue
        day = asked + timedelta(days=setting.approval_reminder_days
                                + 7 * ((waiting - setting.approval_reminder_days) // 7))
        view = session.execute(text(
            "select coalesce(sum(amount), 0) from timebilling.invoice_batch_line where batch_id = :b"),
            {"b": str(batch.id)}).scalar()
        names = common.customer_names(session, {batch.client_id})
        for person in recipients_with_permission(session, TIME_PARTNER):
            if person.user_id == batch.review_requested_by or not person.covers(
                    TIME_PARTNER, company_id, batch.branch_id):
                continue
            told += notify.tell(
                session, company_id=company_id, user_id=person.user_id, kind="approvals", template="partner_review",
                variables={"name": _first_name(person.full_name), "client": names.get(batch.client_id, "-"),
                           "amount": f"{view:,.2f}", "business": business},
                subject_id=batch.id, day=day, ref_type="timebilling.invoice_batch")
    return told


def work_coming_due(session: Session, company_id: UUID, today: date) -> int:
    """Tell whoever does a dated task that it is near (inside its lead time) or late (once, then weekly)."""
    business = notify.business_name(session, company_id)
    told = 0
    recipients = {p.user_id: p for p in recipients_with_permission(session, TIME_LOG)}
    recipients.update({p.user_id: p for p in recipients_with_permission(session, TIME_APPROVE)})
    for task in session.scalars(select(EngagementTask).where(
            EngagementTask.company_id == company_id, EngagementTask.status == "open",
            EngagementTask.assignee_id.is_not(None), EngagementTask.due_on <= today + timedelta(days=30))):
        person = recipients.get(task.assignee_id) if task.assignee_id else None
        project = session.get(Project, task.project_id)
        if person is None or project is None:
            continue
        lead = 14
        if task.recurrence_id is not None:
            lead = int(session.execute(text("select lead_days from timebilling.recurrence where id = :r"),
                                       {"r": str(task.recurrence_id)}).scalar() or 14)
        late = (today - task.due_on).days
        if late > 0:
            day = task.due_on + timedelta(days=1 + 7 * ((late - 1) // 7))
        elif (task.due_on - today).days <= min(lead, 7):
            day = task.due_on - timedelta(days=min(lead, 7))
        else:
            continue
        names = common.customer_names(session, {project.client_id})
        told += notify.tell(
            session, company_id=company_id, user_id=person.user_id, kind="alerts", template="engagement_due",
            variables={"name": _first_name(person.full_name), "task": task.name,
                       "client": names.get(project.client_id, project.name), "date": format_day(task.due_on),
                       "business": business},
            subject_id=task.id, day=day, ref_type="timebilling.task")
    return told


def run_company(session: Session, company_id: UUID, now: datetime) -> dict[str, int]:
    """Every reminder due for one company right now. Idempotent: run as often as you like."""
    zone = company_zone(session, company_id)
    local = now.astimezone(zone)
    today = local.date()
    setting = common.settings(session, company_id)
    done = {"missed_time": 0, "weeks_not_sent": 0, "approvals": 0, "reviews": 0, "due": 0}
    if local.hour >= setting.nudge_hour:
        done["missed_time"] = missed_time(session, company_id, today)
        done["weeks_not_sent"] = weeks_not_sent(session, company_id, today)
        done["approvals"] = approvals_waiting(session, company_id, today, now)
        done["reviews"] = reviews_waiting(session, company_id, today, now)
        done["due"] = work_coming_due(session, company_id, today)
    return done


def my_missing(session: Session, company_id: UUID, user_id: UUID, today: date) -> list[tuple[date, int, int]]:
    """For the app's own banner: working days in the last two weeks where this person logged less than the minimum,
    as (day, minutes logged, minutes wanted). Empty when reminders are off."""
    setting = common.settings(session, company_id)
    wanted = setting.nudge_minutes
    if wanted <= 0:
        return []
    got = {r.work_date: int(r.m) for r in session.execute(text(
        "select work_date, sum(minutes) as m from timebilling.entry where company_id = :c and user_id = :u "
        "and work_date >= :s group by work_date"),
        {"c": str(company_id), "u": str(user_id), "s": today - timedelta(days=14)})}
    first = session.execute(text("select min(work_date) from timebilling.entry where company_id = :c and user_id = :u"),
                            {"c": str(company_id), "u": str(user_id)}).scalar()
    if first is None:
        return []                                   # never logged: nothing to compare with yet
    submitted = {w.week_start for w in session.scalars(select(Week).where(
        Week.company_id == company_id, Week.user_id == user_id, Week.status.in_(("submitted", "approved"))))}
    out = []
    for back in range(1, 15):
        day = today - timedelta(days=back)
        if day < first or day.isoweekday() not in (setting.work_days or []):
            continue
        if week_start(day, setting.week_starts_on) in submitted:
            continue
        if rules.short_of(got.get(day, 0), wanted):
            out.append((day, got.get(day, 0), wanted))
    return sorted(out)
