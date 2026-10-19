"""Money arithmetic for claims. Pure Python: no database, no HTTP. Amounts include tax, as everywhere in Ziira's selling
screens; they are Decimal and always to the cent."""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """What a line is worth: quantity times price, to the cent."""
    return cents(quantity * unit_price)


def allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Share `total` (in cents) over `weights` in proportion, so the shares add up to exactly `total` (the largest
    remainders get the spare cents). No share is negative and none is above its weight when `total` is at most the sum
    of the weights."""
    if total < 0 or any(w < 0 for w in weights):
        raise ValueError("Cannot share a negative amount")
    if not weights:
        if total != 0:
            raise ValueError("Nothing to share the amount over")
        return []
    whole = sum(weights, ZERO)
    if whole == 0:
        if total != 0:
            raise ValueError("Nothing to share the amount over")
        return [ZERO for _ in weights]
    exact = [total * w / whole for w in weights]
    floors = [e.quantize(CENT, rounding=ROUND_FLOOR) for e in exact]
    spare = int(((total - sum(floors, ZERO)) / CENT).to_integral_value())
    order = sorted(range(len(weights)), key=lambda i: (exact[i] - floors[i], weights[i]), reverse=True)
    out = list(floors)
    for i in order[:spare]:
        out[i] += CENT
    return out
