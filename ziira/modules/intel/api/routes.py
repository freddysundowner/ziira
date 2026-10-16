"""HTTP endpoints for Intelligence: findings, what people do with them, the checks and running them now."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from ziira.modules.intel.api.action_routes import router as action_router
from ziira.modules.intel.api.ai_routes import router as ai_router
from ziira.modules.intel.api.schemas import (
    AiExplainIn,
    AskIn,
    AssignIn,
    CheckOut,
    CheckUpdateIn,
    DismissIn,
    ExplainIn,
    FindingDetailOut,
    FindingEventOut,
    FindingOut,
    FindingsSummaryOut,
    GroupedFindingsOut,
    IgnoreIn,
    IgnoreOptionsOut,
    IgnoreOut,
    NoteIn,
    PlainOut,
    RecordOut,
    RunIn,
    RunOut,
    SnoozeIn,
    SuppressionOut,
    TopicsIn,
    TopicsOut,
)
from ziira.modules.intel.permissions import FINDINGS_MANAGE, FINDINGS_VIEW
from ziira.modules.intel.public import INTEL_CHECK
from ziira.modules.intel.services import alerts, checks_admin, engine, explain, findings
from ziira.sdk import (
    DB_SESSION,
    Session,
    check_company,
    current_context,
    implementations,
    page_limit,
    page_offset,
    require_permission,
    tenant_transaction,
)

router = APIRouter()
router.include_router(ai_router)
router.include_router(action_router)
VIEW = [Depends(require_permission(FINDINGS_VIEW))]
MANAGE = [Depends(require_permission(FINDINGS_MANAGE))]

Status = Literal["new", "sent", "acknowledged", "explained", "resolved", "dismissed"]
Severity = Literal["info", "low", "medium", "high", "critical"]


def _detail(session: Session, row: object, events: list[object]) -> FindingDetailOut:
    base = FindingOut.model_validate(row)
    check = next((c for c in implementations(session, INTEL_CHECK) if c.code == base.check_code), None)
    kind: Literal["money", "percent", "count", "days", "number"] = "number"
    declared = getattr(check, "value_kind", "number")
    for known in ("money", "percent", "count", "days"):
        if declared == known:
            kind = known
    evidence = getattr(row, "evidence", None) or {}
    return FindingDetailOut(
        **base.model_dump(), check_title=getattr(check, "title", None),
        value_kind=kind, records=[RecordOut(**r) for r in evidence.get("records", [])],
        owner_name=findings.person_name(session, getattr(row, "owner_user_id", None)),
        events=[FindingEventOut(id=e.id, created_at=e.created_at, event=e.event, user_id=e.user_id,  # type: ignore[attr-defined]
                                user_name=e.user_name, channel=e.channel, note=e.note) for e in events])  # type: ignore[attr-defined]


def _after(session: Session, row: object) -> FindingDetailOut:
    _, events = findings.get_for_user(session, row.id)  # type: ignore[attr-defined]
    return _detail(session, row, list(events))


@router.get("/findings", response_model=list[FindingOut], dependencies=VIEW)
def get_findings(status: list[Status] | None = Query(default=None),
                 severity: list[Severity] | None = Query(default=None), area: str | None = None,
                 company_id: UUID | None = None, branch_id: UUID | None = None,
                 check_code: str | None = None, assigned_to_me: bool = False, search: str | None = None,
                 source: Literal["connected", "ziira"] | None = Query(
                     default=None, description="connected: read from the system the business keeps"),
                 snoozed: Literal["hide", "only", "include"] = "hide",
                 view: Literal["open", "waiting", "done"] | None = Query(
                     default=None, description="open: waiting for me; waiting: someone is on it or put aside; done"),
                 limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    """Findings in the user's scope, most serious first. Without a status filter, open ones only (those put aside for
    now are left out unless `snoozed` says otherwise)."""
    return findings.list_for_user(
        session,
        statuses=list(status) if status else ["new", "sent", "acknowledged", "explained"],
        severities=list(severity) if severity else None,
        area=area,
        company_id=company_id,
        branch_id=branch_id,
        check_code=check_code,
        owner_user_id=current_context().user_id if assigned_to_me else None,
        search=search,
        limit=limit,
        offset=offset,
        source=source,
        snoozed=snoozed,
        view=view,
    )


@router.get("/findings/summary", response_model=FindingsSummaryOut, dependencies=VIEW)
def get_summary(session: Session = DB_SESSION) -> object:
    return findings.summary(session)


@router.get("/findings/grouped", response_model=GroupedFindingsOut, dependencies=VIEW)
def get_grouped(
    view: Literal["open", "waiting", "done"] = "open",
    severity: list[Severity] | None = Query(default=None),
    area: str | None = None,
    company_id: UUID | None = None,
    branch_id: UUID | None = None,
    check_code: str | None = None,
    search: str | None = None,
    assigned_to_me: bool = False,
    limit: int = page_limit(20),
    offset: int = page_offset(),
    session: Session = DB_SESSION,
) -> object:
    """Similar findings (same kind, same branch, same day) as one group each, most pressing first: urgency, money at
    stake, recency. The findings themselves are unchanged."""
    return findings.grouped(
        session,
        view=view,
        limit=limit,
        offset=offset,
        severities=list(severity) if severity else None,
        area=area,
        company_id=company_id,
        branch_id=branch_id,
        check_code=check_code,
        search=search,
        owner_user_id=current_context().user_id if assigned_to_me else None,
    )


@router.get("/plain", response_model=PlainOut, dependencies=VIEW)
def get_plain(lang: Literal["en", "sw"] = "en", session: Session = DB_SESSION) -> object:
    """Plain words for checks (title, why it matters, what to do, limits as a sentence), topics, facts and limits."""
    return checks_admin.plain_dictionary(session, lang)


@router.get("/topics", response_model=TopicsOut, dependencies=VIEW)
def get_topics(session: Session = DB_SESSION) -> object:
    return checks_admin.topics_state(session)


@router.put("/topics", response_model=TopicsOut, dependencies=MANAGE)
def put_topics(body: TopicsIn, session: Session = DB_SESSION) -> object:
    """Choose what Ziira watches by topic: every check of a topic is switched on or off."""
    return checks_admin.set_topics(session, body.topics)


@router.get("/ignore-rules", response_model=list[SuppressionOut], dependencies=MANAGE)
def get_ignore_rules(session: Session = DB_SESSION) -> object:
    """The "this is normal" rules in force."""
    return findings.list_rules(session)


@router.delete("/ignore-rules/{rule_id}", status_code=204, dependencies=MANAGE)
def delete_ignore_rule(rule_id: UUID, session: Session = DB_SESSION) -> Response:
    findings.remove_rule(session, rule_id)
    return Response(status_code=204)


@router.get("/findings/{finding_id}/related", response_model=list[FindingOut], dependencies=VIEW)
def get_related(finding_id: UUID, session: Session = DB_SESSION) -> object:
    """Other open findings about the same person or thing, or of the same kind at the same branch."""
    return findings.related(session, finding_id)


@router.get("/findings/{finding_id}/ignore-options", response_model=IgnoreOptionsOut, dependencies=MANAGE)
def get_ignore_options(finding_id: UUID, session: Session = DB_SESSION) -> object:
    return findings.ignore_options(session, finding_id)


@router.post("/findings/{finding_id}/snooze", response_model=FindingDetailOut, dependencies=VIEW)
def post_snooze(finding_id: UUID, body: SnoozeIn, session: Session = DB_SESSION) -> object:
    """Put a finding aside for some days (null days: bring it back). It returns by itself, or sooner if it gets
    worse."""
    return _after(session, findings.snooze(session, finding_id, body.days))


@router.post("/findings/{finding_id}/ignore", response_model=IgnoreOut, dependencies=MANAGE)
def post_ignore(finding_id: UUID, body: IgnoreIn, session: Session = DB_SESSION) -> object:
    """ "Not a problem" for a kind of thing at a branch or for a person, for some days or always."""
    result = findings.ignore(session, finding_id, scope=body.scope, days=body.days, reason=body.reason, tune=body.tune)
    return IgnoreOut(
        rule_id=result["rule_id"],
        closed=result["closed"],
        tuned=result["tuned"],
        finding=_after(session, findings.get_for_user(session, finding_id)[0]),
    )


@router.get("/findings/{finding_id}", response_model=FindingDetailOut, dependencies=VIEW)
def get_finding(finding_id: UUID, session: Session = DB_SESSION) -> object:
    row, events = findings.get_for_user(session, finding_id)
    return _detail(session, row, list(events))


@router.post("/findings/{finding_id}/acknowledge", response_model=FindingDetailOut, dependencies=VIEW)
def post_acknowledge(finding_id: UUID, body: NoteIn, session: Session = DB_SESSION) -> object:
    return _after(session, findings.acknowledge(session, finding_id, body.note))


@router.post("/findings/{finding_id}/explain", response_model=FindingDetailOut, dependencies=VIEW)
def post_explain(finding_id: UUID, body: ExplainIn, session: Session = DB_SESSION) -> object:
    return _after(session, findings.explain(session, finding_id, body.note))


@router.post("/findings/{finding_id}/resolve", response_model=FindingDetailOut, dependencies=MANAGE)
def post_resolve(finding_id: UUID, body: NoteIn, session: Session = DB_SESSION) -> object:
    return _after(session, findings.resolve(session, finding_id, body.note))


@router.post("/findings/{finding_id}/dismiss", response_model=FindingDetailOut, dependencies=MANAGE)
def post_dismiss(finding_id: UUID, body: DismissIn, session: Session = DB_SESSION) -> object:
    return _after(session, findings.dismiss(session, finding_id, body.reason))


@router.post("/findings/{finding_id}/assign", response_model=FindingDetailOut, dependencies=MANAGE)
def post_assign(finding_id: UUID, body: AssignIn, session: Session = DB_SESSION) -> object:
    return _after(session, findings.assign(session, finding_id, body.user_id))


@router.post("/findings/{finding_id}/ask", response_model=FindingDetailOut, dependencies=MANAGE)
def post_ask(finding_id: UUID, body: AskIn, session: Session = DB_SESSION) -> object:
    """Ask someone to explain a finding (level 2 of what Intelligence may do; the business must allow it)."""
    return _after(session, findings.ask(session, finding_id, body.user_id, body.message))


@router.post("/findings/{finding_id}/ai-explanation", response_model=FindingDetailOut, dependencies=MANAGE)
def post_ai_explanation(finding_id: UUID, body: AiExplainIn) -> object:
    """Have the AI assistant write (or rewrite) the plain-language explanation of a finding from its own figures. The
    text is stored as AI-written; if its figures do not match the finding it is discarded (422) and nothing changes."""
    ctx = current_context()
    with tenant_transaction(ctx.tenant_id) as session:
        row, _ = findings.get_for_user(session, finding_id)
        ctx.require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    explain.explain_finding(ctx.tenant_id, finding_id, user_id=ctx.user_id, language=body.language)
    with tenant_transaction(ctx.tenant_id) as session:
        fresh, events = findings.get_for_user(session, finding_id)
        return _detail(session, fresh, list(events))


@router.get("/checks", response_model=list[CheckOut], dependencies=VIEW)
def get_checks(session: Session = DB_SESSION) -> object:
    """The checks that run for this business, with their limits (and their topic: see `GET /plain` for plain words)."""
    return checks_admin.list_checks(session)


@router.patch("/checks/{code}", response_model=CheckOut, dependencies=MANAGE)
def patch_check(code: str, body: CheckUpdateIn, session: Session = DB_SESSION) -> object:
    """Switch a check off or on, or change its limits."""
    return checks_admin.update_check(session, code, body.enabled, body.params)


@router.post("/checks/{code}/reset", response_model=CheckOut, dependencies=MANAGE)
def post_reset_check(code: str, session: Session = DB_SESSION) -> object:
    """Back to the recommended settings for one check: on, with its default limits."""
    return checks_admin.reset_check(session, code)


@router.post("/run", response_model=RunOut, dependencies=MANAGE)
def post_run(body: RunIn, session: Session = DB_SESSION) -> object:
    """Run the checks for a company now (they also run by themselves every few hours)."""
    check_company(session, body.company_id)
    current_context().require(FINDINGS_MANAGE, company_id=body.company_id)
    result = engine.run_company(session, body.company_id, only=set(body.checks) if body.checks else None)
    alerts.send_alerts(session, body.company_id)
    return RunOut(
        checks_run=result.checks_run,
        created=result.created,
        updated=result.updated,
        resolved=result.resolved,
        reopened=result.reopened,
        failed=result.failed,
    )
