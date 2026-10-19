"""Reading time and billing back: unbilled work (WIP) and its ageing, project summaries and profitability, utilisation,
timesheet compliance and CSV exports. Everything here only reads."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import Row

from ziira.modules.timebilling.domain import budget, timesheet
from ziira.modules.timebilling.domain.billing import cents
from ziira.modules.timebilling.permissions import COST_VIEW, RATES_MANAGE, TIME_APPROVE, TIME_VIEW
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry, Project, Week
from ziira.modules.timebilling.services import access, common
from ziira.sdk import NotFound, Session, company_zone, current_context

BUCKETS = ((0, 30, "0-30"), (31, 60, "31-60"), (61, 90, "61-90"), (91, 100000, "over 90"))


def _visible_projects(company_id: UUID | None = None, client_id: UUID | None = None,
                      project_id: UUID | None = None) -> Any:
    q = select(Project.id).where(repo.in_scope(access.scopes_for(TIME_VIEW, TIME_APPROVE), Project.company_id,
                                               Project.branch_id))
    if company_id:
        q = q.where(Project.company_id == company_id)
    if client_id:
        q = q.where(Project.client_id == client_id)
    if project_id:
        q = q.where(Project.id == project_id)
    return q


# --------------------------------------------------------------------------- unbilled work
@dataclass
class UnbilledRow:
    project_id: UUID
    project_code: str
    project_name: str
    client_id: UUID
    billing_mode: str
    minutes: int = 0                 # billable minutes not yet invoiced (after retainer cover)
    time_amount: Decimal = Decimal(0)
    expense_amount: Decimal = Decimal(0)
    milestone_amount: Decimal = Decimal(0)
    unpriced_minutes: int = 0
    in_review_minutes: int = 0
    oldest: date | None = None
    buckets: dict[str, Decimal] = field(default_factory=dict)

    @property
    def amount(self) -> Decimal:
        return self.time_amount + self.expense_amount + self.milestone_amount


def unbilled(session: Session, *, company_id: UUID | None = None, client_id: UUID | None = None,
             project_id: UUID | None = None, as_of: date | None = None) -> list[UnbilledRow]:
    """Approved work that has not been invoiced, by project, valued at the rates fixed at approval, with ageing buckets
    by the age of the work. Work already set aside in a draft review is counted as unbilled and shown separately."""
    visible = _visible_projects(company_id, client_id, project_id)
    projects = {p.id: p for p in session.scalars(select(Project).where(Project.id.in_(visible)))}
    rows: dict[UUID, UnbilledRow] = {}

    def row_for(pid: UUID) -> UnbilledRow:
        if pid not in rows:
            p = projects[pid]
            rows[pid] = UnbilledRow(pid, p.code, p.name, p.client_id, p.billing_mode,
                                    buckets={label: Decimal(0) for _, _, label in BUCKETS})
        return rows[pid]

    if not projects:
        return []
    day = as_of or date.today()
    ids = [str(i) for i in projects]
    room: dict[UUID, Decimal] = {}       # capped fees: what may still be billed on each (the newest work is lost first)
    for pid, p in projects.items():
        if p.billing_mode == "capped_fee" and p.fee_cap is not None:
            billed = session.execute(text(
                "select coalesce(sum(l.amount), 0) from timebilling.invoice_batch_line l join "
                "timebilling.invoice_batch b on b.id = l.batch_id where l.project_id = :p and l.kind = 'time' "
                "and b.status = 'issued'"), {"p": str(pid)}).scalar_one()
            room[pid] = max(Decimal(0), p.fee_cap - Decimal(billed))
    for r in session.execute(text(
            "select project_id, work_date, minutes - retainer_minutes as m, bill_rate, batch_id from timebilling.entry "
            "where project_id = any(cast(:p as uuid[])) and status = 'approved' and billable and invoice_id is null "
            "and not written_off and minutes > retainer_minutes order by work_date, created_at"), {"p": ids}):
        if projects[r.project_id].billing_mode == "fixed_fee":
            continue
        u = row_for(r.project_id)
        amount = cents(Decimal(r.m) * r.bill_rate / 60) if r.bill_rate is not None else Decimal(0)
        if r.project_id in room:
            amount = min(amount, room[r.project_id])
            room[r.project_id] -= amount
        u.minutes += r.m
        u.time_amount += amount
        if r.bill_rate is None:
            u.unpriced_minutes += r.m
        if r.batch_id is not None:
            u.in_review_minutes += r.m
        u.oldest = r.work_date if u.oldest is None else min(u.oldest, r.work_date)
        _bucket(u, (day - r.work_date).days, amount)
    for r in session.execute(text(
            "select project_id, expense_date, amount, markup_percent from timebilling.expense "
            "where project_id = any(cast(:p as uuid[])) and status = 'approved' and billable and invoice_id is null "
            "and not written_off"), {"p": ids}):
        u = row_for(r.project_id)
        amount = cents(r.amount * (100 + r.markup_percent) / 100)
        u.expense_amount += amount
        u.oldest = r.expense_date if u.oldest is None else min(u.oldest, r.expense_date)
        _bucket(u, (day - r.expense_date).days, amount)
    for r in session.execute(text(
            "select project_id, amount from timebilling.milestone where project_id = any(cast(:p as uuid[])) "
            "and status = 'ready'"), {"p": ids}):
        row_for(r.project_id).milestone_amount += r.amount
    return sorted(rows.values(), key=lambda x: (x.oldest or date.max, x.project_code))


def _bucket(u: UnbilledRow, age: int, amount: Decimal) -> None:
    for low, high, label in BUCKETS:
        if low <= max(age, 0) <= high:
            u.buckets[label] += amount
            return


# --------------------------------------------------------------------------- projects
@dataclass
class ProjectSummary:
    project: Project
    logged_minutes: int = 0
    billable_minutes: int = 0
    unapproved_minutes: int = 0
    budget_minutes_percent: Decimal | None = None
    budget_amount_percent: Decimal | None = None
    budget_state: str = "none"
    billed_amount: Decimal = Decimal(0)
    unbilled_amount: Decimal = Decimal(0)
    cost: Decimal | None = None
    margin: Decimal | None = None
    margin_percent: Decimal | None = None
    unpriced_cost_minutes: int = 0
    fee_cap_percent: Decimal | None = None      # capped fee: the value of the work done as a share of the cap
    over_cap_amount: Decimal = Decimal(0)        # capped fee: work done above the cap (it cannot be billed)


def project_summary(session: Session, project_id: UUID) -> ProjectSummary:
    project = common.project_for_view(session, project_id)
    setting = common.settings(session, project.company_id)
    out = ProjectSummary(project)
    e = session.execute(text(
        "select coalesce(sum(minutes), 0) as logged, coalesce(sum(minutes) filter (where billable), 0) as billable, "
        "coalesce(sum(minutes) filter (where status <> 'approved'), 0) as pending, "
        "coalesce(sum(round(minutes * coalesce(bill_rate, 0) / 60, 2)) filter (where status = 'approved' and billable "
        "  and minutes > retainer_minutes), 0) as worth, "
        "coalesce(sum(round(minutes * coalesce(bill_rate, 0) / 60, 2)) filter (where status = 'approved' and billable "
        "  and minutes > retainer_minutes), 0) as worth_all, "
        "coalesce(sum(round(minutes * cost_rate / 60, 2)) filter (where status = 'approved'), 0) as cost, "
        "coalesce(sum(minutes) filter (where status = 'approved' and cost_rate is null), 0) as no_cost_rate "
        "from timebilling.entry where project_id = :p"), {"p": str(project_id)}).one()
    out.logged_minutes, out.billable_minutes, out.unbilled_amount = int(e.logged), int(e.billable), Decimal(0)
    out.unapproved_minutes, out.unpriced_cost_minutes = int(e.pending), int(e.no_cost_rate)
    spent = session.execute(text(
        "select coalesce(sum(amount), 0) as cost from timebilling.expense where project_id = :p "
        "and status = 'approved'"),
        {"p": str(project_id)}).scalar_one()
    billed = session.execute(text(
        "select coalesce(sum(l.amount), 0) from timebilling.invoice_batch_line l join timebilling.invoice_batch b "
        "on b.id = l.batch_id where l.project_id = :p and b.status = 'issued' and l.kind <> 'retainer_topup'"),
        {"p": str(project_id)}).scalar_one()
    out.billed_amount = Decimal(billed)
    row = next(iter(unbilled(session, project_id=project_id)), None)
    out.unbilled_amount = row.amount if row else Decimal(0)
    out.budget_minutes_percent = budget.percent_used(out.logged_minutes, project.budget_minutes)
    out.budget_amount_percent = budget.percent_used(out.billed_amount + out.unbilled_amount, project.budget_amount)
    if project.billing_mode == "capped_fee" and project.fee_cap:
        worked = Decimal(e.worth_all)
        out.fee_cap_percent = budget.percent_used(worked, project.fee_cap)
        out.over_cap_amount = max(Decimal(0), worked - project.fee_cap)
    worst = max([p for p in (out.budget_minutes_percent, out.budget_amount_percent, out.fee_cap_percent)
                 if p is not None], default=None)
    out.budget_state = budget.state(worst, setting.budget_alert_percent)
    ctx = current_context()
    if ctx.can(COST_VIEW, company_id=project.company_id) or ctx.can(RATES_MANAGE, company_id=project.company_id):
        out.cost = Decimal(e.cost) + Decimal(spent)
        out.margin = out.billed_amount - out.cost
        out.margin_percent = (out.margin * 100 / out.billed_amount).quantize(Decimal("0.1")) \
            if out.billed_amount > 0 else None
    return out


# --------------------------------------------------------------------------- people
@dataclass
class UtilisationRow:
    user_id: UUID
    name: str
    logged_minutes: int
    billable_minutes: int
    capacity_minutes: int
    percent: Decimal


def utilisation(session: Session, company_id: UUID, date_from: date, date_to: date) -> list[UtilisationRow]:
    """Billable time as a share of capacity for each person who logged time in the period. Capacity is the person's
    weekly capacity (their staff profile, else the company's) scaled to the length of the period."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    scopes = access.scopes_for(TIME_VIEW)
    q = select(Entry.user_id, Entry.minutes, Entry.billable).where(
        Entry.company_id == company_id, Entry.work_date >= date_from, Entry.work_date <= date_to,
        repo.in_scope(scopes, Entry.company_id, Entry.branch_id))
    totals: dict[UUID, list[int]] = {}
    for user_id, minutes, billable in session.execute(q):
        t = totals.setdefault(user_id, [0, 0])
        t[0] += minutes
        t[1] += minutes if billable else 0
    setting = common.settings(session, company_id)
    caps = {r.user_id: r.weekly_capacity_minutes for r in session.execute(text(
        "select user_id, weekly_capacity_minutes from timebilling.staff where company_id = :c"),
            {"c": str(company_id)})}
    names = common.user_names(session, set(totals))
    days = (date_to - date_from).days + 1
    out = []
    for uid, (logged, billable_m) in totals.items():
        weekly = caps.get(uid) or setting.capacity_minutes_week
        capacity = round(weekly * days / 7)
        out.append(UtilisationRow(uid, names.get(uid, ""), logged, billable_m, capacity,
                                  timesheet.utilisation(billable_m, capacity)))
    return sorted(out, key=lambda r: r.name)


@dataclass
class MissingWeek:
    user_id: UUID
    name: str
    week_start: date
    minutes: int


def unsubmitted_weeks(session: Session, company_id: UUID, today: date,
                      after_days: int | None = None) -> list[MissingWeek]:
    """People with time logged in a week that ended more than `after_days` ago and has not been submitted."""
    setting = common.settings(session, company_id)
    wait = setting.unsubmitted_after_days if after_days is None else after_days
    found: dict[tuple[UUID, date], int] = {}
    submitted = {(w.user_id, w.week_start) for w in session.scalars(select(Week).where(
        Week.company_id == company_id, Week.status.in_(("submitted", "approved"))))}
    for r in session.execute(text(
            "select user_id, work_date, minutes from timebilling.entry where company_id = :c and status in "
            "('draft') and work_date < :cut"), {"c": str(company_id), "cut": today - timedelta(days=wait)}):
        start = timesheet.week_start(r.work_date, setting.week_starts_on)
        if start + timedelta(days=6 + wait) < today and (r.user_id, start) not in submitted:
            found[(r.user_id, start)] = found.get((r.user_id, start), 0) + r.minutes
    names = common.user_names(session, {u for u, _ in found})
    return sorted((MissingWeek(u, names.get(u, ""), s, m) for (u, s), m in found.items()),
                  key=lambda x: (x.week_start, x.name))


# --------------------------------------------------------------------------- CSV
def entries_csv_rows(rows: list[Row[Any]] | list[Entry], names: dict[UUID, str], projects: dict[UUID, Project],
                     with_cost: bool) -> tuple[list[str], list[list[object]]]:
    header = ["Date", "Person", "Project code", "Project", "Task", "Hours", "Billable", "Status", "Rate", "Invoice",
              "Note"]
    if with_cost:
        header.insert(9, "Cost rate")
    out: list[list[object]] = []
    for e in rows:
        assert isinstance(e, Entry)
        p = projects.get(e.project_id)
        line: list[object] = [e.work_date.isoformat(), names.get(e.user_id, ""), p.code if p else "",
                              p.name if p else "",
                              e.task or "", str(timesheet.hours(e.minutes)), "yes" if e.billable else "no", e.status,
                              str(e.bill_rate) if e.bill_rate is not None else "", "invoiced" if e.invoice_id else "",
                              e.note or ""]
        if with_cost:
            line.insert(9, str(e.cost_rate) if e.cost_rate is not None else "")
        out.append(line)
    return header, out


# --------------------------------------------------------------------------- what the owner acts on
@dataclass
class RealisationRow:
    key: str                         # a project id or a client id
    code: str
    name: str
    standard: Decimal                # what the work was worth at its rates
    billed: Decimal                  # what was invoiced
    written_down: Decimal            # billed for less, with a reason
    written_off: Decimal             # billed at nothing, with a reason
    percent: Decimal | None


def realisation(session: Session, company_id: UUID, date_from: date, date_to: date) -> tuple[
        RealisationRow, list[RealisationRow], list[RealisationRow]]:
    """Of the work invoiced in the period (time, expenses, milestones), how much of its worth was billed. Returns the
    total, then per client, then per project. Realisation is billed / worth; the rest is written down or off."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    zone = getattr(company_zone(session, company_id), "key", "UTC")
    visible = _visible_projects(company_id)
    rows = session.execute(text(
        "select l.project_id, p.client_id, p.code, p.name, "
        "coalesce(sum(coalesce(l.list_amount, l.amount)), 0) as standard, coalesce(sum(l.amount), 0) as billed, "
        "coalesce(sum(coalesce(l.list_amount, l.amount)) filter (where l.amount = 0), 0) as off "
        "from timebilling.invoice_batch_line l join timebilling.invoice_batch b on b.id = l.batch_id "
        "join timebilling.project p on p.id = l.project_id "
        "where b.company_id = :c and b.status = 'issued' and l.kind in ('time', 'expense', 'milestone') "
        "and (b.issued_at at time zone :z)::date between :a and :b "
        "and l.project_id in (select id from timebilling.project where id = any(cast(:v as uuid[]))) "
        "group by l.project_id, p.client_id, p.code, p.name"),
        {"c": str(company_id), "z": zone, "a": date_from, "b": date_to,
         "v": [str(i) for i in session.scalars(visible)]}).all()
    names = common.customer_names(session, {r.client_id for r in rows})

    def make(key: str, code: str, name: str, standard: Decimal, billed: Decimal, off: Decimal) -> RealisationRow:
        pct = (billed * 100 / standard).quantize(Decimal("0.1")) if standard > 0 else None
        return RealisationRow(key, code, name, standard, billed, standard - billed - off, off, pct)

    projects_out = [make(str(r.project_id), r.code, r.name, Decimal(r.standard), Decimal(r.billed), Decimal(r.off))
                    for r in rows]
    by_client: dict[UUID, list[Any]] = {}
    for r in rows:
        by_client.setdefault(r.client_id, []).append(r)
    clients_out = [make(str(cid), "", names.get(cid, ""), sum((Decimal(x.standard) for x in rs), Decimal(0)),
                        sum((Decimal(x.billed) for x in rs), Decimal(0)), sum((Decimal(x.off) for x in rs), Decimal(0)))
                   for cid, rs in by_client.items()]
    total = make("", "", "", sum((Decimal(r.standard) for r in rows), Decimal(0)),
                 sum((Decimal(r.billed) for r in rows), Decimal(0)), sum((Decimal(r.off) for r in rows), Decimal(0)))
    return (total, sorted(clients_out, key=lambda x: x.standard - x.billed, reverse=True),
            sorted(projects_out, key=lambda x: x.standard - x.billed, reverse=True))


@dataclass
class RiskRow:
    project_id: UUID
    code: str
    name: str
    client_id: UUID
    state: str                       # near | over
    percent: Decimal
    reason: str                      # hours | money | cap
    logged_minutes: int
    budget_minutes: int | None
    over_cap_amount: Decimal


def projects_at_risk(session: Session, company_id: UUID) -> list[RiskRow]:
    """Active projects at or over the budget alert level (hours, money or fee cap), worst first."""
    out: list[RiskRow] = []
    for p in session.scalars(select(Project).where(
            Project.id.in_(_visible_projects(company_id)), Project.status == "active")):
        if p.budget_minutes is None and p.budget_amount is None and p.fee_cap is None:
            continue
        s = project_summary(session, p.id)
        if s.budget_state not in ("near", "over"):
            continue
        candidates = [("hours", s.budget_minutes_percent), ("money", s.budget_amount_percent),
                      ("cap", s.fee_cap_percent)]
        reason, percent = max(((r, v) for r, v in candidates if v is not None), key=lambda x: x[1])
        out.append(RiskRow(p.id, p.code, p.name, p.client_id, s.budget_state, percent, reason, s.logged_minutes,
                           p.budget_minutes, s.over_cap_amount))
    return sorted(out, key=lambda r: r.percent, reverse=True)
