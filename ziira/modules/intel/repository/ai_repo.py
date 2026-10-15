"""Database access for the AI layer: consent, usage, the call log, Ask Ziira conversations, the ranking. SQL only."""

import json
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session


def _s(value: UUID | None) -> str | None:
    return str(value) if value else None


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


# --------------------------------------------------------------------------- consent
def latest_consent(s: Session, company_id: UUID) -> Row[Any] | None:
    return s.execute(text(
        "select c.id, c.created_at, c.user_id, u.full_name as user_name, c.action, c.text_version, c.language, "
        "c.consent_text, c.text_hash, c.provider, c.model from intel.ai_consent c "
        "left join kernel.app_user u on u.id = c.user_id where c.company_id = :c "
        "order by c.created_at desc, c.id desc limit 1"), {"c": str(company_id)}).first()


def consents(s: Session, company_id: UUID, limit: int = 10) -> list[Row[Any]]:
    return list(s.execute(text(
        "select c.id, c.created_at, c.user_id, u.full_name as user_name, c.action, c.text_version, c.language, "
        "c.provider, c.model from intel.ai_consent c left join kernel.app_user u on u.id = c.user_id "
        "where c.company_id = :c order by c.created_at desc, c.id desc limit :n"),
        {"c": str(company_id), "n": limit}).all())


def add_consent(s: Session, *, company_id: UUID, user_id: UUID | None, action: str, version: str, language: str,
                consent_text: str, text_hash: str, provider: str, model: str | None) -> None:
    s.execute(text(
        "insert into intel.ai_consent (tenant_id, company_id, user_id, action, text_version, language, consent_text, "
        "text_hash, provider, model) values (kernel.current_tenant(), :c, :u, :a, :v, :l, :t, :h, :p, :m)"),
        {"c": str(company_id), "u": _s(user_id), "a": action, "v": version, "l": language, "t": consent_text,
         "h": text_hash, "p": provider, "m": model})


# --------------------------------------------------------------------------- usage
def month_used(s: Session, company_id: UUID, month: date) -> tuple[int, int, int]:
    """(input tokens, output tokens, calls) used by the company in the month."""
    row = s.execute(text("select input_tokens, output_tokens, calls from intel.ai_usage "
                         "where company_id = :c and month = :m"), {"c": str(company_id), "m": month}).first()
    return (int(row.input_tokens), int(row.output_tokens), int(row.calls)) if row else (0, 0, 0)


def add_usage(s: Session, company_id: UUID, month: date, input_tokens: int, output_tokens: int) -> None:
    s.execute(text(
        "insert into intel.ai_usage (tenant_id, company_id, month, input_tokens, output_tokens, calls) "
        "values (kernel.current_tenant(), :c, :m, :i, :o, 1) on conflict (tenant_id, company_id, month) do update set "
        "input_tokens = intel.ai_usage.input_tokens + :i, output_tokens = intel.ai_usage.output_tokens + :o, "
        "calls = intel.ai_usage.calls + 1, updated_at = now()"),
        {"c": str(company_id), "m": month, "i": input_tokens, "o": output_tokens})


def usage_history(s: Session, company_id: UUID, months: int = 6) -> list[Row[Any]]:
    return list(s.execute(text(
        "select month, input_tokens, output_tokens, calls from intel.ai_usage where company_id = :c "
        "order by month desc limit :n"), {"c": str(company_id), "n": months}).all())


# --------------------------------------------------------------------------- call log
def log_call(s: Session, *, company_id: UUID | None, user_id: UUID | None, purpose: str, ref_type: str | None,
             ref_id: UUID | None, provider: str | None, model: str | None, prompt_hash: str | None,
             tool_calls: list[dict[str, Any]], input_tokens: int, output_tokens: int, latency_ms: int | None,
             status: str, detail: str | None) -> UUID:
    row = s.execute(text(
        "insert into intel.ai_call_log (tenant_id, company_id, user_id, purpose, ref_type, ref_id, provider, model, "
        "prompt_hash, tool_calls, input_tokens, output_tokens, latency_ms, status, detail) values "
        "(kernel.current_tenant(), :c, :u, :p, :rt, :ri, :pr, :m, :h, cast(:t as jsonb), :i, :o, :l, :st, :d) "
        "returning id"),
        {"c": _s(company_id), "u": _s(user_id), "p": purpose, "rt": ref_type, "ri": _s(ref_id), "pr": provider,
         "m": model, "h": prompt_hash, "t": _json(tool_calls), "i": input_tokens, "o": output_tokens, "l": latency_ms,
         "st": status, "d": detail[:500] if detail else None}).one()
    call_id: UUID = row.id
    return call_id


def list_calls(s: Session, company_id: UUID, limit: int, offset: int) -> list[Row[Any]]:
    return list(s.execute(text(
        "select l.id, l.created_at, l.user_id, u.full_name as user_name, l.purpose, l.ref_type, l.ref_id, l.provider, "
        "l.model, l.prompt_hash, l.tool_calls, l.input_tokens, l.output_tokens, l.latency_ms, l.status, l.detail "
        "from intel.ai_call_log l left join kernel.app_user u on u.id = l.user_id where l.company_id = :c "
        "order by l.created_at desc, l.id limit :n offset :o"), {"c": str(company_id), "n": limit, "o": offset}).all())


def purge_old(s: Session, log_days: int, conversation_days: int) -> int:
    """Forget call-log rows older than `log_days` and conversations idle for more than `conversation_days`."""
    n = len(s.execute(text("delete from intel.ai_call_log where created_at < now() - make_interval(days => :d) "
                           "returning id"), {"d": log_days}).all())
    n += len(s.execute(text("delete from intel.ask_session where last_at < now() - make_interval(days => :d) "
                            "returning id"), {"d": conversation_days}).all())
    return n


# --------------------------------------------------------------------------- Ask Ziira conversations
def create_session(s: Session, company_id: UUID, user_id: UUID, title: str) -> UUID:
    row = s.execute(text(
        "insert into intel.ask_session (tenant_id, company_id, user_id, title) "
        "values (kernel.current_tenant(), :c, :u, :t) returning id"),
        {"c": str(company_id), "u": str(user_id), "t": title[:120]}).one()
    session_id: UUID = row.id
    return session_id


def get_session(s: Session, session_id: UUID) -> Row[Any] | None:
    return s.execute(text(
        "select a.id, a.company_id, a.user_id, u.full_name as user_name, a.title, a.created_at, a.last_at "
        "from intel.ask_session a join kernel.app_user u on u.id = a.user_id where a.id = :i"),
        {"i": str(session_id)}).first()


def list_sessions(s: Session, *, user_id: UUID | None, company_id: UUID | None, limit: int,
                  offset: int) -> list[Row[Any]]:
    where = ["true"]
    params: dict[str, Any] = {"n": limit, "o": offset}
    if user_id:
        where.append("a.user_id = :u")
        params["u"] = str(user_id)
    if company_id:
        where.append("a.company_id = :c")
        params["c"] = str(company_id)
    return list(s.execute(text(
        "select a.id, a.company_id, a.user_id, u.full_name as user_name, a.title, a.created_at, a.last_at "
        f"from intel.ask_session a join kernel.app_user u on u.id = a.user_id where {' and '.join(where)} "
        "order by a.last_at desc, a.id limit :n offset :o"), params).all())


def touch_session(s: Session, session_id: UUID) -> None:
    s.execute(text("update intel.ask_session set last_at = now() where id = :i"), {"i": str(session_id)})


def add_message(s: Session, session_id: UUID, role: str, content: str, *, sources: list[dict[str, Any]] | None = None,
                tools_used: list[dict[str, Any]] | None = None, flagged: bool = False, flag_reason: str | None = None,
                input_tokens: int = 0, output_tokens: int = 0) -> UUID:
    row = s.execute(text(
        "insert into intel.ask_message (tenant_id, session_id, role, content, sources, tools_used, flagged, "
        "flag_reason, input_tokens, output_tokens) values (kernel.current_tenant(), :s, :r, :c, cast(:so as jsonb), "
        "cast(:t as jsonb), :f, :fr, :i, :o) returning id"),
        {"s": str(session_id), "r": role, "c": content, "so": _json(sources or []), "t": _json(tools_used or []),
         "f": flagged, "fr": flag_reason, "i": input_tokens, "o": output_tokens}).one()
    message_id: UUID = row.id
    return message_id


def messages_of(s: Session, session_id: UUID) -> list[Row[Any]]:
    return list(s.execute(text(
        "select id, created_at, role, content, sources, tools_used, flagged, flag_reason, input_tokens, output_tokens "
        "from intel.ask_message where session_id = :s order by created_at, (role = 'assistant'), id"),
        {"s": str(session_id)}).all())


# --------------------------------------------------------------------------- ranking and explanations
def get_ranking(s: Session, company_id: UUID) -> Row[Any] | None:
    return s.execute(text("select computed_at, model, items from intel.ai_ranking where company_id = :c"),
                     {"c": str(company_id)}).first()


def save_ranking(s: Session, company_id: UUID, model: str | None, items: list[dict[str, str]]) -> None:
    s.execute(text(
        "insert into intel.ai_ranking (tenant_id, company_id, model, items) values "
        "(kernel.current_tenant(), :c, :m, cast(:i as jsonb)) on conflict (tenant_id, company_id) do update set "
        "model = :m, items = cast(:i as jsonb), computed_at = now()"),
        {"c": str(company_id), "m": model, "i": _json(items)})


def set_ai_explanation(s: Session, finding_id: UUID, explanation: str) -> None:
    s.execute(text("update intel.finding set explanation_ai = :e, explanation_ai_at = now(), "
                   "explanation_ai_tried_at = now() where id = :i"), {"e": explanation, "i": str(finding_id)})


def mark_explanation_tried(s: Session, finding_id: UUID) -> None:
    s.execute(text("update intel.finding set explanation_ai_tried_at = now() where id = :i"), {"i": str(finding_id)})


def findings_to_explain(s: Session, company_id: UUID, limit: int, retry_hours: int) -> list[UUID]:
    """Open findings of medium severity or worse with no AI explanation, not tried in the last `retry_hours`."""
    rows = s.execute(text(
        "select id from intel.finding where company_id = :c and status in ('new', 'sent', 'acknowledged') "
        "and explanation_ai is null and severity in ('medium', 'high', 'critical') "
        "and (explanation_ai_tried_at is null or explanation_ai_tried_at < now() - make_interval(hours => :h)) "
        "order by array_position(array['critical','high','medium'], severity), amount desc nulls last, first_seen_at "
        "limit :n"), {"c": str(company_id), "h": retry_hours, "n": limit}).all()
    return [r.id for r in rows]


def top_for_ranking(s: Session, company_id: UUID, limit: int) -> list[Row[Any]]:
    return list(s.execute(text(
        "select f.id, f.severity, f.area, f.summary, f.recommended_action, f.amount, f.first_seen_at, f.evidence "
        "from intel.finding f where f.company_id = :c and f.status in ('new', 'sent', 'acknowledged') "
        "order by array_position(array['critical','high','medium','low','info'], f.severity), "
        "f.amount desc nulls last, f.first_seen_at limit :n"), {"c": str(company_id), "n": limit}).all())
