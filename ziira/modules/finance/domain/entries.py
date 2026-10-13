"""Rules for journal entries. Pure Python: no database, no HTTP.

An entry is a list of lines, each a debit or a credit of an amount to an account. Total debits must equal
total credits (the database enforces it too, at commit).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.sdk import ValidationFailed

ZERO = Decimal("0")
MONEY = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")          # numeric(18,2)

# The side an account normally increases on.
DEBIT_NORMAL = frozenset({"asset", "expense"})
ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")


@dataclass(frozen=True)
class Line:
    """One line of an entry: a debit or a credit (exactly one is positive)."""

    account_id: UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    branch_id: UUID | None = None
    party_type: str | None = None
    party_id: UUID | None = None
    description: str | None = None

    @property
    def amount(self) -> Decimal:
        return self.debit or self.credit


def check_amount(value: Decimal, what: str = "Amount") -> Decimal:
    """A money amount: a finite number with at most 2 decimal places that fits the column."""
    if not value.is_finite():
        raise ValidationFailed(f"{what} must be a number")
    if abs(value) > MAX_AMOUNT:
        raise ValidationFailed(f"{what} is too large")
    if value != value.quantize(MONEY):
        raise ValidationFailed(f"{what} can have at most 2 decimal places")
    return value


def check_lines(lines: Sequence[Line]) -> tuple[Decimal, Decimal]:
    """Check an entry's lines and return (total debit, total credit). Raises ValidationFailed."""
    if len(lines) < 2:
        raise ValidationFailed("An entry needs at least two lines")
    total_debit = total_credit = ZERO
    for line in lines:
        check_amount(line.debit, "Debit")
        check_amount(line.credit, "Credit")
        if line.debit < 0 or line.credit < 0:
            raise ValidationFailed("Debits and credits cannot be negative")
        if (line.debit == 0) == (line.credit == 0):
            raise ValidationFailed("Each line is either a debit or a credit of a positive amount")
        total_debit += line.debit
        total_credit += line.credit
    if total_debit != total_credit:
        raise ValidationFailed(f"The entry does not balance: debits {total_debit}, credits {total_credit}")
    return total_debit, total_credit


def mirror(lines: Sequence[Line]) -> list[Line]:
    """The reversing lines of an entry: every debit becomes a credit and the other way round."""
    return [Line(account_id=x.account_id, debit=x.credit, credit=x.debit, branch_id=x.branch_id,
                 party_type=x.party_type, party_id=x.party_id, description=x.description) for x in lines]


def natural_balance(account_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    """The balance as the account normally shows it: positive on its own side (assets and expenses on the debit
    side, everything else on the credit side)."""
    return debit - credit if account_type in DEBIT_NORMAL else credit - debit
