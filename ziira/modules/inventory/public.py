"""Public interface of the Inventory and Branches module.

Other units may import only from this file. They normally talk to Inventory through events
(`sale.posted`, `goods.received`, ...); these functions are for reading stock.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.repository import inventory_repo
from ziira.sdk import Session


def stock_on_hand(session: Session, product_id: UUID, *, location_id: UUID | None = None,
                  company_id: UUID | None = None) -> Decimal:
    """Quantity of a product (in its base unit) at a location, across a company's locations, or all."""
    return inventory_repo.on_hand(session, product_id, location_id, company_id)


def average_cost(session: Session, company_id: UUID, product_id: UUID) -> Decimal:
    """The company's current weighted average cost of a product (zero if it never had stock)."""
    cost = inventory_repo.get_cost(session, company_id, product_id)
    return cost.average_cost if cost else Decimal(0)


def posted_cost(session: Session, source_type: str, source_id: UUID) -> dict[UUID, Decimal]:
    """What the stock movements of a document cost, by the document's line id (for example the cost of goods
    sold of each line of a sale, available right after `sale.posted` was published). Lines that moved no stock
    are absent."""
    totals: dict[UUID, Decimal] = {}
    for movement in inventory_repo.movements_for_source(session, source_type, source_id):
        if movement.source_line_id is not None:
            totals[movement.source_line_id] = totals.get(movement.source_line_id, Decimal(0)) + abs(movement.value)
    return totals


def stock_value(session: Session, company_id: UUID) -> Decimal:
    """What the company's stock is worth now at weighted average cost (what its inventory accounts should show)."""
    return inventory_repo.stock_value(session, company_id)


def stock_value_as_of(session: Session, company_id: UUID, day: date) -> Decimal:
    """The value of the company's stock movements dated up to and including `day`."""
    return inventory_repo.stock_value_as_of(session, company_id, day)


@dataclass(frozen=True)
class MovementView:
    """A stock movement as other units may see it (for books that must catch up with the ledger)."""

    id: UUID
    seq: int
    company_id: UUID
    branch_id: UUID | None
    location_kind: str
    movement_type: str
    value: Decimal
    business_date: date


def movements_after(session: Session, after_seq: int = 0, limit: int = 500) -> list[MovementView]:
    """Stock movements after a movement number, oldest first."""
    return [MovementView(m.id, m.seq, m.company_id, m.branch_id, kind, m.movement_type, m.value, m.business_date)
            for m, kind in inventory_repo.movements_after(session, after_seq, limit)]
