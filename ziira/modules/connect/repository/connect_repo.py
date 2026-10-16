"""Database access for connections, sync runs, cursors and the branch map. SQL only; rules live in services/."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session

CONNECTION_COLUMNS = ("id, company_id, kind, name, status, config, credential_id, auto_create_branches, "
                      "sync_every_minutes, last_sync_at, last_success_at, next_sync_at, failures, last_error, "
                      "disconnected_at, created_at, created_by, overlap_choice")
ENTITY_TABLES = {
    "branches": "src_branch", "parties": "src_party", "products": "src_product", "users": "src_user",
    "sales": "src_sale", "payments": "src_payment", "stock_movements": "src_stock_movement",
    "invoices": "src_invoice", "expenses": "src_expense", "journal_entries": "src_journal_entry",
}


# --------------------------------------------------------------------------- connections
def add_connection(session: Session, *, company_id: UUID, kind: str, name: str, config: dict[str, Any],
                   credential_id: UUID | None, auto_create_branches: bool, sync_every_minutes: int,
                   created_by: UUID | None) -> UUID:
    row = session.execute(text(
        "insert into connect.connection (tenant_id, company_id, kind, name, config, credential_id, "
        "auto_create_branches, sync_every_minutes, created_by, next_sync_at) values (kernel.current_tenant(), :c, "
        ":k, :n, cast(:g as jsonb), :cr, :a, :s, :u, now()) returning id"),
        {"c": str(company_id), "k": kind, "n": name, "g": json.dumps(config),
         "cr": str(credential_id) if credential_id else None, "a": auto_create_branches, "s": sync_every_minutes,
         "u": str(created_by) if created_by else None}).one()
    connection_id: UUID = row.id
    return connection_id


def get_connection(session: Session, connection_id: UUID, *, lock: bool = False,
    skip_locked: bool = False) -> Row[Any] | None:
    suffix = " for update skip locked" if lock and skip_locked else " for update" if lock else ""
    return session.execute(text(f"select {CONNECTION_COLUMNS} from connect.connection where id = :i{suffix}"),
                           {"i": str(connection_id)}).first()


def list_connections(session: Session, company_ids: set[UUID] | None) -> list[Row[Any]]:
    scope = "" if company_ids is None else " where company_id = any(:cs)"
    return list(session.execute(text(f"select {CONNECTION_COLUMNS} from connect.connection{scope} order by created_at"),
                                {"cs": [str(c) for c in company_ids or ()]}))


def find_by_name(session: Session, name: str) -> Row[Any] | None:
    return session.execute(text(f"select {CONNECTION_COLUMNS} from connect.connection where lower(name) = lower(:n) "
                                "and status <> 'disconnected'"), {"n": name}).first()


def due_connections(session: Session) -> list[UUID]:
    """Connections whose freshness window has passed (API kinds only; files are read when uploaded)."""
    return [r.id for r in session.execute(text(
        "select id from connect.connection where status in ('active', 'error') and next_sync_at is not null "
        "and next_sync_at <= now() order by next_sync_at"))]


def update_connection(session: Session, connection_id: UUID, changes: dict[str, Any]) -> None:
    """Set the named columns (names come from our own code, never from a request)."""
    if not changes:
        return
    sets = ", ".join(f"{name} = " + (f"cast(:{name} as jsonb)" if name == "config" else f":{name}")
                     for name in changes)
    values = {name: json.dumps(value) if name == "config" else (str(value) if isinstance(value, UUID) else value)
              for name, value in changes.items()}
    session.execute(text(f"update connect.connection set {sets}, updated_at = now() where id = :i"),
                    {**values, "i": str(connection_id)})


# --------------------------------------------------------------------------- runs and cursors
def start_run(session: Session, connection_id: UUID, entity: str, trigger: str) -> UUID:
    row = session.execute(text(
        "insert into connect.sync_run (tenant_id, connection_id, entity, trigger) values "
        "(kernel.current_tenant(), :c, :e, :t) returning id"),
        {"c": str(connection_id), "e": entity, "t": trigger}).one()
    run_id: UUID = row.id
    return run_id


def finish_run(session: Session, run_id: UUID, *, status: str, read: int, new: int, changed: int, skipped: int,
               error: str | None, notes: list[str]) -> None:
    session.execute(text(
        "update connect.sync_run set finished_at = now(), status = :s, records_read = :r, records_new = :n, "
        "records_changed = :c, records_skipped = :k, error = :e, notes = cast(:o as jsonb) where id = :i"),
        {"s": status, "r": read, "n": new, "c": changed, "k": skipped, "e": error, "o": json.dumps(notes[:20]),
         "i": str(run_id)})


def list_runs(session: Session, connection_id: UUID, limit: int, offset: int) -> list[Row[Any]]:
    return list(session.execute(text(
        "select id, entity, trigger, started_at, finished_at, status, records_read, records_new, records_changed, "
        "records_skipped, error, notes from connect.sync_run where connection_id = :c "
        "order by started_at desc, id limit :l offset :o"), {"c": str(connection_id), "l": limit, "o": offset}))


def get_cursor(session: Session, connection_id: UUID, entity: str) -> Row[Any] | None:
    return session.execute(text("select cursor, data_through, updated_at from connect.cursor "
                                "where connection_id = :c and entity = :e"),
                           {"c": str(connection_id), "e": entity}).first()


def set_cursor(session: Session, connection_id: UUID, entity: str, cursor: str | None,
               data_through: datetime | None) -> None:
    session.execute(text(
        "insert into connect.cursor (tenant_id, connection_id, entity, cursor, data_through) values "
        "(kernel.current_tenant(), :c, :e, :r, :d) on conflict (connection_id, entity) do update set "
        "cursor = excluded.cursor, data_through = greatest(excluded.data_through, connect.cursor.data_through), "
        "updated_at = now()"),
        {"c": str(connection_id), "e": entity, "r": cursor, "d": data_through})


def clear_cursors(session: Session, connection_id: UUID) -> None:
    session.execute(text("delete from connect.cursor where connection_id = :c"), {"c": str(connection_id)})


def cursors(session: Session, connection_id: UUID) -> dict[str, Row[Any]]:
    return {r.entity: r for r in session.execute(text(
        "select entity, cursor, data_through, updated_at from connect.cursor where connection_id = :c"),
        {"c": str(connection_id)})}


# --------------------------------------------------------------------------- branch map
def list_branch_map(session: Session, connection_id: UUID) -> list[Row[Any]]:
    return list(session.execute(text(
        "select m.external_ref, m.external_name, m.branch_id, m.ignored, b.name as branch_name from "
        "connect.branch_map m "
        "left join kernel.branch b on b.id = m.branch_id where m.connection_id = :c order by m.external_name, "
        "m.external_ref"), {"c": str(connection_id)}))


def get_branch_map(session: Session, connection_id: UUID) -> dict[str, tuple[UUID | None, bool]]:
    return {r.external_ref: (r.branch_id, r.ignored) for r in session.execute(text(
        "select external_ref, branch_id, ignored from connect.branch_map where connection_id = :c"),
        {"c": str(connection_id)})}


def add_branch_map(session: Session, connection_id: UUID, ref: str, name: str | None, branch_id: UUID | None) -> None:
    session.execute(text(
        "insert into connect.branch_map (tenant_id, connection_id, external_ref, external_name, branch_id) values "
        "(kernel.current_tenant(), :c, :r, :n, :b) on conflict (connection_id, external_ref) do update set "
        "external_name = coalesce(excluded.external_name, connect.branch_map.external_name)"),
        {"c": str(connection_id), "r": ref, "n": name, "b": str(branch_id) if branch_id else None})


def set_branch_map(session: Session, connection_id: UUID, ref: str, branch_id: UUID | None, ignored: bool) -> int:
    row = session.execute(text(
        "update connect.branch_map set branch_id = :b, ignored = :i, updated_at = now() "
        "where connection_id = :c and external_ref = :r"),
        {"b": str(branch_id) if branch_id else None, "i": ignored, "c": str(connection_id), "r": ref})
    return int(row.rowcount)  # type: ignore[attr-defined]


def apply_branch_to_records(session: Session, connection_id: UUID, ref: str, branch_id: UUID | None) -> None:
    """After the mapping changed, point the records of that source branch at the new Ziira branch."""
    for table in ("src_sale", "src_payment", "src_stock_movement", "src_invoice", "src_expense"):
        session.execute(text(f"update connect.{table} set branch_id = :b where connection_id = :c and branch_ref = :r"),
                        {"b": str(branch_id) if branch_id else None, "c": str(connection_id), "r": ref})


# --------------------------------------------------------------------------- counts and deletion
def entity_counts(session: Session, connection_id: UUID) -> dict[str, int]:
    out: dict[str, int] = {}
    for entity, table in ENTITY_TABLES.items():
        out[entity] = int(session.execute(text(f"select count(*) from connect.{table} where connection_id = :c"),
                                          {"c": str(connection_id)}).scalar_one())
    return out


def delete_source_data(session: Session, connection_id: UUID) -> dict[str, int]:
    """Remove everything read from the source (children go with their parents). Returns rows removed per entity."""
    removed: dict[str, int] = {}
    for entity, table in ENTITY_TABLES.items():
        result = session.execute(text(f"delete from connect.{table} where connection_id = :c"),
            {"c": str(connection_id)})
        removed[entity] = int(result.rowcount)  # type: ignore[attr-defined]
    session.execute(text("delete from connect.cursor where connection_id = :c"), {"c": str(connection_id)})
    return removed
