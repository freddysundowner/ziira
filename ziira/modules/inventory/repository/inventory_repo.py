"""Database access for the inventory schema. Row-level security scopes every query to the tenant."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, text, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from ziira.modules.inventory.repository.models import (
    Batch,
    Location,
    ProductCost,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockCount,
    StockCountLine,
    StockMovement,
    Transfer,
    TransferLine,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None     # (company, branch) pairs a user may see; None = all


def add(session: Session, record: Location | Batch | StockMovement | StockAdjustment | StockAdjustmentLine
        | Transfer | TransferLine | StockCount | StockCountLine) -> None:
    """Insert a record and load its generated columns."""
    session.add(record)
    session.flush()
    session.refresh(record)


def _location_in_scope(scopes: Scopes, location: type[Location] = Location) -> ColumnElement[bool]:
    """Locations the user may see: in a company they reach, at a branch they reach or with no branch."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(location.company_id == c,
                               true() if b is None else or_(location.branch_id == b, location.branch_id.is_(None)))
                          for c, b in scopes))


# --------------------------------------------------------------------------- locations
def get_location(session: Session, location_id: UUID) -> Location | None:
    return session.get(Location, location_id)


def location_code_exists(session: Session, company_id: UUID, code: str) -> bool:
    found = select(Location.id).where(Location.company_id == company_id, Location.code == code)
    return session.scalar(found) is not None


def list_locations(session: Session, scopes: Scopes, company_id: UUID | None = None, branch_id: UUID | None = None,
                   kind: str | None = None) -> list[Location]:
    query = select(Location).where(_location_in_scope(scopes)).order_by(Location.company_id, Location.code)
    if company_id:
        query = query.where(Location.company_id == company_id)
    if branch_id:
        query = query.where(Location.branch_id == branch_id)
    if kind:
        query = query.where(Location.kind == kind)
    return list(session.scalars(query))


def find_transit_location(session: Session, company_id: UUID) -> Location | None:
    return session.scalar(select(Location).where(Location.company_id == company_id, Location.kind == "transit",
                                                  Location.is_active).order_by(Location.code))


# --------------------------------------------------------------------------- batches
def find_batch(session: Session, product_id: UUID, batch_no: str) -> Batch | None:
    return session.scalar(select(Batch).where(Batch.product_id == product_id, Batch.batch_no == batch_no))


def get_batch(session: Session, batch_id: UUID) -> Batch | None:
    return session.get(Batch, batch_id)


# --------------------------------------------------------------------------- locking and balances
def lock_cost(session: Session, company_id: UUID, product_id: UUID, tenant_id: UUID) -> ProductCost:
    """The company's cost figure for a product, locked until the transaction ends.

    Every posting for a product takes this lock first, so two sales of the last unit cannot both succeed
    and postings always lock in the same order (no deadlocks).
    """
    session.execute(insert(ProductCost).values(tenant_id=tenant_id, company_id=company_id, product_id=product_id)
                    .on_conflict_do_nothing())
    return session.scalars(select(ProductCost).where(ProductCost.company_id == company_id,
                                                     ProductCost.product_id == product_id)
                           .with_for_update().execution_options(populate_existing=True)).one()


def lock_balance(session: Session, location_id: UUID, product_id: UUID, batch_id: UUID | None,
                 tenant_id: UUID) -> StockBalance:
    """The stock balance row for a location, product and batch (created at zero if new), locked."""
    session.execute(insert(StockBalance).values(tenant_id=tenant_id, location_id=location_id,
                                                product_id=product_id, batch_id=batch_id).on_conflict_do_nothing())
    batch_filter = StockBalance.batch_id.is_(None) if batch_id is None else StockBalance.batch_id == batch_id
    return session.scalars(select(StockBalance).where(StockBalance.location_id == location_id,
                                                      StockBalance.product_id == product_id, batch_filter)
                           .with_for_update().execution_options(populate_existing=True)).one()


def batch_balances(session: Session, location_id: UUID, product_id: UUID) -> list[tuple[UUID, Decimal, date | None]]:
    """(batch id, quantity, expiry date) of every batch of the product at the location."""
    rows = session.execute(select(StockBalance.batch_id, StockBalance.quantity, Batch.expiry_date)
                           .join(Batch, Batch.id == StockBalance.batch_id)
                           .where(StockBalance.location_id == location_id, StockBalance.product_id == product_id))
    return [(r.batch_id, r.quantity, r.expiry_date) for r in rows]


def on_hand(session: Session, product_id: UUID, location_id: UUID | None = None,
            company_id: UUID | None = None) -> Decimal:
    """Quantity of a product at a location, or across the company's locations."""
    query = select(func.coalesce(func.sum(StockBalance.quantity), 0)).where(StockBalance.product_id == product_id)
    if location_id:
        query = query.where(StockBalance.location_id == location_id)
    if company_id:
        query = query.join(Location, Location.id == StockBalance.location_id).where(Location.company_id == company_id)
    return Decimal(session.scalar(query) or 0)


def visible_on_hand(session: Session, scopes: Scopes, product_id: UUID) -> Decimal:
    """Quantity of a product at the locations the user may see."""
    query = (select(func.coalesce(func.sum(StockBalance.quantity), 0))
             .join(Location, Location.id == StockBalance.location_id)
             .where(StockBalance.product_id == product_id, _location_in_scope(scopes)))
    return Decimal(session.scalar(query) or 0)


def get_cost(session: Session, company_id: UUID, product_id: UUID) -> ProductCost | None:
    return session.scalar(select(ProductCost).where(ProductCost.company_id == company_id,
                                                    ProductCost.product_id == product_id))


def has_movements(session: Session, location_id: UUID, product_id: UUID) -> bool:
    return session.scalar(select(StockMovement.id).where(StockMovement.location_id == location_id,
                                                         StockMovement.product_id == product_id).limit(1)) is not None


def list_balances(session: Session, scopes: Scopes, *, location_id: UUID | None = None, product_id: UUID | None = None,
                  branch_id: UUID | None = None, include_zero: bool = False, limit: int = 100,
                  offset: int = 0) -> list[tuple[StockBalance, Location]]:
    query = (select(StockBalance, Location).join(Location, Location.id == StockBalance.location_id)
             .where(_location_in_scope(scopes)).order_by(Location.code, StockBalance.product_id, StockBalance.batch_id)
             .limit(limit).offset(offset))
    if location_id:
        query = query.where(StockBalance.location_id == location_id)
    if product_id:
        query = query.where(StockBalance.product_id == product_id)
    if branch_id:
        query = query.where(Location.branch_id == branch_id)
    if not include_zero:
        query = query.where(StockBalance.quantity != 0)
    return [(row[0], row[1]) for row in session.execute(query)]


def list_movements(session: Session, scopes: Scopes, *, location_id: UUID | None = None, product_id: UUID | None = None,
                   source_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[StockMovement]:
    query = (select(StockMovement).join(Location, Location.id == StockMovement.location_id)
             .where(_location_in_scope(scopes)).order_by(StockMovement.created_at.desc(), StockMovement.id)
             .limit(limit).offset(offset))
    if location_id:
        query = query.where(StockMovement.location_id == location_id)
    if product_id:
        query = query.where(StockMovement.product_id == product_id)
    if source_id:
        query = query.where(StockMovement.source_id == source_id)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- documents
def get_document[DocT: (StockAdjustment, Transfer, StockCount)](
        session: Session, model: type[DocT], document_id: UUID, *, lock: bool = False) -> DocT | None:
    """One stock document (adjustment, transfer or count) by id, optionally locked for update."""
    if lock:
        return session.scalars(select(model).where(model.id == document_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(model, document_id)


def document_lines[LineT: (StockAdjustmentLine, TransferLine, StockCountLine)](
        session: Session, model: type[LineT], parent_column: str, parent_id: UUID) -> list[LineT]:
    column = getattr(model, parent_column)
    return list(session.scalars(select(model).where(column == parent_id).order_by(model.created_at, model.id)))


def list_adjustments(session: Session, scopes: Scopes, *, location_id: UUID | None = None, status: str | None = None,
                     limit: int = 100, offset: int = 0) -> list[StockAdjustment]:
    query = (select(StockAdjustment).join(Location, Location.id == StockAdjustment.location_id)
             .where(_location_in_scope(scopes)).order_by(StockAdjustment.created_at.desc(), StockAdjustment.id)
             .limit(limit).offset(offset))
    if location_id:
        query = query.where(StockAdjustment.location_id == location_id)
    if status:
        query = query.where(StockAdjustment.status == status)
    return list(session.scalars(query))


def list_transfers(session: Session, scopes: Scopes, *, location_id: UUID | None = None, status: str | None = None,
                   limit: int = 100, offset: int = 0) -> list[Transfer]:
    """Transfers touching a location the user may see, newest first."""
    source, target = aliased(Location), aliased(Location)
    visible = or_(_location_in_scope(scopes, source), _location_in_scope(scopes, target))
    query = (select(Transfer).join(source, source.id == Transfer.from_location_id)
             .join(target, target.id == Transfer.to_location_id).where(visible)
             .order_by(Transfer.created_at.desc(), Transfer.id).limit(limit).offset(offset))
    if location_id:
        query = query.where(or_(Transfer.from_location_id == location_id, Transfer.to_location_id == location_id))
    if status:
        query = query.where(Transfer.status == status)
    return list(session.scalars(query))


def movement_cost(session: Session, source_id: UUID, source_line_id: UUID, movement_type: str) -> Decimal | None:
    """Unit cost of the first movement of a type posted for a document line."""
    return session.scalar(select(StockMovement.unit_cost).where(
        StockMovement.source_id == source_id, StockMovement.source_line_id == source_line_id,
        StockMovement.movement_type == movement_type).order_by(StockMovement.created_at).limit(1))


# --------------------------------------------------------------------------- stock counts
def lock_for_snapshot(session: Session) -> int:
    """Hold off every stock posting until the transaction ends, and return the last movement number.

    Postings take a row-level lock on the balance table before they write, so this share lock waits for
    postings in progress to finish and makes new ones wait: the balances read next are exactly the
    movements up to the returned number.
    """
    session.execute(text("lock table inventory.stock_balance in share mode"))
    return int(session.scalar(select(func.coalesce(func.max(StockMovement.seq), 0))) or 0)


def last_movement_seq(session: Session) -> int:
    return int(session.scalar(select(func.coalesce(func.max(StockMovement.seq), 0))) or 0)


def balances_at(session: Session, location_id: UUID, product_ids: set[UUID] | None) -> list[StockBalance]:
    """Non-zero balances at a location (optionally only some products), for a count's snapshot."""
    query = select(StockBalance).where(StockBalance.location_id == location_id, StockBalance.quantity != 0)
    if product_ids is not None:
        query = query.where(StockBalance.product_id.in_(product_ids))
    return list(session.scalars(query.order_by(StockBalance.product_id, StockBalance.batch_id)))


def moved_between(session: Session, location_id: UUID, product_id: UUID, batch_id: UUID | None, after_seq: int,
                  up_to_seq: int) -> Decimal:
    """Net quantity moved for a product and batch at a location after one movement number up to another."""
    batch_filter = StockMovement.batch_id.is_(None) if batch_id is None else StockMovement.batch_id == batch_id
    total = session.scalar(select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
        StockMovement.location_id == location_id, StockMovement.product_id == product_id, batch_filter,
        StockMovement.seq > after_seq, StockMovement.seq <= up_to_seq))
    return Decimal(total or 0)


def list_counts(session: Session, scopes: Scopes, *, location_id: UUID | None = None, status: str | None = None,
                limit: int = 100, offset: int = 0) -> list[StockCount]:
    query = (select(StockCount).join(Location, Location.id == StockCount.location_id)
             .where(_location_in_scope(scopes)).order_by(StockCount.created_at.desc(), StockCount.id)
             .limit(limit).offset(offset))
    if location_id:
        query = query.where(StockCount.location_id == location_id)
    if status:
        query = query.where(StockCount.status == status)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- documents of other units
def source_has_movements(session: Session, source_type: str, source_id: UUID) -> bool:
    """True if stock has already been posted for this document (a sale, a goods receipt)."""
    return session.scalar(select(StockMovement.id).where(
        StockMovement.source_type == source_type, StockMovement.source_id == source_id).limit(1)) is not None


def sale_movement(session: Session, sale_id: UUID, sale_line_id: UUID) -> StockMovement | None:
    """The first stock movement posted for a sale line (what it cost and which batch it came from)."""
    return session.scalar(select(StockMovement).where(
        StockMovement.source_type == "sale", StockMovement.source_id == sale_id,
        StockMovement.source_line_id == sale_line_id).order_by(StockMovement.seq).limit(1))


def single_store(session: Session, company_id: UUID, branch_id: UUID) -> Location | None:
    """The branch's only active store, if it has exactly one."""
    stores = list(session.scalars(select(Location).where(
        Location.company_id == company_id, Location.branch_id == branch_id, Location.kind == "store",
        Location.is_active).limit(2)))
    return stores[0] if len(stores) == 1 else None


def movements_for_source(session: Session, source_type: str, source_id: UUID) -> list[StockMovement]:
    return list(session.scalars(select(StockMovement).where(
        StockMovement.source_type == source_type, StockMovement.source_id == source_id).order_by(StockMovement.seq)))


# --------------------------------------------------------------------------- verification
@dataclass(frozen=True)
class BalanceMismatch:
    location_id: UUID
    product_id: UUID
    batch_id: UUID | None
    stored: Decimal
    moved: Decimal


def balance_mismatches(session: Session) -> list[BalanceMismatch]:
    """Balances that differ from the sum of their movements (in either direction)."""
    rows = session.execute(text(
        "with moved as (select location_id, product_id, batch_id, sum(quantity) as q "
        "  from inventory.stock_movement group by location_id, product_id, batch_id) "
        "select coalesce(b.location_id, m.location_id) as location_id, coalesce(b.product_id, m.product_id) as "
        "  product_id, coalesce(b.batch_id, m.batch_id) as batch_id, coalesce(b.quantity, 0) as stored, "
        "  coalesce(m.q, 0) as moved "
        "from inventory.stock_balance b full join moved m on b.location_id = m.location_id "
        "  and b.product_id = m.product_id and b.batch_id is not distinct from m.batch_id "
        "where coalesce(b.quantity, 0) <> coalesce(m.q, 0) order by 1, 2"))
    return [BalanceMismatch(r.location_id, r.product_id, r.batch_id, r.stored, r.moved) for r in rows]


def set_balance(session: Session, tenant_id: UUID, mismatch: BalanceMismatch) -> None:
    """Make a balance equal to the sum of its movements (creating the row if it was missing)."""
    session.execute(insert(StockBalance).values(
        tenant_id=tenant_id, location_id=mismatch.location_id, product_id=mismatch.product_id,
        batch_id=mismatch.batch_id, quantity=mismatch.moved).on_conflict_do_nothing())
    batch_filter = StockBalance.batch_id.is_(None) if mismatch.batch_id is None \
        else StockBalance.batch_id == mismatch.batch_id
    for balance in session.scalars(select(StockBalance).where(
            StockBalance.location_id == mismatch.location_id, StockBalance.product_id == mismatch.product_id,
            batch_filter).with_for_update()):
        balance.quantity = mismatch.moved
    session.flush()


def movement_history(session: Session) -> dict[tuple[UUID, UUID], list[tuple[str, Decimal, Decimal]]]:
    """(movement type, quantity, value) of every movement in posting order, by (company, product)."""
    history: dict[tuple[UUID, UUID], list[tuple[str, Decimal, Decimal]]] = {}
    for row in session.execute(select(StockMovement.company_id, StockMovement.product_id, StockMovement.movement_type,
                                      StockMovement.quantity, StockMovement.value).order_by(StockMovement.seq)):
        history.setdefault((row.company_id, row.product_id), []).append((row.movement_type, row.quantity, row.value))
    return history


def all_costs(session: Session) -> dict[tuple[UUID, UUID], ProductCost]:
    return {(c.company_id, c.product_id): c for c in session.scalars(select(ProductCost).with_for_update())}
