"""Stock changes caused by other units' documents, received as events inside the publisher's transaction.

Inventory never imports POS or Purchasing: they publish these events and Inventory posts the movements. If
anything fails (no stock, bad product), the publisher's whole operation rolls back, so a sale and its stock
change always stand or fall together. An event for a document that already has movements is refused.

Event contracts (payload keys; ids may be UUIDs or strings, quantities Decimals or strings):

  sale.posted        aggregate = the sale
      company_id, location_id (or branch_id, when the branch has exactly one store), business_date,
      offline (optional, true for sales recorded offline: always accepted),
      lines: [{line_id, product_id, quantity, batch_id (optional: cashier's choice, else first expiry first out)}]

  sale.returned      aggregate = the return
      company_id, location_id (or branch_id), business_date, sale_id,
      lines: [{line_id, product_id, quantity, sale_line_id (optional: returns at the sale's cost),
               batch_id (optional: defaults to the sale's batch)}]

  goods.received     aggregate = the goods receipt
      company_id, location_id, business_date, landed_cost (optional: transport, duty; spread over the lines),
      lines: [{line_id, product_id, quantity, unit_cost, batch_no and expiry_date (batch-tracked products)}]

Lines for services and non-stock products are ignored. Quantities are in the product's base unit.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from ziira.modules.inventory.domain.costing import spread_landed_cost
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import Location
from ziira.modules.inventory.services.ledger import (
    MovementRequest,
    get_or_create_batch,
    post_movement,
    post_stock_out,
)
from ziira.modules.products.public import ProductView, find_product
from ziira.sdk import Conflict, Event, Session, ValidationFailed


# --------------------------------------------------------------------------- reading the payload
def _uuid(value: Any, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        raise ValidationFailed(f"'{name}' is not a valid id") from None


def _decimal(value: Any, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValidationFailed(f"'{name}' is not a number") from None
    if not number.is_finite():
        raise ValidationFailed(f"'{name}' is not a number")
    return number


def _date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValidationFailed("'business_date' is not a date") from None


def _lines(event: Event) -> list[dict[str, Any]]:
    lines = event.payload.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValidationFailed(f"{event.type}: no lines")
    return lines


def _location(session: Session, event: Event, company_id: UUID) -> Location:
    payload = event.payload
    if payload.get("location_id"):
        location = inventory_repo.get_location(session, _uuid(payload["location_id"], "location_id"))
    elif payload.get("branch_id"):
        location = inventory_repo.single_store(session, company_id, _uuid(payload["branch_id"], "branch_id"))
        if location is None:
            raise ValidationFailed(f"{event.type}: the branch has no single store to take stock from; "
                                   "name a location_id")
    else:
        raise ValidationFailed(f"{event.type}: a location_id is required")
    if location is None or location.company_id != company_id:
        raise ValidationFailed(f"{event.type}: location not found in this company")
    return location


@dataclass(frozen=True)
class _Line:
    raw: dict[str, Any]
    product: ProductView
    id: UUID
    quantity: Decimal


def _stock_lines(session: Session, event: Event, company_id: UUID) -> list[_Line]:
    """The event's lines for stock products, in a fixed order (so concurrent documents lock in the same order)."""
    found = []
    for raw in _lines(event):
        product = find_product(session, _uuid(raw.get("product_id"), "product_id"))
        if product is None or product.company_id != company_id:
            raise ValidationFailed(f"{event.type}: product not found in this company")
        if product.product_type != "stock":
            continue
        quantity = _decimal(raw.get("quantity"), "quantity")
        if quantity <= 0:
            raise ValidationFailed(f"{event.type}: quantities are positive")
        found.append(_Line(raw, product, _uuid(raw.get("line_id"), "line_id"), quantity))
    return sorted(found, key=lambda x: (str(x.product.id), str(x.id)))


def _refuse_repeat(session: Session, source_type: str, event: Event) -> None:
    if inventory_repo.source_has_movements(session, source_type, event.aggregate_id):
        raise Conflict(f"Stock was already posted for this {source_type.replace('_', ' ')}")


# --------------------------------------------------------------------------- the handlers
def post_sale(session: Session, event: Event) -> None:
    """`sale.posted`: take the sold stock out of the location (first expiry first out for batch-tracked products)."""
    company_id = _uuid(event.payload.get("company_id"), "company_id")
    location = _location(session, event, company_id)
    _refuse_repeat(session, "sale", event)
    business_date = _date(event.payload.get("business_date"))
    for line in _stock_lines(session, event, company_id):
        batch = line.raw.get("batch_id")
        post_stock_out(session, MovementRequest(
            company_id=company_id, location_id=location.id, product_id=line.product.id, quantity=-line.quantity,
            movement_type="sale", source_type="sale", source_id=event.aggregate_id, source_line_id=line.id,
            batch_id=_uuid(batch, "batch_id") if batch else None, business_date=business_date,
            allow_negative=True if event.payload.get("offline") else None))


def post_sale_return(session: Session, event: Event) -> None:
    """`sale.returned`: put returned stock back, at the cost the sale took it out at."""
    company_id = _uuid(event.payload.get("company_id"), "company_id")
    location = _location(session, event, company_id)
    _refuse_repeat(session, "sale_return", event)
    business_date = _date(event.payload.get("business_date"))
    sale_id = _uuid(event.payload.get("sale_id"), "sale_id") if event.payload.get("sale_id") else None
    for line in _stock_lines(session, event, company_id):
        original = None
        if sale_id and line.raw.get("sale_line_id"):
            original = inventory_repo.sale_movement(session, sale_id, _uuid(line.raw["sale_line_id"], "sale_line_id"))
        batch = _uuid(line.raw["batch_id"], "batch_id") if line.raw.get("batch_id") else (
            original.batch_id if original else None)
        post_movement(session, MovementRequest(
            company_id=company_id, location_id=location.id, product_id=line.product.id, quantity=line.quantity,
            movement_type="sale_return", source_type="sale_return", source_id=event.aggregate_id,
            source_line_id=line.id, batch_id=batch, unit_cost=original.unit_cost if original else None,
            business_date=business_date))


def post_goods_receipt(session: Session, event: Event) -> None:
    """`goods.received`: add the received stock at its cost, with any landed cost spread over the lines."""
    company_id = _uuid(event.payload.get("company_id"), "company_id")
    location = _location(session, event, company_id)
    _refuse_repeat(session, "goods_receipt", event)
    business_date = _date(event.payload.get("business_date"))
    lines = _stock_lines(session, event, company_id)
    costs = [_decimal(x.raw.get("unit_cost"), "unit_cost") for x in lines]
    if any(cost < 0 for cost in costs):
        raise ValidationFailed("goods.received: unit costs cannot be negative")
    landed = _decimal(event.payload.get("landed_cost", 0), "landed_cost")
    if landed < 0:
        raise ValidationFailed("goods.received: landed cost cannot be negative")
    unit_costs = spread_landed_cost([(x.quantity, cost) for x, cost in zip(lines, costs, strict=True)], landed)
    for line, unit_cost in zip(lines, unit_costs, strict=True):
        batch_id = None
        if line.product.is_batch_tracked:
            if not line.raw.get("batch_no"):
                raise ValidationFailed(f"goods.received: {line.product.sku} is batch-tracked, give a batch_no")
            batch_id = get_or_create_batch(session, line.product, str(line.raw["batch_no"]),
                                           _date(line.raw.get("expiry_date"))).id
        post_movement(session, MovementRequest(
            company_id=company_id, location_id=location.id, product_id=line.product.id, quantity=line.quantity,
            movement_type="receipt", source_type="goods_receipt", source_id=event.aggregate_id,
            source_line_id=line.id, batch_id=batch_id, unit_cost=unit_cost, business_date=business_date))


def post_goods_return(session: Session, event: Event) -> None:
    """`goods.returned`: send stock back to the supplier, at the average cost it is held at (a batch-tracked product's
    lines name their batch_no)."""
    company_id = _uuid(event.payload.get("company_id"), "company_id")
    location = _location(session, event, company_id)
    _refuse_repeat(session, "purchase_return", event)
    business_date = _date(event.payload.get("business_date"))
    for line in _stock_lines(session, event, company_id):
        batch_id = None
        if line.product.is_batch_tracked:
            if not line.raw.get("batch_no"):
                raise ValidationFailed(f"goods.returned: {line.product.sku} is batch-tracked, give a batch_no")
            batch_id = get_or_create_batch(session, line.product, str(line.raw["batch_no"]),
                                           _date(line.raw.get("expiry_date"))).id
        post_stock_out(session, MovementRequest(
            company_id=company_id, location_id=location.id, product_id=line.product.id, quantity=-line.quantity,
            movement_type="purchase_return", source_type="purchase_return", source_id=event.aggregate_id,
            source_line_id=line.id, batch_id=batch_id, business_date=business_date, allow_negative=False))
