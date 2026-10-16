"""Database access for the imports schema (staged batches and rows). SQL only; rules live in services/."""

import json
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session

BATCH_COLUMNS = ("id, company_id, kind, filename, status, delimiter, headers, mapping, options, warnings, created_at, "
                 "created_by, committed_by, committed_at, finished_at, file_check, reverted_at, reverted_by, "
                 "revert_reason, source_kind, source_id")
ROW_COLUMNS = "id, batch_id, row_no, raw, parsed, status, errors, record_id"
STATUSES = ("pending", "valid", "invalid", "imported", "skipped", "failed", "reverted")


def add_batch(session: Session, *, company_id: UUID, kind: str, filename: str, delimiter: str, headers: list[str],
              mapping: dict[str, str | None], options: dict[str, str], warnings: list[str],
              created_by: UUID | None, source_kind: str | None = None, source_id: UUID | None = None) -> UUID:
    row = session.execute(text(
        "insert into imports.batch (tenant_id, company_id, kind, filename, delimiter, headers, mapping, options, "
        "warnings, created_by, source_kind, source_id) values (kernel.current_tenant(), :c, :k, :f, :d, "
        "cast(:h as jsonb), cast(:m as jsonb), cast(:o as jsonb), cast(:w as jsonb), :u, :sk, :si) returning id"),
        {"c": str(company_id), "k": kind, "f": filename, "d": delimiter, "h": json.dumps(headers),
         "m": json.dumps(mapping), "o": json.dumps(options), "w": json.dumps(warnings),
         "u": str(created_by) if created_by else None, "sk": source_kind,
         "si": str(source_id) if source_id else None}).one()
    batch_id: UUID = row.id
    return batch_id


def add_rows(session: Session, batch_id: UUID, rows: Sequence[tuple[int, list[str]]]) -> None:
    for start in range(0, len(rows), 1000):
        session.execute(text(
            "insert into imports.batch_row (tenant_id, batch_id, row_no, raw) "
            "values (kernel.current_tenant(), :b, :n, cast(:r as jsonb))"),
            [{"b": str(batch_id), "n": number, "r": json.dumps(cells)} for number, cells in rows[start:start + 1000]])


def get_batch(session: Session, batch_id: UUID, *, lock: bool = False) -> Row[Any] | None:
    return session.execute(text(f"select {BATCH_COLUMNS} from imports.batch where id = :i"
                                + (" for update" if lock else "")), {"i": str(batch_id)}).first()


def list_batches(session: Session, company_ids: set[UUID] | None, limit: int, offset: int) -> list[Row[Any]]:
    where = "true"
    params: dict[str, Any] = {"l": limit, "o": offset}
    if company_ids is not None:
        where, params["c"] = "company_id = any(:c)", [str(c) for c in company_ids]
    return list(session.execute(text(
        f"select {BATCH_COLUMNS} from imports.batch where {where} order by created_at desc, id limit :l offset :o"),
        params))


def update_batch(session: Session, batch_id: UUID, **fields: Any) -> None:
    """Set columns of a batch. Values for jsonb columns (mapping, options) are given as Python objects."""
    json_columns = {"mapping", "options", "warnings", "file_check"}
    sets = [f"{name} = cast(:{name} as jsonb)" if name in json_columns else f"{name} = :{name}" for name in fields]
    params = {n: (json.dumps(v) if n in json_columns else v) for n, v in fields.items()}
    session.execute(text(f"update imports.batch set {', '.join(sets)}, updated_at = now() where id = :id"),
                    {**params, "id": str(batch_id)})


def delete_batch(session: Session, batch_id: UUID) -> None:
    session.execute(text("delete from imports.batch where id = :i"), {"i": str(batch_id)})


def counts(session: Session, batch_id: UUID) -> dict[str, int]:
    found = {r.status: r.n for r in session.execute(text(
        "select status, count(*) as n from imports.batch_row where batch_id = :b group by status"),
        {"b": str(batch_id)})}
    return {status: int(found.get(status, 0)) for status in STATUSES}


def list_rows(session: Session, batch_id: UUID, *, statuses: Sequence[str] | None, limit: int,
              offset: int) -> list[Row[Any]]:
    where = "batch_id = :b" + (" and status = any(:s)" if statuses else "")
    params: dict[str, Any] = {"b": str(batch_id), "l": limit, "o": offset}
    if statuses:
        params["s"] = list(statuses)
    return list(session.execute(text(
        f"select {ROW_COLUMNS} from imports.batch_row where {where} order by row_no limit :l offset :o"), params))


def count_rows(session: Session, batch_id: UUID, statuses: Sequence[str] | None) -> int:
    where = "batch_id = :b" + (" and status = any(:s)" if statuses else "")
    params: dict[str, Any] = {"b": str(batch_id)}
    if statuses:
        params["s"] = list(statuses)
    return int(session.execute(text(f"select count(*) from imports.batch_row where {where}"), params).scalar_one())


def iter_rows(session: Session, batch_id: UUID, statuses: Sequence[str] | None = None,
              chunk: int = 500) -> Iterator[list[Row[Any]]]:
    """The rows in file order, a chunk at a time (so a big file is never held twice)."""
    last = 0
    while True:
        where = "batch_id = :b and row_no > :last" + (" and status = any(:s)" if statuses else "")
        params: dict[str, Any] = {"b": str(batch_id), "last": last, "l": chunk}
        if statuses:
            params["s"] = list(statuses)
        rows = list(session.execute(text(
            f"select {ROW_COLUMNS} from imports.batch_row where {where} order by row_no limit :l"), params))
        if not rows:
            return
        yield rows
        last = rows[-1].row_no


def next_valid_rows(session: Session, batch_id: UUID, limit: int) -> list[Row[Any]]:
    return list(session.execute(text(
        f"select {ROW_COLUMNS} from imports.batch_row where batch_id = :b and status = 'valid' "
        "order by row_no limit :l for update"), {"b": str(batch_id), "l": limit}))


def set_row_results(session: Session, results: Sequence[dict[str, Any]]) -> None:
    """Save validation results: each has id, status, parsed (dict) and errors (list)."""
    if not results:
        return
    session.execute(text(
        "update imports.batch_row set status = :status, parsed = cast(:parsed as jsonb), "
        "errors = cast(:errors as jsonb), updated_at = now() where id = :id"),
        [{"id": str(r["id"]), "status": r["status"], "parsed": json.dumps(r["parsed"]),
          "errors": json.dumps(r["errors"])} for r in results])


def set_row_outcome(session: Session, row_id: UUID, status: str, errors: list[str],
                    record_id: UUID | None = None) -> None:
    session.execute(text(
        "update imports.batch_row set status = :s, errors = cast(:e as jsonb), record_id = :r, updated_at = now() "
        "where id = :i"), {"s": status, "e": json.dumps(errors), "r": str(record_id) if record_id else None,
                           "i": str(row_id)})


def mark_reverted(session: Session, batch_id: UUID) -> None:
    session.execute(text(
        "update imports.batch_row set status = 'reverted', updated_at = now() "
        "where batch_id = :b and status = 'imported'"), {"b": str(batch_id)})


def reset_rows(session: Session, batch_id: UUID) -> None:
    session.execute(text(
        "update imports.batch_row set status = 'pending', parsed = '{}', errors = '[]', updated_at = now() "
        "where batch_id = :b"), {"b": str(batch_id)})
