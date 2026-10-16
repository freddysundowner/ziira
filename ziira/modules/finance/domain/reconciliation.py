"""Reconciling a bank, mobile money or card account to its statement. Pure Python: no database, no HTTP.

The books say what the account holds; the statement says what the bank holds. They differ by the things that have not
reached the other side yet. Lines of the ledger that appear on the statement are *cleared*; the account is reconciled
when the cleared lines add up to the statement's balance.

Amounts are the account's own way round: money in is positive (a debit to the asset account), money out is negative.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from ziira.sdk import ValidationFailed

MAX_LINES = 5000
WINDOW_DAYS = 5
IN_NAMES = ("paid in", "money in", "deposit", "deposits", "received")
OUT_NAMES = ("withdrawn", "paid out", "money out", "withdrawal", "withdrawals")
ALIASES = {
    "date": ("date", "transaction date", "value date", "completion time"),
    "reference": ("reference", "ref", "receipt no", "receipt no.", "transaction id", "receipt"),
    "description": ("description", "details", "narrative", "particulars", "transaction details"),
    "amount": ("amount",),
}


@dataclass(frozen=True)
class StatementItem:
    day: date
    reference: str
    description: str
    amount: Decimal             # + money in, - money out


@dataclass(frozen=True)
class LedgerItem:
    line_id: UUID
    day: date
    number: str
    description: str
    amount: Decimal             # debit less credit


@dataclass(frozen=True)
class Suggestion:
    item_index: int
    line_id: UUID
    reason: str


def normalise(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def parse_day(value: str) -> date:
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationFailed(f"'{value}' is not a date (use 2026-10-31 or 31/10/2026)")


def parse_amount(value: str, *, allow_zero: bool = False) -> Decimal:
    text = re.sub(r"(?i)kes|ksh|[\s,]", "", value.strip())
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    if not text and allow_zero:
        return Decimal(0)
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValidationFailed(f"'{value}' is not an amount") from None
    if not amount.is_finite() or abs(amount) > Decimal("1000000000") or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed(f"'{value}': an amount has at most 2 decimal places")
    amount = -abs(amount) if negative else amount
    if amount == 0 and not allow_zero:
        raise ValidationFailed(f"'{value}': an amount cannot be zero")
    return amount


def item(day: date, reference: str, description: str, amount: Decimal) -> StatementItem:
    if amount == 0:
        raise ValidationFailed("A line's amount cannot be zero")
    if len(reference) > 100 or len(description) > 300:
        raise ValidationFailed("A reference is at most 100 characters and a description at most 300")
    return StatementItem(day, reference.strip(), description.strip(), amount)


def parse_csv(content: str) -> list[StatementItem]:
    """A statement as comma-separated text. With a header row: `date`, `reference`, optional `description`, and either
    a signed `amount` or separate money-in (paid in, deposit) and money-out (withdrawn, paid out) columns. Without one:
    date, reference, description, amount."""
    if len(content) > 3_000_000:
        raise ValidationFailed("That statement is too large")
    rows = [r for r in csv.reader(io.StringIO(content.strip())) if any(c.strip() for c in r)]
    if not rows:
        raise ValidationFailed("The statement is empty")
    header = [c.strip().lower() for c in rows[0]]
    col = {name: next(header.index(a) for a in aliases if a in header)
           for name, aliases in ALIASES.items() if any(a in header for a in aliases)}
    named = "date" in col and ("amount" in col or any(h in IN_NAMES + OUT_NAMES for h in header))
    if named:
        rows = rows[1:]
    else:
        header = ["date", "reference", "description", "amount"]
        col = {name: i for i, name in enumerate(header)}
    if len(rows) > MAX_LINES:
        raise ValidationFailed(f"A statement has at most {MAX_LINES} lines")
    cin = next((header.index(h) for h in IN_NAMES if h in header), None)
    cout = next((header.index(h) for h in OUT_NAMES if h in header), None)
    items = []
    for number, row in enumerate(rows, start=1):
        def cell(index: int | None, row: list[str] = row) -> str:
            return row[index].strip() if index is not None and index < len(row) else ""

        try:
            if "amount" in col:
                amount = parse_amount(cell(col["amount"]))
            else:
                amount = parse_amount(cell(cin), allow_zero=True) - abs(parse_amount(cell(cout), allow_zero=True))
            items.append(item(parse_day(cell(col["date"])), cell(col.get("reference")), cell(col.get("description")),
                              amount))
        except ValidationFailed as error:
            raise ValidationFailed(f"Line {number}: {error.message}") from None
    return items


def suggest_matches(items: list[StatementItem], ledger: list[LedgerItem],
                    window_days: int = WINDOW_DAYS) -> list[Suggestion]:
    """Pair statement lines with uncleared ledger lines of the same amount, one to one. A line whose reference appears
    in the ledger line's number or description is taken first; the rest by the nearest date within a few days."""
    taken: set[UUID] = set()
    chosen: dict[int, Suggestion] = {}
    for stage in ("reference", "date"):
        for index, line in enumerate(items):
            if index in chosen:
                continue
            ref = normalise(line.reference)
            best: tuple[int, LedgerItem] | None = None
            for candidate in ledger:
                if candidate.line_id in taken or candidate.amount != line.amount:
                    continue
                gap = abs((candidate.day - line.day).days)
                if stage == "reference":
                    found = len(ref) >= 4 and ref in normalise(f"{candidate.number} {candidate.description}")
                    if not found:
                        continue
                elif gap > window_days:
                    continue
                if best is None or gap < best[0]:
                    best = (gap, candidate)
            if best is not None:
                taken.add(best[1].line_id)
                chosen[index] = Suggestion(index, best[1].line_id,
                                           "Same reference and amount" if stage == "reference"
                                           else f"Same amount, {best[0]} day(s) apart")
    return [chosen[i] for i in sorted(chosen)]


def difference(statement_balance: Decimal, cleared_balance: Decimal) -> Decimal:
    """What is still unexplained: the statement's balance less the cleared lines. Reconciled when it is zero."""
    return statement_balance - cleared_balance
