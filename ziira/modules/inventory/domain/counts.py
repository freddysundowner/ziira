"""Rules for stock counts. Pure Python: no database, no HTTP."""

from dataclasses import dataclass
from decimal import Decimal

from ziira.modules.inventory.domain.costing import round_value
from ziira.modules.inventory.domain.movements import check_quantity
from ziira.sdk import ValidationFailed


def check_counted_quantity(counted: Decimal) -> Decimal:
    """A counted quantity is zero or positive, with at most 4 decimal places."""
    if not counted.is_finite():
        raise ValidationFailed("Quantity must be a number")
    if counted < 0:
        raise ValidationFailed("Counted quantity cannot be negative")
    if counted != 0:
        check_quantity(counted)
    return counted


def expected_when_counted(snapshot_qty: Decimal, moved_since_snapshot: Decimal) -> Decimal:
    """What the system held when the item was counted: the snapshot plus whatever moved before the count."""
    return snapshot_qty + moved_since_snapshot


def variance(counted: Decimal, expected_when_counted_qty: Decimal) -> Decimal:
    """Counted minus expected: negative is missing stock, positive is stock found."""
    return counted - expected_when_counted_qty


@dataclass(frozen=True)
class VarianceLine:
    variance: Decimal
    average_cost: Decimal
    has_reason: bool


def check_ready_to_submit(lines: list[VarianceLine]) -> None:
    """Every line that differs needs a reason."""
    missing = sum(1 for line in lines if line.variance != 0 and not line.has_reason)
    if missing:
        raise ValidationFailed(f"{missing} line(s) with a difference need a reason")


def variance_amount(lines: list[VarianceLine]) -> Decimal:
    """Size of the differences for the threshold and the approval matrix: sum of |variance| x average cost."""
    return round_value(sum((abs(line.variance) * line.average_cost for line in lines), Decimal(0)))
