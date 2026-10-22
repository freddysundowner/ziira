"""Use case: what a till can sell - products with their prices and stock. The same list, paged, is the snapshot an
offline device downloads before it goes offline. `barcode` keeps only the product with that scanned code."""

import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.inventory.public import stock_at_location
from ziira.modules.pos.permissions import SALES_SELL
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.services import tills
from ziira.modules.products.public import sellable_products, selling_prices
from ziira.sdk import NotFound, Session, company_setting, current_context

# Product fields (a business's own, from Products > custom fields) that make the till ask for a reference note.
REFERENCE_FIELDS = ("prescription_required", "controlled")


def flagged_for_reference(session: Session, product_ids: set[UUID]) -> set[UUID]:
    """Which of these products are marked (yes) in any of the REFERENCE_FIELDS custom fields."""
    if not product_ids:
        return set()
    any_flag = " or ".join(f"data @> cast(:f{n} as jsonb)" for n, _ in enumerate(REFERENCE_FIELDS))
    params: dict[str, object] = {"ids": [str(i) for i in product_ids]}
    params.update({f"f{n}": json.dumps({key: True}) for n, key in enumerate(REFERENCE_FIELDS)})
    rows = session.execute(text(
        "select entity_id from kernel.custom_field_value where entity_type = 'products.product' "
        f"and entity_id = any(cast(:ids as uuid[])) and ({any_flag})"), params)
    return {r.entity_id for r in rows}


def catalog(session: Session, branch_id: UUID, *, location_id: UUID | None = None, search: str | None = None,
            limit: int = 100, offset: int = 0, day: date | None = None,
            barcode: str | None = None) -> list[dict[str, object]]:
    """Active products with their tax-inclusive price at the branch today and the stock at `location_id` (if given).
    Needs 'sales.sell' at the branch."""
    company_id = pos_repo.branch_company(session, branch_id)
    if company_id is None or not current_context().can(SALES_SELL, company_id=company_id, branch_id=branch_id):
        raise NotFound("Branch not found")
    if location_id is not None:
        found = pos_repo.location_branch(session, location_id)
        if found is None or found[0] != company_id:
            raise NotFound("Location not found")
    products = sellable_products(session, company_id, search, limit, offset, barcode)
    ids = {p.id for p in products}
    prices = selling_prices(session, company_id, branch_id, ids, day or tills.today(session, company_id))
    stock = stock_at_location(session, location_id, ids) if location_id is not None else {}
    mode = str(company_setting(session, company_id, "sale_reference_prompt"))
    flagged = flagged_for_reference(session, ids) if mode != "off" else set()
    return [{
        "product_id": p.id, "sku": p.sku, "name": p.name, "product_type": p.product_type, "vat_rate": p.vat_rate,
        "is_batch_tracked": p.is_batch_tracked, "barcodes": list(p.barcodes), "uom_id": p.base_uom_id,
        "price": prices.get(p.id), "reference_prompt": mode if p.id in flagged else "off",
        "stock": stock.get(p.id, Decimal(0)) if location_id is not None and p.product_type == "stock" else None,
    } for p in products]
