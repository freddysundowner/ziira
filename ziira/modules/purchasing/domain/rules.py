"""Business rules of purchasing. Pure Python: no database, no HTTP.

Costs are tax-exclusive; VAT is added on top at the tax code's rate (the opposite of selling prices, which include it).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ziira.sdk import ValidationFailed

CENT = Decimal("0.01")
MAX_COST = Decimal("100000000")
MAX_QUANTITY = Decimal("10000000")
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-_.]{0,19}$")
TAX_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9/\-. ]{2,29}$")
INVOICE_NO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-_./]{0,59}$")
AGEING_BUCKETS = ("not_due", "1_30", "31_60", "61_90", "over_90")
CONFIRMATION_METHODS = ("phone_callback", "in_person", "signed_letter")


def plain(value: Decimal) -> str:
    """A number without trailing zeros, for messages: 6.0000 -> 6, 2.50 -> 2.5."""
    return f"{value.normalize():f}"


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def normalise_code(code: str) -> str:
    value = code.strip().upper()
    if not CODE_PATTERN.match(value):
        raise ValidationFailed("A supplier code is 1-20 letters, digits, '-', '_' or '.', for example TOTAL01")
    return value


def check_name(name: str, label: str = "Name") -> str:
    value = " ".join(name.split())
    if not value or len(value) > 200:
        raise ValidationFailed(f"{label} is required (up to 200 characters)")
    return value


def check_tax_id(number: str | None) -> str | None:
    """A tax number as the tax authority writes it: 3 to 30 letters, digits, '-', '/' or '.'; None when empty."""
    if number is None or not number.strip():
        return None
    value = " ".join(number.strip().upper().split())
    if not TAX_ID_PATTERN.match(value):
        raise ValidationFailed("A tax number is 3 to 30 letters, digits, '-', '/' or '.'")
    return value


def check_terms(days: int) -> int:
    if days < 0 or days > 365:
        raise ValidationFailed("Payment terms are between 0 and 365 days")
    return days


def check_invoice_no(number: str) -> str:
    value = number.strip()
    if not INVOICE_NO_PATTERN.match(value):
        raise ValidationFailed("The supplier's invoice number is required (letters, digits, spaces and - _ . /)")
    return value


def check_quantity(quantity: Decimal) -> Decimal:
    if quantity <= 0 or quantity > MAX_QUANTITY or quantity != quantity.quantize(Decimal("0.0001")):
        raise ValidationFailed("A quantity is more than zero with at most 4 decimal places")
    return quantity


def check_cost(cost: Decimal, label: str = "A cost") -> Decimal:
    if cost < 0 or cost > MAX_COST or cost != cost.quantize(Decimal("0.000001")):
        raise ValidationFailed(f"{label} is zero or more with at most 6 decimal places")
    return cost


@dataclass(frozen=True)
class Amounts:
    net: Decimal
    tax: Decimal

    @property
    def gross(self) -> Decimal:
        return self.net + self.tax


def line_amounts(quantity: Decimal, unit_cost: Decimal, vat_rate: Decimal) -> Amounts:
    """A line's cost before VAT (to the cent), and the VAT on it."""
    check_quantity(quantity)
    check_cost(unit_cost)
    net = cents(quantity * unit_cost)
    return Amounts(net, cents(net * vat_rate / Decimal(100)))


def order_status(lines: list[tuple[Decimal, Decimal]], current: str) -> str:
    """Status of an order after receipts, from (ordered, received) of each line. An order that is cancelled or
    closed stays so."""
    if current in ("cancelled", "closed"):
        return current
    received = [r for _, r in lines]
    if lines and all(r >= q for q, r in lines):
        return "received"
    return "part_received" if any(r > 0 for r in received) else current


def check_receipt_quantity(ordered: Decimal, received: Decimal, receiving: Decimal) -> None:
    if received + receiving > ordered:
        raise ValidationFailed(f"Only {plain(ordered - received)} more can be received on this line (ordered "
                               f"{plain(ordered)}, received {plain(received)})")


def cost_difference_percent(billed: Decimal, expected: Decimal) -> Decimal:
    """How far a billed unit cost is from the expected one, as a percentage of the expected cost."""
    if expected == 0:
        return Decimal(0) if billed == 0 else Decimal(100)
    return abs(billed - expected) / expected * 100


def match_problems(*, label: str, billed_qty: Decimal, billed_cost: Decimal, received_qty: Decimal,
                   already_billed: Decimal, received_cost: Decimal, ordered_cost: Decimal | None,
                   tolerance_percent: Decimal) -> list[str]:
    """What is wrong with one bill line for received goods (the three-way match: order, receipt, bill)."""
    problems: list[str] = []
    if already_billed + billed_qty > received_qty:
        problems.append(f"{label}: billing {plain(billed_qty)} but only {plain(received_qty - already_billed)} of the "
                        f"{plain(received_qty)} received is still unbilled")
    expected = ordered_cost if ordered_cost is not None else received_cost
    gap = cost_difference_percent(billed_cost, expected)
    if gap > tolerance_percent:
        problems.append(f"{label}: cost per unit {plain(billed_cost)} is {gap.quantize(CENT)}% away from "
                        f"{'the order' if ordered_cost is not None else 'the receipt'} ({plain(expected)}); the limit "
                        f"is {plain(tolerance_percent)}%")
    return problems


def ageing_bucket(due: date, as_of: date) -> str:
    late = (as_of - due).days
    if late <= 0:
        return "not_due"
    return "1_30" if late <= 30 else "31_60" if late <= 60 else "61_90" if late <= 90 else "over_90"


def mask_account(number: str) -> str:
    digits = re.sub(r"\s", "", number)
    return "*" * max(len(digits) - 4, 0) + digits[-4:]


def check_account_number(method: str, number: str) -> str:
    value = re.sub(r"[\s-]", "", number)
    if method == "mobile_money":
        if not re.fullmatch(r"\+?\d{8,15}", value):
            raise ValidationFailed("A mobile money number is 8 to 15 digits (start with + if it is international)")
        return value
    if not re.fullmatch(r"[A-Za-z0-9]{5,30}", value):
        raise ValidationFailed("A bank account number is 5-30 letters or digits")
    return value


def refundable(total: Decimal, paid: Decimal, credited: Decimal, refunded: Decimal) -> Decimal:
    """What the supplier still owes back on a bill: paid and credited beyond its worth, less what has come back."""
    return max(paid + credited - total - refunded, Decimal(0))
