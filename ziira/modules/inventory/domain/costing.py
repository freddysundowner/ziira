"""Weighted average costing per company and product. Pure Python: no database, no HTTP.

The company keeps one running figure per product: quantity, value and average cost.

- A receipt (or opening stock, a customer's return, a transfer arriving) adds quantity and value
  and the average becomes (existing value + receipt value) / (existing quantity + receipt quantity).
- Anything leaving takes the current average. Whatever leaves is worth quantity x average, and the
  value goes to cost of goods sold (or to shrinkage for write-offs).
- Moves between two locations of the same company do not change the company's figure.

Negative stock: when more has gone out than came in, the quantity is below zero and the value too,
at the last average. The next receipt uses the same formula on the net quantities, so the cost of
the units that were sold before they arrived is corrected through the new average. If a receipt
leaves the quantity at or below zero, the old average is kept. A small value can remain at zero
quantity until the next receipt; the invariant "value = sum of movement values" always holds.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ziira.modules.inventory.domain.movements import INTERNAL_TRANSFER

ZERO = Decimal("0")
COST_PLACES = Decimal("0.000001")
MONEY_PLACES = Decimal("0.01")


def round_cost(value: Decimal) -> Decimal:
    """Unit costs keep 6 decimal places (the database precision)."""
    return value.quantize(COST_PLACES, rounding=ROUND_HALF_UP)


def round_value(value: Decimal) -> Decimal:
    """Values are money: 2 decimal places, half up."""
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostState:
    """A company's running figure for one product."""

    quantity: Decimal = ZERO
    value: Decimal = ZERO
    average_cost: Decimal = ZERO


@dataclass(frozen=True)
class CostedMovement:
    """What a movement is worth, and the company's figure after it."""

    unit_cost: Decimal
    value: Decimal          # signed like the quantity: + in, - out
    state: CostState


def cost_movement(state: CostState, movement_type: str, quantity: Decimal,
                  unit_cost: Decimal | None = None) -> CostedMovement:
    """Cost one movement against the company's figure.

    Inbound movements use `unit_cost` when given (receipts, opening stock, transfers arriving, a
    customer's return at its original cost) and the current average otherwise (stock found in a
    count or adjustment). Outbound movements take the current average, except a transfer leaving
    the in-transit location, which carries the cost it had when it was dispatched.
    """
    if quantity == 0:
        raise ValueError("A movement has a non-zero quantity")
    if quantity > 0 or (movement_type in INTERNAL_TRANSFER and unit_cost is not None):
        cost = round_cost(unit_cost if unit_cost is not None else state.average_cost)
        value = round_value(quantity * cost)
    else:
        cost = state.average_cost
        # Taking out everything there is takes out all the value, so no rounding crumbs remain.
        value = -state.value if state.quantity + quantity == 0 else round_value(quantity * cost)

    if movement_type in INTERNAL_TRANSFER:
        return CostedMovement(cost, value, state)          # same company: its figure is unchanged

    new_quantity = state.quantity + quantity
    new_value = state.value + value
    average = round_cost(new_value / new_quantity) if quantity > 0 and new_quantity > 0 else state.average_cost
    return CostedMovement(cost, value, CostState(new_quantity, new_value, average))


def rebuild(movements: list[tuple[str, Decimal, Decimal]]) -> CostState:
    """The figure implied by a history of (movement_type, quantity, value), in order.

    Quantity and value are plain sums; the average is recomputed the same way costing does. Used by
    the nightly check to compare against the stored figure.
    """
    state = CostState()
    for movement_type, quantity, value in movements:
        if movement_type in INTERNAL_TRANSFER:
            continue
        new_quantity, new_value = state.quantity + quantity, state.value + value
        average = round_cost(new_value / new_quantity) if quantity > 0 and new_quantity > 0 else state.average_cost
        state = CostState(new_quantity, new_value, average)
    return state


def spread_landed_cost(lines: list[tuple[Decimal, Decimal]], landed_cost: Decimal) -> list[Decimal]:
    """Unit costs of a receipt's lines with transport, duty and similar costs spread over them.

    `lines` are (quantity, unit cost) as invoiced; the landed cost is shared in proportion to each line's value,
    the last line taking the rounding remainder so the shares add up exactly. Returns the landed unit cost of
    each line, to be averaged into stock like any receipt.
    """
    if landed_cost < 0:
        raise ValueError("Landed cost cannot be negative")
    values = [round_value(quantity * unit_cost) for quantity, unit_cost in lines]
    total = sum(values, Decimal(0))
    if landed_cost == 0 or not lines:
        return [round_cost(unit_cost) for _, unit_cost in lines]
    if total == 0:                                    # nothing to weigh by: share by quantity
        weights = [quantity for quantity, _ in lines]
        total = sum(weights, Decimal(0))
    else:
        weights = values
    result: list[Decimal] = []
    allocated = Decimal(0)
    for index, ((quantity, unit_cost), weight) in enumerate(zip(lines, weights, strict=True)):
        share = (landed_cost - allocated if index == len(lines) - 1
                 else round_value(landed_cost * weight / total))
        allocated += share
        result.append(round_cost(unit_cost + share / quantity))
    return result
