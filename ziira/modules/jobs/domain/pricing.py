"""Prices on a job. Pure Python: no database, no HTTP.

Unit prices include tax, as everywhere in Ziira's selling screens. A line is worth quantity times price to the cent;
the tax inside it is worked out at the line's rate and rounded to the cent, the same way the invoice does, so the total
of a document is the sum of what its lines show.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """What a line is worth, tax included."""
    return cents(quantity * unit_price)


def tax_inside(total: Decimal, rate_percent: Decimal) -> Decimal:
    """The tax contained in a tax-inclusive amount at a percentage rate."""
    return cents(total * rate_percent / (HUNDRED + rate_percent))


@dataclass(frozen=True)
class Totals:
    total: Decimal
    tax: Decimal

    @property
    def net(self) -> Decimal:
        return self.total - self.tax


def add_up(lines: list[tuple[Decimal, Decimal]]) -> Totals:
    """Totals of (line total, tax inside) pairs."""
    return Totals(sum((t for t, _ in lines), Decimal(0)), sum((x for _, x in lines), Decimal(0)))


def warranty_end(collected_on: date, days: int) -> date | None:
    """The last day of the warranty, which starts the day the customer collects; None when there is none."""
    return collected_on + timedelta(days=days) if days > 0 else None


def in_warranty(ends: date | None, day: date) -> bool:
    return ends is not None and day <= ends
