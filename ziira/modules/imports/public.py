"""Public interface of the Data Import module.

Each unit that owns data supplies the importer for it through the extension point `imports.importer`: subclass
`Importer`, decorate with `@provides(IMPORTS_IMPORTER)` in its hooks.py, list "imports.importer" under
`[extends] implements` and "imports" under `optional` in its manifest. The importer only describes the columns,
checks a row without writing, and creates the record through its own unit's services (so every rule, permission,
audit entry, number series and event applies). The Data Import module does the rest: reading the file, mapping
columns, the dry run, the background commit, the reconciliation report.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ziira.modules.imports.domain import values
from ziira.sdk import Session, ZiiraError

IMPORTS_IMPORTER = "imports.importer"

__all__ = [
    "IMPORTS_IMPORTER", "BatchSummary", "ExistingRecord", "FileCheck", "ImportColumn", "ImportOptions", "ImportRow",
    "Importer", "RowCheck", "attempt", "available_importers", "batch_summary", "check_rows", "discard_staged",
    "find_existing", "reverse_import", "stage_rows", "start_import", "validate_staged",
]


def attempt[T](errors: list[str], check: Callable[[], T]) -> T | None:
    """Run a unit's own rule (which raises when the value is wrong); on failure add its message to `errors` and give
    None. Lets `validate_row` reuse the exact rules the screens use."""
    try:
        return check()
    except ZiiraError as error:
        errors.append(error.message)
        return None


@dataclass(frozen=True)
class ImportColumn:
    """One field a file may carry. `total` names a figure to add up for the reconciliation report (for example
    "quantity"): the file's sum of this column is compared with what ended up in Ziira."""

    name: str
    required: bool
    description: str
    example: str
    aliases: tuple[str, ...] = ()
    total: str | None = None


@dataclass(frozen=True)
class ImportOptions:
    """How the file writes numbers and dates (chosen by the user when the file is uploaded)."""

    decimal_separator: str = "."
    date_format: str = "iso"
    as_of: date | None = None             # the go-live date, for the kinds that bring in opening balances
    tolerance: Decimal = Decimal(0)       # how far a file that should balance may be out before it must be confirmed


@dataclass(frozen=True)
class FileCheck:
    """What a whole-file importer finds wrong with the file as a whole (as opposed to one row): `problems` stop the
    import; `confirm` is a warning the user must accept before it goes on; `notes` are for information."""

    problems: list[str] = field(default_factory=list)
    confirm: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExistingRecord:
    """A record already in Ziira that is the same real-world thing as a row (same phone, same tax number...): the code
    it has there (customer code, supplier code, SKU) and, in plain words, why we think so."""

    code: str
    reason: str


@dataclass(frozen=True)
class ImportRow:
    """One line of the file after column mapping: field name -> trimmed text ("" when empty or not mapped)."""

    values: Mapping[str, str]
    options: ImportOptions = field(default_factory=ImportOptions)

    def text(self, name: str) -> str:
        return self.values.get(name, "").strip()

    def number(self, name: str, errors: list[str], *, minimum: Decimal | None = None) -> Decimal | None:
        """The column as a number; None when empty. A bad value adds a plain message to `errors`."""
        raw = self.text(name)
        if not raw:
            return None
        try:
            number = values.parse_decimal(raw, self.options.decimal_separator)
        except ValueError as error:
            errors.append(f"{name}: {error}")
            return None
        if minimum is not None and number < minimum:
            errors.append(f"{name}: must be {minimum} or more")
            return None
        return number

    def day(self, name: str, errors: list[str]) -> date | None:
        """The column as a date; None when empty. A bad value adds a plain message to `errors`."""
        raw = self.text(name)
        if not raw:
            return None
        try:
            return values.parse_date(raw, self.options.date_format)
        except ValueError as error:
            errors.append(f"{name}: {error}")
            return None

    def yes_no(self, name: str, errors: list[str]) -> bool | None:
        """The column as yes/no; None when empty. A bad value adds a plain message to `errors`."""
        raw = self.text(name)
        if not raw:
            return None
        try:
            return values.parse_bool(raw)
        except ValueError as error:
            errors.append(f"{name}: {error}")
            return None

    def whole_number(self, name: str, errors: list[str], *, minimum: int = 0) -> int | None:
        """The column as a whole number; None when empty."""
        number = self.number(name, errors, minimum=Decimal(minimum))
        if number is not None and number != number.to_integral_value():
            errors.append(f"{name}: must be a whole number")
            return None
        return int(number) if number is not None else None


class Importer(ABC):
    """What a unit supplies to let a business bring one kind of record in from a file."""

    kind: str                      # short code in URLs and on the command line, e.g. "products"
    title: str                     # shown to people, e.g. "Products and prices"
    description: str               # one or two sentences: what the file should contain
    permission: str                # the permission (of the owning unit) needed to create these records
    columns: tuple[ImportColumn, ...]
    money_totals: tuple[str, ...] = ()   # which of the `total` figures are money (shown with 2 decimals)
    reversible: bool = False       # True only if the owning unit can safely undo a whole import
    reversal_note: str = ""        # what to do instead when it cannot
    needs_go_live: bool = False    # the file brings in balances as at a date: the upload must say which
    whole_file: bool = False       # the rows only make sense together (one entry): all are imported, or none

    @abstractmethod
    def validate_row(self, session: Session, company_id: UUID, row: ImportRow) -> list[str]:
        """Plain-language problems with this row (empty when it can be imported). Reads only; never writes."""

    @abstractmethod
    def import_row(self, session: Session, company_id: UUID, row: ImportRow, local_id: UUID) -> UUID:
        """Create the record through the owning unit's service and return its id. `local_id` is the staged row's id:
        stable across retries, for importers whose service takes a client-made id. Must raise on any problem."""

    def key(self, row: ImportRow) -> str | None:
        """What makes a row unique within the file (for example the lower-case SKU); None for no check."""
        return None

    def existing(self, session: Session, company_id: UUID, row: ImportRow) -> str | None:
        """A message when this record is already in Ziira (the row is then skipped, not an error); else None."""
        return None

    def find_match(self, session: Session, company_id: UUID, row: ImportRow) -> ExistingRecord | None:
        """The record already in Ziira that is the same real-world thing as this row, found by more than its code (same
        phone or tax number), so a move from another system does not make a second copy. None when there is none or the
        kind does not look. Reads only."""
        return None

    def check_file(self, session: Session, company_id: UUID, rows: Sequence[ImportRow]) -> FileCheck:
        """Whole-file importers: problems with the rows taken together (they do not balance, an earlier import is in
        the way). Reads only. Run at the check and again just before the import."""
        return FileCheck()

    def import_file(self, session: Session, company_id: UUID, rows: Sequence[ImportRow], *,
                    confirmed: bool) -> UUID:
        """Whole-file importers: create the one record all the rows make, and return its id. `confirmed` says the user
        accepted the warning in `check_file`. Must raise on any problem (then no row is imported)."""
        raise NotImplementedError(f"{self.kind} imports row by row")

    def reverse(self, session: Session, company_id: UUID, record_ids: list[UUID], reason: str) -> int:
        """Undo a whole import (importers with `reversible`): reverse the records the import created, through the owning
        unit's own reversal. Raise a plain-language error, changing nothing, when later activity (a payment) makes that
        unsafe. Returns how many records were reversed."""
        raise NotImplementedError(f"{self.kind} cannot be reversed")

    def totals(self, rows: Sequence[ImportRow]) -> dict[str, Decimal]:
        """The sums the file claims, per figure (default: the columns that name a `total`). Rows that cannot be read
        as numbers add nothing."""
        sums: dict[str, Decimal] = {}
        for column in self.columns:
            if column.total is None:
                continue
            sums.setdefault(column.total, Decimal(0))
            for row in rows:
                number = row.number(column.name, [])
                if number is not None:
                    sums[column.total] += number
        return sums

    def imported_totals(self, session: Session, company_id: UUID, record_ids: list[UUID]) -> dict[str, Decimal]:
        """The same figures read back from the records that were created (the ids `import_row` returned)."""
        return {}

    def read_back(self, session: Session, company_id: UUID, rows: Sequence[ImportRow],
                  record_ids: list[UUID]) -> dict[str, Decimal]:
        """What the reconciliation report compares with the file's sums: by default `imported_totals`. An importer whose
        figures depend on the rows themselves (a trial balance read back account by account) overrides this."""
        return self.imported_totals(session, company_id, record_ids)


# --------------------------------------------------------------------------- driving imports from another unit
# A unit that holds data to bring into Ziira (Connectors moving a connected system's records) does not write the
# target unit's tables: it stages rows here, has them checked by the owning unit's importer, and starts the import.
# The permissions of the person are checked exactly as for an uploaded file.


@dataclass(frozen=True)
class RowCheck:
    """The dry-run result for one row: valid (would be created), skipped (already in Ziira) or invalid."""

    status: Literal["valid", "invalid", "skipped"]
    messages: list[str]


@dataclass(frozen=True)
class BatchSummary:
    """A batch as another unit may see it."""

    id: UUID
    company_id: UUID
    kind: str
    title: str
    status: str
    counts: dict[str, int]
    reversible: bool
    reversal_note: str
    source_kind: str | None
    source_id: UUID | None
    revert_reason: str | None = None


def available_importers(session: Session) -> dict[str, Importer]:
    """The importers of the units switched on for this business, by kind."""
    from ziira.modules.imports.services import batches

    return {i.kind: i for i in batches.all_importers(session)}


def _row(values: Mapping[str, str], as_of: date | None) -> ImportRow:
    return ImportRow(values, ImportOptions(as_of=as_of))


def check_rows(session: Session, kind: str, company_id: UUID, rows: Sequence[Mapping[str, str]], *,
               as_of: date | None = None) -> list[RowCheck]:
    """Dry run of rows (field name -> text) as the importer of `kind` would see them: values, duplicates inside the
    rows, and records already in Ziira. Writes nothing; stores nothing."""
    from ziira.modules.imports.services import batches

    return batches.check_rows(session, kind, company_id, [_row(r, as_of) for r in rows])


def find_existing(session: Session, kind: str, company_id: UUID, values: Mapping[str, str]) -> ExistingRecord | None:
    """The record already in Ziira that a row is the same thing as (see `Importer.find_match`), or None."""
    from ziira.modules.imports.services import batches

    importer = batches.get_importer(session, kind)
    return importer.find_match(session, company_id, _row(values, None))


def stage_rows(session: Session, *, kind: str, company_id: UUID, rows: Sequence[Mapping[str, str]], name: str,
               as_of: date | None = None, source: tuple[str, UUID] | None = None) -> UUID:
    """Stage rows as a batch (the same as uploading a file whose columns are the importer's field names). `source`
    tags the batch with what staged it. Nothing is imported until `validate_staged` and `start_import`."""
    from ziira.modules.imports.services import batches

    return batches.create_batch_from_rows(session, kind=kind, company_id=company_id, rows=rows, name=name,
                                          as_of=as_of, source=source)


def _summary(session: Session, batch_id: UUID) -> BatchSummary:
    from ziira.modules.imports.services import batches

    d = batches.get_batch(session, batch_id)
    b = d.batch
    return BatchSummary(b.id, b.company_id, b.kind, d.importer.title, b.status, d.counts, d.importer.reversible,
                        d.importer.reversal_note, b.source_kind, b.source_id, b.revert_reason)


def batch_summary(session: Session, batch_id: UUID) -> BatchSummary:
    """Where a batch stands: its status and counts of rows by state."""
    return _summary(session, batch_id)


def validate_staged(session: Session, batch_id: UUID) -> BatchSummary:
    """The batch's dry run (rows already in Ziira are skipped, not errors)."""
    from ziira.modules.imports.services import batches

    batches.validate_batch(session, batch_id)
    return _summary(session, batch_id)


def start_import(session: Session, batch_id: UUID) -> BatchSummary:
    """Import the valid rows in the background (`ziira worker`). Asking twice changes nothing."""
    from ziira.modules.imports.services import batches

    batches.commit_batch(session, batch_id)
    return _summary(session, batch_id)


def discard_staged(session: Session, batch_id: UUID) -> None:
    """Throw away a batch that was never imported."""
    from ziira.modules.imports.services import batches

    batches.discard_batch(session, batch_id)


def reverse_import(session: Session, batch_id: UUID, reason: str) -> BatchSummary:
    """Undo a finished import of a kind that can be undone (opening balances)."""
    from ziira.modules.imports.services import batches

    batches.reverse_batch(session, batch_id, reason=reason)
    return _summary(session, batch_id)
