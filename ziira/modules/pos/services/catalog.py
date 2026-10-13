"""Use case: what a till can sell - products with their prices and stock. The same list, paged, is the snapshot an
offline device downloads before it goes offline."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.public import stock_at_location
from ziira.modules.pos.permissions import SALES_SELL
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.services import tills
from ziira.modules.products.public import sellable_products, selling_prices
from ziira.sdk import NotFound, Session, current_context


def catalog(session: Session, branch_id: UUID, *, location_id: UUID | None = None, search: str | None = None,
            limit: int = 100, offset: int = 0, day: date | None = None) -> list[dict[str, object]]:
    """Active products with their tax-inclusive price at the branch today and the stock at `location_id` (if given).
    Needs 'sales.sell' at the branch."""
    company_id = pos_repo.branch_company(session, branch_id)
    if company_id is None or not current_context().can(SALES_SELL, company_id=company_id, branch_id=branch_id):
        raise NotFound("Branch not found")
    if location_id is not None:
        found = pos_repo.location_branch(session, location_id)
        if found is None or found[0] != company_id:
            raise NotFound("Location not found")
    products = sellable_products(session, company_id, search, limit, offset)
    ids = {p.id for p in products}
    prices = selling_prices(session, company_id, branch_id, ids, day or tills.today())
    stock = stock_at_location(session, location_id, ids) if location_id is not None else {}
    return [{
        "product_id": p.id, "sku": p.sku, "name": p.name, "product_type": p.product_type, "vat_rate": p.vat_rate,
        "is_batch_tracked": p.is_batch_tracked, "uom_id": p.base_uom_id, "price": prices.get(p.id),
        "stock": stock.get(p.id, Decimal(0)) if location_id is not None and p.product_type == "stock" else None,
    } for p in products]
