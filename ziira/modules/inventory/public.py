"""Public interface of the Inventory and Branches module.

Other units may import only from this file. They normally talk to Inventory through events
(`sale.posted`, `goods.received`, ...); these functions are for reading stock.
"""

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
