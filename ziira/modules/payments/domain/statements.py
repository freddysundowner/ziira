"""Reading statements people upload: bank CSV files, and the helpers a provider plugin uses to read its own statement
format (public.py re-exports them). Pure Python."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from decimal import Decimal, InvalidOperation

from ziira.sdk import ValidationFailed

MAX_ROWS = 20000
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
                "%d %b %Y", "%d-%b-%Y")


@dataclass(frozen=True)
class StatementRow:
    ref: str
    time: datetime
    amount: Decimal
    direction: str                 # "in" or "out"
    description: str
    bill_ref: str | None = None
    payer_name: str | None = None
    payer_phone: str | None = None


@dataclass(frozen=True)
class ParsedStatement:
    rows: list[StatementRow]
    skipped: list[str]             # one line per row that could not be read, with its line number


def statement_amount(value: str | None) -> Decimal:
    """An amount cell: thousands separators and a leading currency word ("USD 1,200.50") are ignored; empty is 0."""
    text = re.sub(r"^[A-Za-z]{1,4}\.?\s*(?=[\d.])", "", (value or "").replace(",", "").strip())
    if not text or text in ("-", "0", "0.00"):
        return Decimal(0)
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"'{value}' is not an amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"'{value}' is not a usable amount")
    return amount


def statement_time(value: str, tz: tzinfo) -> datetime:
    """A date or date-time cell, read in the time zone `tz` (the business's own, or the provider's)."""
    cleaned = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    raise ValueError(f"'{value}' is not a date")


def column_key(name: str) -> str:
    """A header reduced to lower-case letters, so 'Receipt No.' and 'receipt_no' compare alike."""
    return re.sub(r"[^a-z]", "", name.lower())


GENERIC_HEADER_WORDS = frozenset({"date", "description", "amount", "debit", "credit", "reference"})


def csv_rows(text: str, header_words: frozenset[str] = GENERIC_HEADER_WORDS) -> tuple[
        list[str], list[tuple[int, dict[str, str]]]]:
    """The header names and the data rows (with line numbers), after skipping any lines before the header (the first
    line with at least two of `header_words`)."""
    if len(text) > 10_000_000:
        raise ValidationFailed("The statement is too large")
    reader = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    for index, row in enumerate(reader):
        keys = {column_key(c) for c in row}
        if len(keys & header_words) >= 2:
            header = [column_key(c) for c in row]
            data = [(n + index + 2, dict(zip(header, r, strict=False))) for n, r in enumerate(reader[index + 1:])
                    if any(c.strip() for c in r)]
            if len(data) > MAX_ROWS:
                raise ValidationFailed(f"A statement can have at most {MAX_ROWS} rows")
            return header, data
    raise ValidationFailed("No header row found: is this a statement in CSV form?")


def parse_bank_statement(text: str, *, tz: tzinfo = UTC, date_column: str = "date",
                         description_column: str = "description", reference_column: str | None = "reference",
                         amount_column: str | None = None, debit_column: str | None = "debit",
                         credit_column: str | None = "credit") -> ParsedStatement:
    """A bank CSV. Either one signed `amount` column (negative = out) or separate debit and credit columns. Lines
    without a bank reference get a stable one made from their date, amount and description (so uploading twice adds
    nothing)."""
    header, data = csv_rows(text)
    columns = {name: column_key(name) for name in (date_column, description_column) if name}
    for needed, key in columns.items():
        if key not in header:
            raise ValidationFailed(f"The statement has no '{needed}' column")
    rows: list[StatementRow] = []
    skipped: list[str] = []
    for line, row in data:
        try:
            when = statement_time(row.get(columns[date_column], ""), tz)
            description = (row.get(columns[description_column]) or "").strip()
            if amount_column and column_key(amount_column) in header:
                signed = Decimal(str(row.get(column_key(amount_column), "")).replace(",", "").strip() or "0")
                amount, direction = abs(signed), ("in" if signed > 0 else "out")
            else:
                credit = statement_amount(row.get(column_key(credit_column or ""), ""))
                debit = statement_amount(row.get(column_key(debit_column or ""), ""))
                if (credit > 0) == (debit > 0):
                    raise ValueError("exactly one of debit and credit is expected")
                amount, direction = credit or debit, ("in" if credit > 0 else "out")
            if amount <= 0:
                raise ValueError("no amount")
            ref = (row.get(column_key(reference_column or ""), "") or "").strip().upper()
            if not ref:
                fingerprint = f"{when.date()}|{amount}|{direction}|{description}"
                ref = "B" + hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
            rows.append(StatementRow(ref=ref, time=when, amount=amount, direction=direction, description=description))
        except (ValueError, InvalidOperation) as exc:
            skipped.append(f"line {line}: {exc}")
    return ParsedStatement(rows, skipped)
