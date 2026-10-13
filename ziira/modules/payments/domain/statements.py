"""Reading statements people upload: M-Pesa business statements and bank CSV files. Pure Python."""

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from ziira.modules.payments.domain.mpesa import EAT
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


def _amount(value: str | None) -> Decimal:
    text = (value or "").replace(",", "").replace("KES", "").replace("Ksh", "").strip()
    if not text or text in ("-", "0", "0.00"):
        return Decimal(0)
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"'{value}' is not an amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"'{value}' is not a usable amount")
    return amount


def _time(value: str) -> datetime:
    cleaned = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=EAT)
        except ValueError:
            continue
    raise ValueError(f"'{value}' is not a date")


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def _rows(text: str) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """The header names and the data rows (with line numbers), after skipping any lines before the header."""
    if len(text) > 10_000_000:
        raise ValidationFailed("The statement is too large")
    reader = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    for index, row in enumerate(reader):
        keys = {_key(c) for c in row}
        if len(keys & {"receiptno", "completiontime", "paidin", "withdrawn", "date", "description", "amount",
                       "debit", "credit", "reference"}) >= 2:
            header = [_key(c) for c in row]
            data = [(n + index + 2, dict(zip(header, r, strict=False))) for n, r in enumerate(reader[index + 1:])
                    if any(c.strip() for c in r)]
            if len(data) > MAX_ROWS:
                raise ValidationFailed(f"A statement can have at most {MAX_ROWS} rows")
            return header, data
    raise ValidationFailed("No header row found: is this a statement in CSV form?")


def parse_mpesa_statement(text: str) -> ParsedStatement:
    """Safaricom's business statement: Receipt No., Completion Time, Details, Status, Paid In, Withdrawn."""
    header, data = _rows(text)
    if "receiptno" not in header:
        raise ValidationFailed("This does not look like an M-Pesa statement (no 'Receipt No.' column)")
    rows: list[StatementRow] = []
    skipped: list[str] = []
    for line, row in data:
        try:
            status = (row.get("transactionstatus") or "Completed").strip().lower()
            if status not in ("completed", "complete", "success", "successful"):
                continue                                       # failed or reversed items did not move money
            paid_in, withdrawn = _amount(row.get("paidin")), _amount(row.get("withdrawn"))
            if (paid_in > 0) == (withdrawn > 0):
                raise ValueError("exactly one of Paid In and Withdrawn is expected")
            details = (row.get("details") or "").strip()
            phone = re.search(r"(2547\*{4}\d{3}|254[17]\d{8}|07\d{8})", details)
            name = re.search(r"-\s*(.+)$", details)
            rows.append(StatementRow(
                ref=(row.get("receiptno") or "").strip().upper(), time=_time(row.get("completiontime") or ""),
                amount=paid_in or withdrawn, direction="in" if paid_in > 0 else "out", description=details,
                payer_name=name.group(1).strip() if name and paid_in > 0 else None,
                payer_phone=phone.group(1) if phone else None))
            if not rows[-1].ref:
                raise ValueError("no receipt number")
        except ValueError as exc:
            skipped.append(f"line {line}: {exc}")
            rows = [r for r in rows if r.ref]
    return ParsedStatement(rows, skipped)


def parse_bank_statement(text: str, *, date_column: str = "date", description_column: str = "description",
                         reference_column: str | None = "reference", amount_column: str | None = None,
                         debit_column: str | None = "debit", credit_column: str | None = "credit") -> ParsedStatement:
    """A bank CSV. Either one signed `amount` column (negative = out) or separate debit and credit columns. Lines
    without a bank reference get a stable one made from their date, amount and description (so uploading twice adds
    nothing)."""
    header, data = _rows(text)
    columns = {name: _key(name) for name in (date_column, description_column) if name}
    for needed, key in columns.items():
        if key not in header:
            raise ValidationFailed(f"The statement has no '{needed}' column")
    rows: list[StatementRow] = []
    skipped: list[str] = []
    for line, row in data:
        try:
            when = _time(row.get(columns[date_column], ""))
            description = (row.get(columns[description_column]) or "").strip()
            if amount_column and _key(amount_column) in header:
                signed = Decimal(str(row.get(_key(amount_column), "")).replace(",", "").strip() or "0")
                amount, direction = abs(signed), ("in" if signed > 0 else "out")
            else:
                credit = _amount(row.get(_key(credit_column or ""), ""))
                debit = _amount(row.get(_key(debit_column or ""), ""))
                if (credit > 0) == (debit > 0):
                    raise ValueError("exactly one of debit and credit is expected")
                amount, direction = credit or debit, ("in" if credit > 0 else "out")
            if amount <= 0:
                raise ValueError("no amount")
            ref = (row.get(_key(reference_column or ""), "") or "").strip().upper()
            if not ref:
                fingerprint = f"{when.date()}|{amount}|{direction}|{description}"
                ref = "B" + hashlib.sha256(fingerprint.encode()).hexdigest()[:20]
            rows.append(StatementRow(ref=ref, time=when, amount=amount, direction=direction, description=description))
        except (ValueError, InvalidOperation) as exc:
            skipped.append(f"line {line}: {exc}")
    return ParsedStatement(rows, skipped)
