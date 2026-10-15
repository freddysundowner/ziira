"""Background work of the Connectors module: reading connected systems (never inside a request)."""

from typing import Any
from uuid import UUID

from ziira.modules.connect.repository import scan_repo
from ziira.modules.connect.services import scans, sync
from ziira.sdk import Session, job, periodic


@job(sync.JOB)
def run_sync(session: Session, payload: dict[str, Any]) -> None:
    """Read one connection (a 'sync now' click, or one that was due)."""
    sync.sync_connection(session, UUID(str(payload["connection_id"])), trigger=str(payload.get("trigger", "manual")),
                         full=bool(payload.get("full", False)))


@periodic("connect.sync", every_seconds=900)
def queue_due_syncs(session: Session) -> None:
    """Every 15 minutes: queue a read for each connection whose freshness window has passed."""
    sync.queue_due(session)


@job(scans.JOB)
def run_read_scan(session: Session, payload: dict[str, Any]) -> None:
    """Read a scanned statement or photo with the OCR engine (slow: never in a request)."""
    scans.read_scan(session, UUID(str(payload["scan_id"])))


@periodic("connect.purge_scans", every_seconds=3600)
def purge_scans(session: Session) -> None:
    """Delete pictures and unconfirmed lines older than a day."""
    scan_repo.purge_older_than_a_day(session)
