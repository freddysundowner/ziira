"""Rules shared by stock documents (adjustments, transfers, counts). Pure Python: no database, no HTTP."""

from collections.abc import Sequence
from decimal import Decimal

from ziira.modules.inventory.domain.costing import round_value
from ziira.modules.inventory.domain.movements import check_quantity
from ziira.sdk import Conflict, ValidationFailed


def check_status(document: str, current: str, allowed: tuple[str, ...], action: str) -> None:
    """Raise Conflict unless the document is in a status that allows `action`."""
    if current not in allowed:
        raise Conflict(f"This {document} is {current.replace('_', ' ')}, so it cannot be {action}")


def check_adjustment_lines(lines: Sequence[tuple[object, object | None, Decimal]]) -> None:
    """Lines are (product, batch, quantity change): at least one, each non-zero, none repeated."""
    if not lines:
        raise ValidationFailed("Add at least one line")
    seen: set[tuple[object, object | None]] = set()
    for product, batch, change in lines:
        check_quantity(change)
        if (product, batch) in seen:
            raise ValidationFailed("Each product (and batch) can appear once")
        seen.add((product, batch))


def adjustment_amount(changes: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Size of an adjustment for the approval matrix: the sum of |quantity change| x average cost."""
    return round_value(sum((abs(quantity) * average for quantity, average in changes), Decimal(0)))
