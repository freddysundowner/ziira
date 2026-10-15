"""HTTP endpoints of the Command Center: the overview, briefs and when they are sent, and the dashboard layout."""

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from ziira.modules.command.api.schemas import (
    BriefOut,
    BriefPreviewOut,
    BriefSummaryOut,
    Channel,
    FigureOut,
    Kind,
    OverviewOut,
    ScheduleIn,
    ScheduleOut,
    TopFindingOut,
    WidgetIn,
    WidgetOut,
)
from ziira.modules.command.permissions import BRIEFS_MANAGE, COMMAND_VIEW
from ziira.modules.command.repository import command_repo as repo
from ziira.modules.command.services import briefs, overview, pulse
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_setting,
    current_context,
    page_limit,
    page_offset,
    recipients_with_permission,
    require_permission,
)

router = APIRouter()
VIEW = [Depends(require_permission(COMMAND_VIEW))]
MANAGE = [Depends(require_permission(BRIEFS_MANAGE))]
NO_CONTENT = 204


def _me(session: Session):  # type: ignore[no-untyped-def]
    ctx = current_context()
    if ctx.user_id is None:
        raise Forbidden("Briefs are for signed-in people")
    person = next((p for p in recipients_with_permission(session, COMMAND_VIEW) if p.user_id == ctx.user_id), None)
    if person is None:
        raise Forbidden("You do not have permission 'command.view'")
    return person


def _company(session: Session, company_id: UUID | None) -> UUID:
    """The company asked for (checked against the user's reach), else the first they can see."""
    ctx = current_context()
    allowed = ctx.companies_with(COMMAND_VIEW)
    if company_id is not None:
        check_company(session, company_id)
        if allowed is not None and company_id not in allowed:
            raise Forbidden("You do not have permission 'command.view' for this company")
        return company_id
    row = next((c for c in session.execute(text("select id from kernel.company order by name")).scalars()
                if allowed is None or c in allowed), None)
    if row is None:
        raise NotFound("No company to show")
    return UUID(str(row))


def _today(session: Session, company_id: UUID) -> date:
    return datetime.now(ZoneInfo(str(company_setting(session, company_id, "timezone")))).date()


@router.get("/overview", response_model=OverviewOut, dependencies=VIEW)
def get_overview(company_id: UUID | None = None, day: date | None = None,
                 session: Session = DB_SESSION) -> object:
    """The figures for today so far (against yesterday) and the findings that need the user, within their role."""
    cid = _company(session, company_id)
    o = overview.build(session, current_context(), cid, day or _today(session, cid))
    return OverviewOut(
        company_id=o.company_id, company_name=o.company_name, currency=o.currency, day=o.day,
        figures=[FigureOut(metric=f.metric, label=f.label, kind=f.kind, value=f.value, previous=f.previous,  # type: ignore[arg-type]
                           branch_id=f.branch_id, branch_name=f.branch_name, higher_is_better=f.higher_is_better)
                 for f in o.figures],
        refreshed_at=o.refreshed_at, open_findings=o.open_findings, findings_by_severity=o.findings_by_severity,
        top_findings=[TopFindingOut(id=t.id, severity=t.severity, area=t.area, summary=t.summary,
                                    recommended_action=t.recommended_action, status=t.status, branch_id=t.branch_id,
                                    amount=t.amount, reason=t.reason) for t in o.top_findings])


@router.post("/pulse/refresh", status_code=NO_CONTENT, dependencies=MANAGE)
def post_refresh(company_id: UUID | None = None, session: Session = DB_SESSION) -> Response:
    """Collect today's figures again now (they are also collected every hour)."""
    cid = _company(session, company_id)
    pulse.refresh_company(session, cid, _today(session, cid))
    return Response(status_code=NO_CONTENT)


# --------------------------------------------------------------------------- when briefs are sent
def _out(row: object, user_name: str | None = None) -> ScheduleOut:
    return ScheduleOut(id=row.id, user_id=row.user_id, user_name=user_name or getattr(row, "user_name", None),  # type: ignore[attr-defined]
                       kind=row.kind, channel=row.channel, send_time=row.send_time, weekday=row.weekday,  # type: ignore[attr-defined]
                       is_active=row.is_active)  # type: ignore[attr-defined]


@router.get("/schedules/mine", response_model=list[ScheduleOut], dependencies=VIEW)
def get_my_schedules(session: Session = DB_SESSION) -> object:
    return [_out(r) for r in repo.list_schedules(session, current_context().user_id)]


@router.put("/schedules/mine/{kind}", response_model=ScheduleOut, dependencies=VIEW)
def put_my_schedule(kind: Kind, body: ScheduleIn, session: Session = DB_SESSION) -> object:
    """Choose when and how you get your brief. SMS or email needs that contact on your profile."""
    person = _me(session)
    if kind == "weekly" and body.weekday is None:
        raise ValidationFailed("A weekly brief needs a weekday")
    if body.channel == "sms" and not person.phone:
        raise ValidationFailed("Add a phone number to your profile to get briefs by SMS")
    if body.channel == "email" and not person.email:
        raise ValidationFailed("Add an email address to your profile to get briefs by email")
    row = repo.save_schedule(session, person.user_id, kind, body.channel, body.send_time,
                             body.weekday if kind == "weekly" else None, body.is_active)
    audit_record(session, "command.schedule", "command.brief_schedule", row.id, {"kind": kind, "channel": body.channel})
    return _out(row)


@router.delete("/schedules/mine/{kind}", status_code=NO_CONTENT, dependencies=VIEW)
def delete_my_schedule(kind: Kind, session: Session = DB_SESSION) -> Response:
    repo.delete_schedule(session, _me(session).user_id, kind)
    return Response(status_code=NO_CONTENT)


@router.get("/schedules", response_model=list[ScheduleOut], dependencies=MANAGE)
def get_all_schedules(session: Session = DB_SESSION) -> object:
    """Everyone's brief schedules (for the people who manage them)."""
    return [_out(r) for r in repo.list_schedules(session, None)]


# --------------------------------------------------------------------------- briefs
@router.get("/briefs", response_model=list[BriefSummaryOut], dependencies=VIEW)
def get_briefs(limit: int = page_limit(20), offset: int = page_offset(),
               session: Session = DB_SESSION) -> object:
    """Briefs sent to you, newest first."""
    return [BriefSummaryOut(**dict(r._mapping)) for r in repo.list_briefs(session, _me(session).user_id, limit, offset)]


@router.get("/briefs/{brief_id}", response_model=BriefOut, dependencies=VIEW)
def get_brief(brief_id: UUID, session: Session = DB_SESSION) -> object:
    row = repo.get_brief(session, _me(session).user_id, brief_id)
    if row is None:
        raise NotFound("Brief not found")
    repo.mark_read(session, brief_id)
    return BriefOut(**{k: v for k, v in row._mapping.items() if k != "data"})


@router.post("/briefs/preview", response_model=BriefPreviewOut, dependencies=VIEW)
def post_preview(kind: Kind = "daily", company_id: UUID | None = None,
                 session: Session = DB_SESSION) -> object:
    """What your brief would say right now. Nothing is stored or sent."""
    cid = _company(session, company_id)
    brief, _ = briefs.build(session, _me(session), cid, kind, _today(session, cid))
    return BriefPreviewOut(subject=brief.subject, body=brief.body, short=brief.short)


@router.post("/briefs/send-now", response_model=BriefSummaryOut | None, dependencies=VIEW)
def post_send_now(kind: Kind = "daily", channel: Channel = "in_app", company_id: UUID | None = None,
                  session: Session = DB_SESSION) -> object:
    """Compose your brief and send it now, by the channel chosen (once per day and kind)."""
    person = _me(session)
    cid = _company(session, company_id)
    today = _today(session, cid)
    brief, data = briefs.build(session, person, cid, kind, today)
    brief_id = briefs.deliver(session, person, cid, kind, today, channel, brief, data)
    if brief_id is None:
        raise ValidationFailed("You already have this brief for today: open it from your briefs")
    row = repo.get_brief(session, person.user_id, brief_id)
    assert row is not None
    return BriefSummaryOut(**{k: v for k, v in row._mapping.items() if k not in ("data", "body")})


# --------------------------------------------------------------------------- dashboard layout
@router.get("/dashboard/widgets", response_model=list[WidgetOut], dependencies=VIEW)
def get_widgets(session: Session = DB_SESSION) -> object:
    user = current_context().user_id
    return [WidgetOut(widget_code=r.widget_code, position=r.position, settings=dict(r.settings or {}))
            for r in repo.widgets(session, user)] if user else []


@router.put("/dashboard/widgets", response_model=list[WidgetOut], dependencies=VIEW)
def put_widgets(body: list[WidgetIn], session: Session = DB_SESSION) -> object:
    """Choose and order the boxes on your Command Center."""
    user = current_context().user_id
    if user is None:
        raise Forbidden("The layout belongs to a signed-in person")
    if len({w.widget_code for w in body}) != len(body) or len(body) > 30:
        raise ValidationFailed("Each box may appear once, up to 30")
    repo.replace_widgets(session, user, [(w.widget_code, dict(w.settings)) for w in body])
    return [WidgetOut(widget_code=w.widget_code, position=i, settings=w.settings) for i, w in enumerate(body)]
