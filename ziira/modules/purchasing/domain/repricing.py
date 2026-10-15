"""The arithmetic of putting a selling price right after a cost rise. Pure; money is Decimal."""

from decimal import ROUND_HALF_UP, Decimal

HUNDRED = Decimal(100)
CENT = Decimal("0.01")


def margin_percent(price_incl_tax: Decimal, vat_rate: Decimal, cost: Decimal) -> Decimal | None:
    """The margin on cost at a tax-inclusive price: (net price - cost) / net price, in percent. None when there is no
    price to speak of."""
    net = price_incl_tax / (1 + vat_rate / HUNDRED)
    if net <= 0:
        return None
    return (net - cost) / net * HUNDRED


def price_keeping_margin(price_incl_tax: Decimal, vat_rate: Decimal, earlier_cost: Decimal,
                         new_cost: Decimal) -> Decimal | None:
    """The tax-inclusive price (to the cent, half up) that gives `new_cost` the margin the current price gave
    `earlier_cost`. None when that margin is not between 0 and 100 percent (there is nothing to keep), or the result
    is no more than the current price (nothing to change)."""
    margin = margin_percent(price_incl_tax, vat_rate, earlier_cost)
    if margin is None or margin <= 0 or margin >= HUNDRED:
        return None
    net = new_cost / (1 - margin / HUNDRED)
    price = (net * (1 + vat_rate / HUNDRED)).quantize(CENT, rounding=ROUND_HALF_UP)
    return price if price > price_incl_tax else None
