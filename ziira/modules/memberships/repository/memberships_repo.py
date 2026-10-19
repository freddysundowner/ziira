"""Queries for the `memberships` schema (plain SQL; this schema only). Rows come back as dictionaries."""

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session

Row = dict[str, Any]
JSON_COLUMNS = {"covered_services", "lines", "access_rules", "branch_ids", "tags", "reasons"}
SETTING_DEFAULTS: Row = {
    "allow_overdraw": False, "catch_up_max_periods": 3, "prorate_first_period": False, "reminders_enabled": True,
    "renewal_reminder_days": 7, "expiry_reminder_days": 14, "quiet_start": 21, "quiet_end": 7,
    "message_language": "en", "grace_days": 7, "dunning_days": "1,7,14", "auto_freeze_days": 0, "inactive_weeks": 0,
    "birthday_messages": False, "waiver_required": False, "repeat_window_minutes": 10, "expiry_warning_days": 7,
    "late_cancel_hours": 0, "late_cancel_consumes": True, "no_show_consumes": True, "points_per_unit": 0,
    "point_value": 0, "referral_reward": 0, "auto_apply_credit": True, "voucher_product_id": None, "offline_valid_hours": 24}  # noqa: E501


def _value(column: str, value: Any) -> Any:
    if column in JSON_COLUMNS:
        return json.dumps(value, default=str)
    return str(value) if isinstance(value, UUID) else value


def _placeholder(column: str) -> str:
    return f"cast(:{column} as jsonb)" if column in JSON_COLUMNS else f":{column}"


def one(session: Session, sql: str, **params: Any) -> Row | None:
    found = session.execute(text(sql), {k: _plain(v) for k, v in params.items()}).mappings().first()
    return dict(found) if found is not None else None


def many(session: Session, sql: str, **params: Any) -> list[Row]:
    return [dict(r) for r in session.execute(text(sql), {k: _plain(v) for k, v in params.items()}).mappings()]


def run(session: Session, sql: str, **params: Any) -> int:
    """Run a statement that returns nothing; the number of rows it changed."""
    result = session.execute(text(sql), {k: _plain(v) for k, v in params.items()})
    return int(getattr(result, "rowcount", 0) or 0)


def scalar(session: Session, sql: str, **params: Any) -> Any:
    return session.execute(text(sql), {k: _plain(v) for k, v in params.items()}).scalar_one()


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, UUID) else value


def insert(session: Session, table: str, values: Row) -> Row:
    """Add a row and return it."""
    columns = list(values)
    marks = ", ".join(_placeholder(c) for c in columns)
    found = session.execute(text(
        f"insert into memberships.{table} ({', '.join(columns)}) values ({marks}) returning *"),
        {c: _value(c, values[c]) for c in columns}).mappings().one()
    return dict(found)


def update(session: Session, table: str, row_id: UUID, values: Row) -> Row:
    """Change some columns of a row (and stamp it) and return it."""
    if not values:
        return get(session, table, row_id) or {}
    sets = ", ".join(f"{c} = {_placeholder(c)}" for c in values)
    found = session.execute(text(
        f"update memberships.{table} set {sets}, updated_at = now() where id = :row_id returning *"),
        {**{c: _value(c, v) for c, v in values.items()}, "row_id": str(row_id)}).mappings().one()
    return dict(found)


def get(session: Session, table: str, row_id: UUID, *, lock: bool = False) -> Row | None:
    return one(session, f"select * from memberships.{table} where id = :i{' for update' if lock else ''}", i=row_id)


# --------------------------------------------------------------------------- settings
def get_settings(session: Session, company_id: UUID) -> Row:
    found = one(session, "select * from memberships.setting where company_id = :c", c=company_id)
    return found if found is not None else {**SETTING_DEFAULTS, "company_id": company_id}


def save_settings(session: Session, tenant_id: UUID, company_id: UUID, values: Row, user_id: UUID | None) -> Row:
    current = one(session, "select id from memberships.setting where company_id = :c", c=company_id)
    if current is None:
        return insert(session, "setting", {"tenant_id": tenant_id, "created_by": user_id, "company_id": company_id,
                                           **values})
    return update(session, "setting", current["id"], {**values, "updated_by": user_id})


# --------------------------------------------------------------------------- scope
def scope_sql(scopes: list[tuple[UUID | None, UUID | None]] | None, alias: str = "") -> tuple[str, Row]:
    """A condition keeping the rows of the (company, branch) pairs a person may see; None: everything."""
    if scopes is None:
        return "true", {}
    prefix = f"{alias}." if alias else ""
    parts: list[str] = []
    params: Row = {}
    for n, (company, branch) in enumerate(scopes):
        piece = []
        if company is not None:
            piece.append(f"{prefix}company_id = :sc{n}")
            params[f"sc{n}"] = str(company)
        if branch is not None:
            piece.append(f"{prefix}branch_id = :sb{n}")
            params[f"sb{n}"] = str(branch)
        parts.append("(" + (" and ".join(piece) or "true") + ")")
    return ("(" + " or ".join(parts) + ")") if parts else "false", params


# --------------------------------------------------------------------------- credits
def holder_balance(session: Session, holder_id: UUID) -> Decimal:
    return Decimal(scalar(session, "select coalesce(sum(quantity), 0) from memberships.credit_entry "
                                   "where holder_id = :h", h=holder_id))


def balances(session: Session, holder_ids: list[UUID]) -> dict[UUID, Decimal]:
    found: dict[UUID, Decimal] = {h: Decimal(0) for h in holder_ids}
    if holder_ids:
        for r in many(session, "select holder_id, sum(quantity) as balance from memberships.credit_entry "
                               "where holder_id = any(cast(:ids as uuid[])) group by holder_id",
                      ids=[str(h) for h in holder_ids]):
            found[r["holder_id"]] = Decimal(r["balance"])
    return found


def add_entry(session: Session, tenant_id: UUID, user_id: UUID | None, values: Row) -> Row:
    return insert(session, "credit_entry", {"tenant_id": tenant_id, "created_by": user_id, **values})


def used_entries(session: Session, source_type: str, source_id: UUID) -> list[Row]:
    """The 'use' entries made for a source, with whether each was already reversed."""
    return many(session, "select e.*, exists(select 1 from memberships.credit_entry r where r.reverses_id = e.id) "
                         "as reversed from memberships.credit_entry e where e.entry_type = 'use' "
                         "and e.source_type = :t and e.source_id = :s order by e.seq",
                t=source_type, s=source_id)


def history(session: Session, member_id: UUID, *, tenant_id: UUID, user_id: UUID | None, action: str,
            from_status: str | None, to_status: str | None, note: str | None, day: date) -> None:
    insert(session, "member_history", {"tenant_id": tenant_id, "created_by": user_id, "member_id": member_id,
                                       "action": action, "from_status": from_status, "to_status": to_status,
                                       "note": note, "happened_on": day})
