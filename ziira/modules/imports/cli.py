"""`ziira import`: assisted onboarding from the command line. Reads a file, checks it (a dry run) and, with --commit,
imports the valid rows. The same services as the web screens, so the same rules apply."""

import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from ziira.modules.imports.services import batches
from ziira.sdk import NotFound, Session, ValidationFailed, system_session

SHOW_ERRORS = 20


def _company(session: Session, wanted: str | None) -> UUID:
    """The company named by id or by name; the only company when none is named."""
    rows = session.execute(text("select id, name from kernel.company order by name")).all()
    if wanted is None:
        if len(rows) != 1:
            raise ValidationFailed("This business has several companies; name one with --company (its name or id)")
        company_id: UUID = rows[0].id
        return company_id
    for row in rows:
        if wanted.lower() in (str(row.id).lower(), row.name.lower()):
            found: UUID = row.id
            return found
    raise NotFound(f"No company '{wanted}'. Known: {', '.join(r.name for r in rows)}")


def _print_rows(session: Session, batch_id: UUID) -> None:
    total, rows = batches.list_rows(session, batch_id, status=None, only_errors=True, limit=SHOW_ERRORS, offset=0)
    for row in rows:
        print(f"  row {row.row_no}: {'; '.join(row.errors)}")
    if total > SHOW_ERRORS:
        print(f"  ... and {total - SHOW_ERRORS} more")


def run_import(tenant_id: UUID, *, kind: str, path: Path, company: str | None, commit: bool, decimal_separator: str,
               date_format: str, mapping: dict[str, str], rejected: Path | None) -> int:
    """Validate a file (and import it with `commit`). Returns the exit code: 0 when every row was fine."""
    data = path.read_bytes()
    with system_session(tenant_id) as session:
        company_id = _company(session, company)
        detail = batches.create_batch(session, kind=kind, company_id=company_id, filename=path.name, data=data,
                                      decimal_separator=decimal_separator, date_format=date_format)
        chosen = {**detail.batch.mapping, **mapping}
        detail = batches.set_mapping(session, detail.batch.id, columns=chosen, decimal_separator=None,
                                     date_format=None)
        batch_id = detail.batch.id
        print("Columns: " + ", ".join(f"{k} <- {v}" for k, v in detail.batch.mapping.items() if v))
        detail = batches.validate_batch(session, batch_id)
        counts = detail.counts
        print(f"Checked {sum(counts.values())} row(s): {counts['valid']} valid, {counts['invalid']} with problems, "
              f"{counts['skipped']} skipped (already in Ziira)")
        _print_rows(session, batch_id)
        problems = counts["invalid"]
    if not commit:
        print("Nothing was imported. Run again with --commit to import the valid rows.")
        return 1 if problems else 0
    with system_session(tenant_id) as session:
        batches.commit_batch(session, batch_id)
    while True:
        with system_session(tenant_id) as session:
            if batches.import_chunk(session, batch_id) == 0:
                break
    with system_session(tenant_id) as session:
        result = batches.report(session, batch_id)
        print(f"Imported {result.counts['imported']}, skipped {result.counts['skipped']}, "
              f"failed {result.counts['failed']}, rejected {result.counts['invalid']}")
        for line in result.totals:
            print(f"  {line.label}: file {line.in_file}, imported rows {line.expected}, in Ziira {line.in_ziira}"
                  + ("" if line.matches else f"  DIFFERENCE {line.difference}"))
        for problem in result.problems:
            print(f"  ! {problem}", file=sys.stderr)
        if rejected is not None and (result.counts["invalid"] or result.counts["failed"]):
            rejected.write_text(batches.rejected_csv(session, batch_id), encoding="utf-8")
            print(f"Rejected rows written to {rejected}")
        return 1 if result.problems or result.counts["invalid"] else 0
