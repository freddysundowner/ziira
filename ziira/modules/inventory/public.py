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


def stock_at_location(session: Session, location_id: UUID, product_ids: set[UUID]) -> dict[UUID, Decimal]:
    """Quantity on hand at a location for each of the products (all batches added up; products with none are absent)."""
    totals: dict[UUID, Decimal] = {}
    for balance in inventory_repo.balances_at(session, location_id, product_ids):
        totals[balance.product_id] = totals.get(balance.product_id, Decimal(0)) + balance.quantity
    return totals


def location_scope(session: Session, location_id: UUID) -> tuple[UUID, UUID | None] | None:
    """(company, branch) of an active stock location, or None when it does not exist or is not in use."""
    location = inventory_repo.get_location(session, location_id)
    if location is None or not location.is_active:
        return None
    return location.company_id, location.branch_id


@dataclass(frozen=True)
class LocationView:
    """A stock location as other units may see it."""

    id: UUID
    code: str
    name: str
    kind: str
    branch_id: UUID | None


def locations_for_branch(session: Session, company_id: UUID, branch_id: UUID) -> list[LocationView]:
    """The active stores and warehouses of a branch, stores first (for choosing where stock is brought in)."""
    from sqlalchemy import text

    rows = session.execute(text(
        "select id, code, name, kind, branch_id from inventory.location where company_id = :c and branch_id = :b "
        "and is_active and kind in ('store', 'warehouse') order by kind, code"),
        {"c": str(company_id), "b": str(branch_id)})
    return [LocationView(r.id, r.code, r.name, r.kind, r.branch_id) for r in rows]


def branch_stock_position(session: Session, company_id: UUID, branch_id: UUID, product_id: UUID, *,
                          sold_since: date) -> tuple[Decimal, Decimal]:
    """(quantity on hand in the branch's stores and warehouses, quantity sold there since `sold_since` net of returns),
    in the product's base unit. For deciding how much to reorder."""
    from sqlalchemy import text

    on_hand = session.execute(text(
        "select coalesce(sum(b.quantity), 0) from inventory.stock_balance b "
        "join inventory.location l on l.id = b.location_id where l.company_id = :c and l.branch_id = :b "
        "and l.kind in ('store', 'warehouse') and b.product_id = :p"),
        {"c": str(company_id), "b": str(branch_id), "p": str(product_id)}).scalar_one()
    sold = session.execute(text(
        "select coalesce(-sum(m.quantity), 0) from inventory.stock_movement m where m.company_id = :c "
        "and m.branch_id = :b and m.product_id = :p and m.movement_type in ('sale', 'sale_return') "
        "and m.business_date >= :since"),
        {"c": str(company_id), "b": str(branch_id), "p": str(product_id), "since": sold_since}).scalar_one()
    return Decimal(on_hand), max(Decimal(sold), Decimal(0))


@dataclass(frozen=True)
class JobStockView:
    """What stock used on a job cost (all positive): the quantity, the cost of one base unit and the total."""

    quantity: Decimal
    unit_cost: Decimal
    value: Decimal


def issue_stock_to_job(session: Session, *, company_id: UUID, location_id: UUID, product_id: UUID, quantity: Decimal,
                       job_id: UUID, line_id: UUID) -> JobStockView:
    """Take a positive `quantity` (base unit) of a stock product out of a location for a job (repair, installation) at
    the current average cost: a `job_issue` movement that the books post as cost of goods sold. `job_id` and `line_id`
    name the job and its parts line. Raises ValidationFailed when the stock is not there (the negative stock policy
    never applies to jobs). The caller checks that the person may do this."""
    from ziira.modules.inventory.services import job_stock

    made = job_stock.issue(session, company_id=company_id, location_id=location_id, product_id=product_id,
                           quantity=quantity, job_id=job_id, line_id=line_id)
    return JobStockView(made.quantity, made.unit_cost, made.value)


def return_stock_from_job(session: Session, *, job_id: UUID, line_id: UUID) -> JobStockView | None:
    """Put back into stock everything issued for one line of a job, at the cost it left at (a `job_return` movement).
    Returns None when nothing was issued for the line or it was already put back."""
    from ziira.modules.inventory.services import job_stock

    made = job_stock.take_back(session, job_id=job_id, line_id=line_id)
    return JobStockView(made.quantity, made.unit_cost, made.value) if made is not None else None
