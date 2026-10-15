"""Findings for people: list them within the user's scope, and the things a person does with one."""

from datetime import UTC
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.intel.domain.rules import CLOSED_STATUSES, OPEN_STATUSES, can_move, rank_score, reorder_by_preference
from ziira.modules.intel.permissions import FINDINGS_MANAGE, FINDINGS_RESPOND, FINDINGS_VIEW
from ziira.modules.intel.public import FindingBrief
from ziira.modules.intel.repository import findings_repo as repo
from ziira.sdk import (
    Event,
    NotFound,
    RequestContext,
    Session,
    ValidationFailed,
    audit_record,
    company_setting,
    current_context,
    publish,
    recipients_with_permission,
    send_notification,
)


def _brief(r: Row[Any], reason: str | None = None) -> FindingBrief:
    return FindingBrief(id=r.id, severity=r.severity, area=r.area, summary=r.summary or "",
                        recommended_action=r.recommended_action, status=r.status, company_id=r.company_id,
                        branch_id=r.branch_id, amount=r.amount, reason=reason)


def top_for(session: Session, context: RequestContext, limit: int) -> list[FindingBrief]:
    """The most pressing open findings in the user's scope, ranked by severity, money at stake and age."""
    from datetime import datetime

    sql, params = repo.scope_clause(context, FINDINGS_VIEW)
    rows = repo.open_for_ranking(session, sql, params, max(limit * 4, 20))
    now = datetime.now(UTC)
    ranked = sorted(rows, key=lambda r: -rank_score(r.severity, r.amount, (now - r.first_seen_at).days))
    ordered, reasons = _with_ai_order(session, ranked)
    return [_brief(r, reasons.get(r.id)) for r in ordered[:limit]]


def _with_ai_order(session: Session, ranked: list[Row[Any]]) -> tuple[list[Row[Any]], dict[UUID, str]]:
    """The deterministic order, adjusted by the AI layer's stored order where there is a fresh one (same places, new
    order among the findings it ranked). Any problem leaves the deterministic order as it is."""
    from ziira.modules.intel.services import explain

    preferred: dict[UUID, list[UUID]] = {}
    reasons: dict[UUID, str] = {}
    try:
        with session.begin_nested():
            for company_id in {r.company_id for r in ranked if r.company_id}:
                stored = explain.fresh_ranking(session, company_id)
                if stored:
                    preferred[company_id] = [i for i, _ in stored]
                    reasons.update({i: why for i, why in stored if why})
        if not preferred:
            return ranked, {}
        by_id = {r.id: r for r in ranked}
        order = reorder_by_preference([(r.id, r.company_id) for r in ranked], preferred)
        return [by_id[i] for i in order], {i: why for i, why in reasons.items() if i in by_id}
    except Exception:  # noqa: BLE001 - the deterministic order is always good enough
        return ranked, {}


def counts_by_severity(session: Session, context: RequestContext) -> dict[str, int]:
    sql, params = repo.scope_clause(context, FINDINGS_VIEW)
    out: dict[str, int] = {}
    for r in repo.counts(session, sql, params, open_only=True):
        out[r.severity] = out.get(r.severity, 0) + int(r.n)
    return out


def summary(session: Session) -> dict[str, Any]:
    """Open findings by severity, status and area, with the money at stake, for the user's scope."""
    ctx = current_context()
    sql, params = repo.scope_clause(ctx, FINDINGS_VIEW)
    rows = repo.counts(session, sql, params, open_only=True)
    by_severity: dict[str, int] = {}
    by_area: dict[str, int] = {}
    by_status: dict[str, int] = {}
    amount = 0
    for r in rows:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + int(r.n)
        by_area[r.area or "general"] = by_area.get(r.area or "general", 0) + int(r.n)
        by_status[r.status] = by_status.get(r.status, 0) + int(r.n)
        amount += r.amount
    return {"open": sum(by_severity.values()), "by_severity": by_severity, "by_area": by_area, "by_status": by_status,
            "amount_at_stake": amount}


def list_for_user(session: Session, **filters: Any) -> list[Row[Any]]:
    ctx = current_context()
    sql, params = repo.scope_clause(ctx, FINDINGS_VIEW)
    return repo.list_findings(session, sql, params, **filters)


def get_for_user(session: Session, finding_id: UUID) -> tuple[Row[Any], list[Row[Any]]]:
    ctx = current_context()
    row = repo.get_finding(session, finding_id)
    if row is None or not ctx.can(FINDINGS_VIEW, company_id=row.company_id, branch_id=row.branch_id):
        raise NotFound("Finding not found")
    return row, repo.events_of(session, finding_id)


def _load(session: Session, finding_id: UUID) -> Row[Any]:
    row = repo.get_finding(session, finding_id)
    ctx = current_context()
    if row is None or not ctx.can(FINDINGS_VIEW, company_id=row.company_id, branch_id=row.branch_id):
        raise NotFound("Finding not found")
    return row


def _may_respond(row: Row[Any]) -> bool:
    ctx = current_context()
    if ctx.can(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id):
        return True
    return row.owner_user_id is not None and row.owner_user_id == ctx.user_id and ctx.can(
        FINDINGS_RESPOND, company_id=row.company_id, branch_id=row.branch_id)


def _move(session: Session, row: Row[Any], target: str, event: str, note: str | None, *,
          explanation: str | None = None) -> Row[Any]:
    if not can_move(row.status, target):
        raise ValidationFailed(f"A finding that is {row.status} cannot become {target}")
    repo.set_status(session, row.id, target, explanation=explanation)
    if target in CLOSED_STATUSES:
        from ziira.modules.intel.services import actions

        actions.expire_for_finding(session, row.id)
    repo.add_event(session, row.id, event, user_id=current_context().user_id, channel="app", note=note)
    audit_record(session, f"finding.{event}", "intel.finding", row.id, {"from": row.status, "to": target})
    updated = repo.get_finding(session, row.id)
    assert updated is not None
    return updated


def acknowledge(session: Session, finding_id: UUID, note: str | None) -> Row[Any]:
    row = _load(session, finding_id)
    if not _may_respond(row):
        current_context().require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    return _move(session, row, "acknowledged", "acknowledged", note)


def explain(session: Session, finding_id: UUID, note: str) -> Row[Any]:
    """Someone gives the answer to a finding: the explanation is recorded with who said it, which protects honest staff
    as well as the business."""
    row = _load(session, finding_id)
    if not _may_respond(row):
        current_context().require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    if not note.strip():
        raise ValidationFailed("Say what happened")
    return _move(session, row, "explained", "explained", note, explanation=note.strip())


def resolve(session: Session, finding_id: UUID, note: str | None) -> Row[Any]:
    row = _load(session, finding_id)
    current_context().require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    return _move(session, row, "resolved", "resolved", note)


def dismiss(session: Session, finding_id: UUID, reason: str) -> Row[Any]:
    """Close a finding as not a problem. A reason is required; the same problem is not raised again."""
    row = _load(session, finding_id)
    current_context().require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    if not reason.strip():
        raise ValidationFailed("Give a reason for dismissing this finding")
    return _move(session, row, "dismissed", "dismissed", reason.strip())


def assign(session: Session, finding_id: UUID, user_id: UUID | None) -> Row[Any]:
    row = _load(session, finding_id)
    ctx = current_context()
    ctx.require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    if row.status in CLOSED_STATUSES:
        raise ValidationFailed("This finding is closed")
    if user_id is not None:
        _require_can_answer(session, row, user_id)
    repo.set_owner(session, row.id, user_id)
    repo.add_event(session, row.id, "assigned" if user_id else "unassigned", user_id=ctx.user_id, channel="app")
    updated = repo.get_finding(session, row.id)
    assert updated is not None
    return updated


def _require_can_answer(session: Session, row: Row[Any], user_id: UUID) -> None:
    people = {p.user_id: p for p in recipients_with_permission(session, FINDINGS_RESPOND)}
    person = people.get(user_id)
    if person is None or not person.covers(FINDINGS_RESPOND, row.company_id, row.branch_id):
        raise ValidationFailed("That person cannot answer findings for this branch")


def ask(session: Session, finding_id: UUID, user_id: UUID, message: str) -> Row[Any]:
    """Level 2 action: ask a person to explain. They see it in their findings, and are messaged if the business has a
    channel on. Needs the business to allow it (company setting `intel_action_level` of 2 or more)."""
    row = _load(session, finding_id)
    ctx = current_context()
    ctx.require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    if int(company_setting(session, row.company_id, "intel_action_level")) < 2:
        raise ValidationFailed("Asking people to explain is switched off: raise the 'intel_action_level' setting to 2")
    if row.status in CLOSED_STATUSES:
        raise ValidationFailed("This finding is closed")
    _require_can_answer(session, row, user_id)
    repo.set_owner(session, row.id, user_id)
    channel = str(company_setting(session, row.company_id, "intel_alert_channel"))
    person = next(p for p in recipients_with_permission(session, FINDINGS_RESPOND) if p.user_id == user_id)
    delivered = None
    address = person.phone if channel == "sms" else person.email if channel == "email" else None
    if address:
        text = f"Please explain: {row.summary} {message}".strip()
        delivered = send_notification(session, company_id=row.company_id, channel=channel, recipient=address, body=text,
                                      subject="Please explain a finding" if channel == "email" else None,
                                      ref_type="intel.finding", ref_id=row.id)
    repo.add_event(session, row.id, "asked", user_id=ctx.user_id, channel=channel if delivered else "app",
                   note=f"Asked {person.full_name}: {message}".strip())
    audit_record(session, "finding.asked", "intel.finding", row.id, {"user": str(user_id)})
    publish(session, Event("finding.asked", "intel.finding", row.id, {"user_id": user_id}))
    updated = repo.get_finding(session, row.id)
    assert updated is not None
    return updated


def open_statuses() -> tuple[str, ...]:
    return OPEN_STATUSES
