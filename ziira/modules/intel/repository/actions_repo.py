"""Database access for actions: proposals, automation rules and the action log. SQL only."""

import json
from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session

PROPOSAL_COLUMNS = (
    "p.id, p.finding_id, p.company_id, p.branch_id, p.action_type, p.params, p.description, p.facts, p.status, "
    "p.level_at_proposal, p.proposed_at, p.decided_by, u.full_name as decided_by_name, p.decided_at, p.decision_note, "
    "p.executed_at, p.result, f.summary as finding_summary, f.severity as finding_severity, "
    "f.status as finding_status, f.check_code as finding_check_code"
)
PROPOSAL_FROM = (
    "from intel.action_proposal p join intel.finding f on f.id = p.finding_id "
    "left join kernel.app_user u on u.id = p.decided_by"
)
LOG_COLUMNS = (
    "l.id, l.created_at, l.proposal_id, l.finding_id, l.company_id, l.branch_id, l.action_type, l.mode, "
    "l.actor_user_id, u.full_name as actor_name, l.rule_id, l.level, l.params, l.outcome, l.message, l.result, "
    "f.summary as finding_summary"
)


def _s(value: UUID | None) -> str | None:
    return str(value) if value else None


def _j(value: Any) -> str:
    return json.dumps(value, default=str)


# --------------------------------------------------------------------------- findings still to look at
def findings_to_look_at(s: Session, company_id: UUID, check_codes: list[str], limit: int) -> Sequence[Row[Any]]:
    """Open findings of these checks that the action providers have not looked at yet (new, or come back), most
    serious first."""
    return s.execute(text(
        "select f.id, f.check_code, f.severity, f.company_id, f.branch_id, f.entity_type, f.entity_id, f.amount, "
        "f.value, f.summary, f.evidence from intel.finding f where f.company_id = :c "
        "and f.status in ('new', 'sent', 'acknowledged', 'explained') and f.check_code = any(:codes) "
        "and f.actions_checked_at is null order by array_position(array['critical','high','medium','low','info'], "
        "f.severity), f.amount desc nulls last, f.first_seen_at limit :n"),
        {"c": str(company_id), "codes": check_codes, "n": limit}).all()


def mark_looked_at(s: Session, finding_ids: list[UUID]) -> None:
    if finding_ids:
        s.execute(text("update intel.finding set actions_checked_at = now() where id = any(:ids)"),
                  {"ids": [str(i) for i in finding_ids]})


def forget_looked_at(s: Session, finding_ids: list[UUID]) -> None:
    """A finding that came back is looked at again."""
    if finding_ids:
        s.execute(text("update intel.finding set actions_checked_at = null where id = any(:ids)"),
                  {"ids": [str(i) for i in finding_ids]})


# --------------------------------------------------------------------------- proposals
def blocked(s: Session, finding_id: UUID, action_type: str, params_hash: str, cooldown_days: int) -> bool:
    """True if the same proposal is already waiting, was turned down or failed (a failure is never tried again by
    itself), or was done within the cooldown."""
    return s.execute(text(
        "select 1 from intel.action_proposal where finding_id = :f and action_type = :t and params_hash = :h "
        "and (status in ('proposed', 'approved', 'rejected', 'failed') or (status = 'executed' "
        "and proposed_at > now() - make_interval(days => :d))) limit 1"),
        {"f": str(finding_id), "t": action_type, "h": params_hash, "d": cooldown_days}).first() is not None


def insert_proposal(s: Session, *, finding_id: UUID, company_id: UUID, branch_id: UUID | None, action_type: str,
                    params: dict[str, Any], params_hash: str, description: str, facts: dict[str, str],
                    level: int) -> UUID | None:
    row = s.execute(text(
        "insert into intel.action_proposal (tenant_id, finding_id, company_id, branch_id, action_type, params, "
        "params_hash, description, facts, level_at_proposal) values (kernel.current_tenant(), :f, :c, :b, :t, "
        "cast(:p as jsonb), :h, :d, cast(:fa as jsonb), :l) on conflict (tenant_id, finding_id, action_type, "
        "params_hash) where status in ('proposed', 'approved') do nothing returning id"),
        {"f": str(finding_id), "c": str(company_id), "b": _s(branch_id), "t": action_type, "p": _j(params),
         "h": params_hash, "d": description[:1000], "fa": _j(facts), "l": level}).first()
    found: UUID | None = row.id if row else None
    return found


def get_proposal(s: Session, proposal_id: UUID, *, lock: bool = False) -> Row[Any] | None:
    """A proposal with its finding's summary and status. With `lock`, the proposal row is locked (not the finding)."""
    if lock:
        s.execute(text("select 1 from intel.action_proposal where id = :i for update"), {"i": str(proposal_id)})
    return s.execute(text(f"select {PROPOSAL_COLUMNS} {PROPOSAL_FROM} where p.id = :i"),
                     {"i": str(proposal_id)}).first()


def list_proposals(s: Session, scope_sql: str, scope_params: dict[str, Any], *, statuses: list[str] | None,
                   finding_id: UUID | None, company_id: UUID | None, limit: int, offset: int) -> Sequence[Row[Any]]:
    clauses = [scope_sql]
    params: dict[str, Any] = {**scope_params, "limit": limit, "offset": offset}
    if statuses:
        clauses.append("p.status = any(:statuses)")
        params["statuses"] = statuses
    if finding_id:
        clauses.append("p.finding_id = :finding")
        params["finding"] = str(finding_id)
    if company_id:
        clauses.append("p.company_id = :company")
        params["company"] = str(company_id)
    return s.execute(text(
        f"select {PROPOSAL_COLUMNS} {PROPOSAL_FROM} where {' and '.join(clauses)} "
        "order by (p.status = 'proposed') desc, p.proposed_at desc, p.id limit :limit offset :offset"), params).all()


def proposals_of_finding(s: Session, finding_id: UUID) -> Sequence[Row[Any]]:
    return s.execute(text(f"select {PROPOSAL_COLUMNS} {PROPOSAL_FROM} where p.finding_id = :f "
                          "order by p.proposed_at, p.id"), {"f": str(finding_id)}).all()


def set_decision(s: Session, proposal_id: UUID, *, status: str, user_id: UUID | None, note: str | None,
                 params: dict[str, Any] | None = None) -> None:
    s.execute(text(
        "update intel.action_proposal set status = :st, decided_by = :u, decided_at = now(), decision_note = :n, "
        "params = coalesce(cast(:p as jsonb), params) where id = :i"),
        {"st": status, "u": _s(user_id), "n": note, "p": _j(params) if params is not None else None,
         "i": str(proposal_id)})


def set_outcome(s: Session, proposal_id: UUID, *, status: str, result: dict[str, Any]) -> None:
    s.execute(text("update intel.action_proposal set status = :st, executed_at = now(), result = cast(:r as jsonb) "
                   "where id = :i"), {"st": status, "r": _j(result), "i": str(proposal_id)})


def expire_for_closed_findings(s: Session, company_id: UUID | None = None,
                               finding_id: UUID | None = None) -> Sequence[Row[Any]]:
    """Proposals still waiting on a finding that has closed (resolved or dismissed) become expired. Returns
    (id, finding_id, action_type) of each."""
    return s.execute(text(
        "update intel.action_proposal p set status = 'expired', decision_note = 'The finding was closed' "
        "from intel.finding f where f.id = p.finding_id and p.status in ('proposed', 'approved') "
        "and f.status in ('resolved', 'dismissed') and (cast(:c as uuid) is null or p.company_id = :c) "
        "and (cast(:f as uuid) is null or p.finding_id = :f) returning p.id, p.finding_id, p.action_type"),
        {"c": _s(company_id), "f": _s(finding_id)}).all()


def cancel_waiting(s: Session, company_id: UUID, note: str) -> int:
    """Withdraw every proposal still waiting for a company (the owner took Intelligence back to a lower level)."""
    return len(s.execute(text(
        "update intel.action_proposal set status = 'cancelled', decision_note = :n where company_id = :c "
        "and status = 'proposed' returning id"), {"c": str(company_id), "n": note}).all())


# --------------------------------------------------------------------------- rules
def list_rules(s: Session, company_id: UUID | None = None) -> Sequence[Row[Any]]:
    return s.execute(text(
        "select r.*, (select count(*) from intel.action_log l where l.rule_id = r.id) as times_used "
        "from intel.auto_rule r where (cast(:c as uuid) is null or r.company_id = :c) "
        "order by r.created_at, r.id"), {"c": _s(company_id)}).all()


def get_rule(s: Session, rule_id: UUID) -> Row[Any] | None:
    return s.execute(text(
        "select r.*, (select count(*) from intel.action_log l where l.rule_id = r.id) as times_used "
        "from intel.auto_rule r where r.id = :i"), {"i": str(rule_id)}).first()


def active_rules(s: Session, company_id: UUID, action_type: str) -> Sequence[Row[Any]]:
    return s.execute(text(
        "select * from intel.auto_rule where company_id = :c and action_type = :t and enabled and paused_at is null "
        "order by created_at, id"), {"c": str(company_id), "t": action_type}).all()


def has_active_rule(s: Session, company_id: UUID) -> bool:
    return s.execute(text("select 1 from intel.auto_rule where company_id = :c and enabled and paused_at is null "
                          "limit 1"), {"c": str(company_id)}).first() is not None


def insert_rule(s: Session, *, company_id: UUID, action_type: str, conditions: dict[str, Any], daily_cap: int,
                note: str | None, user_id: UUID | None) -> UUID:
    row = s.execute(text(
        "insert into intel.auto_rule (tenant_id, company_id, action_type, conditions, daily_cap, note, created_by) "
        "values (kernel.current_tenant(), :c, :t, cast(:co as jsonb), :d, :n, :u) returning id"),
        {"c": str(company_id), "t": action_type, "co": _j(conditions), "d": daily_cap, "n": note,
         "u": _s(user_id)}).one()
    rule_id: UUID = row.id
    return rule_id


def update_rule(s: Session, rule_id: UUID, *, enabled: bool, conditions: dict[str, Any], daily_cap: int,
                note: str | None, paused: bool, user_id: UUID | None) -> None:
    s.execute(text(
        "update intel.auto_rule set enabled = :e, conditions = cast(:co as jsonb), daily_cap = :d, note = :n, "
        "paused_at = case when :p then coalesce(paused_at, now()) else null end, updated_at = now(), updated_by = :u "
        "where id = :i"),
        {"e": enabled, "co": _j(conditions), "d": daily_cap, "n": note, "p": paused, "u": _s(user_id),
         "i": str(rule_id)})


def runs_today(s: Session, rule_id: UUID, timezone: str, today: date) -> int:
    """How many times the rule acted on this day of the company's time zone (failures count: they were attempts)."""
    return int(s.execute(text(
        "select count(*) from intel.action_log where rule_id = :r and mode = 'automatic' "
        "and (created_at at time zone :tz)::date = :d"), {"r": str(rule_id), "tz": timezone, "d": today}).scalar_one())


# --------------------------------------------------------------------------- the log
def add_log(s: Session, *, proposal_id: UUID | None, finding_id: UUID | None, company_id: UUID,
            branch_id: UUID | None, action_type: str, mode: str, actor_user_id: UUID | None, rule_id: UUID | None,
            level: int, params: dict[str, Any], outcome: str, message: str, result: dict[str, Any] | None) -> UUID:
    row = s.execute(text(
        "insert into intel.action_log (tenant_id, proposal_id, finding_id, company_id, branch_id, action_type, mode, "
        "actor_user_id, rule_id, level, params, outcome, message, result) values (kernel.current_tenant(), :p, :f, "
        ":c, :b, :t, :m, :u, :r, :l, cast(:pa as jsonb), :o, :me, cast(:re as jsonb)) returning id"),
        {"p": _s(proposal_id), "f": _s(finding_id), "c": str(company_id), "b": _s(branch_id), "t": action_type,
         "m": mode, "u": _s(actor_user_id), "r": _s(rule_id), "l": level, "pa": _j(params), "o": outcome,
         "me": message[:1000], "re": _j(result) if result is not None else None}).one()
    log_id: UUID = row.id
    return log_id


def list_log(s: Session, scope_sql: str, scope_params: dict[str, Any], *, company_id: UUID | None,
             action_type: str | None, mode: str | None, limit: int, offset: int) -> Sequence[Row[Any]]:
    clauses = [scope_sql.replace("f.", "l.")]
    params: dict[str, Any] = {**scope_params, "limit": limit, "offset": offset}
    if company_id:
        clauses.append("l.company_id = :company")
        params["company"] = str(company_id)
    if action_type:
        clauses.append("l.action_type = :atype")
        params["atype"] = action_type
    if mode:
        clauses.append("l.mode = :mode")
        params["mode"] = mode
    return s.execute(text(
        f"select {LOG_COLUMNS} from intel.action_log l left join kernel.app_user u on u.id = l.actor_user_id "
        f"left join intel.finding f on f.id = l.finding_id where {' and '.join(clauses)} "
        "order by l.created_at desc, l.id limit :limit offset :offset"), params).all()
