"""Database access for pictures waiting to be read and their lines waiting for confirmation. SQL only."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session

COLUMNS = "id, connection_id, created_at, filename, kind, status, pages, pages_done, error, rows, warnings"


def add_scan(session: Session, connection_id: UUID, *, filename: str, kind: str, pages: int, data: bytes,
             created_by: UUID | None) -> UUID:
    row = session.execute(text(
        "insert into connect.scan (tenant_id, connection_id, filename, kind, pages, data, created_by) values "
        "(kernel.current_tenant(), :c, :f, :k, :p, :d, :u) returning id"),
        {"c": str(connection_id), "f": filename[:300], "k": kind, "p": pages, "d": data,
         "u": str(created_by) if created_by else None}).one()
    scan_id: UUID = row.id
    return scan_id


def get_scan(session: Session, scan_id: UUID, connection_id: UUID, *, with_data: bool = False) -> Row[Any] | None:
    extra = ", data" if with_data else ""
    return session.execute(text(f"select {COLUMNS}{extra} from connect.scan where id = :i and connection_id = :c"),
                           {"i": str(scan_id), "c": str(connection_id)}).first()


def get_scan_by_id(session: Session, scan_id: UUID) -> Row[Any] | None:
    return session.execute(text(f"select {COLUMNS}, data from connect.scan where id = :i"),
                           {"i": str(scan_id)}).first()


def set_status(session: Session, scan_id: UUID, status: str, *, pages_done: int | None = None,
               error: str | None = None) -> None:
    session.execute(text("update connect.scan set status = :s, pages_done = coalesce(:p, pages_done), "
                         "error = :e where id = :i"), {"s": status, "p": pages_done, "e": error, "i": str(scan_id)})


def set_rows(session: Session, scan_id: UUID, rows: list[dict[str, Any]], warnings: list[str]) -> None:
    """Keep the lines read, drop the file itself."""
    session.execute(text("update connect.scan set rows = cast(:r as jsonb), warnings = cast(:w as jsonb), "
                         "data = null, status = 'ready', pages_done = pages, error = null where id = :i"),
                    {"r": json.dumps(rows), "w": json.dumps(warnings), "i": str(scan_id)})


def delete_scan(session: Session, scan_id: UUID) -> None:
    session.execute(text("delete from connect.scan where id = :i"), {"i": str(scan_id)})


def purge_older_than_a_day(session: Session) -> int:
    removed = session.execute(text("delete from connect.scan where created_at < now() - interval '1 day' "
                                   "returning id")).all()
    return len(removed)
