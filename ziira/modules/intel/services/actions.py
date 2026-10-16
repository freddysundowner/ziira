"""Levels 3 and 4 of Intelligence: proposing actions for findings, a person approving or turning them down, and the
routine ones an owner has allowed running by themselves.

    finding ──▶ providers propose ──▶ proposal (waiting) ──▶ approved by a person ─▶ executed ─▶ action log
                                             └─▶ level 4, provider auto-allowed, owner's rule covers it,
                                                 daily limit not reached ──▶ executed as "Intelligence"

A manual action runs as the person who approved it, so the owning unit's permissions and approval rules apply to
them. An automatic one runs in a context that holds exactly the provider's `needs_permission` and nothing else.
Everything is recorded in the action log, the finding's history and the audit log. Ziira never moves money: a provider
that needs a money permission is never automatic, and the providers themselves only create drafts, send messages or
call the owning unit's own services.
"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.intel.domain import action_rules as rules
from ziira.modules.intel.domain.model import Record
from ziira.modules.intel.permissions import FINDINGS_MANAGE, FINDINGS_VIEW, INTEL_AUTOMATION
from ziira.modules.intel.public import (
    INTEL_ACTION,
    ActionContext,
    ActionProvider,
    ActionResult,
    FindingInfo,
)
from ziira.modules.intel.repository import actions_repo as repo
from ziira.modules.intel.repository import findings_repo
from ziira.modules.intel.services import approver_messages
from ziira.sdk import (
    Assignment,
    Conflict,
    NotFound,
    RequestContext,
    Session,
    ValidationFailed,
    ZiiraError,
    audit_record,
    check_company,
    company_setting,
    current_context,
    flag_for_review,
    implementations,
    set_context,
)

log = logging.getLogger("ziira.intel")

MAX_FINDINGS_LOOKED_AT = 100       # findings the providers look at in one run for one company
MAX_PROPOSALS_PER_RUN = 100        # proposals one run adds for one company
MAX_AUTOMATIC_PER_RUN = 100        # automatic actions one run carries out for one company
PROPOSALS_PER_FINDING = 3
COOLDOWN_DAYS = 7                  # the same action, done, is not proposed again for a finding sooner than this


@dataclass
class ActionRun:
    proposed: int = 0
    executed: int = 0
    failed: int = 0
    expired: int = 0
    errors: list[str] = field(default_factory=list)
    to_announce: list[tuple[ActionProvider, FindingInfo, UUID, str]] = field(default_factory=list)


# --------------------------------------------------------------------------- providers and levels
def providers(session: Session) -> dict[str, ActionProvider]:
    """The action providers of the units enabled for this business, by type."""
    return {p.type: p for p in implementations(session, INTEL_ACTION)}


def provider_for(session: Session, action_type: str) -> ActionProvider:
    found = providers(session).get(action_type)
    if found is None:
        raise ValidationFailed("This kind of action is not available for this business")
    return found


def action_level(session: Session, company_id: UUID) -> int:
    return int(company_setting(session, company_id, "intel_action_level"))


def automatic_refusal(provider: ActionProvider) -> str | None:
    """Why this provider may never run without a person, or None."""
    return rules.auto_refusal(auto_allowed=provider.auto_allowed, needs_permission=provider.needs_permission)


def finding_info(row: Row[Any]) -> FindingInfo:
    evidence = row.evidence or {}
    records = tuple(Record(r["type"], UUID(r["id"]) if r.get("id") else None, r.get("label", ""))
                    for r in evidence.get("records", []))
    return FindingInfo(
        id=row.id, check_code=row.check_code, severity=row.severity, company_id=row.company_id,
        branch_id=row.branch_id, entity_type=row.entity_type, entity_id=row.entity_id, amount=row.amount,
        value=row.value, summary=row.summary or "", records=records,
        figures={str(k): str(v) for k, v in (evidence.get("figures") or {}).items()})


def _local_today(session: Session, company_id: UUID) -> tuple[date, str]:
    from ziira.modules.intel.services.engine import local_today

    return local_today(session, company_id), str(company_setting(session, company_id, "timezone"))


@contextmanager
def acting_as(context: RequestContext) -> Iterator[None]:
    """Run a piece of work with another context (the limited one of an automatic action), then put the first back."""
    previous = current_context()
    set_context(context)
    try:
        yield
    finally:
        set_context(previous)


def automatic_context(base: RequestContext, permission: str, company_id: UUID) -> RequestContext:
    """Who an automatic action runs as: nobody signed in, channel 'intelligence', and exactly one permission."""
    return RequestContext(
        tenant_id=base.tenant_id, user_id=None, channel="intelligence",
        assignments=(Assignment(role_id=None, role_name="Intelligence", scope="company", company_id=company_id,
                                branch_id=None, permissions=frozenset({permission})),))


# --------------------------------------------------------------------------- proposing
def after_checks(session: Session, company_id: UUID, reopened: list[UUID]) -> ActionRun:
    """Called by the checks engine when it has finished a company: withdraw proposals whose finding has closed and, at
    level 3 or more, let the providers look at new findings. At level 4, carry out what the owner's rules allow."""
    run = ActionRun(expired=_expire(session, company_id=company_id))
    level = action_level(session, company_id)
    if level < rules.LEVEL_PREPARE:
        run.expired += cancel_waiting(session, company_id)
        return run
    repo.forget_looked_at(session, reopened)
    available = providers(session)
    codes = sorted({code for p in available.values() for code in p.check_codes})
    if codes:
        _propose_for_new_findings(session, company_id, level, available, codes, run)
    if level >= rules.LEVEL_ACT:
        _run_automatic(session, company_id, level, available, run)
    _announce(session, run)
    return run


def _announce(session: Session, run: ActionRun) -> None:
    """Tell the approvers about the suggestions made in this run that are still waiting for a person (one an owner's
    rule has already carried out needs no decision)."""
    for provider, info, proposal_id, description in run.to_announce:
        row = repo.get_proposal(session, proposal_id)
        if row is not None and row.status == "proposed":
            approver_messages.tell_approvers(session, provider, info, proposal_id, description)
    run.to_announce.clear()


def _propose_for_new_findings(session: Session, company_id: UUID, level: int, available: dict[str, ActionProvider],
                              codes: list[str], run: ActionRun) -> None:
    looked: list[UUID] = []
    for row in repo.findings_to_look_at(session, company_id, codes, MAX_FINDINGS_LOOKED_AT):
        if run.proposed >= MAX_PROPOSALS_PER_RUN:
            break
        info = finding_info(row)
        clean = True
        for provider in available.values():
            if info.check_code in provider.check_codes and not _propose(session, provider, info, level, run):
                clean = False
        if clean:
            looked.append(row.id)
    repo.mark_looked_at(session, looked)


def _propose(session: Session, provider: ActionProvider, info: FindingInfo, level: int, run: ActionRun) -> bool:
    """Ask one provider about one finding and store what it proposes. False when the provider failed (it is asked again
    next time)."""
    try:
        with session.begin_nested():
            proposals = provider.proposes(session, info)
    except Exception as error:  # a broken provider must not stop the others, and must not pass silently
        log.exception("Action provider %s failed for finding %s", provider.type, info.id)
        run.errors.append(provider.type)
        flag_for_review(session, unit="intel", kind="action_provider_failed", severity="low",
                        company_id=info.company_id,
                        message=f"The action '{provider.title}' could not look at a finding: {error}"[:500],
                        dedupe_key=f"intel-action-provider:{provider.type}:{info.company_id}")
        return False
    for proposal in proposals[:PROPOSALS_PER_FINDING]:
        try:
            params = rules.validate_values(provider.params_schema, proposal.params)
        except rules.ParamError as error:
            log.warning("Action provider %s proposed unusable parameters: %s", provider.type, error)
            continue
        digest = rules.params_hash(params)
        if repo.blocked(session, info.id, provider.type, digest, COOLDOWN_DAYS):
            continue
        created = repo.insert_proposal(
            session, finding_id=info.id, company_id=info.company_id, branch_id=info.branch_id,
            action_type=provider.type, params=params, params_hash=digest, description=proposal.description,
            facts=proposal.facts, level=level)
        if created is None:
            continue
        findings_repo.add_event(session, info.id, "action_proposed", note=proposal.description)
        run.to_announce.append((provider, info, created, proposal.description))
        run.proposed += 1
    return True


def _expire(session: Session, *, company_id: UUID | None = None, finding_id: UUID | None = None) -> int:
    expired = repo.expire_for_closed_findings(session, company_id, finding_id)
    findings_repo.add_events(session, [(r.finding_id, "action_expired", "The finding closed before this was done")
                                       for r in expired])
    return len(expired)


def expire_for_finding(session: Session, finding_id: UUID) -> None:
    """A finding was closed by a person: what was waiting on it is withdrawn."""
    _expire(session, finding_id=finding_id)


def cancel_waiting(session: Session, company_id: UUID) -> int:
    """The business lowered the action level below 3: suggestions still waiting are withdrawn."""
    return repo.cancel_waiting(session, company_id, "Intelligence was set to a level that does not prepare actions")


# --------------------------------------------------------------------------- doing it
def _execute(session: Session, provider: ActionProvider, row: Row[Any], params: dict[str, Any], *,
             automatic: bool) -> ActionResult:
    """Run the provider in a savepoint: if it fails, nothing it did stays. Never raises."""
    today, _ = _local_today(session, row.company_id)
    context = ActionContext(company_id=row.company_id, branch_id=row.branch_id, finding_id=row.finding_id,
                            proposal_id=row.id, automatic=automatic, today=today,
                            finding_summary=row.finding_summary or "")
    nested = session.begin_nested()
    try:
        result = provider.execute(session, context, params)
    except ZiiraError as error:
        nested.rollback()
        return ActionResult(False, error.message)
    except Exception:
        log.exception("Action %s failed for proposal %s", provider.type, row.id)
        nested.rollback()
        return ActionResult(False, "Something went wrong and nothing was changed")
    if result.ok:
        nested.commit()
    else:
        nested.rollback()
    return result


def decision_channel(mode: str = "manual") -> str:
    """Where a decision is made: 'intelligence' for an automatic action, 'chat' for a reply in a chat channel,
    otherwise 'app'."""
    if mode == "automatic":
        return "intelligence"
    return "chat" if current_context().channel == "chat" else "app"


def _record_outcome(session: Session, provider: ActionProvider, row: Row[Any], params: dict[str, Any],
                    result: ActionResult, *, mode: str, actor: UUID | None, rule_id: UUID | None) -> None:
    status = "executed" if result.ok else "failed"
    stored = {"ok": result.ok, "message": result.message,
              "created": [{"type": t, "id": str(i) if i else None, "label": label}
                          for t, i, label in result.created_refs]}
    repo.set_outcome(session, row.id, status=status, result=stored)
    level = action_level(session, row.company_id)
    repo.add_log(session, proposal_id=row.id, finding_id=row.finding_id, company_id=row.company_id,
                 branch_id=row.branch_id, action_type=provider.type, mode=mode, actor_user_id=actor, rule_id=rule_id,
                 level=level, params=params, outcome=status, message=result.message, result=stored,
                 channel=decision_channel(mode))
    who = "Intelligence under a rule" if mode == "automatic" else "approved"
    findings_repo.add_event(
        session, row.finding_id, "action_taken" if result.ok else "action_failed", user_id=actor,
        channel=decision_channel(mode), note=f"{provider.title} ({who}): {result.message}")
    audit_record(session, "intel.action.executed" if result.ok else "intel.action.failed", "intel.action_proposal",
                 row.id, {"type": provider.type, "mode": mode, "rule": str(rule_id) if rule_id else None,
                          "finding": str(row.finding_id), "message": result.message,
                          "channel": decision_channel(mode)})


def _load(session: Session, proposal_id: UUID, *, lock: bool = False) -> Row[Any]:
    row = repo.get_proposal(session, proposal_id, lock=lock)
    ctx = current_context()
    if row is None or not ctx.can(FINDINGS_VIEW, company_id=row.company_id, branch_id=row.branch_id):
        raise NotFound("Suggestion not found")
    return row


def get(session: Session, proposal_id: UUID) -> Row[Any]:
    return _load(session, proposal_id)


def approve(session: Session, proposal_id: UUID, *, edits: dict[str, Any] | None = None,
            note: str | None = None) -> Row[Any]:
    """A person approves a suggestion, optionally with changed parameters, and it is done now, as them. Approving what
    is already done changes nothing and returns it."""
    row = _load(session, proposal_id, lock=True)
    provider = provider_for(session, row.action_type)
    ctx = current_context()
    ctx.require(provider.needs_permission, company_id=row.company_id, branch_id=row.branch_id)
    if row.status == "executed":
        return row
    if row.status not in ("proposed", "failed"):
        raise Conflict(f"This suggestion is {row.status}")
    if row.finding_status in ("resolved", "dismissed"):
        _expire(session, finding_id=row.finding_id)
        raise Conflict("The finding it was about has closed")
    if action_level(session, row.company_id) < rules.LEVEL_PREPARE:
        raise ValidationFailed("Preparing actions is switched off: raise the Intelligence level to 3 in Settings")
    try:
        params = rules.apply_edits(provider.params_schema, dict(row.params), edits or {})
    except rules.ParamError as error:
        raise ValidationFailed(str(error)) from None
    repo.set_decision(session, row.id, status="approved", user_id=ctx.user_id, note=(note or "").strip() or None,
                      params=params)
    result = _execute(session, provider, row, params, automatic=False)
    _record_outcome(session, provider, row, params, result, mode="manual", actor=ctx.user_id, rule_id=None)
    return _load(session, proposal_id)


def reject(session: Session, proposal_id: UUID, reason: str) -> Row[Any]:
    """A person turns a suggestion down. A reason is required; it is not made again for the same finding."""
    row = _load(session, proposal_id, lock=True)
    provider = provider_for(session, row.action_type)
    ctx = current_context()
    if not ctx.can(provider.needs_permission, company_id=row.company_id, branch_id=row.branch_id):
        ctx.require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    if not reason.strip():
        raise ValidationFailed("Say why you are turning this down")
    if row.status not in ("proposed", "failed"):
        raise Conflict(f"This suggestion is {row.status}")
    repo.set_decision(session, row.id, status="rejected", user_id=ctx.user_id, note=reason.strip())
    findings_repo.add_event(session, row.finding_id, "action_rejected", user_id=ctx.user_id,
                            channel=decision_channel(), note=f"{provider.title}: {reason.strip()}")
    audit_record(session, "intel.action.rejected", "intel.action_proposal", row.id,
                 {"type": row.action_type, "reason": reason.strip(), "channel": decision_channel()})
    return _load(session, proposal_id)


# --------------------------------------------------------------------------- automatic actions (level 4)
def _run_automatic(session: Session, company_id: UUID, level: int, available: dict[str, ActionProvider],
                   run: ActionRun) -> None:
    """Carry out waiting suggestions that an owner's rule covers. Each at most once: a failure is recorded and left
    alone."""
    waiting = repo.list_proposals(
        session, "p.company_id = :wc", {"wc": str(company_id)}, statuses=["proposed"], finding_id=None,
        company_id=None, limit=500, offset=0)
    done = 0
    for row in reversed(waiting):                                   # oldest first
        if done >= MAX_AUTOMATIC_PER_RUN:
            break
        provider = available.get(row.action_type)
        if provider is None or automatic_refusal(provider) is not None:
            continue
        outcome = _try_automatic(session, provider, row, level)
        if outcome is None:
            continue
        done += 1
        run.executed += 1 if outcome else 0
        run.failed += 0 if outcome else 1


def _try_automatic(session: Session, provider: ActionProvider, row: Row[Any], level: int) -> bool | None:
    """Do one suggestion under the first rule that covers it and still has room today. None: no rule applies (it keeps
    waiting for a person). True/False: done / failed."""
    if row.finding_status in ("resolved", "dismissed"):
        return None
    finding = findings_repo.get_finding(session, row.finding_id)
    if finding is None:
        return None
    info = finding_info(finding)
    rule = _covering_rule(session, provider, row, info)
    if rule is None:
        return None
    try:
        params = rules.validate_values(provider.params_schema, dict(row.params))
    except rules.ParamError as error:
        _record_automatic_failure(session, provider, row, rule, f"The suggestion is no longer valid: {error}")
        return False
    repo.set_decision(session, row.id, status="approved", user_id=None, note=f"Automatic, by rule {rule.id}")
    base = current_context()
    with acting_as(automatic_context(base, provider.needs_permission, row.company_id)):
        result = _execute(session, provider, row, params, automatic=True)
        _record_outcome(session, provider, row, params, result, mode="automatic", actor=None, rule_id=rule.id)
    if not result.ok:
        flag_for_review(session, unit="intel", kind="automatic_action_failed", severity="low",
                        company_id=row.company_id, branch_id=row.branch_id, ref_type="intel.finding",
                        ref_id=row.finding_id, message=f"{provider.title} did not go through: {result.message}"[:500],
                        dedupe_key=f"intel-auto-failed:{row.id}")
    return result.ok


def _covering_rule(session: Session, provider: ActionProvider, row: Row[Any], info: FindingInfo) -> Row[Any] | None:
    today, timezone = _local_today(session, row.company_id)
    params = dict(row.params)
    for rule in repo.active_rules(session, row.company_id, row.action_type):
        conditions = dict(rule.conditions or {})
        if not rules.rule_covers(conditions, finding_branch=row.branch_id, finding_amount=info.amount):
            continue
        if not provider.covered_by(conditions, params, info):
            continue
        if repo.runs_today(session, rule.id, timezone, today) >= rule.daily_cap:
            continue
        return rule
    return None


def _record_automatic_failure(session: Session, provider: ActionProvider, row: Row[Any], rule: Row[Any],
                              message: str) -> None:
    result = ActionResult(False, message)
    with acting_as(automatic_context(current_context(), provider.needs_permission, row.company_id)):
        _record_outcome(session, provider, row, dict(row.params), result, mode="automatic", actor=None,
                        rule_id=rule.id)


# --------------------------------------------------------------------------- listing
def list_proposals(session: Session, *, statuses: list[str] | None, finding_id: UUID | None,
                   company_id: UUID | None, mine: bool, limit: int, offset: int) -> Sequence[Row[Any]]:
    """Suggestions in the user's scope (they can see the finding). With `mine`, only those waiting for a decision that
    this person has the permission to make where it applies."""
    ctx = current_context()
    sql, params = findings_repo.scope_clause(ctx, FINDINGS_VIEW)
    sql = sql.replace("f.company_id", "p.company_id").replace("f.branch_id", "p.branch_id")
    if not mine:
        return repo.list_proposals(session, sql, params, statuses=statuses, finding_id=finding_id,
                                   company_id=company_id, limit=limit, offset=offset)
    available = providers(session)
    rows = repo.list_proposals(session, sql, params, statuses=statuses or ["proposed"], finding_id=finding_id,
                               company_id=company_id, limit=1000, offset=0)
    chosen = [r for r in rows if r.action_type in available and ctx.can(
        available[r.action_type].needs_permission, company_id=r.company_id, branch_id=r.branch_id)]
    return chosen[offset:offset + limit]


def proposals_of(session: Session, finding_id: UUID) -> Sequence[Row[Any]]:
    """The suggestions made for one finding the user can see."""
    ctx = current_context()
    finding = findings_repo.get_finding(session, finding_id)
    if finding is None or not ctx.can(FINDINGS_VIEW, company_id=finding.company_id, branch_id=finding.branch_id):
        raise NotFound("Finding not found")
    return repo.proposals_of_finding(session, finding_id)


def list_log(session: Session, *, company_id: UUID | None, action_type: str | None, mode: str | None, limit: int,
             offset: int) -> Sequence[Row[Any]]:
    sql, params = findings_repo.scope_clause(current_context(), FINDINGS_MANAGE)
    return repo.list_log(session, sql, params, company_id=company_id, action_type=action_type, mode=mode, limit=limit,
                         offset=offset)


# --------------------------------------------------------------------------- automation rules
GENERIC_RULE_SCHEMA: dict[str, Any] = {"properties": {
    "branch_id": {"type": "uuid", "title": "Only this branch"},
    "max_amount": {"type": "number", "title": "Only when the amount at stake is at most", "minimum": "0"},
}}


def rule_schema(provider: ActionProvider) -> dict[str, Any]:
    """The conditions a rule for this provider may set: its own plus the generic ones."""
    return {"properties": {**GENERIC_RULE_SCHEMA["properties"], **provider.rule_schema.get("properties", {})},
            "required": provider.rule_schema.get("required", [])}


def _clean_conditions(session: Session, provider: ActionProvider, company_id: UUID,
                      conditions: dict[str, Any]) -> dict[str, Any]:
    try:
        clean = rules.validate_values(rule_schema(provider), conditions, label="Condition")
    except rules.ParamError as error:
        raise ValidationFailed(str(error)) from None
    if clean.get("branch_id"):
        check_company(session, company_id, UUID(str(clean["branch_id"])))
    return clean


def _check_auto_provider(session: Session, action_type: str) -> ActionProvider:
    provider = provider_for(session, action_type)
    refusal = automatic_refusal(provider)
    if refusal:
        raise ValidationFailed(refusal)
    return provider


def create_rule(session: Session, *, company_id: UUID, action_type: str, conditions: dict[str, Any], daily_cap: int,
                note: str | None) -> Row[Any]:
    ctx = current_context()
    check_company(session, company_id)
    ctx.require(FINDINGS_MANAGE, company_id=company_id)
    ctx.require(INTEL_AUTOMATION, company_id=company_id)         # letting Ziira act by itself is the owner's decision
    provider = _check_auto_provider(session, action_type)
    clean = _clean_conditions(session, provider, company_id, conditions)
    rule_id = repo.insert_rule(session, company_id=company_id, action_type=action_type, conditions=clean,
                               daily_cap=daily_cap, note=(note or "").strip() or None, user_id=ctx.user_id)
    audit_record(session, "intel.rule.created", "intel.auto_rule", rule_id,
                 {"type": action_type, "conditions": clean, "daily_cap": daily_cap})
    found = repo.get_rule(session, rule_id)
    assert found is not None
    return found


def get_rule(session: Session, rule_id: UUID) -> Row[Any]:
    row = repo.get_rule(session, rule_id)
    if row is None or not current_context().can(FINDINGS_VIEW, company_id=row.company_id):
        raise NotFound("Rule not found")
    return row


def list_rules(session: Session) -> Sequence[Row[Any]]:
    ctx = current_context()
    allowed = ctx.companies_with(FINDINGS_VIEW)
    return [r for r in repo.list_rules(session) if allowed is None or r.company_id in allowed]


def update_rule(session: Session, rule_id: UUID, *, enabled: bool | None, conditions: dict[str, Any] | None,
                daily_cap: int | None, note: str | None, paused: bool | None) -> Row[Any]:
    row = get_rule(session, rule_id)
    ctx = current_context()
    ctx.require(FINDINGS_MANAGE, company_id=row.company_id)
    # Pausing or switching a rule off only makes Ziira do less; anything else is the owner's decision.
    only_less = (conditions is None and daily_cap is None and note is None and enabled in (None, False)
                 and paused in (None, True))
    if not only_less:
        ctx.require(INTEL_AUTOMATION, company_id=row.company_id)
    provider = provider_for(session, row.action_type)
    clean = (_clean_conditions(session, provider, row.company_id, conditions) if conditions is not None
             else dict(row.conditions or {}))
    new_enabled = row.enabled if enabled is None else enabled
    new_paused = (row.paused_at is not None) if paused is None else paused
    if new_enabled and not new_paused:
        _check_auto_provider(session, row.action_type)
    repo.update_rule(session, rule_id, enabled=new_enabled, conditions=clean,
                     daily_cap=row.daily_cap if daily_cap is None else daily_cap,
                     note=row.note if note is None else (note.strip() or None), paused=new_paused,
                     user_id=ctx.user_id)
    audit_record(session, "intel.rule.updated", "intel.auto_rule", rule_id, {
        "enabled": new_enabled, "paused": new_paused, "conditions": clean,
        "daily_cap": row.daily_cap if daily_cap is None else daily_cap})
    return get_rule(session, rule_id)
