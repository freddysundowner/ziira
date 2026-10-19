"""HTTP endpoints of the Time and Billing module. Routes only convert HTTP to service calls."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from ziira.modules.timebilling.api import schemas as sc
from ziira.modules.timebilling.permissions import (
    ALL,
    PROJECTS_MANAGE,
    RATES_MANAGE,
    TIME_APPROVE,
    TIME_BILL,
    TIME_LOG,
    TIME_PARTNER,
    TIME_SETTINGS,
    TIME_VIEW,
)
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import (
    ClientTerms,
    Entry,
    Expense,
    Project,
    Retainer,
    Week,
)
from ziira.modules.timebilling.services import (
    access,
    billing,
    common,
    engagements,
    entries,
    expenses,
    nudges,
    projects,
    rate_cards,
    reports,
    retainers,
    sample_data,
    settings,
    setup,
    timers,
    weeks,
)
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    RequestContext,
    Session,
    company_today,
    idempotency_key_header,
    idempotent,
    page_limit,
    page_offset,
    request_context,
    to_csv,
)

router = APIRouter()
CREATED = status.HTTP_201_CREATED


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(*ALL))]
LOG = [Depends(any_of(TIME_LOG))]
READ_TIME = [Depends(any_of(TIME_LOG, TIME_VIEW, TIME_APPROVE))]
REPORT = [Depends(any_of(TIME_VIEW, TIME_APPROVE))]
APPROVE = [Depends(any_of(TIME_APPROVE))]
BILL = [Depends(any_of(TIME_BILL))]
PROJECTS = [Depends(any_of(PROJECTS_MANAGE))]
RATES = [Depends(any_of(RATES_MANAGE))]
SETTINGS = [Depends(any_of(TIME_SETTINGS))]
STAFF_EDIT = [Depends(any_of(PROJECTS_MANAGE, TIME_SETTINGS))]
PARTNER = [Depends(any_of(TIME_PARTNER))]


# --------------------------------------------------------------------------- output helpers
def _project_out(session: Session, ps: list[Project]) -> list[sc.ProjectOut]:
    names = common.customer_names(session, {p.client_id for p in ps})
    out = []
    for p in ps:
        o = sc.ProjectOut.model_validate(p)
        o.client_name = names.get(p.client_id, "")
        out.append(o)
    return out


def _entry_outs(session: Session, rows: list[Entry]) -> list[sc.TimeBillingEntryOut]:
    names = common.user_names(session, {e.user_id for e in rows})
    ps = repo.projects_by_ids(session, {e.project_id for e in rows})
    out = []
    seen_cost: dict[UUID, bool] = {}
    for e in rows:
        o = sc.TimeBillingEntryOut.model_validate(e)
        o.user_name = names.get(e.user_id, "")
        p = ps.get(e.project_id)
        o.project_code, o.project_name = (p.code, p.name) if p else ("", "")
        if e.company_id not in seen_cost:
            seen_cost[e.company_id] = rate_cards.can_see_cost(e.company_id)
        if not seen_cost[e.company_id]:
            o.cost_rate = None
        o.in_review = e.batch_id is not None and e.invoice_id is None
        out.append(o)
    return out


def _expense_outs(session: Session, rows: list[Expense]) -> list[sc.TimeBillingExpenseOut]:
    names = common.user_names(session, {e.user_id for e in rows})
    ps = repo.projects_by_ids(session, {e.project_id for e in rows})
    out = []
    for e in rows:
        o = sc.TimeBillingExpenseOut.model_validate(e)
        o.user_name = names.get(e.user_id, "")
        p = ps.get(e.project_id)
        o.project_code, o.project_name = (p.code, p.name) if p else ("", "")
        out.append(o)
    return out


def _week_out(session: Session, view: weeks.WeekView) -> sc.WeekOut:
    names = common.user_names(session, {view.user_id})
    w = view.week
    return sc.WeekOut(
        week_id=w.id if w else None, company_id=view.company_id, user_id=view.user_id,
        user_name=names.get(view.user_id, ""), week_start=view.week_start, status=view.status,
        approval_pending=bool(w and w.approval_pending), decision_note=w.decision_note if w else None,
        minutes=view.minutes, billable_minutes=view.billable_minutes, submitted_at=w.submitted_at if w else None,
        entries=_entry_outs(session, view.entries), expenses=_expense_outs(session, view.expenses))


def _review_out(v: billing.BatchView) -> sc.ReviewOut:
    b = v.batch
    lines = []
    for x in v.lines:
        o = sc.ReviewLineOut.model_validate(x)
        o.entry_count, o.expense_count = len(x.entry_ids), len(x.expense_ids)
        lines.append(o)
    return sc.ReviewOut(
        id=b.id, company_id=b.company_id, branch_id=b.branch_id, client_id=b.client_id, client_name=v.client_name,
        project_id=b.project_id, status=b.status, group_by=b.group_by, round_minutes=b.round_minutes,
        due_days=b.due_days, memo=b.memo, invoice_id=b.invoice_id, invoice_number=b.invoice_number, total=b.total,
        tax_total=b.tax_total, net_total=v.net_total, estimated_tax=v.estimated_tax, created_at=b.created_at,
        lines=lines, problems=v.problems,
        problem_items=[sc.TimeBillingProblemOut(code=c, line_no=n) for c, n in v.problem_items],
        write_down=v.write_down, review_status=b.review_status, review_note=b.review_note, review_by=b.review_by,
        review_needed=v.review_needed, narrative=b.narrative)


def _retainer_outs(session: Session, rows: list[Retainer]) -> list[sc.RetainerOut]:
    ps = repo.projects_by_ids(session, {r.project_id for r in rows})
    out = []
    for r in rows:
        o = sc.RetainerOut.model_validate(r)
        p = ps.get(r.project_id)
        o.project_code, o.project_name = (p.code, p.name) if p else ("", "")
        o.used_percent = retainers.used_percent(r)
        out.append(o)
    return out


# --------------------------------------------------------------------------- settings and staff
@router.get("/settings", response_model=sc.TimeBillingSettingsOut, dependencies=VIEW)
def get_settings(company_id: UUID, session: Session = DB_SESSION) -> object:
    return settings.get_settings(session, company_id)


@router.put("/settings", response_model=sc.TimeBillingSettingsOut, dependencies=SETTINGS)
def put_settings(body: sc.TimeBillingSettingsUpdate, session: Session = DB_SESSION) -> object:
    data = body.model_dump(exclude_unset=True)
    return settings.update_settings(session, data.pop("company_id"), **data)


@router.get("/staff", response_model=list[sc.StaffOut], dependencies=VIEW)
def get_staff(company_id: UUID, session: Session = DB_SESSION) -> object:
    return [sc.StaffOut(user_id=s.user_id, name=s.name, email=s.email, title=s.title,
                        weekly_capacity_minutes=s.weekly_capacity_minutes, active=s.active, approver_id=s.approver_id,
                        away_until=s.away_until, nudges=s.nudges)
            for s in settings.list_staff(session, company_id)]


@router.put("/staff/{user_id}", response_model=sc.StaffOut, dependencies=STAFF_EDIT)
def put_staff(user_id: UUID, body: sc.StaffIn, session: Session = DB_SESSION) -> object:
    row = settings.set_staff(session, body.company_id, user_id, title=body.title,
                             weekly_capacity_minutes=body.weekly_capacity_minutes, active=body.active,
                             approver_id=body.approver_id, away_until=body.away_until, nudges=body.nudges)
    name = common.user_names(session, {user_id}).get(user_id, "")
    return sc.StaffOut(user_id=user_id, name=name, email=None, title=row.title,
                       weekly_capacity_minutes=row.weekly_capacity_minutes, active=row.active,
                       approver_id=row.approver_id, away_until=row.away_until, nudges=row.nudges)


# --------------------------------------------------------------------------- clients
@router.get("/clients", response_model=list[sc.ClientOut], dependencies=VIEW)
def get_clients(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Customers that have projects or billing settings here, with what is unbilled for each."""
    project_rows = projects.list_projects(session, company_id=company_id, limit=200)
    terms = {t.customer_id: t for t in session.scalars(select(ClientTerms).where(ClientTerms.company_id == company_id))}
    counts: dict[UUID, int] = {}
    for p in project_rows:
        counts[p.client_id] = counts.get(p.client_id, 0) + 1
    owed: dict[UUID, Any] = {}
    for u in reports.unbilled(session, company_id=company_id, as_of=company_today(session, company_id)):
        owed[u.client_id] = owed.get(u.client_id, 0) + u.amount
    ids = set(counts) | set(terms)
    names = common.customer_names(session, ids)
    return sorted((sc.ClientOut(
        customer_id=i, name=names.get(i, ""), payment_terms_days=terms[i].payment_terms_days if i in terms else None,
        invoice_group_by=terms[i].invoice_group_by if i in terms else None,
        billing_notes=terms[i].billing_notes if i in terms else None, active=terms[i].active if i in terms else True,
        expense_markup_percent=terms[i].expense_markup_percent if i in terms else None,
        projects=counts.get(i, 0), unbilled_amount=owed.get(i, 0)) for i in ids), key=lambda c: c.name.casefold())


@router.put("/clients/{customer_id}", response_model=sc.ClientOut, dependencies=PROJECTS)
def put_client(customer_id: UUID, body: sc.ClientTermsIn, session: Session = DB_SESSION) -> object:
    t = settings.set_client_terms(session, body.company_id, customer_id, payment_terms_days=body.payment_terms_days,
                                  invoice_group_by=body.invoice_group_by, billing_notes=body.billing_notes,
                                  active=body.active, expense_markup_percent=body.expense_markup_percent)
    names = common.customer_names(session, {customer_id})
    n = session.scalar(select(func.count()).select_from(Project).where(
        Project.company_id == body.company_id, Project.client_id == customer_id)) or 0
    return sc.ClientOut(customer_id=customer_id, name=names.get(customer_id, ""),
                        payment_terms_days=t.payment_terms_days, invoice_group_by=t.invoice_group_by,
                        billing_notes=t.billing_notes, active=t.active, projects=int(n), unbilled_amount=Decimal(0),
                        expense_markup_percent=t.expense_markup_percent)


# --------------------------------------------------------------------------- projects
@router.post("/projects", response_model=sc.ProjectOut, status_code=CREATED, dependencies=PROJECTS)
def post_project(body: sc.ProjectIn, session: Session = DB_SESSION) -> object:
    return _project_out(session, [projects.create_project(session, **body.model_dump())])[0]


@router.get("/projects", response_model=list[sc.ProjectOut], dependencies=VIEW)
def get_projects(company_id: UUID | None = None, client_id: UUID | None = None,
                 status_: str | None = Query(default=None, alias="status"),
                 search: str | None = Query(default=None, max_length=100), limit: int = page_limit(50),
                 offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return _project_out(session, projects.list_projects(session, company_id=company_id, client_id=client_id,
                                                         status=status_, search=search, limit=limit, offset=offset))


@router.get("/projects/{project_id}", response_model=sc.ProjectOut, dependencies=VIEW)
def get_project(project_id: UUID, session: Session = DB_SESSION) -> object:
    return _project_out(session, [projects.get_project(session, project_id)])[0]


@router.patch("/projects/{project_id}", response_model=sc.ProjectOut, dependencies=PROJECTS)
def patch_project(project_id: UUID, body: sc.ProjectUpdate, session: Session = DB_SESSION) -> object:
    changed = projects.update_project(session, project_id, **body.model_dump(exclude_unset=True))
    return _project_out(session, [changed])[0]


@router.get("/projects/{project_id}/summary", response_model=sc.ProjectSummaryOut, dependencies=REPORT)
def get_project_summary(project_id: UUID, session: Session = DB_SESSION) -> object:
    s = reports.project_summary(session, project_id)
    return sc.ProjectSummaryOut(
        project=_project_out(session, [s.project])[0], logged_minutes=s.logged_minutes,
        billable_minutes=s.billable_minutes, unapproved_minutes=s.unapproved_minutes,
        budget_minutes_percent=s.budget_minutes_percent, budget_amount_percent=s.budget_amount_percent,
        budget_state=s.budget_state, billed_amount=s.billed_amount, unbilled_amount=s.unbilled_amount, cost=s.cost,
        margin=s.margin, margin_percent=s.margin_percent, unpriced_cost_minutes=s.unpriced_cost_minutes,
        fee_cap_percent=s.fee_cap_percent, over_cap_amount=s.over_cap_amount)


@router.get("/projects/{project_id}/milestones", response_model=list[sc.MilestoneOut], dependencies=VIEW)
def get_milestones(project_id: UUID, session: Session = DB_SESSION) -> object:
    return projects.list_milestones(session, project_id)


@router.post("/projects/{project_id}/milestones", response_model=sc.MilestoneOut, status_code=CREATED,
             dependencies=PROJECTS)
def post_milestone(project_id: UUID, body: sc.MilestoneIn, session: Session = DB_SESSION) -> object:
    return projects.add_milestone(session, project_id, **body.model_dump())


@router.patch("/milestones/{milestone_id}", response_model=sc.MilestoneOut, dependencies=PROJECTS)
def patch_milestone(milestone_id: UUID, body: sc.MilestoneUpdate, session: Session = DB_SESSION) -> object:
    return projects.update_milestone(session, milestone_id, **body.model_dump(exclude_unset=True))


@router.delete("/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=PROJECTS)
def delete_milestone(milestone_id: UUID, session: Session = DB_SESSION) -> None:
    projects.delete_milestone(session, milestone_id)


# --------------------------------------------------------------------------- rates
@router.get("/rates", response_model=list[sc.RateOut], dependencies=VIEW)
def get_rates(company_id: UUID, kind: str | None = Query(default=None, pattern="^(bill|cost)$"),
              session: Session = DB_SESSION) -> object:
    return rate_cards.list_rates(session, company_id, kind=kind)


@router.post("/rates", response_model=sc.RateOut, status_code=CREATED, dependencies=RATES)
def post_rate(body: sc.RateIn, session: Session = DB_SESSION) -> object:
    return rate_cards.create_rate(session, **body.model_dump())


@router.patch("/rates/{rate_id}", response_model=sc.RateOut, dependencies=RATES)
def patch_rate(rate_id: UUID, body: sc.RateUpdate, session: Session = DB_SESSION) -> object:
    return rate_cards.update_rate(session, rate_id, **body.model_dump(exclude_unset=True))


@router.delete("/rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=RATES)
def delete_rate(rate_id: UUID, session: Session = DB_SESSION) -> None:
    rate_cards.delete_rate(session, rate_id)


@router.get("/rates/explain", response_model=sc.ExplainOut, dependencies=VIEW)
def explain_rate(company_id: UUID, day: date, project_id: UUID | None = None, user_id: UUID | None = None,
                 service_product_id: UUID | None = None, kind: str = Query(default="bill", pattern="^(bill|cost)$"),
                 session: Session = DB_SESSION) -> object:
    """Which row of the rate card would price this work."""
    found = rate_cards.explain(session, company_id=company_id, day=day, project_id=project_id, user_id=user_id,
                               service_product_id=service_product_id, kind=kind)
    return sc.ExplainOut(rate=sc.RateOut.model_validate(found) if found else None)


# --------------------------------------------------------------------------- time entries
@router.post("/entries", response_model=sc.TimeBillingEntryOut, status_code=CREATED, dependencies=LOG)
def post_entry(body: sc.EntryIn, session: Session = DB_SESSION) -> object:
    return _entry_outs(session, [entries.create_entry(session, **body.model_dump())])[0]


@router.get("/entries", response_model=list[sc.TimeBillingEntryOut], dependencies=READ_TIME)
def get_entries(user_id: UUID | None = None, project_id: UUID | None = None, client_id: UUID | None = None,
                date_from: date | None = None, date_to: date | None = None,
                status_: str | None = Query(default=None, alias="status", pattern="^(draft|submitted|approved)$"),
                billable: bool | None = None, limit: int = page_limit(100), offset: int = page_offset(),
                session: Session = DB_SESSION) -> object:
    return _entry_outs(session, entries.list_entries(
        session, user_id=user_id, project_id=project_id, client_id=client_id, date_from=date_from, date_to=date_to,
        status=status_, billable=billable, limit=limit, offset=offset))


@router.patch("/entries/{entry_id}", response_model=sc.TimeBillingEntryOut, dependencies=LOG)
def patch_entry(entry_id: UUID, body: sc.EntryUpdate, session: Session = DB_SESSION) -> object:
    return _entry_outs(session, [entries.update_entry(session, entry_id, **body.model_dump(exclude_unset=True))])[0]


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=LOG)
def delete_entry(entry_id: UUID, session: Session = DB_SESSION) -> None:
    entries.delete_entry(session, entry_id)


@router.put("/grid", response_model=list[sc.TimeBillingEntryOut], dependencies=LOG)
def put_grid(body: sc.GridIn, session: Session = DB_SESSION) -> object:
    """Save cells of the week grid (project, task, day -> minutes; 0 clears). Safe to send twice."""
    saved = entries.save_grid(session, [entries.GridCell(**c.model_dump()) for c in body.cells])
    return _entry_outs(session, saved)


# --------------------------------------------------------------------------- timer
def _timer_out(session: Session, v: timers.TimerView) -> sc.TimerOut:
    p = session.get(Project, v.timer.project_id)
    t = v.timer
    return sc.TimerOut(project_id=t.project_id, project_code=p.code if p else "", project_name=p.name if p else "",
                       task=t.task, note=t.note, billable=t.billable, started_at=t.started_at, running=v.running,
                       elapsed_seconds=v.elapsed_seconds)


@router.get("/timer", response_model=sc.TimerOut | None, dependencies=LOG)
def get_timer(session: Session = DB_SESSION) -> object:
    v = timers.current(session)
    return _timer_out(session, v) if v else None


@router.post("/timer/start", response_model=sc.TimerOut, status_code=CREATED, dependencies=LOG)
def post_timer_start(body: sc.TimerStartIn, key: str | None = Depends(idempotency_key_header),
                     session: Session = DB_SESSION) -> object:
    """Start your timer. Send an Idempotency-Key so a retry does not fail with 'already running'."""
    def start() -> object:
        return jsonable_encoder(_timer_out(session, timers.start(session, **body.model_dump())))

    response, _ = idempotent(session, key, body.model_dump(mode="json"), start)
    return response


@router.post("/timer/pause", response_model=sc.TimerOut, dependencies=LOG)
def post_timer_pause(session: Session = DB_SESSION) -> object:
    return _timer_out(session, timers.pause(session))


@router.post("/timer/resume", response_model=sc.TimerOut, dependencies=LOG)
def post_timer_resume(session: Session = DB_SESSION) -> object:
    return _timer_out(session, timers.resume(session))


@router.patch("/timer", response_model=sc.TimerOut, dependencies=LOG)
def patch_timer(body: sc.TimerUpdateIn, session: Session = DB_SESSION) -> object:
    return _timer_out(session, timers.update(session, task=body.task, note=body.note, billable=body.billable))


@router.post("/timer/stop", response_model=sc.TimeBillingEntryOut, dependencies=LOG)
def post_timer_stop(body: sc.TimerStopIn, session: Session = DB_SESSION) -> object:
    """Stop the timer and save the time as an entry."""
    return _entry_outs(session, [timers.stop(session, minutes=body.minutes)])[0]


@router.post("/timer/discard", status_code=status.HTTP_204_NO_CONTENT, dependencies=LOG)
def post_timer_discard(session: Session = DB_SESSION) -> None:
    timers.discard(session)


# --------------------------------------------------------------------------- expenses
@router.post("/expenses", response_model=sc.TimeBillingExpenseOut, status_code=CREATED, dependencies=LOG)
def post_expense(body: sc.TimeBillingExpenseIn, session: Session = DB_SESSION) -> object:
    return _expense_outs(session, [expenses.create_expense(session, **body.model_dump())])[0]


@router.get("/expenses", response_model=list[sc.TimeBillingExpenseOut], dependencies=READ_TIME)
def get_expenses(user_id: UUID | None = None, project_id: UUID | None = None,
                 status_: str | None = Query(default=None, alias="status", pattern="^(draft|submitted|approved)$"),
                 date_from: date | None = None, date_to: date | None = None, limit: int = page_limit(100),
                 offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return _expense_outs(session, expenses.list_expenses(
        session, user_id=user_id, project_id=project_id, status=status_, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset))


@router.patch("/expenses/{expense_id}", response_model=sc.TimeBillingExpenseOut, dependencies=LOG)
def patch_expense(expense_id: UUID, body: sc.ExpenseUpdate, session: Session = DB_SESSION) -> object:
    changed = expenses.update_expense(session, expense_id, **body.model_dump(exclude_unset=True))
    return _expense_outs(session, [changed])[0]


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=LOG)
def delete_expense(expense_id: UUID, session: Session = DB_SESSION) -> None:
    expenses.delete_expense(session, expense_id)


# --------------------------------------------------------------------------- weeks
@router.get("/weeks/mine", response_model=sc.WeekOut, dependencies=LOG)
def get_my_week(company_id: UUID, week_start: date | None = None, user_id: UUID | None = None,
                session: Session = DB_SESSION) -> object:
    """Your week (or, with 'time.view', another person's): entries, expenses and where the week stands."""
    me = access.user_id()
    day = week_start or company_today(session, company_id)
    return _week_out(session, weeks.view_week(session, company_id, user_id or me, day))


@router.get("/weeks", response_model=list[sc.WeekRow], dependencies=READ_TIME)
def get_weeks(status_: str | None = Query(default=None, alias="status",
                                          pattern="^(draft|submitted|approved|rejected)$"),
              user_id: UUID | None = None, company_id: UUID | None = None, limit: int = page_limit(50),
              offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    rows = weeks.list_weeks(session, status=status_, user_id=user_id, company_id=company_id, limit=limit,
                            offset=offset)
    names = common.user_names(session, {w.user_id for w in rows})
    return [sc.WeekRow(id=w.id, company_id=w.company_id, user_id=w.user_id, user_name=names.get(w.user_id, ""),
                       week_start=w.week_start, status=w.status, approval_pending=w.approval_pending,
                       minutes=w.minutes, submitted_at=w.submitted_at, decision_note=w.decision_note) for w in rows]


@router.get("/weeks/{week_id}", response_model=sc.WeekOut, dependencies=READ_TIME)
def get_week(week_id: UUID, session: Session = DB_SESSION) -> object:
    w = repo.get(session, Week, week_id)
    if w is None:
        from ziira.sdk import NotFound

        raise NotFound("Week not found")
    return _week_out(session, weeks.view_week(session, w.company_id, w.user_id, w.week_start))


@router.post("/weeks/submit", response_model=sc.WeekRow, dependencies=LOG)
def post_submit_week(body: sc.WeekSubmitIn, key: str | None = Depends(idempotency_key_header),
                     session: Session = DB_SESSION) -> object:
    """Send your week for approval. Send an Idempotency-Key so a retry returns the same answer."""
    def submit() -> object:
        w = weeks.submit_week(session, body.company_id, body.week_start)
        return jsonable_encoder(sc.WeekRow(
            id=w.id, company_id=w.company_id, user_id=w.user_id,
            user_name=common.user_names(session, {w.user_id}).get(w.user_id, ""), week_start=w.week_start,
            status=w.status, approval_pending=w.approval_pending, minutes=w.minutes, submitted_at=w.submitted_at,
            decision_note=w.decision_note))

    response, _ = idempotent(session, key, body.model_dump(mode="json"), submit)
    return response


def _week_row(session: Session, w: Week) -> sc.WeekRow:
    return sc.WeekRow(id=w.id, company_id=w.company_id, user_id=w.user_id,
                      user_name=common.user_names(session, {w.user_id}).get(w.user_id, ""), week_start=w.week_start,
                      status=w.status, approval_pending=w.approval_pending, minutes=w.minutes,
                      submitted_at=w.submitted_at, decision_note=w.decision_note)


@router.post("/weeks/{week_id}/approve", response_model=sc.WeekRow, dependencies=APPROVE)
def post_approve_week(week_id: UUID, body: sc.TimeBillingNoteIn, session: Session = DB_SESSION) -> object:
    return _week_row(session, weeks.approve_week(session, week_id, body.note))


@router.post("/weeks/{week_id}/reject", response_model=sc.WeekRow, dependencies=APPROVE)
def post_reject_week(week_id: UUID, body: sc.TimeBillingNoteIn, session: Session = DB_SESSION) -> object:
    return _week_row(session, weeks.reject_week(session, week_id, body.note))


@router.post("/weeks/{week_id}/reopen", response_model=sc.WeekRow, dependencies=APPROVE)
def post_reopen_week(week_id: UUID, body: sc.TimeBillingNoteIn, session: Session = DB_SESSION) -> object:
    return _week_row(session, weeks.reopen_week(session, week_id, body.note))


@router.post("/weeks/{week_id}/recall", response_model=sc.WeekRow, dependencies=LOG)
def post_recall_week(week_id: UUID, session: Session = DB_SESSION) -> object:
    return _week_row(session, weeks.recall_week(session, week_id))


# --------------------------------------------------------------------------- unbilled work and invoicing
@router.get("/unbilled", response_model=list[sc.UnbilledOut], dependencies=REPORT)
def get_unbilled(company_id: UUID | None = None, client_id: UUID | None = None, project_id: UUID | None = None,
                 session: Session = DB_SESSION) -> object:
    """Approved work not yet invoiced, by project, with its age."""
    rows = reports.unbilled(session, company_id=company_id, client_id=client_id, project_id=project_id,
                            as_of=company_today(session, company_id) if company_id else date.today())
    names = common.customer_names(session, {r.client_id for r in rows})
    today = company_today(session, company_id) if company_id else date.today()
    return [sc.UnbilledOut(
        project_id=r.project_id, project_code=r.project_code, project_name=r.project_name, client_id=r.client_id,
        client_name=names.get(r.client_id, ""), billing_mode=r.billing_mode, minutes=r.minutes,
        time_amount=r.time_amount, expense_amount=r.expense_amount, milestone_amount=r.milestone_amount,
        amount=r.amount, unpriced_minutes=r.unpriced_minutes, in_review_minutes=r.in_review_minutes, oldest=r.oldest,
        age_days=(today - r.oldest).days if r.oldest else None, buckets=r.buckets) for r in rows]


@router.post("/invoice-reviews", response_model=sc.ReviewOut, status_code=CREATED, dependencies=BILL)
def post_review(body: sc.ReviewCreateIn, key: str | None = Depends(idempotency_key_header),
                session: Session = DB_SESSION) -> object:
    """Set aside a client's approved work as an invoice review that can be edited before it is issued."""
    def create() -> object:
        return jsonable_encoder(_review_out(billing.create_draft(session, **body.model_dump())))

    response, _ = idempotent(session, key, body.model_dump(mode="json"), create)
    return response


@router.get("/invoice-reviews", response_model=list[sc.ReviewRow], dependencies=BILL)
def get_reviews(company_id: UUID | None = None, client_id: UUID | None = None,
                status_: str | None = Query(default=None, alias="status",
                                            pattern="^(draft|issued|cancelled|discarded)$"),
                limit: int = page_limit(50), offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return billing.list_batches(session, company_id=company_id, client_id=client_id, status=status_, limit=limit,
                                offset=offset)


@router.get("/invoice-reviews/{batch_id}", response_model=sc.ReviewOut, dependencies=BILL)
def get_review(batch_id: UUID, session: Session = DB_SESSION) -> object:
    return _review_out(billing.view_batch(session, batch_id))


@router.patch("/invoice-reviews/{batch_id}", response_model=sc.ReviewOut, dependencies=BILL)
def patch_review(batch_id: UUID, body: sc.ReviewUpdateIn, session: Session = DB_SESSION) -> object:
    return _review_out(billing.update_batch(session, batch_id, **body.model_dump(exclude_unset=True)))


@router.post("/invoice-reviews/{batch_id}/lines", response_model=sc.ReviewOut, status_code=CREATED, dependencies=BILL)
def post_review_line(batch_id: UUID, body: sc.TimeBillingManualLineIn, session: Session = DB_SESSION) -> object:
    return _review_out(billing.add_manual_line(session, batch_id, **body.model_dump()))


@router.patch("/invoice-reviews/{batch_id}/lines/{line_id}", response_model=sc.ReviewOut, dependencies=BILL)
def patch_review_line(batch_id: UUID, line_id: UUID, body: sc.LineUpdateIn, session: Session = DB_SESSION) -> object:
    return _review_out(billing.update_line(session, batch_id, line_id, **body.model_dump(exclude_unset=True)))


@router.delete("/invoice-reviews/{batch_id}/lines/{line_id}", response_model=sc.ReviewOut, dependencies=BILL)
def delete_review_line(batch_id: UUID, line_id: UUID, session: Session = DB_SESSION) -> object:
    return _review_out(billing.remove_line(session, batch_id, line_id))


@router.post("/invoice-reviews/{batch_id}/narrative", response_model=sc.ReviewOut, dependencies=BILL)
def post_review_narrative(batch_id: UUID, body: sc.TimeBillingNarrativeIn, session: Session = DB_SESSION) -> object:
    """Write the account of the work from the entries' notes; optionally into the invoice lines' wording."""
    return _review_out(billing.write_narrative(session, batch_id, into_lines=body.into_lines))


@router.post("/invoice-reviews/{batch_id}/request-review", response_model=sc.ReviewOut, dependencies=BILL)
def post_request_review(batch_id: UUID, session: Session = DB_SESSION) -> object:
    """Ask a partner to look at the review before it goes out."""
    return _review_out(billing.request_review(session, batch_id))


@router.post("/invoice-reviews/{batch_id}/review", response_model=sc.ReviewOut, dependencies=PARTNER)
def post_decide_review(batch_id: UUID, body: sc.TimeBillingReviewDecisionIn, session: Session = DB_SESSION) -> object:
    """A partner approves the review or sends it back with a note."""
    return _review_out(billing.decide_review(session, batch_id, approve=body.approve, note=body.note))


@router.get("/invoice-reviews/{batch_id}/schedule.csv", dependencies=BILL)
def export_schedule(batch_id: UUID, session: Session = DB_SESSION) -> Response:
    """The time and expense schedule behind the review, as a spreadsheet to send with the invoice (audited)."""
    header, rows = billing.schedule(session, batch_id)
    return _csv(f"time-schedule-{str(batch_id)[:8]}.csv", header, rows)


@router.post("/invoice-reviews/{batch_id}/issue", response_model=sc.ReviewOut, dependencies=BILL)
def post_issue_review(batch_id: UUID, session: Session = DB_SESSION) -> object:
    """Issue the invoice. Asking again returns the same invoice."""
    return _review_out(billing.issue_batch(session, batch_id))


@router.post("/invoice-reviews/{batch_id}/discard", response_model=sc.ReviewRow, dependencies=BILL)
def post_discard_review(batch_id: UUID, session: Session = DB_SESSION) -> object:
    return billing.discard_batch(session, batch_id)


# --------------------------------------------------------------------------- retainers
@router.get("/retainers", response_model=list[sc.RetainerOut], dependencies=VIEW)
def get_retainers(company_id: UUID | None = None, project_id: UUID | None = None,
                  status_: str | None = Query(default=None, alias="status", pattern="^(active|closed)$"),
                  session: Session = DB_SESSION) -> object:
    return _retainer_outs(session, retainers.list_retainers(session, company_id=company_id, project_id=project_id,
                                                            status=status_))


@router.post("/projects/{project_id}/retainer", response_model=sc.RetainerOut, status_code=CREATED,
             dependencies=PROJECTS)
def post_retainer(project_id: UUID, body: sc.RetainerIn, session: Session = DB_SESSION) -> object:
    return _retainer_outs(session, [retainers.create_retainer(session, project_id, **body.model_dump())])[0]


@router.get("/retainers/{retainer_id}", response_model=sc.RetainerOut, dependencies=VIEW)
def get_retainer(retainer_id: UUID, session: Session = DB_SESSION) -> object:
    return _retainer_outs(session, [retainers.get_retainer(session, retainer_id)])[0]


@router.patch("/retainers/{retainer_id}", response_model=sc.RetainerOut, dependencies=PROJECTS)
def patch_retainer(retainer_id: UUID, body: sc.RetainerUpdate, session: Session = DB_SESSION) -> object:
    return _retainer_outs(session, [retainers.update_retainer(session, retainer_id,
                                                              **body.model_dump(exclude_unset=True))])[0]


@router.get("/retainers/{retainer_id}/history", response_model=list[sc.RetainerTxnOut], dependencies=VIEW)
def get_retainer_history(retainer_id: UUID, session: Session = DB_SESSION) -> object:
    return retainers.list_txns(session, retainer_id)


@router.post("/retainers/{retainer_id}/topup", response_model=sc.ReviewOut, status_code=CREATED, dependencies=BILL)
def post_topup(retainer_id: UUID, body: sc.TopupIn, session: Session = DB_SESSION) -> object:
    """Start an invoice review for a top-up of prepaid hours."""
    return _review_out(billing.add_retainer_topup(session, retainer_id, **body.model_dump()))


@router.post("/retainers/{retainer_id}/fee", response_model=sc.ReviewOut, status_code=CREATED, dependencies=BILL)
def post_fee(retainer_id: UUID, body: sc.FeeIn, session: Session = DB_SESSION) -> object:
    """Start an invoice review for one month of a monthly-fee retainer."""
    return _review_out(billing.add_retainer_fee(session, retainer_id, **body.model_dump()))


# --------------------------------------------------------------------------- reports
@router.get("/reports/utilisation", response_model=list[sc.UtilisationOut], dependencies=REPORT)
def get_utilisation(company_id: UUID, date_from: date, date_to: date, session: Session = DB_SESSION) -> object:
    if date_to < date_from or (date_to - date_from) > timedelta(days=400):
        from ziira.sdk import ValidationFailed

        raise ValidationFailed("Give a period of up to a year and a day")
    return reports.utilisation(session, company_id, date_from, date_to)


@router.get("/reports/unsubmitted", response_model=list[sc.MissingWeekOut], dependencies=REPORT)
def get_unsubmitted(company_id: UUID, session: Session = DB_SESSION) -> object:
    return reports.unsubmitted_weeks(session, company_id, company_today(session, company_id))


def _csv(name: str, header: list[str], rows: list[list[object]]) -> Response:
    return Response(to_csv(header, rows), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports/entries.csv", dependencies=REPORT)
def export_entries(date_from: date, date_to: date, project_id: UUID | None = None, user_id: UUID | None = None,
                   session: Session = DB_SESSION) -> Response:
    """Time entries as a spreadsheet (every download is audited)."""
    rows = entries.list_entries(session, project_id=project_id, user_id=user_id, date_from=date_from, date_to=date_to,
                                limit=500)
    names = common.user_names(session, {e.user_id for e in rows})
    ps = repo.projects_by_ids(session, {e.project_id for e in rows})
    with_cost = bool(rows) and all(rate_cards.can_see_cost(c) for c in {e.company_id for e in rows})
    header, lines = reports.entries_csv_rows(rows, names, ps, with_cost)
    return _csv(f"time-{date_from}-{date_to}.csv", header, lines)


@router.get("/reports/unbilled.csv", dependencies=REPORT)
def export_unbilled(company_id: UUID, session: Session = DB_SESSION) -> Response:
    rows = reports.unbilled(session, company_id=company_id, as_of=company_today(session, company_id))
    names = common.customer_names(session, {r.client_id for r in rows})
    return _csv("unbilled-work.csv", ["Client", "Project code", "Project", "Hours", "Time", "Expenses", "Milestones",
                                      "Total", "Oldest work"],
                [[names.get(r.client_id, ""), r.project_code, r.project_name, str(round(r.minutes / 60, 2)),
                  str(r.time_amount), str(r.expense_amount), str(r.milestone_amount), str(r.amount),
                  r.oldest.isoformat() if r.oldest else ""] for r in rows])


@router.get("/reports/realisation", response_model=sc.TimeBillingRealisationOut, dependencies=REPORT)
def get_realisation(company_id: UUID, date_from: date, date_to: date, session: Session = DB_SESSION) -> object:
    """Of the work invoiced in the period, how much of its worth was billed, written down and written off."""
    if date_to < date_from or (date_to - date_from) > timedelta(days=800):
        from ziira.sdk import ValidationFailed

        raise ValidationFailed("Give a period of up to two years")
    total, clients, projects_ = reports.realisation(session, company_id, date_from, date_to)
    return sc.TimeBillingRealisationOut(
        total=sc.TimeBillingRealisationRow.model_validate(total, from_attributes=True),
        clients=[sc.TimeBillingRealisationRow.model_validate(r, from_attributes=True) for r in clients],
        projects=[sc.TimeBillingRealisationRow.model_validate(r, from_attributes=True) for r in projects_])


def _risk_out(session: Session, rows: list[reports.RiskRow]) -> list[sc.TimeBillingRiskOut]:
    names = common.customer_names(session, {r.client_id for r in rows})
    return [sc.TimeBillingRiskOut(
        project_id=r.project_id, code=r.code, name=r.name, client_id=r.client_id,
        client_name=names.get(r.client_id, ""), state=r.state, percent=r.percent, reason=r.reason,
        logged_minutes=r.logged_minutes, budget_minutes=r.budget_minutes, over_cap_amount=r.over_cap_amount)
        for r in rows]


@router.get("/reports/at-risk", response_model=list[sc.TimeBillingRiskOut], dependencies=REPORT)
def get_at_risk(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Active projects at or over their budget (hours, money or fee cap), worst first."""
    return _risk_out(session, reports.projects_at_risk(session, company_id))


@router.get("/reports/owner", response_model=sc.TimeBillingOwnerOut, dependencies=REPORT)
def get_owner_summary(company_id: UUID, date_from: date, date_to: date, session: Session = DB_SESSION) -> object:
    """What an owner or partner acts on, in one call: work in progress by age, realisation, utilisation, projects
    at risk, retainers nearly used, work that is late and approvals waiting."""
    from ziira.sdk import ValidationFailed

    if date_to < date_from or (date_to - date_from) > timedelta(days=800):
        raise ValidationFailed("Give a period of up to two years")
    today = company_today(session, company_id)
    wip = reports.unbilled(session, company_id=company_id, as_of=today)
    buckets = {label: Decimal(0) for _, _, label in reports.BUCKETS}
    for row in wip:
        for label, amount in row.buckets.items():
            buckets[label] += amount
    total, _, _ = reports.realisation(session, company_id, date_from, date_to)
    people = reports.utilisation(session, company_id, date_from, date_to)
    capacity = sum(p.capacity_minutes for p in people)
    billable = sum(p.billable_minutes for p in people)
    low = [r for r in retainers.list_retainers(session, company_id=company_id, status="active")
           if r.kind == "hours" and r.topped_up_minutes > 0 and (
               retainers.used_percent(r) >= r.alert_percent or (r.expires_on is not None and r.balance_minutes > 0
                                                               and r.expires_on <= today + timedelta(days=30)))]
    weeks_waiting = len(weeks.list_weeks(session, status="submitted", company_id=company_id, limit=200))
    reviews = len(billing.list_batches(session, company_id=company_id, status="draft", limit=200))
    late = len([t for t in engagements.list_tasks(session, company_id=company_id, status="open", due_before=today,
                                                  limit=500) if t.due_on < today])
    return sc.TimeBillingOwnerOut(
        wip_total=sum(buckets.values(), Decimal(0)),
        wip_buckets=[sc.TimeBillingBucketTotal(label=k, amount=v) for k, v in buckets.items()],
        realisation=sc.TimeBillingRealisationRow.model_validate(total, from_attributes=True),
        utilisation_percent=(Decimal(billable) * 100 / capacity).quantize(Decimal("0.1")) if capacity else None,
        at_risk=_risk_out(session, reports.projects_at_risk(session, company_id)),
        retainers=_retainer_outs(session, low), tasks_overdue=late, weeks_waiting=weeks_waiting,
        reviews_waiting=reviews)


@router.get("/my/missing", response_model=list[sc.TimeBillingMissingDayOut], dependencies=LOG)
def get_my_missing(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Working days in the last two weeks where you logged less than the company's minimum (My week's banner)."""
    return [sc.TimeBillingMissingDayOut(day=d, logged_minutes=got, wanted_minutes=wanted)
            for d, got, wanted in nudges.my_missing(session, company_id, access.user_id(),
                                                    company_today(session, company_id))]


# --------------------------------------------------------------------------- recurring work and its checklists
def _recurrence_outs(session: Session, rows: list[Any]) -> list[sc.TimeBillingRecurrenceOut]:
    ps = repo.projects_by_ids(session, {r.project_id for r in rows})
    out = []
    for r in rows:
        o = sc.TimeBillingRecurrenceOut.model_validate(r)
        p = ps.get(r.project_id)
        o.project_code, o.project_name = (p.code, p.name) if p else ("", "")
        out.append(o)
    return out


def _task_outs(session: Session, rows: list[Any]) -> list[sc.TimeBillingTaskOut]:
    ps = repo.projects_by_ids(session, {r.project_id for r in rows})
    clients = common.customer_names(session, {p.client_id for p in ps.values()})
    people = common.user_names(session, {r.assignee_id for r in rows if r.assignee_id})
    today = {c: company_today(session, c) for c in {r.company_id for r in rows}}
    out = []
    for r in rows:
        p = ps.get(r.project_id)
        out.append(sc.TimeBillingTaskOut(
            id=r.id, company_id=r.company_id, project_id=r.project_id, project_code=p.code if p else "",
            project_name=p.name if p else "", client_name=clients.get(p.client_id, "") if p else "",
            recurrence_id=r.recurrence_id, name=r.name, period=r.period, due_on=r.due_on, status=r.status,
            assignee_id=r.assignee_id, assignee_name=people.get(r.assignee_id, "") if r.assignee_id else "",
            items=[sc.TimeBillingTaskItem(label=i.get("label", ""), done=bool(i.get("done")), by=i.get("by"),
                                          at=i.get("at")) for i in r.items],
            note=r.note, done_at=r.done_at, overdue=r.status == "open" and r.due_on < today[r.company_id]))
    return out


@router.get("/recurrences", response_model=list[sc.TimeBillingRecurrenceOut], dependencies=VIEW)
def get_recurrences(company_id: UUID | None = None, project_id: UUID | None = None,
                    session: Session = DB_SESSION) -> object:
    return _recurrence_outs(session, engagements.list_recurrences(session, company_id=company_id,
                                                                  project_id=project_id))


@router.post("/projects/{project_id}/recurrences", response_model=sc.TimeBillingRecurrenceOut, status_code=CREATED,
             dependencies=PROJECTS)
def post_recurrence(project_id: UUID, body: sc.TimeBillingRecurrenceIn, session: Session = DB_SESSION) -> object:
    return _recurrence_outs(session, [engagements.create_recurrence(session, project_id, **body.model_dump())])[0]


@router.patch("/recurrences/{recurrence_id}", response_model=sc.TimeBillingRecurrenceOut, dependencies=PROJECTS)
def patch_recurrence(recurrence_id: UUID, body: sc.TimeBillingRecurrenceUpdate,
                     session: Session = DB_SESSION) -> object:
    changed = engagements.update_recurrence(session, recurrence_id, **body.model_dump(exclude_unset=True))
    return _recurrence_outs(session, [changed])[0]


@router.get("/tasks", response_model=list[sc.TimeBillingTaskOut], dependencies=VIEW)
def get_tasks(company_id: UUID | None = None, project_id: UUID | None = None,
              status_: str | None = Query(default=None, alias="status", pattern="^(open|done|skipped)$"),
              assignee_id: UUID | None = None, due_before: date | None = None, limit: int = page_limit(200),
              offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return _task_outs(session, engagements.list_tasks(
        session, company_id=company_id, project_id=project_id, status=status_, assignee_id=assignee_id,
        due_before=due_before, limit=limit, offset=offset))


@router.post("/projects/{project_id}/tasks", response_model=sc.TimeBillingTaskOut, status_code=CREATED,
             dependencies=PROJECTS)
def post_task(project_id: UUID, body: sc.TimeBillingTaskIn, session: Session = DB_SESSION) -> object:
    return _task_outs(session, [engagements.add_task(session, project_id, **body.model_dump())])[0]


@router.patch("/tasks/{task_id}", response_model=sc.TimeBillingTaskOut, dependencies=PROJECTS)
def patch_task(task_id: UUID, body: sc.TimeBillingTaskUpdate, session: Session = DB_SESSION) -> object:
    return _task_outs(session, [engagements.update_task(session, task_id, **body.model_dump(exclude_unset=True))])[0]


@router.post("/tasks/{task_id}/tick", response_model=sc.TimeBillingTaskOut, dependencies=VIEW)
def post_tick(task_id: UUID, body: sc.TimeBillingTickIn, session: Session = DB_SESSION) -> object:
    return _task_outs(session, [engagements.tick(session, task_id, body.index, body.done)])[0]


@router.post("/tasks/{task_id}/finish", response_model=sc.TimeBillingTaskOut, dependencies=VIEW)
def post_finish_task(task_id: UUID, body: sc.TimeBillingFinishIn, session: Session = DB_SESSION) -> object:
    return _task_outs(session, [engagements.finish_task(session, task_id, skipped=body.skipped, note=body.note)])[0]


@router.post("/tasks/{task_id}/reopen", response_model=sc.TimeBillingTaskOut, dependencies=PROJECTS)
def post_reopen_task(task_id: UUID, session: Session = DB_SESSION) -> object:
    return _task_outs(session, [engagements.reopen_task(session, task_id)])[0]


# --------------------------------------------------------------------------- templates, activities, wording
@router.get("/templates", response_model=list[sc.TimeBillingTemplateOut], dependencies=VIEW)
def get_templates(company_id: UUID, include_inactive: bool = False, session: Session = DB_SESSION) -> object:
    return engagements.list_templates(session, company_id, include_inactive=include_inactive)


@router.post("/templates", response_model=sc.TimeBillingTemplateOut, status_code=CREATED, dependencies=PROJECTS)
def post_template(body: sc.TimeBillingTemplateIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return engagements.save_template(session, data.pop("company_id"), **data)


@router.put("/templates/{template_id}", response_model=sc.TimeBillingTemplateOut, dependencies=PROJECTS)
def put_template(template_id: UUID, body: sc.TimeBillingTemplateIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return engagements.save_template(session, data.pop("company_id"), template_id=template_id, **data)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=PROJECTS)
def delete_template(template_id: UUID, session: Session = DB_SESSION) -> None:
    engagements.delete_template(session, template_id)


@router.get("/activities", response_model=list[sc.TimeBillingActivityOut], dependencies=READ_TIME)
def get_activities(company_id: UUID, include_inactive: bool = False, session: Session = DB_SESSION) -> object:
    return engagements.list_activities(session, company_id, include_inactive=include_inactive)


@router.post("/activities", response_model=sc.TimeBillingActivityOut, status_code=CREATED, dependencies=PROJECTS)
def post_activity(body: sc.TimeBillingActivityIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return engagements.save_activity(session, data.pop("company_id"), **data)


@router.put("/activities/{activity_id}", response_model=sc.TimeBillingActivityOut, dependencies=PROJECTS)
def put_activity(activity_id: UUID, body: sc.TimeBillingActivityIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return engagements.save_activity(session, data.pop("company_id"), activity_id=activity_id, **data)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=PROJECTS)
def delete_activity(activity_id: UUID, session: Session = DB_SESSION) -> None:
    engagements.delete_activity(session, activity_id)


@router.get("/snippets", response_model=list[sc.TimeBillingSnippetOut], dependencies=VIEW)
def get_snippets(company_id: UUID, kind: str | None = Query(default=None, pattern="^(invoice_note|engagement_note)$"),
                 session: Session = DB_SESSION) -> object:
    return engagements.list_snippets(session, company_id, kind=kind)


@router.post("/snippets", response_model=sc.TimeBillingSnippetOut, status_code=CREATED, dependencies=PROJECTS)
def post_snippet(body: sc.TimeBillingSnippetIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return engagements.save_snippet(session, data.pop("company_id"), **data)


@router.put("/snippets/{snippet_id}", response_model=sc.TimeBillingSnippetOut, dependencies=PROJECTS)
def put_snippet(snippet_id: UUID, body: sc.TimeBillingSnippetIn, session: Session = DB_SESSION) -> object:
    data = body.model_dump()
    return engagements.save_snippet(session, data.pop("company_id"), snippet_id=snippet_id, **data)


@router.delete("/snippets/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=PROJECTS)
def delete_snippet(snippet_id: UUID, session: Session = DB_SESSION) -> None:
    engagements.delete_snippet(session, snippet_id)


# --------------------------------------------------------------------------- getting started and sample data
@router.get("/setup", response_model=sc.TimeBillingSetupOut, dependencies=VIEW)
def get_setup(company_id: UUID, session: Session = DB_SESSION) -> object:
    """The first-run checklist, ticked from what the business has actually done."""
    return setup.checklist(session, company_id)


@router.post("/sample-data", response_model=sc.TimeBillingSampleResult, status_code=CREATED, dependencies=PROJECTS)
def post_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Fill the business with the sample practice its industry pack ships (clients, projects, a week of your time)."""
    return sc.TimeBillingSampleResult(counts=sample_data.load(session, company_id))


@router.delete("/sample-data", response_model=sc.TimeBillingSampleResult, dependencies=PROJECTS)
def delete_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Take the sample practice away again (time already sent in or invoiced stays)."""
    return sc.TimeBillingSampleResult(counts=sample_data.remove(session, company_id))
