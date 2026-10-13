"""Business rules of a sale. Pure Python: no database, no HTTP.

Prices include VAT. A line's money is worked out from what the customer pays, and the VAT in it is taken out:

    gross = quantity x unit price - discount        (what the customer pays for the line)
    tax   = gross x rate / (100 + rate)             (the VAT inside it, rounded half up to the cent)
    net   = gross - tax
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ziira.sdk import ValidationFailed

CENT = Decimal("0.01")
MAX_LINES = 200
MAX_QUANTITY = Decimal("1000000")
MAX_PRICE = Decimal("100000000")
SALE_METHODS = ("cash", "mpesa", "card", "other")     # "credit" arrives with customer accounts (phase 6)
NUMBER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-]{2,59}$")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineAmounts:
    """The money of one sale line."""

    before_discount: Decimal
    discount: Decimal
    gross: Decimal
    tax: Decimal

    @property
    def net(self) -> Decimal:
        return self.gross - self.tax


def check_quantity(quantity: Decimal) -> Decimal:
    if quantity <= 0 or quantity > MAX_QUANTITY or quantity != quantity.quantize(Decimal("0.0001")):
        raise ValidationFailed("A quantity is more than zero with at most 4 decimal places")
    return quantity


def check_price(price: Decimal, label: str = "A price") -> Decimal:
    if price < 0 or price > MAX_PRICE or price != price.quantize(CENT):
        raise ValidationFailed(f"{label} is zero or more with at most 2 decimal places")
    return price


def price_line(quantity: Decimal, unit_price: Decimal, discount: Decimal, vat_rate: Decimal) -> LineAmounts:
    """Work out one line from its (tax-inclusive) unit price and the discount given on the whole line."""
    check_quantity(quantity)
    check_price(unit_price)
    check_price(discount, "A discount")
    before = cents(quantity * unit_price)
    if discount > before:
        raise ValidationFailed("A discount cannot be more than the line is worth")
    gross = before - discount
    tax = cents(gross * vat_rate / (Decimal(100) + vat_rate))
    return LineAmounts(before, discount, gross, tax)


@dataclass(frozen=True)
class PaymentLeg:
    """One way the customer paid: `amount` is what was applied to the sale; `change` was given back (cash only)."""

    method: str
    amount: Decimal
    change: Decimal = Decimal(0)


def settle(total: Decimal, offered: list[tuple[str, Decimal]]) -> list[PaymentLeg]:
    """Turn what the customer handed over into payments that add up to the total. Only cash can be more than is due
    (the rest is change); every other method must be at most what is still owed."""
    if total <= 0:
        raise ValidationFailed("A sale must be worth more than nothing")
    if not offered:
        raise ValidationFailed("Say how the sale was paid")
    legs: list[PaymentLeg] = []
    owed = total
    for method, amount in offered:
        if method not in SALE_METHODS:
            raise ValidationFailed(f"Payment method must be one of: {', '.join(SALE_METHODS)}")
        if amount <= 0 or amount != amount.quantize(CENT):
            raise ValidationFailed("Each payment is an amount of more than zero with at most 2 decimal places")
    # cash goes last so that it alone absorbs any overpayment as change
    for method, amount in sorted(offered, key=lambda x: x[0] == "cash"):
        if method == "cash":
            applied = min(amount, owed)
            legs.append(PaymentLeg(method, applied, amount - applied))
            owed -= applied
        else:
            if amount > owed:
                raise ValidationFailed(f"The {method} payment is more than is still owed ({owed})")
            legs.append(PaymentLeg(method, amount))
            owed -= amount
    if owed != 0:
        raise ValidationFailed(f"The payments are {owed} short of the total {total}")
    return legs


def return_amounts(line_total: Decimal, line_tax: Decimal, sold: Decimal, returned_before: Decimal,
                   returning: Decimal) -> tuple[Decimal, Decimal]:
    """(gross, tax) to give back for `returning` units of a line. Worked out on the running total of units returned,
    so that returning a line in several parts gives back exactly what it was sold for."""
    if returning <= 0:
        raise ValidationFailed("Return at least some of the line")
    if returned_before + returning > sold:
        raise ValidationFailed(f"Only {sold - returned_before} of this line can still be returned")

    def share(value: Decimal, units: Decimal) -> Decimal:
        return cents(value * units / sold)

    after = returned_before + returning
    return (share(line_total, after) - share(line_total, returned_before),
            share(line_tax, after) - share(line_tax, returned_before))


def till_expected_cash(opening_float: Decimal, cash_in_session: Decimal) -> Decimal:
    """What the drawer should hold: the float plus cash taken less cash paid out."""
    return opening_float + cash_in_session


def device_prefix(branch_code: str, device_code: str) -> str:
    return f"POS-{branch_code}-{device_code}"


def check_offline_number(number: str, prefix: str) -> str:
    """Offline sales are numbered by the device: '<prefix>-L<digits>'. The L keeps them apart from numbers the server
    hands out, so the two can never collide."""
    value = number.strip().upper()
    if not NUMBER_PATTERN.match(value) or not re.fullmatch(re.escape(prefix) + r"-L\d{1,9}", value):
        raise ValidationFailed(f"An offline sale number looks like {prefix}-L000123")
    return value


def server_number(prefix: str, sequence: int) -> str:
    return f"{prefix}-{sequence:06d}"
