"""Database access for the intel schema (checks, findings, baselines). SQL only; rules live in domain/ and services/."""

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import RequestContext, Session

COLUMNS = (
    "f.id, f.check_code, f.area, f.company_id, f.branch_id, f.entity_type, f.entity_id, f.period_start, f.period_end, "
    "f.value, f.expected_value, f.amount, f.severity, f.summary, f.recommended_action, f.evidence, f.explanation, "
    "f.status, f.owner_user_id, f.first_seen_at, f.last_seen_at, f.resolved_at, f.alerted_at, f.created_at"
)


def _s(value: UUID | None) -> str | None:
    return str(value) if value else None


# --------------------------------------------------------------------------- scope
def scope_clause(context: RequestContext, permission: str) -> tuple[str, dict[str, Any]]:
    """SQL limiting findings to the companies and branches where the user holds `permission`."""
    scopes = context.scopes_with(permission)
    if scopes is None:
        return "true", {}
    if not scopes:
        return "false", {}
    parts: list[str] = []
    params: dict[str, Any] = {}
    for i, (company, branch) in enumerate(scopes):
        if company is None:
            return "true", {}
        params[f"sc{i}"] = str(company)
        if branch is None:
            parts.append(f"f.company_id = :sc{i}")
        else:
            params[f"sb{i}"] = str(branch)
            parts.append(f"(f.company_id = :sc{i} and f.branch_id = :sb{i})")
    return "(" + " or ".join(parts) + ")", params


# --------------------------------------------------------------------------- check definitions and settings
def upsert_definition(s: Session, *, code: str, version: int, title: str, area: str, description: str, severity: str,
                      params: dict[str, Any]) -> UUID:
    row = s.execute(text(
        "insert into intel.check_definition (code, version, title, area, description, severity_default, definition) "
        "values (:c, :v, :t, :a, :d, :s, cast(:p as jsonb)) on conflict (code, version) do update set title = :t, "
        "area = :a, description = :d, severity_default = :s, definition = cast(:p as jsonb) returning id"),
        {"c": code, "v": version, "t": title, "a": area, "d": description, "s": severity,
         "p": json.dumps(params, default=str)}).one()
    check_id: UUID = row.id
    return check_id


def check_settings(s: Session) -> dict[str, tuple[bool, dict[str, Any]]]:
    rows = s.execute(text("select check_code, enabled, params from intel.check_setting")).all()
    return {r.check_code: (r.enabled, dict(r.params or {})) for r in rows}


def save_check_setting(s: Session, code: str, enabled: bool, params: dict[str, Any], user_id: UUID | None) -> None:
    s.execute(text(
        "insert into intel.check_setting (tenant_id, check_code, enabled, params, updated_at, updated_by) "
        "values (kernel.current_tenant(), :c, :e, cast(:p as jsonb), now(), :u) on conflict (tenant_id, check_code) "
        "do update set enabled = :e, params = cast(:p as jsonb), updated_at = now(), updated_by = :u"),
        {"c": code, "e": enabled, "p": json.dumps(params, default=str), "u": _s(user_id)})


# --------------------------------------------------------------------------- findings
def find_by_fingerprint(s: Session, code: str, fingerprint: str) -> Row[Any] | None:
    return s.execute(text(f"select {COLUMNS} from intel.finding f where f.check_code = :c and f.fingerprint = :fp"),
                     {"c": code, "fp": fingerprint}).first()


def insert_finding(s: Session, *, check_id: UUID, code: str, area: str, fingerprint: str, severity: str,
                   company_id: UUID, branch_id: UUID | None, entity_type: str | None, entity_id: UUID | None,
                   period_start: date | None, period_end: date | None, value: Decimal | None,
                   expected_value: Decimal | None, amount: Decimal | None, summary: str, action: str,
                   evidence: dict[str, Any]) -> UUID:
    row = s.execute(text(
        "insert into intel.finding (tenant_id, check_id, check_code, area, fingerprint, severity, company_id, "
        "branch_id, entity_type, entity_id, period_start, period_end, value, expected_value, amount, summary, "
        "recommended_action, evidence) values (kernel.current_tenant(), :ci, :cc, :ar, :fp, :sv, :co, :br, :et, :ei, "
        ":ps, :pe, :v, :ev, :am, :su, :ra, cast(:evd as jsonb)) returning id"),
        {"ci": str(check_id), "cc": code, "ar": area, "fp": fingerprint, "sv": severity, "co": str(company_id),
         "br": _s(branch_id), "et": entity_type, "ei": _s(entity_id), "ps": period_start, "pe": period_end,
         "v": value, "ev": expected_value, "am": amount, "su": summary[:1000], "ra": action[:1000],
         "evd": json.dumps(evidence, default=str)}).one()
    finding_id: UUID = row.id
    return finding_id


def refresh_finding(s: Session, finding_id: UUID, *, severity: str, value: Decimal | None,
                    expected_value: Decimal | None, amount: Decimal | None, summary: str, action: str,
                    evidence: dict[str, Any], reopen: bool) -> None:
    """The problem is still there: update what we know about it (and reopen it if it had been resolved)."""
    s.execute(text(
        "update intel.finding set severity = :sv, value = :v, expected_value = :ev, amount = :am, summary = :su, "
        "recommended_action = :ra, evidence = cast(:evd as jsonb), last_seen_at = now(), updated_at = now(), "
        "status = case when :reopen then 'new' else status end, resolved_at = case when :reopen then null "
        "else resolved_at end, alerted_at = case when :reopen then null else alerted_at end where id = :i"),
        {"sv": severity, "v": value, "ev": expected_value, "am": amount, "su": summary[:1000], "ra": action[:1000],
         "evd": json.dumps(evidence, default=str), "reopen": reopen, "i": str(finding_id)})


def open_ids_for_check(s: Session, code: str, company_id: UUID) -> dict[str, UUID]:
    """Fingerprint -> id of this check's findings that are still open, in the company."""
    rows = s.execute(text(
        "select fingerprint, id from intel.finding where check_code = :c and company_id = :co and status in "
        "('new', 'sent', 'acknowledged', 'explained')"), {"c": code, "co": str(company_id)}).all()
    return {r.fingerprint: r.id for r in rows}


def set_status(s: Session, finding_id: UUID, status: str, *, explanation: str | None = None) -> None:
    s.execute(text(
        "update intel.finding set status = :st, updated_at = now(), explanation = coalesce(:ex, explanation), "
        "resolved_at = case when :st in ('resolved', 'dismissed') then now() else resolved_at end where id = :i"),
        {"st": status, "ex": explanation, "i": str(finding_id)})


def set_owner(s: Session, finding_id: UUID, user_id: UUID | None) -> None:
    s.execute(text("update intel.finding set owner_user_id = :u, updated_at = now() where id = :i"),
              {"u": _s(user_id), "i": str(finding_id)})


def mark_alerted(s: Session, finding_id: UUID) -> None:
    s.execute(text("update intel.finding set alerted_at = now(), status = case when status = 'new' then 'sent' "
                   "else status end where id = :i"), {"i": str(finding_id)})


def add_event(s: Session, finding_id: UUID, event: str, *, user_id: UUID | None = None, channel: str | None = None,
              note: str | None = None) -> None:
    s.execute(text(
        "insert into intel.finding_event (tenant_id, finding_id, event, user_id, channel, note) "
        "values (kernel.current_tenant(), :f, :e, :u, :c, :n)"),
        {"f": str(finding_id), "e": event, "u": _s(user_id), "c": channel, "n": note[:2000] if note else None})


def events_of(s: Session, finding_id: UUID) -> list[Row[Any]]:
    return list(s.execute(text(
        "select e.id, e.created_at, e.event, e.user_id, u.full_name as user_name, e.channel, e.note "
        "from intel.finding_event e left join kernel.app_user u on u.id = e.user_id where e.finding_id = :f "
        "order by e.created_at, e.id"), {"f": str(finding_id)}).all())


def get_finding(s: Session, finding_id: UUID) -> Row[Any] | None:
    return s.execute(text(f"select {COLUMNS} from intel.finding f where f.id = :i"), {"i": str(finding_id)}).first()


def list_findings(s: Session, scope_sql: str, scope_params: dict[str, Any], *, statuses: list[str] | None,
                  severities: list[str] | None, area: str | None, company_id: UUID | None, branch_id: UUID | None,
                  check_code: str | None, owner_user_id: UUID | None, search: str | None, limit: int,
                  offset: int) -> list[Row[Any]]:
    where = [scope_sql]
    params: dict[str, Any] = dict(scope_params, limit=limit, offset=offset)
    if statuses:
        where.append("f.status = any(:statuses)")
        params["statuses"] = statuses
    if severities:
        where.append("f.severity = any(:severities)")
        params["severities"] = severities
    if area:
        where.append("f.area = :area")
        params["area"] = area
    if company_id:
        where.append("f.company_id = :company")
        params["company"] = str(company_id)
    if branch_id:
        where.append("f.branch_id = :branch")
        params["branch"] = str(branch_id)
    if check_code:
        where.append("f.check_code = :check_code")
        params["check_code"] = check_code
    if owner_user_id:
        where.append("f.owner_user_id = :owner")
        params["owner"] = str(owner_user_id)
    if search:
        where.append("(f.summary ilike :q or f.recommended_action ilike :q)")
        params["q"] = f"%{search}%"
    sql = (f"select {COLUMNS} from intel.finding f where {' and '.join(where)} order by "
           "array_position(array['critical','high','medium','low','info'], f.severity), f.last_seen_at desc, f.id "
           "limit :limit offset :offset")
    return list(s.execute(text(sql), params).all())


def open_for_ranking(s: Session, scope_sql: str, scope_params: dict[str, Any], limit: int) -> list[Row[Any]]:
    return list(s.execute(text(
        f"select {COLUMNS} from intel.finding f where {scope_sql} and f.status in ('new', 'sent', 'acknowledged') "
        "order by array_position(array['critical','high','medium','low','info'], f.severity), f.amount desc nulls last "
        "limit :limit"), dict(scope_params, limit=limit)).all())


def counts(s: Session, scope_sql: str, scope_params: dict[str, Any], *, open_only: bool) -> list[Row[Any]]:
    status = "f.status in ('new', 'sent', 'acknowledged', 'explained')" if open_only else "true"
    return list(s.execute(text(
        "select f.severity, f.status, f.area, count(*) as n, coalesce(sum(f.amount), 0) as amount "
        f"from intel.finding f where {scope_sql} and {status} "
        "group by f.severity, f.status, f.area"), scope_params).all())


def unalerted(s: Session, company_id: UUID) -> list[Row[Any]]:
    return list(s.execute(text(
        f"select {COLUMNS} from intel.finding f where f.company_id = :c and f.status = 'new' and f.alerted_at is null "
        "order by f.first_seen_at"), {"c": str(company_id)}).all())


# --------------------------------------------------------------------------- baselines
def replace_baselines(s: Session, company_id: UUID, metric: str,
                      rows: list[tuple[str, Decimal, Decimal, Decimal, int]]) -> None:
    s.execute(text("delete from intel.baseline where company_id = :c and metric = :m"),
              {"c": str(company_id), "m": metric})
    for key, mean, stddev, p95, n in rows:
        s.execute(text(
            "insert into intel.baseline (tenant_id, company_id, metric, dimension, mean, stddev, p95, sample_size, "
            "computed_at) values (kernel.current_tenant(), :c, :m, cast(:d as jsonb), :mean, :sd, :p95, :n, now())"),
            {"c": str(company_id), "m": metric, "d": json.dumps({"key": key}), "mean": mean, "sd": stddev, "p95": p95,
             "n": n})


def load_baselines(s: Session, company_id: UUID) -> dict[tuple[str, str], tuple[Decimal, Decimal, Decimal, int]]:
    rows = s.execute(text(
        "select metric, dimension ->> 'key' as k, mean, stddev, p95, sample_size from intel.baseline "
        "where company_id = :c"), {"c": str(company_id)}).all()
    return {(r.metric, r.k): (Decimal(r.mean), Decimal(r.stddev), Decimal(r.p95), int(r.sample_size)) for r in rows}


def baselines_computed_at(s: Session, company_id: UUID) -> Any:
    return s.execute(text("select max(computed_at) from intel.baseline where company_id = :c"),
                     {"c": str(company_id)}).scalar()
