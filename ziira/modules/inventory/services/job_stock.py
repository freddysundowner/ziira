"""Stock used on a job (a repair, an installation): parts issued to it and parts taken back off it.

Both are ordinary ledger movements (`job_issue` out at the average cost, `job_return` in at the cost they went out at),
so the books follow through the stock movement posting (cost of goods sold). The Jobs module decides who may do this
and calls these through `inventory.public`; like every ledger writer here they do not check permissions themselves.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.services.ledger import MovementRequest, post_movement, post_stock_out
from ziira.sdk import Session, ValidationFailed

SOURCE = "job"


@dataclass(frozen=True)
class JobStock:
    """What a job's stock movement cost: `value` is positive, `unit_cost` is per base unit."""

    quantity: Decimal
    unit_cost: Decimal
    value: Decimal


def issue(session: Session, *, company_id: UUID, location_id: UUID, product_id: UUID, quantity: Decimal, job_id: UUID,
          line_id: UUID) -> JobStock:
    """Take `quantity` (positive, base unit) of a product out of a location for a job, at the current average cost."""
    if quantity <= 0:
        raise ValidationFailed("Quantity must be more than zero")
    made = post_stock_out(session, MovementRequest(
        company_id=company_id, location_id=location_id, product_id=product_id, quantity=-quantity,
        movement_type="job_issue", source_type=SOURCE, source_id=job_id, source_line_id=line_id))
    value = -sum((m.value for m in made), Decimal(0))
    return JobStock(quantity, (value / quantity).quantize(Decimal("0.000001")), value)


def take_back(session: Session, *, job_id: UUID, line_id: UUID) -> JobStock | None:
    """Put back everything issued for one line of a job, at the cost it went out at (batches kept). Does nothing
    (None) when nothing is out, so asking twice is harmless."""
    moves = [m for m in inventory_repo.movements_for_source(session, SOURCE, job_id) if m.source_line_id == line_id]
    issued = [m for m in moves if m.movement_type == "job_issue"]
    returned = [m for m in moves if m.movement_type == "job_return"]
    if not issued or returned:
        return None
    total = Decimal(0)
    quantity = Decimal(0)
    for m in issued:
        post_movement(session, MovementRequest(
            company_id=m.company_id, location_id=m.location_id, product_id=m.product_id, quantity=-m.quantity,
            movement_type="job_return", source_type=SOURCE, source_id=job_id, source_line_id=line_id,
            batch_id=m.batch_id, unit_cost=m.unit_cost))
        total += -m.value
        quantity += -m.quantity
    return JobStock(quantity, (total / quantity).quantize(Decimal("0.000001")), total)
