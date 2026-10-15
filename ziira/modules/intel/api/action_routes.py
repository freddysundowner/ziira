"""HTTP endpoints for levels 3 and 4: the suggestions Intelligence prepares, approving or turning them down, the rules
that let routine ones run by themselves, and the log of everything done."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Row

from ziira.modules.intel.api.schemas import (
    ActionLogOut,
    ActionResultOut,
    ActionTypeOut,
    ApproveIn,
    ProposalOut,
    RecordOut,
    RejectIn,
    RuleIn,
    RuleOut,
    RuleUpdateIn,
)
from ziira.modules.intel.permissions import FINDINGS_MANAGE, FINDINGS_VIEW
from ziira.modules.intel.public import ActionProvider
from ziira.modules.intel.services import actions
from ziira.sdk import DB_SESSION, Session, current_context, page_limit, page_offset, require_permission

router = APIRouter()
VIEW = [Depends(require_permission(FINDINGS_VIEW))]
MANAGE = [Depends(require_permission(FINDINGS_MANAGE))]

ProposalStatus = Literal["proposed", "approved", "executed", "failed", "rejected", "expired", "cancelled"]


def _result(raw: dict[str, Any] | None) -> ActionResultOut | None:
    if not raw:
        return None
    return ActionResultOut(ok=bool(raw.get("ok")), message=str(raw.get("message", "")), created=[
        RecordOut(type=c["type"], id=c.get("id"), label=c.get("label", "")) for c in raw.get("created", [])])


def _proposal(row: Row[Any], available: dict[str, ActionProvider]) -> ProposalOut:
    provider = available.get(row.action_type)
    ctx = current_context()
    permission = provider.needs_permission if provider else ""
    return ProposalOut(
        id=row.id, finding_id=row.finding_id, finding_summary=row.finding_summary,
        finding_severity=row.finding_severity, finding_status=row.finding_status, company_id=row.company_id,
        branch_id=row.branch_id, action_type=row.action_type,
        action_title=provider.title if provider else row.action_type,
        description=row.description, facts={str(k): str(v) for k, v in (row.facts or {}).items()},
        params=dict(row.params), params_schema=provider.params_schema if provider else {}, status=row.status,
        level_at_proposal=row.level_at_proposal, proposed_at=row.proposed_at, decided_by=row.decided_by,
        decided_by_name=row.decided_by_name, decided_at=row.decided_at, decision_note=row.decision_note,
        executed_at=row.executed_at, result=_result(row.result), needs_permission=permission,
        can_decide=bool(provider) and ctx.can(permission, company_id=row.company_id, branch_id=row.branch_id))


def _rule(row: Row[Any], available: dict[str, ActionProvider]) -> RuleOut:
    provider = available.get(row.action_type)
    return RuleOut(
        id=row.id, company_id=row.company_id, action_type=row.action_type,
        action_title=provider.title if provider else row.action_type, enabled=row.enabled,
        paused=row.paused_at is not None, conditions=dict(row.conditions or {}), daily_cap=row.daily_cap,
        note=row.note, created_at=row.created_at, times_used=int(row.times_used))


@router.get("/actions/types", response_model=list[ActionTypeOut], dependencies=VIEW)
def get_action_types(session: Session = DB_SESSION) -> object:
    """Every kind of action Intelligence can propose for this business, with its parameters and whether it may run by a
    rule."""
    out = []
    for provider in sorted(actions.providers(session).values(), key=lambda p: p.type):
        refusal = actions.automatic_refusal(provider)
        out.append(ActionTypeOut(
            type=provider.type, title=provider.title, description=provider.description,
            check_codes=list(provider.check_codes), needs_permission=provider.needs_permission,
            can_run_by_rule=refusal is None, why_not_by_rule=refusal, params_schema=provider.params_schema,
            rule_schema=actions.rule_schema(provider)))
    return out


@router.get("/actions/log", response_model=list[ActionLogOut], dependencies=MANAGE)
def get_action_log(company_id: UUID | None = None, action_type: str | None = None,
                   mode: Literal["manual", "automatic"] | None = None, limit: int = page_limit(50),
                   offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    """Everything Intelligence did or tried to do, by approval or by rule, newest first."""
    available = actions.providers(session)
    rows = actions.list_log(session, company_id=company_id, action_type=action_type, mode=mode, limit=limit,
                            offset=offset)
    return [ActionLogOut(
        id=r.id, created_at=r.created_at, proposal_id=r.proposal_id, finding_id=r.finding_id,
        finding_summary=r.finding_summary, company_id=r.company_id, branch_id=r.branch_id, action_type=r.action_type,
        action_title=available[r.action_type].title if r.action_type in available else r.action_type, mode=r.mode,
        actor_user_id=r.actor_user_id, actor_name=r.actor_name, rule_id=r.rule_id, level=r.level,
        params=dict(r.params), outcome=r.outcome, message=r.message, result=_result(r.result)) for r in rows]


@router.get("/actions", response_model=list[ProposalOut], dependencies=VIEW)
def get_proposals(status: list[ProposalStatus] | None = Query(default=None), finding_id: UUID | None = None,
                  company_id: UUID | None = None, mine: bool = False, limit: int = page_limit(50),
                  offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    """Suggestions Intelligence has prepared, in the user's scope. `mine`: those waiting for a decision this person is
    allowed to make."""
    rows = actions.list_proposals(session, statuses=list(status) if status else None, finding_id=finding_id,
                                  company_id=company_id, mine=mine, limit=limit, offset=offset)
    available = actions.providers(session)
    return [_proposal(r, available) for r in rows]


@router.get("/actions/{proposal_id}", response_model=ProposalOut, dependencies=VIEW)
def get_proposal(proposal_id: UUID, session: Session = DB_SESSION) -> object:
    return _proposal(actions.get(session, proposal_id), actions.providers(session))


@router.post("/actions/{proposal_id}/approve", response_model=ProposalOut, dependencies=VIEW)
def post_approve(proposal_id: UUID, body: ApproveIn, session: Session = DB_SESSION) -> object:
    """Approve a suggestion (optionally with changed parameters) and do it now, as the signed-in user. Needs the
    permission the action itself needs, where the finding is. Approving what is already done changes nothing."""
    row = actions.approve(session, proposal_id, edits=body.params, note=body.note)
    return _proposal(row, actions.providers(session))


@router.post("/actions/{proposal_id}/reject", response_model=ProposalOut, dependencies=VIEW)
def post_reject(proposal_id: UUID, body: RejectIn, session: Session = DB_SESSION) -> object:
    """Turn a suggestion down, with a reason. It is not made again for the same finding."""
    return _proposal(actions.reject(session, proposal_id, body.reason), actions.providers(session))


@router.get("/findings/{finding_id}/actions", response_model=list[ProposalOut], dependencies=VIEW)
def get_finding_actions(finding_id: UUID, session: Session = DB_SESSION) -> object:
    """The suggestions made for one finding, waiting or done."""
    available = actions.providers(session)
    return [_proposal(r, available) for r in actions.proposals_of(session, finding_id)]


@router.get("/automation/rules", response_model=list[RuleOut], dependencies=MANAGE)
def get_rules(session: Session = DB_SESSION) -> object:
    """The owner's rules for actions that may run by themselves (level 4)."""
    available = actions.providers(session)
    return [_rule(r, available) for r in actions.list_rules(session)]


@router.post("/automation/rules", response_model=RuleOut, status_code=201, dependencies=MANAGE)
def post_rule(body: RuleIn, session: Session = DB_SESSION) -> object:
    """Let a routine action run by itself within conditions and a daily limit. Only actions that move no money and
    change no price, credit limit or stock may be made automatic. It acts only while the business is at level 4."""
    row = actions.create_rule(session, company_id=body.company_id, action_type=body.action_type,
                              conditions=body.conditions, daily_cap=body.daily_cap, note=body.note)
    return _rule(row, actions.providers(session))


@router.patch("/automation/rules/{rule_id}", response_model=RuleOut, dependencies=MANAGE)
def patch_rule(rule_id: UUID, body: RuleUpdateIn, session: Session = DB_SESSION) -> object:
    """Change a rule's conditions or limit, switch it off, or pause and resume it."""
    row = actions.update_rule(session, rule_id, enabled=body.enabled, conditions=body.conditions,
                              daily_cap=body.daily_cap, note=body.note, paused=body.paused)
    return _rule(row, actions.providers(session))
