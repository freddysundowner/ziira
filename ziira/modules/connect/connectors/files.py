"""Connectors that read an uploaded file instead of a live system (`freshness = "on_upload"`).

A file connector says which fields a file may carry (with the names those columns usually have), and turns the rows of a
file into canonical records. Everything else (reading the CSV, the saved column mapping, the preview, the validation
report, storing, idempotence by `ref`) is done once by the connectors module, so every file kind behaves the same way.
Nothing here depends on a country: dates and numbers are read with the options the business chose for its file.
"""

import hashlib
import re
from abc import abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ziira.modules.connect.domain import values
from ziira.modules.connect.public import CanonicalBatch, ConnectionCheck, Connector, Record

MOBILE_WORDS = ("mobile", "momo", "wallet", "mpesa", "m-pesa", "airtel", "stk", "paybill")
BANK_WORDS = ("bank", "transfer", "eft", "wire", "cheque", "check", "rtgs", "swift", "ach", "direct debit", "deposit")
CARD_WORDS = ("card", "visa", "mastercard", "pos terminal", "debit card", "credit card")
CREDIT_WORDS = ("credit", "account", "on account", "tab", "invoice")


@dataclass(frozen=True)
class FileField:
    """One thing a file may carry. `aliases` are other names for the column; they are data, not logic."""

    name: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    help: str = ""
    example: str = ""


@dataclass(frozen=True)
class FileSettings:
    """How the business's file is written: which column is which, how numbers and dates look, the time zone."""

    mapping: dict[str, str | None] = field(default_factory=dict)
    decimal_separator: str = "."
    date_format: str = "iso"
    delimiter: str | None = None
    timezone: str = "UTC"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RowIssue:
    row: int
    message: str


@dataclass
class ParsedRow:
    """One line of the file after column mapping: field name -> trimmed text ('' when empty or not mapped)."""

    number: int
    values: dict[str, str]
    low_confidence: bool = False         # read from a picture with a doubtful word in it

    def text(self, name: str) -> str:
        return self.values.get(name, "").strip()


class RowReader:
    """Reads the typed values of rows with the file's settings; problems are collected as row issues."""

    def __init__(self, settings: FileSettings) -> None:
        self.settings = settings
        self.issues: list[RowIssue] = []
        self._seen: dict[str, int] = {}

    def unique(self, ref: str) -> str:
        """A reference made from a row's content: identical rows in one file get a count (#2, #3) so they are not
        merged, and the same file read again gives the same references."""
        self._seen[ref] = self._seen.get(ref, 0) + 1
        return ref if self._seen[ref] == 1 else f"{ref}#{self._seen[ref]}"

    def issue(self, row: ParsedRow, message: str) -> None:
        self.issues.append(RowIssue(row.number, message))

    def number(self, row: ParsedRow, name: str, *, required: bool = False) -> Decimal | None:
        raw = row.text(name)
        if not raw:
            if required:
                self.issue(row, f"{name}: a number is needed")
            return None
        try:
            return values.parse_decimal(raw, self.settings.decimal_separator)
        except ValueError as error:
            self.issue(row, f"{name}: {error}")
            return None

    def moment(self, row: ParsedRow, name: str, time_name: str | None = None, *,
        required: bool = False) -> datetime | None:
        raw = row.text(name)
        if not raw:
            if required:
                self.issue(row, f"{name}: a date is needed")
            return None
        try:
            return values.parse_datetime(raw, self.settings.date_format, self.settings.timezone,
                                         row.text(time_name) if time_name else "")
        except (ValueError, KeyError) as error:
            self.issue(row, f"{name}: {error}")
            return None

    def day(self, row: ParsedRow, name: str, *, required: bool = False) -> date | None:
        moment = self.moment(row, name, required=required)
        return moment.date() if moment is not None else None


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    """True when any of the words or phrases appears as whole words in the text."""
    return any(re.search(rf"\b{re.escape(re.sub(r'[^a-z0-9]+', ' ', w.lower()).strip())}\b", text) for w in words)


def method_of(word: str) -> str:
    """cash / card / mobile_money / bank / credit / other from whatever the file calls the payment method."""
    low = re.sub(r"[^a-z0-9]+", " ", word.lower()).strip()
    if not low:
        return "other"
    if low in ("cash", "cash payment"):
        return "cash"
    for method, words in (("mobile_money", MOBILE_WORDS), ("card", CARD_WORDS), ("credit", CREDIT_WORDS),
                          ("bank", BANK_WORDS)):
        if _has_word(low, words):
            return method
    return "cash" if "cash" in low.split() else "other"


def stable_ref(*parts: object) -> str:
    """A short stable reference made from what defines a record (for files that carry no id of their own)."""
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()[:24]


class FileConnector(Connector):
    """A connector whose data comes from uploaded files. Nothing is pulled on a schedule."""

    freshness = "on_upload"
    fields: tuple[FileField, ...] = ()
    options_help: dict[str, str] = {}
    header_names: tuple[str, ...] = ()           # extra names that mark a header line (for files with a title above)
    family = "export"                            # what the file is about: statement | export (wrong-kind advice)
    needs_any: tuple[tuple[str, ...], ...] = ()  # groups of fields of which at least one must be present
    needs_any_label: str = ""                    # what a missing group is called in plain words
    skip_phrases: tuple[str, ...] = ()           # lines starting like this are not transactions (opening balance ...)
    simple_fields: tuple[str, ...] = ()          # the fields a person may need to correct (else: the required ones)
    lenient: bool = False                        # titles, totals and wrapped lines are expected around the table

    def vocabulary(self) -> set[str]:
        """Every column name this kind knows, normalised (finds the header line in a PDF or a spreadsheet)."""
        from ziira.modules.connect.domain.csvfile import normalise
        return {normalise(n) for f in self.fields for n in (f.name, *f.aliases) if normalise(n)}

    def missing(self, mapping: dict[str, str | None]) -> list[str]:
        """Plain names of what the file lacks: required fields, and groups of which one is needed."""
        absent = [f.label for f in self.fields if f.required and not mapping.get(f.name)]
        if self.needs_any and not all(any(mapping.get(n) for n in group) for group in self.needs_any):
            absent.append(self.needs_any_label)
        return absent

    def describe_fields(self) -> list[dict[str, Any]]:
        return [{"name": f.name, "label": f.label, "required": f.required, "help": f.help, "example": f.example,
                 "aliases": list(f.aliases)} for f in self.fields]

    def check(self, config: dict[str, Any], secrets: dict[str, Any]) -> ConnectionCheck:
        return ConnectionCheck(ok=True, message="Nothing to test: upload a file to read it.")

    def pull(self, config: dict[str, Any], secrets: dict[str, Any], entity: str, since: str | None,
             limit: int | None = None) -> Iterator[CanonicalBatch]:
        return iter(())

    @abstractmethod
    def records(self, rows: list[ParsedRow], reader: RowReader, account: str) -> dict[str, list[Record]]:
        """Canonical records by entity from the rows. Report a bad row with `reader.issue(row, message)` and leave it
        out; never raise for a bad value. `account` is the connection's name (a statement's account label)."""
