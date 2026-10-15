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
from uuid import UUID

from ziira.modules.imports.domain import values
from ziira.sdk import Session, ZiiraError

IMPORTS_IMPORTER = "imports.importer"

__all__ = ["IMPORTS_IMPORTER", "FileCheck", "ImportColumn", "ImportOptions", "ImportRow", "Importer", "attempt"]


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
