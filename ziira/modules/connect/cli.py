"""`ziira connect`: standalone mode from the command line. The same services as the web screens."""

import sys
from pathlib import Path
from uuid import UUID

from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.services import connectors, sync, uploads
from ziira.sdk import NotFound, ValidationFailed, system_session


def run_sync(tenant_id: UUID, name: str | None) -> int:
    """Read the tenant's connections now (one by name, or every live one). Exit code 1 when a read fails."""
    failed = 0
    with system_session(tenant_id) as session:
        rows = [r for r in repo.list_connections(session, None) if r.status != "disconnected"
                and (name is None or r.name.lower() == name.lower())]
        if name is not None and not rows:
            raise NotFound(f"No connection called '{name}'")
        for row in rows:
            if connectors.is_file_kind(connectors.connector_for(session, row.kind)):
                if name is not None:
                    print(f"{row.name}: reads uploaded files; use 'ziira connect upload'")
                continue
            result = sync.sync_connection(session, row.id, trigger="cli")
            line = f"{row.name}: {result.status}"
            if result.error:
                line += f" ({result.error})"
                failed += 1
            print(line)
            for entity, counts in result.counts.items():
                print(f"  {entity}: {counts.read} read, {counts.new} new, {counts.changed} changed, {counts.skipped} "
                      f"skipped")
    return 1 if failed else 0


def run_upload(tenant_id: UUID, name: str, path: Path, *, check_only: bool) -> int:
    """Upload a file or statement to a file connection (or only check it). Exit code 1 when rows were rejected."""
    data = path.read_bytes()
    with system_session(tenant_id) as session:
        row = repo.find_by_name(session, name)
        if row is None:
            raise NotFound(f"No connection called '{name}'")
        if check_only:
            shown = uploads.preview(session, row.id, data, path.name)
            done = None
            if shown.state != "ready":
                print(shown.message or "This file is a picture: it is read in the background by the web app.",
                      file=sys.stderr)
                return 1
        else:
            done = uploads.commit(session, row.id, data, path.name, trigger="cli")
            shown = done.preview
        print("Columns: " + ", ".join(f"{k} <- {v}" for k, v in shown.mapping.items() if v))
        if shown.missing:
            print("  ! no column chosen for: " + ", ".join(shown.missing), file=sys.stderr)
        print(f"{shown.total_rows} row(s): {shown.valid_rows} readable, {shown.issue_count} with problems")
        for issue in shown.issues[:20]:
            print(f"  row {issue.row}: {issue.message}")
        if done is None:
            print("Nothing was stored. Run again without --check to store the readable rows.")
        else:
            for entity, counts in done.counts.items():
                print(f"  {entity}: {counts.new} new, {counts.changed} changed, {counts.skipped} skipped")
    if shown.missing:
        raise ValidationFailed("Choose the missing columns first (in the web app, or with a saved mapping)")
    return 1 if shown.issue_count else 0


def run_ocr_check() -> int:
    """Say whether pictures of statements can be read on this server, and what to install if not."""
    from ziira.modules.connect.ocr.tesseract import TesseractEngine
    engine = TesseractEngine()
    reason = engine.unavailable()
    if reason is None:
        print(f"OK: {engine.name}, languages {engine.languages}")
        return 0
    print(f"NOT AVAILABLE: {reason}", file=sys.stderr)
    return 1
