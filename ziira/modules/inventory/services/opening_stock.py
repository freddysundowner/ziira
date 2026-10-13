"""Use case: record opening stock when a business starts using Ziira."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from ziira.modules.inventory.domain import movements
from ziira.modules.inventory.permissions import STOCK_ADJUST
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import StockMovement
from ziira.modules.inventory.services.ledger import MovementRequest, get_or_create_batch, post_movement
from ziira.modules.products.public import find_product
from ziira.sdk import Conflict, Session, ValidationFailed, audit_record, check_company, current_context


@dataclass(frozen=True)
class OpeningLine:
    """Stock a product already had at the location when the business started."""

    product_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    batch_no: str | None = None
    expiry_date: date | None = None


def post_opening_stock(session: Session, *, company_id: UUID, location_id: UUID, lines: list[OpeningLine],
                       business_date: date | None = None) -> list[StockMovement]:
    """Post opening stock for a location: one `opening` movement per line, all in one transaction.

    Only for a product that has no stock history at the location; later corrections are adjustments,
    which need a reason. Needs 'stock.adjust' for the location's branch.
    """
    if not lines:
        raise ValidationFailed("Add at least one line")
    check_company(session, company_id)
    location = inventory_repo.get_location(session, location_id)
    if location is None or location.company_id != company_id:
        raise ValidationFailed("Location not found in this company")
    current_context().require(STOCK_ADJUST, company_id=company_id, branch_id=location.branch_id)
    if len({(line.product_id, line.batch_no) for line in lines}) != len(lines):
        raise ValidationFailed("Each product (and batch) can appear once")

    for line in lines:
        movements.check_movement("opening", line.quantity, unit_cost=line.unit_cost)
    for product_id in {line.product_id for line in lines}:
        product = find_product(session, product_id)
        if product is None or product.company_id != company_id:
            raise ValidationFailed("Product not found in this company")
        if inventory_repo.has_movements(session, location_id, product_id):
            raise Conflict(f"{product.sku} already has stock history at {location.code}; use an adjustment")

    source_id = uuid4()
    posted: list[StockMovement] = []
    for line in sorted(lines, key=lambda x: str(x.product_id)):          # same lock order everywhere
        product = find_product(session, line.product_id)
        assert product is not None
        batch_id = None
        if product.is_batch_tracked:
            if not line.batch_no:
                raise ValidationFailed(f"{product.sku} is batch-tracked: give a batch number")
            batch_id = get_or_create_batch(session, product, line.batch_no, line.expiry_date).id
        elif line.batch_no:
            raise ValidationFailed(f"{product.sku} is not batch-tracked")
        posted.append(post_movement(session, MovementRequest(
            company_id=company_id, location_id=location_id, product_id=product.id, quantity=line.quantity,
            movement_type="opening", source_type="opening_stock", source_id=source_id, batch_id=batch_id,
            unit_cost=line.unit_cost, business_date=business_date)))
    audit_record(session, "post", "inventory.opening_stock", source_id,
                 {"location_id": location_id, "lines": len(posted),
                  "value": sum((m.value for m in posted), Decimal(0))})
    return posted
