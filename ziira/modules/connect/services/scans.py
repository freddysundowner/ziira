"""Pictures of statements (a scanned PDF, a photo): reading them is slow, so it happens in a background job.

The upload stores the file in `connect.scan` and queues the job; the web page polls the scan's progress. When the
job is done only the lines it read are kept (the file is cleared); the person checks them, may correct a cell, and
confirms. A day later anything left over is deleted.
"""

import logging
from typing import Any
from uuid import UUID

from ziira.modules.connect.domain.csvfile import FileProblem
from ziira.modules.connect.domain.tabular import RawRow, RawTable
from ziira.modules.connect.ocr import pages as ocr_pages
from ziira.modules.connect.public import OCR_ENGINE, ConnectorError, OcrEngine
from ziira.modules.connect.repository import scan_repo
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    current_context,
    enqueue,
    implementations,
    platform_settings,
    tenant_transaction,
)

JOB = "connect.read_scan"
log = logging.getLogger("ziira.connect")


def engine(session: Session) -> OcrEngine | None:
    """The first plugged-in engine that can read now."""
    for candidate in implementations(session, OCR_ENGINE):
        if candidate.unavailable() is None:
            found: OcrEngine = candidate
            return found
    return None


def why_unavailable(session: Session) -> str | None:
    """None when pictures can be read on this server; else the reason in plain words."""
    engines = implementations(session, OCR_ENGINE)
    if not engines:
        return "Reading pictures is not switched on on this server yet."
    reasons = [r for e in engines if (r := e.unavailable())]
    return None if len(reasons) < len(engines) else reasons[0]


def start(session: Session, connection_id: UUID, *, data: bytes, filename: str, kind: str, pages: int) -> UUID:
    """Store the picture and queue the reading. The caller has checked the connection."""
    reason = why_unavailable(session)
    if reason is not None:
        raise ValidationFailed(reason)
    limit = platform_settings().ocr_max_pages
    if pages > limit:
        raise ValidationFailed(f"This file has {pages} pages; at most {limit} pages are read from a picture. "
                               "Upload it in parts, or download a text version from your bank.")
    created_by = current_context().user_id
    scan_id = scan_repo.add_scan(session, connection_id, filename=filename, kind=kind, pages=pages, data=data,
                                 created_by=created_by)
    enqueue(session, JOB, {"scan_id": str(scan_id)}, dedupe_key=f"scan:{scan_id}", max_attempts=1)
    return scan_id


def read_scan(session: Session, scan_id: UUID) -> None:
    """The job: read the pictures with the engine, page by page, and keep the lines. Never raises for a bad file."""
    row = scan_repo.get_scan_by_id(session, scan_id)
    if row is None or row.status in ("ready", "failed") or row.data is None:
        return
    tenant_id = current_context().tenant_id

    def progress(done: int, total: int) -> None:
        with tenant_transaction(tenant_id) as other:
            scan_repo.set_status(other, scan_id, "reading", pages_done=done)

    try:
        found = engine(session)
        if found is None:
            raise FileProblem(why_unavailable(session) or "Reading pictures is not switched on on this server yet.")
        from ziira.modules.connect.services import connectors
        vocab: set[str] = set()
        for connector in connectors.all_connectors(session):
            vocab |= getattr(connector, "vocabulary", lambda: set())()
        table = ocr_pages.read_pictures(bytes(row.data), row.kind, found, vocab,
                                        max_pages=platform_settings().ocr_max_pages, progress=progress)
        scan_repo.set_rows(session, scan_id, [{"n": r.number, "c": r.cells, "p": r.page, "l": r.low_confidence}
                                              for r in table.rows], table.warnings)
    except (FileProblem, ConnectorError) as error:
        scan_repo.set_status(session, scan_id, "failed", error=str(error))
    except Exception:                                                              # noqa: BLE001 - never retry OCR
        log.exception("reading scan %s failed", scan_id)
        scan_repo.set_status(session, scan_id, "failed",
                             error="The picture could not be read. Try a sharper photo, or download the statement as "
                                   "PDF, Excel or CSV.")


def get(session: Session, scan_id: UUID, connection_id: UUID) -> Any:
    row = scan_repo.get_scan(session, scan_id, connection_id)
    if row is None:
        raise NotFound("That upload is no longer available (they are kept for a day). Upload the file again.")
    return row


def table_of(row: Any) -> RawTable:
    """The lines the job read, as a table (the same shape every other file gives)."""
    if row.status != "ready" or row.rows is None:
        raise ValidationFailed("The picture has not been read yet" if row.status in ("queued", "reading")
                               else str(row.error or "The picture could not be read"))
    return RawTable([RawRow(int(r["n"]), list(r["c"]), int(r["p"]), bool(r["l"])) for r in row.rows], "scan",
                    list(row.warnings), None, True)


def correct(session: Session, scan_id: UUID, connection_id: UUID, changes: dict[int, dict[int, str]]) -> None:
    """Fix cells of the lines read: {line number: {column position: new text}}; a corrected line is no longer in
    doubt."""
    row = get(session, scan_id, connection_id)
    table = table_of(row)
    by_number = {r.number: r for r in table.rows}
    for number, cells in changes.items():
        target = by_number.get(number)
        if target is None:
            raise ValidationFailed(f"There is no line {number} in this file")
        for position, value in cells.items():
            if not 0 <= position < len(target.cells):
                raise ValidationFailed("That column does not exist")
            target.cells[position] = " ".join(value.split())[:500]
        target.low_confidence = False
    scan_repo.set_rows(session, scan_id, [{"n": r.number, "c": r.cells, "p": r.page, "l": r.low_confidence}
                                          for r in table.rows], table.warnings)
    scan_repo.set_status(session, scan_id, "ready")
