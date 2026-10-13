"""The stock ledger: every change of stock is an immutable movement (specification section 08).

`post_movement` is the one place stock changes. It validates the movement, locks the product's cost
figure and the balance row, applies the negative stock policy, costs the movement (weighted average),
saves it, updates the balance and cost figure in the same transaction, and publishes `stock.moved`
(plus `stock.negative` and `stock.below_reorder` when they apply).

It does not check permissions: it is called by services that did (adjustments, transfers, counts) and
by event handlers acting for another unit's document (a sale, a goods receipt). Callers also check a
reason code's category with `check_reason` before passing it in.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.domain import movements
from ziira.modules.inventory.domain.batches import BatchStock, Pick, pick_first_expiry_first_out
from ziira.modules.inventory.domain.costing import CostState, cost_movement
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import Batch, Location, StockMovement
from ziira.modules.products.public import ProductView, find_product
from ziira.sdk import (
    Event,
    Session,
    ValidationFailed,
    company_setting,
    current_context,
    publish,
)

NAIROBI = timezone(timedelta(hours=3))        # Kenya has no daylight saving time


def business_today() -> date:
    """Today's date in Kenya: the business date of a movement unless the document says otherwise."""
    return datetime.now(UTC).astimezone(NAIROBI).date()


@dataclass(frozen=True)
class MovementRequest:
    """One change of stock to post. Quantity: + in, - out, in the product's base unit."""

    company_id: UUID
    location_id: UUID
    product_id: UUID
    quantity: Decimal
    movement_type: str
    source_type: str                      # the document behind it, e.g. "stock_adjustment"
    source_id: UUID
    source_line_id: UUID | None = None
    batch_id: UUID | None = None
    unit_cost: Decimal | None = None      # for stock coming in; outgoing stock takes the average
    reason_code_id: UUID | None = None
    business_date: date | None = None
    approved_by: UUID | None = None
    # Sales only: None follows the company policy; True always accepts (offline POS sales are facts).
    allow_negative: bool | None = None


def load_location(session: Session, company_id: UUID, location_id: UUID) -> Location:
    """An active location of the company, or ValidationFailed."""
    location = inventory_repo.get_location(session, location_id)
    if location is None or location.company_id != company_id:
        raise ValidationFailed("Location not found in this company")
    if not location.is_active:
        raise ValidationFailed(f"Location {location.code} is not active")
    return location


def load_stock_product(session: Session, company_id: UUID, product_id: UUID) -> ProductView:
    """An active stock product of the company, or ValidationFailed."""
    product = find_product(session, product_id)
    if product is None or product.company_id != company_id:
        raise ValidationFailed("Product not found in this company")
    movements.check_product_can_hold_stock(product.product_type, product.is_active)
    return product


def check_batch(session: Session, product: ProductView, batch_id: UUID | None) -> None:
    """A batch-tracked product needs one of its own batches; any other product must not have one."""
    if product.is_batch_tracked and batch_id is None:
        raise ValidationFailed(f"{product.sku} is batch-tracked: a batch is required")
    if not product.is_batch_tracked and batch_id is not None:
        raise ValidationFailed(f"{product.sku} is not batch-tracked")
    if batch_id is not None:
        batch = inventory_repo.get_batch(session, batch_id)
        if batch is None or batch.product_id != product.id:
            raise ValidationFailed("Batch not found for this product")


def post_movement(session: Session, request: MovementRequest) -> StockMovement:
    """Post one movement. Raises ValidationFailed if it is not allowed (see domain/movements.py)."""
    ctx = current_context()
    movements.check_movement(request.movement_type, request.quantity, reason_code_id=request.reason_code_id,
                             unit_cost=request.unit_cost)
    location = load_location(session, request.company_id, request.location_id)
    product = load_stock_product(session, request.company_id, request.product_id)
    check_batch(session, product, request.batch_id)

    # Lock order is always the same (cost figure, then balance) so concurrent postings cannot deadlock.
    cost = inventory_repo.lock_cost(session, request.company_id, request.product_id, ctx.tenant_id)
    balance = inventory_repo.lock_balance(session, request.location_id, request.product_id, request.batch_id,
                                          ctx.tenant_id)

    allowed = request.movement_type == "sale" and (
        request.allow_negative if request.allow_negative is not None
        else bool(company_setting(session, request.company_id, "negative_stock_allowed")))
    went_negative = movements.check_negative_stock(balance.quantity, request.quantity, allowed=allowed)

    before = CostState(cost.quantity, cost.value, cost.average_cost)
    costed = cost_movement(before, request.movement_type, request.quantity, request.unit_cost)

    movement = StockMovement(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=request.company_id, branch_id=location.branch_id,
        location_id=request.location_id, product_id=request.product_id, batch_id=request.batch_id,
        quantity=request.quantity, unit_cost=costed.unit_cost, value=costed.value,
        movement_type=request.movement_type, source_type=request.source_type, source_id=request.source_id,
        source_line_id=request.source_line_id, reason_code_id=request.reason_code_id,
        business_date=request.business_date or business_today(), approved_by=request.approved_by)
    inventory_repo.add(session, movement)

    balance.quantity += request.quantity
    cost.quantity, cost.value, cost.average_cost = costed.state.quantity, costed.state.value, costed.state.average_cost
    session.flush()

    payload = {"company_id": request.company_id, "location_id": request.location_id,
               "product_id": request.product_id, "batch_id": request.batch_id, "quantity": request.quantity,
               "unit_cost": costed.unit_cost, "value": costed.value, "movement_type": request.movement_type,
               "source_type": request.source_type, "source_id": request.source_id,
               "business_date": movement.business_date}
    publish(session, Event("stock.moved", "inventory.stock_movement", movement.id, payload))
    if went_negative:
        publish(session, Event("stock.negative", "inventory.stock_movement", movement.id,
                               {**payload, "balance_after": balance.quantity}))
    level = product.reorder_level
    if level is not None and before.quantity >= level > costed.state.quantity:
        publish(session, Event("stock.below_reorder", "products.product", product.id,
                               {"company_id": request.company_id, "product_id": product.id, "sku": product.sku,
                                "quantity": costed.state.quantity, "reorder_level": level}))
    return movement


def post_stock_out(session: Session, request: MovementRequest) -> list[StockMovement]:
    """Take stock out, choosing batches first-expiry-first-out for a batch-tracked product.

    One movement per batch used. `request.quantity` is negative, and its batch is ignored when the
    product is batch-tracked and none was named. If the stock is not there, a sale may still post
    under the negative stock policy: the shortage is taken from the batch expiring first.
    """
    movements.check_movement(request.movement_type, request.quantity, reason_code_id=request.reason_code_id,
                             unit_cost=request.unit_cost)
    if request.quantity > 0:
        raise ValidationFailed("Stock going out has a negative quantity")
    product = load_stock_product(session, request.company_id, request.product_id)
    if not product.is_batch_tracked or request.batch_id is not None:
        return [post_movement(session, request)]

    ctx = current_context()
    # Lock before reading what each batch holds, so a concurrent sale cannot take the same units.
    inventory_repo.lock_cost(session, request.company_id, request.product_id, ctx.tenant_id)
    rows = inventory_repo.batch_balances(session, request.location_id, request.product_id)
    stock = [BatchStock(*row) for row in rows]
    picks, shortage = pick_first_expiry_first_out(stock, -request.quantity)
    if shortage > 0:
        if not picks:
            earliest = sorted(stock, key=lambda b: (b.expiry_date is None, b.expiry_date or date.max))
            if not earliest:
                raise ValidationFailed(f"Not enough stock of {product.sku}: no batch has any")
            picks = [Pick(earliest[0].batch_id, Decimal(0))]
        # The last batch used takes the shortage; post_movement then applies the negative stock policy.
        last = picks[-1]
        picks[-1] = Pick(last.batch_id, last.quantity + shortage)
    return [post_movement(session, MovementRequest(
        company_id=request.company_id, location_id=request.location_id, product_id=request.product_id,
        quantity=-pick.quantity, movement_type=request.movement_type, source_type=request.source_type,
        source_id=request.source_id, source_line_id=request.source_line_id, batch_id=pick.batch_id,
        unit_cost=request.unit_cost, reason_code_id=request.reason_code_id, business_date=request.business_date,
        approved_by=request.approved_by, allow_negative=request.allow_negative)) for pick in picks]


def get_or_create_batch(session: Session, product: ProductView, batch_no: str, expiry_date: date | None) -> Batch:
    """The product's batch with this number, created if new. An existing batch keeps its expiry date."""
    batch_no = batch_no.strip()
    if not batch_no:
        raise ValidationFailed("Batch number is required")
    batch = inventory_repo.find_batch(session, product.id, batch_no)
    if batch is not None:
        if expiry_date is not None and batch.expiry_date != expiry_date:
            raise ValidationFailed(f"Batch {batch_no} of {product.sku} already exists with a different expiry date")
        return batch
    ctx = current_context()
    batch = Batch(tenant_id=ctx.tenant_id, created_by=ctx.user_id, product_id=product.id, batch_no=batch_no,
                  expiry_date=expiry_date)
    inventory_repo.add(session, batch)
    return batch
