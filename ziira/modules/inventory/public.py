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
