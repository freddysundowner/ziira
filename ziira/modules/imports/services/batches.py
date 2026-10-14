"""Use cases: bring a file in. Upload and read it, map its columns, check every row without writing, then import the
valid rows in the background, one at a time, each in its own savepoint.

    uploaded --validate--> validated --commit--> committing --last row handled--> done
        '------ mapping changes send a validated batch back to uploaded ------'

Every record is created by the owning unit's own service (through its importer), so its rules, permissions, audit
entries, number series and events apply exactly as if the record had been typed in.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.imports.domain import files, mapping, values
from ziira.modules.imports.permissions import IMPORTS_MANAGE
from ziira.modules.imports.public import IMPORTS_IMPORTER, Importer, ImportOptions, ImportRow
from ziira.modules.imports.repository import imports_repo as repo
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    ZiiraError,
    audit_record,
    check_company,
    current_context,
    enqueue,
    implementations,
    publish,
    to_csv,
)

log = logging.getLogger("ziira.imports")
COMMIT_JOB = "imports.commit"
CHUNK = 200
MESSAGE_LIMIT = 500


@dataclass(frozen=True)
class BatchDetail:
    batch: Row[Any]
    importer: Importer
    counts: dict[str, int]


# --------------------------------------------------------------------------- kinds and access
def all_importers(session: Session) -> list[Importer]:
    """The importers of the units enabled for this business, by title."""
    return sorted(implementations(session, IMPORTS_IMPORTER), key=lambda i: i.title)


def usable_importers(session: Session) -> list[Importer]:
    """The importers the signed-in user may use somewhere (they hold imports.manage and the permission of the data)."""
    ctx = current_context()
    return [i for i in all_importers(session) if ctx.has_anywhere(i.permission)]


def get_importer(session: Session, kind: str) -> Importer:
    found = next((i for i in all_importers(session) if i.kind == kind), None)
    if found is None:
        raise NotFound(f"'{kind}' cannot be imported here: the part of Ziira that keeps it is not switched on")
    return found


def _authorise(importer: Importer, company_id: UUID) -> None:
    ctx = current_context()
    ctx.require(IMPORTS_MANAGE, company_id=company_id)
    ctx.require(importer.permission, company_id=company_id)


def template_csv(importer: Importer) -> str:
    """A sample file: the header row and one example row."""
    return to_csv([c.name for c in importer.columns], [[c.example for c in importer.columns]])


# --------------------------------------------------------------------------- reading a batch
def _load(session: Session, batch_id: UUID, *, lock: bool = False) -> Row[Any]:
    batch = repo.get_batch(session, batch_id, lock=lock)
    if batch is None or not current_context().can(IMPORTS_MANAGE, company_id=batch.company_id):
        raise NotFound("Import not found")
    return batch


def get_batch(session: Session, batch_id: UUID) -> BatchDetail:
    batch = _load(session, batch_id)
    return BatchDetail(batch, get_importer(session, batch.kind), repo.counts(session, batch_id))


def list_batches(session: Session, *, limit: int, offset: int) -> list[Row[Any]]:
    return repo.list_batches(session, current_context().companies_with(IMPORTS_MANAGE), min(limit, 200), offset)


def options_of(batch: Row[Any]) -> ImportOptions:
    return ImportOptions(batch.options.get("decimal_separator", "."), batch.options.get("date_format", "iso"))


def import_row(importer: Importer, batch: Row[Any], cells: list[str]) -> ImportRow:
    """A staged row as the importer sees it: the file's cells placed under the field names by the batch's mapping."""
    index = {header: i for i, header in enumerate(batch.headers)}
    found: dict[str, str] = {}
    for column in importer.columns:
        header = batch.mapping.get(column.name)
        found[column.name] = cells[index[header]].strip() if header in index and index[header] < len(cells) else ""
    return ImportRow(found, options_of(batch))


@dataclass(frozen=True)
class RowView:
    row_no: int
    status: str
    errors: list[str]
    raw: list[str]
    values: dict[str, str]
    record_id: UUID | None


def list_rows(session: Session, batch_id: UUID, *, status: str | None, only_errors: bool, limit: int,
              offset: int) -> tuple[int, list[RowView]]:
    """(how many rows match, a page of them). `only_errors` means rows that were rejected or failed."""
    detail = get_batch(session, batch_id)
    statuses = ["invalid", "failed"] if only_errors else ([status] if status else None)
    total = repo.count_rows(session, batch_id, statuses)
    rows = repo.list_rows(session, batch_id, statuses=statuses, limit=min(limit, 500), offset=offset)
    return total, [RowView(r.row_no, r.status, list(r.errors), list(r.raw),
                           dict(import_row(detail.importer, detail.batch, list(r.raw)).values), r.record_id)
                   for r in rows]


# --------------------------------------------------------------------------- upload and mapping
def create_batch(session: Session, *, kind: str, company_id: UUID, filename: str, data: bytes,
                 decimal_separator: str = ".", date_format: str = "iso", delimiter: str | None = None) -> BatchDetail:
    """Read an uploaded file into a batch, with the column mapping we suggest. Nothing is imported yet."""
    importer = get_importer(session, kind)
    check_company(session, company_id)
    _authorise(importer, company_id)
    _check_options(decimal_separator, date_format)
    try:
        parsed = files.parse_file(data, delimiter=delimiter)
    except files.ImportFileError as error:
        raise ValidationFailed(str(error)) from error
    suggestion = mapping.suggest_mapping(parsed.headers, [(c.name, c.aliases) for c in importer.columns])
    batch_id = repo.add_batch(
        session, company_id=company_id, kind=kind, filename=(filename or "import.csv").strip()[:200] or "import.csv",
        delimiter=parsed.delimiter, headers=parsed.headers, mapping=suggestion,
        options={"decimal_separator": decimal_separator, "date_format": date_format}, warnings=parsed.warnings,
        created_by=current_context().user_id)
    repo.add_rows(session, batch_id, parsed.rows)
    audit_record(session, "upload", "imports.batch", batch_id,
                 {"kind": kind, "file": filename, "rows": len(parsed.rows)})
    return get_batch(session, batch_id)


def _check_options(decimal_separator: str, date_format: str) -> None:
    if decimal_separator not in values.DECIMAL_SEPARATORS:
        raise ValidationFailed("The decimal separator must be '.' or ','")
    if date_format not in values.DATE_FORMATS:
        raise ValidationFailed(f"The date format must be one of: {', '.join(values.DATE_FORMATS)}")


def _missing_required(importer: Importer, chosen: dict[str, str | None]) -> list[str]:
    return [c.name for c in importer.columns if c.required and not chosen.get(c.name)]


def set_mapping(session: Session, batch_id: UUID, *, columns: dict[str, str | None], decimal_separator: str | None,
                date_format: str | None) -> BatchDetail:
    """Choose which column of the file holds each field (and how the file writes numbers and dates). Checked rows go
    back to unchecked, because their meaning changed."""
    batch = _load(session, batch_id, lock=True)
    importer = get_importer(session, batch.kind)
    _authorise(importer, batch.company_id)
    if batch.status not in ("uploaded", "validated"):
        raise Conflict("This import has already been started, so its columns can no longer be changed")
    names = {c.name for c in importer.columns}
    unknown = sorted(set(columns) - names)
    if unknown:
        raise ValidationFailed(f"Unknown field(s): {', '.join(unknown)}")
    chosen = {name: columns.get(name) or None for name in names}
    bad = sorted(h for h in chosen.values() if h is not None and h not in batch.headers)
    if bad:
        raise ValidationFailed(f"The file has no column called {', '.join(bad)}")
    used = [h for h in chosen.values() if h is not None]
    if len(used) != len(set(used)):
        raise ValidationFailed("A column of the file can fill only one field")
    missing = _missing_required(importer, chosen)
    if missing:
        raise ValidationFailed(f"Choose a column for: {', '.join(missing)}")
    options = dict(batch.options)
    options["decimal_separator"] = decimal_separator or options.get("decimal_separator", ".")
    options["date_format"] = date_format or options.get("date_format", "iso")
    _check_options(options["decimal_separator"], options["date_format"])
    ordered = {c.name: chosen[c.name] for c in importer.columns}
    repo.update_batch(session, batch_id, mapping=ordered, options=options, status="uploaded")
    repo.reset_rows(session, batch_id)
    return get_batch(session, batch_id)


def discard_batch(session: Session, batch_id: UUID) -> None:
    """Throw away a batch that was never committed. Only the staged file is removed; no business record is touched."""
    batch = _load(session, batch_id, lock=True)
    _authorise(get_importer(session, batch.kind), batch.company_id)
    if batch.status == "committing":
        raise Conflict("This import is running; wait until it has finished")
    if batch.status == "done" and repo.counts(session, batch_id)["imported"]:
        raise Conflict("Records were created by this import, so its report is kept")
    audit_record(session, "discard", "imports.batch", batch_id, {"file": batch.filename})
    repo.delete_batch(session, batch_id)


# --------------------------------------------------------------------------- the dry run
def _message(error: Exception) -> str:
    if isinstance(error, ZiiraError):
        return error.message[:MESSAGE_LIMIT]
    return f"Unexpected problem: {type(error).__name__}"


def _check_row(session: Session, importer: Importer, company_id: UUID, row: ImportRow) -> list[str]:
    """Problems with a row, found without writing. A crash in an importer rejects the row, never the batch."""
    try:
        with session.begin_nested():
            return [m[:MESSAGE_LIMIT] for m in importer.validate_row(session, company_id, row)]
    except Exception as error:   # noqa: BLE001 - one bad row must not stop the dry run
        if not isinstance(error, ZiiraError):
            log.exception("Importer %s could not check a row", importer.kind)
        return [_message(error)]


def validate_batch(session: Session, batch_id: UUID) -> BatchDetail:
    """Check every row without writing anything: values, lookups, duplicates inside the file, and records that already
    exist (those rows are skipped, not errors)."""
    batch = _load(session, batch_id, lock=True)
    importer = get_importer(session, batch.kind)
    _authorise(importer, batch.company_id)
    if batch.status not in ("uploaded", "validated"):
        raise Conflict("This import has already been started")
    missing = _missing_required(importer, batch.mapping)
    if missing:
        raise ValidationFailed(f"Choose a column for: {', '.join(missing)}")
    first_seen: dict[str, int] = {}
    for chunk in repo.iter_rows(session, batch_id):
        results: list[dict[str, Any]] = []
        for staged in chunk:
            row = import_row(importer, batch, list(staged.raw))
            errors = _check_row(session, importer, batch.company_id, row)
            key = importer.key(row)
            if key is not None:
                if key in first_seen:
                    errors.append(f"Row {first_seen[key]} of this file has the same {key!r}")
                else:
                    first_seen[key] = staged.row_no
            status = "invalid" if errors else "valid"
            if not errors:
                try:
                    with session.begin_nested():
                        found = importer.existing(session, batch.company_id, row)
                except Exception as error:   # noqa: BLE001
                    errors, status = [_message(error)], "invalid"
                else:
                    if found:
                        errors, status = [found[:MESSAGE_LIMIT]], "skipped"
            results.append({"id": staged.id, "status": status, "parsed": dict(row.values), "errors": errors})
        repo.set_row_results(session, results)
    repo.update_batch(session, batch_id, status="validated")
    counts = repo.counts(session, batch_id)
    audit_record(session, "validate", "imports.batch", batch_id,
                 {"valid": counts["valid"], "invalid": counts["invalid"], "skipped": counts["skipped"]})
    return get_batch(session, batch_id)


# --------------------------------------------------------------------------- the import
def commit_batch(session: Session, batch_id: UUID) -> BatchDetail:
    """Start importing the valid rows in the background. Asking again while it runs (or after) changes nothing."""
    batch = _load(session, batch_id, lock=True)
    importer = get_importer(session, batch.kind)
    _authorise(importer, batch.company_id)
    if batch.status in ("committing", "done"):
        return get_batch(session, batch_id)
    if batch.status != "validated":
        raise Conflict("Check the file first: choose the columns and run the check")
    counts = repo.counts(session, batch_id)
    if counts["pending"]:
        raise Conflict("Some rows have not been checked since the columns changed; run the check again")
    if not counts["valid"]:
        raise ValidationFailed("There is no valid row to import")
    repo.update_batch(session, batch_id, status="committing", committed_by=current_context().user_id,
                      committed_at=_now(session))
    enqueue(session, COMMIT_JOB, {"batch_id": str(batch_id)}, dedupe_key=f"{COMMIT_JOB}:{batch_id}:start")
    audit_record(session, "commit", "imports.batch", batch_id, {"valid_rows": counts["valid"]})
    return get_batch(session, batch_id)


def _now(session: Session) -> Any:
    return session.execute(text("select now()")).scalar_one()


def import_chunk(session: Session, batch_id: UUID, size: int | None = None) -> int:
    """Import the next rows of a committing batch, each in its own savepoint (a failed row never blocks the others).
    Returns how many valid rows are left. Safe to run twice: a handled row is never handled again."""
    batch = repo.get_batch(session, batch_id, lock=True)
    if batch is None or batch.status != "committing":
        return 0
    importer = get_importer(session, batch.kind)
    for staged in repo.next_valid_rows(session, batch_id, size or CHUNK):
        row = import_row(importer, batch, list(staged.raw))
        try:
            with session.begin_nested():
                found = importer.existing(session, batch.company_id, row)
                if found:
                    repo.set_row_outcome(session, staged.id, "skipped", [found[:MESSAGE_LIMIT]])
                    continue
                record_id = importer.import_row(session, batch.company_id, row, staged.id)
                repo.set_row_outcome(session, staged.id, "imported", [], record_id)
        except Exception as error:   # noqa: BLE001 - recorded on the row; the rest go on
            if not isinstance(error, ZiiraError):
                log.exception("Importer %s failed on row %s", importer.kind, staged.row_no)
            repo.set_row_outcome(session, staged.id, "failed", [_message(error)])
    left = repo.counts(session, batch_id)["valid"]
    if left == 0:
        _finish(session, batch)
    else:
        enqueue(session, COMMIT_JOB, {"batch_id": str(batch_id)}, dedupe_key=f"{COMMIT_JOB}:{batch_id}:{left}")
    return left


def _finish(session: Session, batch: Row[Any]) -> None:
    repo.update_batch(session, batch.id, status="done", finished_at=_now(session))
    counts = repo.counts(session, batch.id)
    audit_record(session, "finish", "imports.batch", batch.id, dict(counts))
    publish(session, Event("import.committed", "imports.batch", batch.id, {
        "company_id": batch.company_id, "kind": batch.kind, "imported": counts["imported"],
        "failed": counts["failed"], "skipped": counts["skipped"]}))


# --------------------------------------------------------------------------- reconciliation and rejected rows
@dataclass(frozen=True)
class TotalLine:
    label: str
    in_file: Decimal             # everything the file claims
    expected: Decimal            # what the imported rows should add up to, from the file
    in_ziira: Decimal            # what the created records add up to, read back
    not_imported: Decimal        # in_file - expected: the rows that were rejected, skipped or failed
    difference: Decimal          # expected - in_ziira: must be zero

    @property
    def matches(self) -> bool:
        return self.difference == 0


@dataclass(frozen=True)
class Report:
    batch: Row[Any]
    importer: Importer
    counts: dict[str, int]
    rows_in_file: int
    totals: list[TotalLine]
    problems: list[str]


def report(session: Session, batch_id: UUID) -> Report:
    """Rows in the file / imported / skipped / failed, and each money or quantity column added up in the file and
    again from the records that were created. Differences are listed in plain words."""
    detail = get_batch(session, batch_id)
    batch, importer = detail.batch, detail.importer
    every: list[ImportRow] = []
    imported: list[ImportRow] = []
    record_ids: list[UUID] = []
    for chunk in repo.iter_rows(session, batch_id):
        for staged in chunk:
            row = import_row(importer, batch, list(staged.raw))
            every.append(row)
            if staged.status == "imported":
                imported.append(row)
                if staged.record_id is not None:
                    record_ids.append(staged.record_id)
    in_file, expected = importer.totals(every), importer.totals(imported)
    actual = importer.imported_totals(session, batch.company_id, record_ids) if record_ids else {}
    lines = [TotalLine(label, in_file[label], expected.get(label, Decimal(0)), actual.get(label, Decimal(0)),
                       in_file[label] - expected.get(label, Decimal(0)),
                       expected.get(label, Decimal(0)) - actual.get(label, Decimal(0))) for label in in_file]
    problems = [f"{x.label}: the imported rows add up to {x.expected} in the file but {x.in_ziira} in Ziira "
                f"(difference {x.difference})" for x in lines if not x.matches and detail.counts["imported"]]
    if detail.counts["failed"]:
        problems.append(f"{detail.counts['failed']} row(s) failed while importing; download them, fix the cause "
                        "and upload them again")
    return Report(batch, importer, detail.counts, sum(detail.counts.values()), lines, problems)


def rejected_csv(session: Session, batch_id: UUID) -> str:
    """The rows that were rejected or failed, as the user wrote them, with an `error` column; fix and upload again."""
    detail = get_batch(session, batch_id)
    rows: list[list[object]] = []
    for chunk in repo.iter_rows(session, batch_id, ["invalid", "failed"]):
        rows += [[*list(r.raw), "; ".join(r.errors)] for r in chunk]
    return to_csv([*detail.batch.headers, "error"], rows)
