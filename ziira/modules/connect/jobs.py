"""Background work of the Connectors module: reading connected systems (never inside a request)."""

from typing import Any
from uuid import UUID

from ziira.modules.connect.repository import scan_repo
from ziira.modules.connect.services import move, scans, sync
from ziira.sdk import Session, enqueue, job, periodic


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


@job(move.ADVANCE_JOB)
def advance_move(session: Session, payload: dict[str, Any]) -> None:
    """Take a "Move to Ziira Core" a step on (stage the second group once the first is imported, then finish). While
    the move is still running it queues itself again, at once for the first few looks and every few seconds after."""
    move_id, attempt = UUID(str(payload["move_id"])), int(payload.get("attempt", 0)) + 1
    if move.advance(session, move_id):
        enqueue(session, move.ADVANCE_JOB, {"move_id": str(move_id), "attempt": attempt},
                delay_seconds=0 if attempt < 5 else 5, dedupe_key=f"{move.ADVANCE_JOB}:{move_id}:{attempt}")
