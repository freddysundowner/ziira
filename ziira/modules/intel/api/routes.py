"""HTTP endpoints for Intelligence: findings, what people do with them, the checks and running them now."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ziira.modules.intel.api.schemas import (
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
    NoteIn,
    RecordOut,
    RunIn,
    RunOut,
)
from ziira.modules.intel.permissions import FINDINGS_MANAGE, FINDINGS_VIEW
from ziira.modules.intel.services import alerts, checks_admin, engine, findings
from ziira.sdk import DB_SESSION, Session, check_company, current_context, page_limit, page_offset, require_permission

router = APIRouter()
VIEW = [Depends(require_permission(FINDINGS_VIEW))]
MANAGE = [Depends(require_permission(FINDINGS_MANAGE))]

Status = Literal["new", "sent", "acknowledged", "explained", "resolved", "dismissed"]
Severity = Literal["info", "low", "medium", "high", "critical"]


def _detail(row: object, events: list[object]) -> FindingDetailOut:
    base = FindingOut.model_validate(row)
    evidence = getattr(row, "evidence", None) or {}
    return FindingDetailOut(
        **base.model_dump(), records=[RecordOut(**r) for r in evidence.get("records", [])],
        figures={str(k): str(v) for k, v in (evidence.get("figures") or {}).items()},
        events=[FindingEventOut(id=e.id, created_at=e.created_at, event=e.event, user_id=e.user_id,  # type: ignore[attr-defined]
                                user_name=e.user_name, channel=e.channel, note=e.note) for e in events])  # type: ignore[attr-defined]


def _after(session: Session, row: object) -> FindingDetailOut:
    _, events = findings.get_for_user(session, row.id)  # type: ignore[attr-defined]
    return _detail(row, list(events))


@router.get("/findings", response_model=list[FindingOut], dependencies=VIEW)
def get_findings(status: list[Status] | None = Query(default=None),
                 severity: list[Severity] | None = Query(default=None), area: str | None = None,
                 company_id: UUID | None = None, branch_id: UUID | None = None,
                 check_code: str | None = None, assigned_to_me: bool = False, search: str | None = None,
                 limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    """Findings in the user's scope, most serious first. Without a status filter, open ones only."""
    return findings.list_for_user(
        session, statuses=list(status) if status else ["new", "sent", "acknowledged", "explained"],
        severities=list(severity) if severity else None, area=area, company_id=company_id, branch_id=branch_id,
        check_code=check_code, owner_user_id=current_context().user_id if assigned_to_me else None, search=search,
        limit=limit, offset=offset)


@router.get("/findings/summary", response_model=FindingsSummaryOut, dependencies=VIEW)
def get_summary(session: Session = DB_SESSION) -> object:
    return findings.summary(session)


@router.get("/findings/{finding_id}", response_model=FindingDetailOut, dependencies=VIEW)
def get_finding(finding_id: UUID, session: Session = DB_SESSION) -> object:
    row, events = findings.get_for_user(session, finding_id)
    return _detail(row, list(events))


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


@router.get("/checks", response_model=list[CheckOut], dependencies=VIEW)
def get_checks(session: Session = DB_SESSION) -> object:
    """The checks that run for this business, with their limits."""
    return checks_admin.list_checks(session)


@router.patch("/checks/{code}", response_model=CheckOut, dependencies=MANAGE)
def patch_check(code: str, body: CheckUpdateIn, session: Session = DB_SESSION) -> object:
    """Switch a check off or on, or change its limits."""
    return checks_admin.update_check(session, code, body.enabled, body.params)


@router.post("/run", response_model=RunOut, dependencies=MANAGE)
def post_run(body: RunIn, session: Session = DB_SESSION) -> object:
    """Run the checks for a company now (they also run by themselves every few hours)."""
    check_company(session, body.company_id)
    current_context().require(FINDINGS_MANAGE, company_id=body.company_id)
    result = engine.run_company(session, body.company_id, only=set(body.checks) if body.checks else None)
    alerts.send_alerts(session, body.company_id)
    return RunOut(checks_run=result.checks_run, created=result.created, updated=result.updated,
                  resolved=result.resolved, reopened=result.reopened, failed=result.failed)
