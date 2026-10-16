"""Findings for people: list them within the user's scope, and the things a person does with one."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.intel.domain import plain
from ziira.modules.intel.domain.grouping import group_findings
from ziira.modules.intel.domain.rules import CLOSED_STATUSES, OPEN_STATUSES, can_move, rank_score, reorder_by_preference
from ziira.modules.intel.domain.source import is_connected_check
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
    can_reach,
    company_setting,
    current_context,
    notify_user,
    publish,
    recipients_with_permission,
)


def _brief(r: Row[Any], reason: str | None = None) -> FindingBrief:
    return FindingBrief(id=r.id, severity=r.severity, area=r.area, summary=r.summary or "",
                        recommended_action=r.recommended_action, status=r.status, company_id=r.company_id,
                        branch_id=r.branch_id, amount=r.amount, reason=reason,
                        source="connected" if is_connected_check(r.check_code) else "ziira")


def top_for(session: Session, context: RequestContext, limit: int) -> list[FindingBrief]:
    """The most pressing open findings in the user's scope, ranked by severity, money at stake and age."""
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
            "amount_at_stake": amount, "snoozed": repo.count_snoozed(session, sql, params)}


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
    ways = [channel]
    if channel != "off" and can_reach(session, row.company_id, user_id, "alerts", ways):
        text = f"Please explain: {row.summary} {message}".strip()
        delivered = notify_user(session, company_id=row.company_id, user_id=user_id, kind="alerts", body=text,
                                subject="Please explain a finding", default_channels=ways,
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


# --------------------------------------------------------------------------- less noise
GROUP_SCAN = 500  # the most findings looked at when grouping (more than this is far beyond what anyone reads)
MEMBERS_SHOWN = 25  # members listed inside one group


def grouped(session: Session, *, view: str, limit: int, offset: int, **filters: Any) -> dict[str, Any]:
    """Findings in the user's scope as groups (same kind, same branch, same day), most pressing first: urgency, money at
    stake, recency. Nothing stored changes; `members` are the findings themselves."""
    ctx = current_context()
    sql, params = repo.scope_clause(ctx, FINDINGS_VIEW)
    rows = repo.list_findings(
        session, sql, params, statuses=None, limit=GROUP_SCAN, offset=0, view=view, **filters
    )
    groups = group_findings(rows)
    urgent = sum(1 for g in groups if g.severity in ("critical", "high"))
    page = groups[offset : offset + limit]
    return {
        "total_groups": len(groups),
        "total_findings": len(rows),
        "urgent_groups": urgent,
        "groups": [
            {
                "key": g.key,
                "check_code": g.members[0].check_code,
                "area": g.members[0].area,
                "company_id": g.members[0].company_id,
                "branch_id": g.members[0].branch_id,
                "day": g.members[0].first_seen_at.date(),
                "count": len(g.members),
                "severity": g.severity,
                "amount": g.amount,
                "last_seen_at": g.last_seen_at,
                "members": g.members[:MEMBERS_SHOWN],
            }
            for g in page
        ],
    }


def related(session: Session, finding_id: UUID, limit: int = 8) -> list[Row[Any]]:
    row = _load(session, finding_id)
    sql, params = repo.scope_clause(current_context(), FINDINGS_VIEW)
    return repo.related_findings(session, sql, params, row, limit)


def snooze(session: Session, finding_id: UUID, days: int | None) -> Row[Any]:
    """Put an open finding aside for some days (None brings it back now). It returns by itself, or sooner if it
    gets worse."""
    row = _load(session, finding_id)
    if not _may_respond(row):
        current_context().require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    if row.status not in OPEN_STATUSES:
        raise ValidationFailed("This is already finished")
    if days is not None and not 1 <= days <= 90:
        raise ValidationFailed("Choose between 1 and 90 days")
    until = datetime.now(UTC) + timedelta(days=days) if days else None
    repo.set_snooze(session, row.id, until)
    repo.add_event(
        session,
        row.id,
        "snoozed" if days else "unsnoozed",
        user_id=current_context().user_id,
        channel="app",
        note=f"Until {until.date().isoformat()}" if until else None,
    )
    audit_record(session, "finding.snoozed" if days else "finding.unsnoozed", "intel.finding", row.id, {"days": days})
    updated = repo.get_finding(session, row.id)
    assert updated is not None
    return updated


def subject_of(row: Row[Any]) -> dict[str, Any] | None:
    """The person or thing a finding is about (a cashier, a supplier, a product), when it is about one, with
    its name."""
    kind = plain.subject_kind(row.entity_type)
    if not kind or row.entity_id is None:
        return None
    for record in (row.evidence or {}).get("records", []):
        if record.get("type") == row.entity_type and record.get("id") == str(row.entity_id):
            return {"type": row.entity_type, "kind": kind, "id": row.entity_id, "label": record.get("label") or kind}
    return None


def ignore_options(session: Session, finding_id: UUID) -> dict[str, Any]:
    """What "this is normal" can be limited to for this finding: its branch, the person or thing it is about,
    or everywhere."""
    from sqlalchemy import text

    row = _load(session, finding_id)
    branch = None
    if row.branch_id:
        found = session.execute(text("select name from kernel.branch where id = :i"), {"i": str(row.branch_id)}).first()
        branch = {"id": row.branch_id, "name": found.name if found else ""}
    return {"branch": branch, "subject": subject_of(row), "tunable": row.check_code in plain.TUNABLE}


def ignore(
    session: Session, finding_id: UUID, *, scope: str, days: int | None, reason: str | None, tune: bool
) -> dict[str, Any]:
    """Not a problem, for a kind of thing: close this finding, remember the rule (so it is not raised again for
    that branch or person, for some days or always), close the other open ones the rule covers, and (only when
    asked, and only for the checks that allow it) raise the check's own limit a little above this one. All of it
    is on the record."""
    row = _load(session, finding_id)
    ctx = current_context()
    ctx.require(FINDINGS_MANAGE, company_id=row.company_id, branch_id=row.branch_id)
    options = ignore_options(session, finding_id)
    if scope not in ("branch", "person", "everywhere"):
        raise ValidationFailed("Choose where to ignore it")
    if days is not None and not 1 <= days <= 3650:
        raise ValidationFailed("Choose a number of days")
    branch_id = row.branch_id if scope == "branch" else None
    subject = options["subject"] if scope == "person" else None
    if scope == "branch" and branch_id is None:
        raise ValidationFailed("This is not about one branch")
    if scope == "person" and subject is None:
        raise ValidationFailed("This is not about one person or thing")
    label = options["branch"]["name"] if scope == "branch" else subject["label"] if subject else ""
    text_reason = (reason or "").strip() or "This is normal for us"
    rule_id = repo.insert_rule(
        session,
        company_id=row.company_id,
        check_code=row.check_code,
        branch_id=branch_id,
        entity_type=row.entity_type if subject else None,
        entity_id=row.entity_id if subject else None,
        scope_label=label,
        until_date=date.today() + timedelta(days=days) if days else None,
        reason=text_reason,
        user_id=ctx.user_id,
    )
    audit_record(
        session,
        "finding.ignore_rule",
        "intel.finding",
        row.id,
        {"rule": str(rule_id), "scope": scope, "days": days, "check": row.check_code},
    )
    closed = 0
    if can_move(row.status, "dismissed"):
        _move(session, row, "dismissed", "dismissed", text_reason)
    for other in repo.open_matching(
        session,
        company_id=row.company_id,
        check_code=row.check_code,
        branch_id=branch_id,
        entity_type=row.entity_type if subject else None,
        entity_id=row.entity_id if subject else None,
    ):
        if other.id != row.id and can_move(other.status, "dismissed"):
            _move(session, other, "dismissed", "dismissed", f"{text_reason} (ignore rule)")
            closed += 1
    tuned = _tune(session, row) if tune else None
    return {"rule_id": rule_id, "closed": closed, "tuned": tuned}


def _tune(session: Session, row: Row[Any]) -> dict[str, str] | None:
    """Raise the check's own limit to a little above this finding's size, when the check allows and it would be
    a rise."""
    from ziira.modules.intel.services import checks_admin

    name = plain.TUNABLE.get(row.check_code or "")
    if not name or row.value is None:
        return None
    new = (abs(Decimal(row.value)) * Decimal("1.1")).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    current = next((c for c in checks_admin.list_checks(session) if c["code"] == row.check_code), None)
    if current is None or Decimal(str(current["params"].get(name, 0))) >= new:
        return None
    checks_admin.update_check(session, row.check_code, None, {name: str(new)})
    return {"param": name, "value": str(new)}


def list_rules(session: Session) -> list[Row[Any]]:
    ctx = current_context()
    rules = repo.active_rules(session, date.today())
    return [r for r in rules if ctx.can(FINDINGS_MANAGE, company_id=r.company_id, branch_id=r.branch_id)]


def remove_rule(session: Session, rule_id: UUID) -> None:
    rule = repo.get_rule(session, rule_id)
    ctx = current_context()
    if rule is None or not ctx.can(FINDINGS_MANAGE, company_id=rule.company_id, branch_id=rule.branch_id):
        raise NotFound("Rule not found")
    repo.remove_rule(session, rule_id, ctx.user_id)
    audit_record(
        session, "finding.ignore_rule_removed", "intel.finding", None, {"rule": str(rule_id), "check": rule.check_code}
    )


def person_name(session: Session, user_id: UUID | None) -> str | None:
    """The name of a user, for showing who has a finding."""
    from sqlalchemy import text

    if user_id is None:
        return None
    found = session.execute(text("select full_name from kernel.app_user where id = :i"), {"i": str(user_id)}).first()
    return str(found.full_name) if found else None
