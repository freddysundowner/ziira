"""Database access for the command schema."""

import json
from datetime import date, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session


def replace_figures(s: Session, company_id: UUID, day: date, metrics: set[str], rows: list[dict[str, Any]]) -> None:
    """Store the figures a source produced for the day, replacing what it stored before."""
    if metrics:
        s.execute(text("delete from command.pulse_figure where company_id = :c and day = :d and metric = any(:m)"),
                  {"c": str(company_id), "d": day, "m": list(metrics)})
    for r in rows:
        s.execute(text(
            "insert into command.pulse_figure (tenant_id, company_id, branch_id, day, metric, label, kind, value, "
            "higher_is_better) values (kernel.current_tenant(), :c, :b, :d, :m, :l, :k, :v, :h) "
            "on conflict (tenant_id, company_id, coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid), "
            "day, metric) do update set label = :l, kind = :k, value = :v, higher_is_better = :h, computed_at = now()"),
            {"c": str(company_id), "b": str(r["branch_id"]) if r["branch_id"] else None, "d": day, "m": r["metric"],
             "l": r["label"][:100], "k": r["kind"], "v": r["value"], "h": r["higher_is_better"]})


def figures_between(s: Session, company_id: UUID, date_from: date, date_to: date) -> list[Row[Any]]:
    return list(s.execute(text(
        "select p.branch_id, b.name as branch_name, p.day, p.metric, p.label, p.kind, p.value, p.higher_is_better, "
        "p.computed_at from command.pulse_figure p left join kernel.branch b on b.id = p.branch_id "
        "where p.company_id = :c and p.day between :f and :t order by p.metric, b.name nulls first, p.day"),
        {"c": str(company_id), "f": date_from, "t": date_to}).all())


def latest_computed(s: Session, company_id: UUID, day: date) -> Any:
    return s.execute(text("select max(computed_at) from command.pulse_figure where company_id = :c and day = :d"),
                     {"c": str(company_id), "d": day}).scalar()


# --------------------------------------------------------------------------- schedules
def get_schedule(s: Session, user_id: UUID, kind: str) -> Row[Any] | None:
    return s.execute(text(
        "select id, user_id, kind, channel, send_time, weekday, is_active from command.brief_schedule "
        "where user_id = :u and kind = :k"), {"u": str(user_id), "k": kind}).first()


def list_schedules(s: Session, user_id: UUID | None) -> list[Row[Any]]:
    return list(s.execute(text(
        "select sc.id, sc.user_id, u.full_name as user_name, sc.kind, sc.channel, sc.send_time, sc.weekday, "
        "sc.is_active from command.brief_schedule sc join kernel.app_user u on u.id = sc.user_id "
        "where (cast(:u as uuid) is null or sc.user_id = :u) order by u.full_name, sc.kind"),
        {"u": str(user_id) if user_id else None}).all())


def save_schedule(s: Session, user_id: UUID, kind: str, channel: str, send_time: time, weekday: int | None,
                  is_active: bool) -> Row[Any]:
    return s.execute(text(
        "insert into command.brief_schedule (tenant_id, user_id, kind, channel, send_time, weekday, is_active) "
        "values (kernel.current_tenant(), :u, :k, :c, :t, :w, :a) on conflict (user_id, kind) do update set "
        "channel = :c, send_time = :t, weekday = :w, is_active = :a, updated_at = now() "
        "returning id, user_id, kind, channel, send_time, weekday, is_active"),
        {"u": str(user_id), "k": kind, "c": channel, "t": send_time, "w": weekday, "a": is_active}).one()


def delete_schedule(s: Session, user_id: UUID, kind: str) -> None:
    s.execute(text("delete from command.brief_schedule where user_id = :u and kind = :k"),
              {"u": str(user_id), "k": kind})


def active_schedules(s: Session) -> list[Row[Any]]:
    return list(s.execute(text(
        "select id, user_id, kind, channel, send_time, weekday from command.brief_schedule where is_active")).all())


# --------------------------------------------------------------------------- briefs
def brief_exists(s: Session, user_id: UUID, company_id: UUID, kind: str, day: date) -> bool:
    return s.execute(text(
        "select 1 from command.brief where user_id = :u and company_id = :c and kind = :k and brief_date = :d"),
        {"u": str(user_id), "c": str(company_id), "k": kind, "d": day}).first() is not None


def save_brief(s: Session, user_id: UUID, company_id: UUID, kind: str, day: date, subject: str, body: str,
               data: dict[str, Any], delivered_via: str) -> UUID | None:
    row = s.execute(text(
        "insert into command.brief (tenant_id, user_id, company_id, kind, brief_date, subject, body, data, "
        "delivered_via) values (kernel.current_tenant(), :u, :c, :k, :d, :s, :b, cast(:data as jsonb), :v) "
        "on conflict (user_id, company_id, kind, brief_date) do nothing returning id"),
        {"u": str(user_id), "c": str(company_id), "k": kind, "d": day, "s": subject, "b": body,
         "data": json.dumps(data, default=str), "v": delivered_via}).first()
    return row.id if row else None


def list_briefs(s: Session, user_id: UUID, limit: int, offset: int) -> list[Row[Any]]:
    return list(s.execute(text(
        "select id, company_id, kind, brief_date, subject, delivered_via, read_at, created_at from command.brief "
        "where user_id = :u order by created_at desc limit :l offset :o"),
        {"u": str(user_id), "l": limit, "o": offset}).all())


def get_brief(s: Session, user_id: UUID, brief_id: UUID) -> Row[Any] | None:
    return s.execute(text(
        "select id, company_id, kind, brief_date, subject, body, delivered_via, read_at, created_at, data "
        "from command.brief where id = :i and user_id = :u"), {"i": str(brief_id), "u": str(user_id)}).first()


def mark_read(s: Session, brief_id: UUID) -> None:
    s.execute(text("update command.brief set read_at = coalesce(read_at, now()) where id = :i"), {"i": str(brief_id)})


# --------------------------------------------------------------------------- dashboard
def widgets(s: Session, user_id: UUID) -> list[Row[Any]]:
    return list(s.execute(text(
        "select id, widget_code, position, settings from command.dashboard_widget where user_id = :u "
        "order by position"),
        {"u": str(user_id)}).all())


def replace_widgets(s: Session, user_id: UUID, items: list[tuple[str, dict[str, Any]]]) -> None:
    s.execute(text("delete from command.dashboard_widget where user_id = :u"), {"u": str(user_id)})
    for position, (code, settings) in enumerate(items):
        s.execute(text(
            "insert into command.dashboard_widget (tenant_id, user_id, widget_code, position, settings) "
            "values (kernel.current_tenant(), :u, :c, :p, cast(:s as jsonb))"),
            {"u": str(user_id), "c": code, "p": position, "s": json.dumps(settings)})


def company_names(s: Session, company_ids: list[UUID]) -> dict[UUID, str]:
    rows = s.execute(text("select id, name from kernel.company where id = any(:i)"),
                     {"i": [str(c) for c in company_ids]}).all()
    return {r.id: r.name for r in rows}


def decimal_or_none(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value)
