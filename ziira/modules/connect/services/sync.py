"""The sync engine: read a connected system through its connector and keep the canonical copy (`connect.src_*`) up to
date. Reads only: nothing here ever writes to the source system.

For a connection it walks the entities the connector supplies (branches first, so records can be mapped), asks the
connector for what is newer than the cursor of the last COMPLETE read, and stores each page in savepoints (a bad
record is skipped and counted). The cursor moves only after an entity was read to the end, so a failure in the middle
simply resumes from the last good cursor next time (re-reading is harmless: records are keyed by their reference).
Problems go to the exceptions inbox; retryable ones are tried again with a growing delay.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import ENTITIES, CanonicalBatch, Connector, ConnectorError
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.repository import store
from ziira.modules.connect.services import connections, connectors
from ziira.modules.connect.services.branches import BranchResolver
from ziira.sdk import (
    Event,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    enqueue,
    flag_for_review,
    publish,
    tenant_transaction,
)

log = logging.getLogger("ziira.connect")
RETRY_MINUTES, RETRY_CAP_MINUTES = 5, 360
FAILURES_BEFORE_ERROR = 3
JOB = "connect.sync"


@dataclass
class SyncResult:
    status: str                                   # ok | partial | failed | busy | skipped
    counts: dict[str, store.Counts] = field(default_factory=dict)
    error: str | None = None


def retry_delay(failures: int) -> timedelta:
    """How long to wait after the n-th failure in a row: 5 minutes, doubling, at most 6 hours."""
    return timedelta(minutes=min(RETRY_MINUTES * 2 ** max(failures - 1, 0), RETRY_CAP_MINUTES))


def sync_connection(session: Session, connection_id: UUID, *, trigger: str = "schedule",
                    entities: list[str] | None = None, full: bool = False) -> SyncResult:
    """Read one connection now. Connector failures never raise: they are recorded on the connection and the run."""
    row = repo.get_connection(session, connection_id, lock=True, skip_locked=True)
    if row is None:
        return SyncResult("busy" if repo.get_connection(session, connection_id) is not None else "skipped")
    if row.status in ("disconnected", "paused") and trigger == "schedule":
        return SyncResult("skipped")
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected")
    connector = connectors.connector_for(session, row.kind)
    if connectors.is_file_kind(connector):
        raise ValidationFailed("Files are read when they are uploaded, not on a schedule")
    wanted = [e for e in ENTITIES if e in connector.entities and (entities is None or e in entities)]
    if full:
        for entity in wanted:
            session.execute(text("delete from connect.cursor where connection_id = :c and entity = :e"),
                            {"c": str(connection_id), "e": entity})
    config = connections.public_config(row)
    secrets = connections.load_secrets(session, row)
    resolver = BranchResolver(session, connection_id, row.company_id, row.auto_create_branches)
    target = store.Target(connection_id, row.company_id, resolver.resolve)
    result = SyncResult("ok")
    if connector.needs_oauth and not secrets:
        return _fail(session, row, result, ConnectorError("This system has not been authorised yet", retryable=False))
    for entity in wanted:
        try:
            counts = _sync_entity(session, row, connector, config, secrets, entity, target, resolver, trigger)
        except ConnectorError as error:
            return _fail(session, row, result, error)
        except Exception as error:  # noqa: BLE001 - never let one system's surprise stop the others
            log.exception("Connector %s failed reading %s", row.kind, entity)
            return _fail(session, row, result, ConnectorError(
                f"Unexpected problem reading {entity} ({type(error).__name__})", retryable=True))
        result.counts[entity] = counts
        if counts.skipped:
            result.status = "partial"
    _succeed(session, row, result)
    return result


def save_rotated_secrets(session: Session, row: Any, connector: Connector, secrets: dict[str, Any]) -> None:
    """A vendor that rotates secrets on every refresh (QuickBooks) hands the new ones back in `updated_secrets`. Save
    them in their own transaction so they survive even if this read then fails, and use them for the next entity."""
    fresh = connector.updated_secrets
    if fresh is None:
        return
    connector.updated_secrets = None
    secrets.update(fresh)
    if row.credential_id is None:
        credential_id = connections.store_secrets(session, row, connector, fresh)
        repo.update_connection(session, row.id, {"credential_id": credential_id})
        return
    with tenant_transaction(current_context().tenant_id) as other:
        connections.store_secrets(other, row, connector, fresh)


def _sync_entity(session: Session, row: Any, connector: Connector, config: dict[str, Any], secrets: dict[str, Any],
                 entity: str, target: store.Target, resolver: BranchResolver, trigger: str) -> store.Counts:
    cursor_row = repo.get_cursor(session, row.id, entity)
    since = cursor_row.cursor if cursor_row is not None else None
    started = datetime.now(UTC)
    run_id = repo.start_run(session, row.id, entity, trigger)
    counts = store.Counts()
    last_cursor: str | None = None
    finished = True
    try:
        pages = connector.pull(config, secrets, entity, since, None)
        for batch in pages:
            if not isinstance(batch, CanonicalBatch) or batch.entity != entity:
                counts.note("The system returned a page of the wrong kind; it was ignored")
                continue
            if entity == "branches":
                for record in batch.records:
                    if hasattr(record, "ref") and hasattr(record, "name"):
                        resolver.note_name(str(record.ref).strip(), str(record.name))
            counts.add(store.store_records(session, target, entity, batch.records))
            if batch.cursor is not None:
                last_cursor = batch.cursor
            finished = batch.complete
    except ConnectorError as error:
        save_rotated_secrets(session, row, connector, secrets)
        for note in getattr(connector, "notes", []):
            counts.note(str(note))
        repo.finish_run(session, run_id, status="failed", read=counts.read, new=counts.new, changed=counts.changed,
                        skipped=counts.skipped, error=str(error)[:500], notes=counts.notes)
        raise
    except Exception as error:
        save_rotated_secrets(session, row, connector, secrets)
        repo.finish_run(session, run_id, status="failed", read=counts.read, new=counts.new, changed=counts.changed,
                        skipped=counts.skipped, error=f"Unexpected problem ({type(error).__name__})",
                            notes=counts.notes)
        raise
    save_rotated_secrets(session, row, connector, secrets)
    for note in getattr(connector, "notes", []):
        counts.note(str(note))
    if not finished:
        repo.finish_run(session, run_id, status="partial", read=counts.read, new=counts.new, changed=counts.changed,
                        skipped=counts.skipped, error="The system stopped before the end; it will carry on next time",
                        notes=counts.notes)
        raise ConnectorError("The system stopped before sending everything", retryable=True)
    repo.set_cursor(session, row.id, entity, last_cursor if last_cursor is not None else since, started)
    repo.finish_run(session, run_id, status="partial" if counts.skipped else "ok", read=counts.read, new=counts.new,
                    changed=counts.changed, skipped=counts.skipped, error=None, notes=counts.notes)
    return counts


def _succeed(session: Session, row: Any, result: SyncResult) -> None:
    now = datetime.now(UTC)
    repo.update_connection(session, row.id, {
        "last_sync_at": now, "last_success_at": now, "failures": 0, "last_error": None,
        "status": "active" if row.status == "error" else row.status,
        "next_sync_at": now + timedelta(minutes=row.sync_every_minutes)})
    skipped = sum(c.skipped for c in result.counts.values())
    if skipped:
        flag_for_review(session, unit="connect", kind="records_skipped", severity="low", company_id=row.company_id,
                        message=f"{row.name}: {skipped} record(s) could not be read and were skipped "
                                "(see the sync history for which)",
                        dedupe_key=f"connect-skipped:{row.id}:{now.date()}")
    publish(session, Event("connect.synced", "connect.connection", row.id, {
        "company_id": row.company_id, "kind": row.kind,
        "new": sum(c.new for c in result.counts.values()), "changed": sum(c.changed for c in result.counts.values())}))


def _fail(session: Session, row: Any, result: SyncResult, error: ConnectorError) -> SyncResult:
    now = datetime.now(UTC)
    failures = row.failures + 1
    message = str(error)[:500]
    status = row.status
    if not error.retryable or failures >= FAILURES_BEFORE_ERROR:
        status = "error"
    repo.update_connection(session, row.id, {
        "last_sync_at": now, "failures": failures, "last_error": message, "status": status,
        "next_sync_at": now + retry_delay(failures) if error.retryable else None})
    flag_for_review(session, unit="connect", kind="sync_failed", severity="medium" if error.retryable else "high",
                    company_id=row.company_id, message=f"{row.name}: {message}",
                    dedupe_key=f"connect-sync:{row.id}:{now.date()}")
    audit_record(session, "sync_failed", "connect.connection", row.id, {"retryable": error.retryable})
    result.status, result.error = "failed", message
    return result


# --------------------------------------------------------------------------- background work
def queue_sync(session: Session, connection_id: UUID, *, full: bool = False, trigger: str = "manual") -> bool:
    """Ask the worker to read a connection. Returns False when one is already waiting (so a double click is one run)."""
    waiting = session.execute(text(
        "select 1 from kernel.job where job_type = :t and status = 'queued' and payload->>'connection_id' = :c"),
        {"t": JOB, "c": str(connection_id)}).first()
    if waiting is not None:
        return False
    enqueue(session, JOB, {"connection_id": str(connection_id), "full": full, "trigger": trigger}, max_attempts=3)
    return True


def queue_due(session: Session) -> int:
    """Queue a read of every connection whose freshness window has passed (the recurring task)."""
    queued = 0
    for connection_id in repo.due_connections(session):
        if queue_sync(session, connection_id, trigger="schedule"):
            queued += 1
    return queued
