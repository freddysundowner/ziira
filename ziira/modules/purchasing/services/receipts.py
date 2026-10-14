"""Use cases: receive goods.

Receiving is one transaction: the receipt and its lines, the order's received quantities, and the stock arriving
(Inventory reacts to `goods.received` in the same transaction; Finance then books it as stock against "goods received
not invoiced"). Against an order, a receipt can be partial, takes its cost from the order, and can never be more than
was ordered; the price difference, if any, shows up on the supplier's bill.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.public import location_scope
from ziira.modules.products.public import find_product
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import GOODS_RECEIVE
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrderLine, SupplierPrice
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import active_supplier, unit_enabled
from ziira.sdk import (
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_date_of,
    current_context,
    next_document_number,
    publish,
)

RECEIVABLE = ("approved", "sent", "part_received")


@dataclass(frozen=True)
class ReceiptLineIn:
    quantity: Decimal
    order_line_id: UUID | None = None        # a line of the order being received against
    product_id: UUID | None = None           # without an order
    unit_cost: Decimal | None = None         # without an order (an order's cost comes from the order)
    batch_no: str | None = None
    expiry_date: date | None = None


@dataclass
class ReceiptView:
    receipt: GoodsReceipt
    lines: list[GoodsReceiptLine]


def get_receipt(session: Session, receipt_id: UUID) -> ReceiptView:
    receipt = repo.get_receipt(session, receipt_id)
    if receipt is None or not access.can_view(receipt.company_id, receipt.branch_id):
        raise NotFound("Receipt not found")
    return ReceiptView(receipt, repo.receipt_lines(session, receipt.id))


def list_receipts(session: Session, *, order_id: UUID | None = None, supplier_id: UUID | None = None, limit: int = 50,
                  offset: int = 0) -> list[GoodsReceipt]:
    return repo.list_receipts(session, access.view_scopes(), order_id=order_id, supplier_id=supplier_id,
                              limit=min(limit, 200), offset=offset)


def receive_goods(session: Session, *, lines: list[ReceiptLineIn], order_id: UUID | None = None,
                  supplier_id: UUID | None = None, location_id: UUID | None = None, received_at: datetime | None = None,
                  delivery_note_no: str | None = None, landed_cost: Decimal = Decimal(0)) -> ReceiptView:
    """Receive goods into a stock location, against an order or on their own. Needs 'goods.receive' at the location's
    branch. `landed_cost` (transport, duty) is spread over the lines by value."""
    ctx = current_context()
    if not unit_enabled(session, "inventory"):
        raise ValidationFailed("Enable Inventory to receive goods")
    if not lines or len(lines) > 200:
        raise ValidationFailed("A receipt has between 1 and 200 lines")
    if landed_cost < 0 or landed_cost != landed_cost.quantize(rules.CENT) or landed_cost > rules.MAX_COST:
        raise ValidationFailed("Landed cost is an amount of zero or more with at most 2 decimal places")

    order = None
    order_lines: dict[UUID, PurchaseOrderLine] = {}
    if order_id is not None:
        order = repo.get_order(session, order_id, lock=True)
        if order is None or not access.can_view(order.company_id, order.branch_id):
            raise NotFound("Order not found")
        if order.status not in RECEIVABLE:
            raise ValidationFailed(f"Goods cannot be received on an order that is {order.status.replace('_', ' ')}")
        supplier_id = order.supplier_id
        location_id = location_id or order.deliver_to_location_id
        company_id = order.company_id
        # lock the order's lines in a fixed order so two receipts at once cannot both take the last units
        order_lines = {x.id: x for x in sorted(repo.order_lines(session, order.id, lock=True), key=lambda x: str(x.id))}
    else:
        if supplier_id is None:
            raise ValidationFailed("Name the supplier, or receive against an order")
        supplier = repo.get_supplier(session, supplier_id)
        if supplier is None:
            raise ValidationFailed("Supplier not found")
        company_id = supplier.company_id
    supplier = active_supplier(repo.get_supplier(session, supplier_id), company_id)
    if location_id is None:
        raise ValidationFailed("Say which stock location the goods go to")
    where = location_scope(session, location_id)
    if where is None or where[0] != company_id:
        raise ValidationFailed("The stock location was not found in this company")
    branch_id = where[1]
    ctx.require(GOODS_RECEIVE, company_id=company_id, branch_id=branch_id)

    seen: set[UUID] = set()
    prepared: list[tuple[ReceiptLineIn, UUID, Decimal]] = []
    for line in lines:
        rules.check_quantity(line.quantity)
        if order is not None:
            order_line = order_lines.get(line.order_line_id) if line.order_line_id else None
            if order_line is None:
                raise ValidationFailed("Each line must name a line of this order")
            if line.order_line_id in seen:
                raise ValidationFailed("A line of the order appears once in a receipt")
            seen.add(line.order_line_id)  # type: ignore[arg-type]
            if line.unit_cost is not None and line.unit_cost != order_line.unit_cost:
                raise ValidationFailed("Goods received on an order are costed at the order's cost: the difference, "
                                       "if any, is dealt with when the supplier's bill is entered")
            rules.check_receipt_quantity(order_line.quantity, order_line.qty_received, line.quantity)
            prepared.append((line, order_line.product_id, order_line.unit_cost))
        else:
            if line.product_id is None or line.unit_cost is None:
                raise ValidationFailed("Without an order, each line needs a product and a cost")
            rules.check_cost(line.unit_cost)
            prepared.append((line, line.product_id, line.unit_cost))
    for line, product_id, _ in prepared:
        product = find_product(session, product_id)
        if product is None or product.company_id != company_id or not product.is_active:
            raise ValidationFailed("A product in the receipt was not found in this company")
        if product.product_type != "stock":
            raise ValidationFailed(f"{product.sku} is not a stock product")
        if product.is_batch_tracked and not (line.batch_no and line.batch_no.strip()):
            raise ValidationFailed(f"{product.sku} is batch-tracked: give the batch number")

    moment = received_at or datetime.now(UTC)
    day = company_date_of(session, company_id, moment)
    receipt = GoodsReceipt(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="goods_receipt",
                                    prefix="GRN"), order_id=order_id, supplier_id=supplier.id, location_id=location_id,
        received_at=moment, delivery_note_no=(delivery_note_no or "").strip() or None, status="posted",
        landed_cost=landed_cost)
    repo.add(session, receipt)
    rows = []
    for line, product_id, cost in prepared:
        rows.append(GoodsReceiptLine(
            tenant_id=ctx.tenant_id, receipt_id=receipt.id, order_line_id=line.order_line_id, product_id=product_id,
            batch_no=(line.batch_no or "").strip() or None, expiry_date=line.expiry_date, quantity=line.quantity,
            unit_cost=cost))
    session.add_all(rows)
    session.flush()

    if order is not None:
        for line, _, _ in prepared:
            order_line = order_lines[line.order_line_id]  # type: ignore[index]
            order_line.qty_received += line.quantity
        order.status = rules.order_status(
            [(x.quantity, x.qty_received) for x in order_lines.values()], order.status)
        session.flush()

    publish(session, Event("goods.received", "purchasing.goods_receipt", receipt.id, {
        "company_id": company_id, "branch_id": branch_id, "location_id": location_id, "business_date": day,
        "number": receipt.number, "supplier_id": supplier.id, "landed_cost": landed_cost, "order_id": order_id,
        "lines": [{"line_id": row.id, "product_id": row.product_id, "quantity": row.quantity,
                   "unit_cost": row.unit_cost, "batch_no": row.batch_no, "expiry_date": row.expiry_date}
                  for row in rows]}))
    _remember_prices(session, supplier.id, company_id, receipt, rows, day)
    audit_record(session, "receive", "purchasing.goods_receipt", receipt.id,
                 {"number": receipt.number, "order": order.number if order else None, "lines": len(rows)})
    return ReceiptView(receipt, rows)


def _remember_prices(session: Session, supplier_id: UUID, company_id: UUID, receipt: GoodsReceipt,
                     rows: list[GoodsReceiptLine], day: date) -> None:
    """Keep what each supplier charged for each product, and say when it changed."""
    ctx = current_context()
    for row in rows:
        previous = repo.last_price(session, supplier_id, row.product_id)
        session.add(SupplierPrice(tenant_id=ctx.tenant_id, supplier_id=supplier_id, product_id=row.product_id,
                                  unit_cost=row.unit_cost, effective_date=day, source_type="goods_receipt",
                                  source_id=receipt.id))
        session.flush()
        if previous is not None and previous.unit_cost != row.unit_cost:
            publish(session, Event("supplier.price_changed", "purchasing.supplier", supplier_id, {
                "company_id": company_id, "product_id": row.product_id, "previous": previous.unit_cost,
                "new": row.unit_cost, "receipt": receipt.number}))
