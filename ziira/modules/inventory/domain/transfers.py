"""Rules for transfers between locations. Pure Python: no database, no HTTP."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.domain.costing import round_value
from ziira.modules.inventory.domain.movements import check_quantity
from ziira.sdk import ValidationFailed


def check_transfer_locations(from_id: UUID, to_id: UUID, from_kind: str, to_kind: str) -> None:
    """Stock moves between two different places where it is actually kept."""
    if from_id == to_id:
        raise ValidationFailed("A transfer needs two different locations")
    if "transit" in (from_kind, to_kind):
        raise ValidationFailed("The in-transit location is used by the system; choose stores or warehouses")


def check_transfer_lines(lines: list[tuple[UUID, UUID | None, Decimal]]) -> None:
    """Lines are (product, batch, quantity): at least one, each positive, none repeated."""
    if not lines:
        raise ValidationFailed("Add at least one line")
    seen: set[tuple[UUID, UUID | None]] = set()
    for product, batch, quantity in lines:
        check_quantity(quantity)
        if quantity < 0:
            raise ValidationFailed("Quantities to transfer must be positive")
        if (product, batch) in seen:
            raise ValidationFailed("Each product (and batch) can appear once")
        seen.add((product, batch))


@dataclass(frozen=True)
class Receipt:
    """What arrived for one line, compared with what was sent."""

    qty_sent: Decimal
    qty_received: Decimal

    @property
    def difference(self) -> Decimal:
        """Negative: some did not arrive. Positive: more arrived than was sent."""
        return self.qty_received - self.qty_sent


def check_received_quantity(qty_received: Decimal) -> None:
    """Received quantities are zero (nothing arrived) or positive, with at most 4 decimal places."""
    if qty_received < 0:
        raise ValidationFailed("Received quantity cannot be negative")
    if qty_received != 0:
        check_quantity(qty_received)


def variance_value(differences: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Size of the differences for the approval matrix: the sum of |difference| x dispatch cost."""
    return round_value(sum((abs(difference) * cost for difference, cost in differences), Decimal(0)))
