"""Reading a supplier's statement. Pure Python: no database, no HTTP.

A supplier's statement lists what they say happened on our account: invoices they issued, credit notes they gave and
payments they received, with an amount and a reference (their invoice number, their credit note number, our payment's
reference). Each line has a kind, a date, a reference and a positive amount.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ziira.sdk import ValidationFailed

MAX_LINES = 2000
KIND_NAMES = {
    "invoice": "invoice", "inv": "invoice", "bill": "invoice", "debit": "invoice",
    "credit": "credit", "credit note": "credit", "cn": "credit", "cr": "credit", "crn": "credit",
    "payment": "payment", "pmt": "payment", "paid": "payment", "receipt": "payment", "pay": "payment",
}


@dataclass(frozen=True)
class StatementLine:
    day: date
    reference: str
    kind: str          # invoice | credit | payment
    amount: Decimal    # always positive; the kind says which way it goes


def normalise_reference(reference: str) -> str:
    """References compared without case, spaces or punctuation: 'INV/2026-001' equals 'inv 2026 001'."""
    return re.sub(r"[^A-Z0-9]", "", reference.upper())


def parse_kind(value: str) -> str:
    kind = KIND_NAMES.get(" ".join(value.lower().split()))
    if kind is None:
        raise ValidationFailed(f"A line's kind is invoice, credit or payment, not '{value}'")
    return kind


def parse_day(value: str) -> date:
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationFailed(f"'{value}' is not a date (use 2026-10-31 or 31/10/2026)")


def parse_amount(value: str) -> Decimal:
    text = re.sub(r"(?i)kes|ksh|[\s,]", "", value.strip())
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValidationFailed(f"'{value}' is not an amount") from None
    if not amount.is_finite():
        raise ValidationFailed(f"'{value}' is not an amount")
    amount = abs(amount) if negative else amount
    if amount <= 0 or amount > Decimal("1000000000") or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed(f"'{value}': an amount is more than zero with at most 2 decimal places")
    return amount


def parse_csv(content: str) -> list[StatementLine]:
    """A statement as comma-separated text: date, reference, kind, amount (a header row naming the columns is used when
    present, in any order)."""
    if len(content) > 2_000_000:
        raise ValidationFailed("That statement is too large")
    rows = [r for r in csv.reader(io.StringIO(content.strip())) if any(c.strip() for c in r)]
    if not rows:
        raise ValidationFailed("The statement is empty")
    names = ["date", "reference", "kind", "amount"]
    header = [c.strip().lower() for c in rows[0]]
    order = {n: header.index(n) for n in names if n in header}
    if len(order) == 4:
        rows = rows[1:]
    else:
        order = {n: i for i, n in enumerate(names)}
    if len(rows) > MAX_LINES:
        raise ValidationFailed(f"A statement has at most {MAX_LINES} lines")
    lines = []
    for number, row in enumerate(rows, start=1):
        try:
            cells = {n: row[i].strip() for n, i in order.items()}
        except IndexError:
            raise ValidationFailed(f"Line {number}: expected date, reference, kind and amount") from None
        try:
            lines.append(line(parse_day(cells["date"]), cells["reference"], parse_kind(cells["kind"]),
                              parse_amount(cells["amount"])))
        except ValidationFailed as error:
            raise ValidationFailed(f"Line {number}: {error.message}") from None
    return lines


def line(day: date, reference: str, kind: str, amount: Decimal) -> StatementLine:
    if not reference.strip() or len(reference) > 60:
        raise ValidationFailed("Each line needs the supplier's reference (up to 60 characters)")
    if kind not in ("invoice", "credit", "payment"):
        raise ValidationFailed("A line's kind is invoice, credit or payment")
    return StatementLine(day, reference.strip(), kind, amount)


def effect(kind: str, amount: Decimal) -> Decimal:
    """How a line moves what we owe: invoices add to it, credit notes and payments reduce it."""
    return amount if kind == "invoice" else -amount
