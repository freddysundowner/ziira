"""HTTP endpoints of the Inventory module. Routes only convert HTTP to service calls."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from ziira.modules.inventory.api.schemas import (
    AdjustmentIn,
    AdjustmentLineOut,
    AdjustmentOut,
    AdjustmentSummaryOut,
    BalanceOut,
    CountEntriesIn,
    CountFinishIn,
    CountLineOut,
    CountOut,
    CountStartIn,
    CountSubmitIn,
    CountSummaryOut,
    LocationIn,
    LocationOut,
    MovementOut,
    OpeningStockIn,
    ProductStockOut,
    ReceiveIn,
    TransferIn,
    TransferLineOut,
    TransferOut,
    TransferSummaryOut,
)
from ziira.modules.inventory.permissions import (
    LOCATIONS_MANAGE,
    STOCK_ADJUST,
    STOCK_COUNT,
    STOCK_TRANSFER,
    STOCK_VIEW,
)
from ziira.modules.inventory.services.adjustments import (
    AdjustmentDetail,
    AdjustmentLineIn,
    create_adjustment,
    get_adjustment,
    list_adjustments,
    submit_adjustment,
)
from ziira.modules.inventory.services.counts import (
    CountDetail,
    CountEntry,
    cancel_count,
    finish_counting,
    get_count,
    list_counts,
    record_counts,
    start_count,
    submit_count,
)
from ziira.modules.inventory.services.find_stock import (
    can_see_cost,
    list_balances,
    list_movements,
    product_stock,
)
from ziira.modules.inventory.services.locations import create_location, list_locations
from ziira.modules.inventory.services.opening_stock import OpeningLine, post_opening_stock
from ziira.modules.inventory.services.transfers import (
    ReceivedLine,
    TransferDetail,
    TransferLineIn,
    cancel_transfer,
    create_transfer,
    dispatch_transfer,
    get_transfer,
    list_transfers,
    receive_transfer,
)
from ziira.sdk import Session, db_session, require_permission

router = APIRouter()
VIEW = [Depends(require_permission(STOCK_VIEW))]


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(LOCATIONS_MANAGE))])
def post_location(body: LocationIn, session: Session = Depends(db_session)) -> object:
    """Create a store, warehouse, in-transit or virtual location."""
    return create_location(session, company_id=body.company_id, branch_id=body.branch_id, code=body.code,
                           name=body.name, kind=body.kind)


@router.get("/locations", response_model=list[LocationOut], dependencies=VIEW)
def get_locations(company_id: UUID | None = None, branch_id: UUID | None = None, kind: str | None = None,
                  session: Session = Depends(db_session)) -> object:
    return list_locations(session, company_id, branch_id, kind)


@router.post("/opening-stock", response_model=list[MovementOut], status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(STOCK_ADJUST))])
def post_opening(body: OpeningStockIn, session: Session = Depends(db_session)) -> object:
    """Record the stock a location already had when the business started using Ziira."""
    posted = post_opening_stock(
        session, company_id=body.company_id, location_id=body.location_id, business_date=body.business_date,
        lines=[OpeningLine(line.product_id, line.quantity, line.unit_cost, line.batch_no, line.expiry_date)
               for line in body.lines])
    return [_movement_out(m) for m in posted]


@router.post("/adjustments", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission(STOCK_ADJUST))])
def post_adjustment(body: AdjustmentIn, session: Session = Depends(db_session)) -> object:
    """Write a draft stock adjustment. It changes nothing until it is submitted (and approved)."""
    return _adjustment_out(create_adjustment(
        session, company_id=body.company_id, location_id=body.location_id, reason_code_id=body.reason_code_id,
        note=body.note, lines=[AdjustmentLineIn(x.product_id, x.qty_change, x.batch_id) for x in body.lines]))


@router.get("/adjustments", response_model=list[AdjustmentSummaryOut], dependencies=VIEW)
def get_adjustments(location_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                    limit: int = 100, offset: int = 0, session: Session = Depends(db_session)) -> object:
    return list_adjustments(session, location_id=location_id, status=status_, limit=limit, offset=offset)


@router.get("/adjustments/{adjustment_id}", response_model=AdjustmentOut, dependencies=VIEW)
def get_one_adjustment(adjustment_id: UUID, session: Session = Depends(db_session)) -> object:
    return _adjustment_out(get_adjustment(session, adjustment_id))


@router.post("/adjustments/{adjustment_id}/submit", response_model=AdjustmentOut,
             dependencies=[Depends(require_permission(STOCK_ADJUST))])
def post_submit_adjustment(adjustment_id: UUID, session: Session = Depends(db_session)) -> object:
    """Send the adjustment for approval. It posts at once if the approval matrix needs no approval for its size;
    otherwise an approver decides it under /api/v1/approvals."""
    return _adjustment_out(submit_adjustment(session, adjustment_id))


TRANSFER = [Depends(require_permission(STOCK_TRANSFER))]


@router.post("/transfers", response_model=TransferOut, status_code=status.HTTP_201_CREATED, dependencies=TRANSFER)
def post_transfer(body: TransferIn, session: Session = Depends(db_session)) -> object:
    """Write a draft transfer between two locations of a company. Nothing moves until it is dispatched."""
    return _transfer_out(create_transfer(
        session, company_id=body.company_id, from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        lines=[TransferLineIn(x.product_id, x.quantity, x.batch_id) for x in body.lines]))


@router.get("/transfers", response_model=list[TransferSummaryOut], dependencies=VIEW)
def get_transfers(location_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                  limit: int = 100, offset: int = 0, session: Session = Depends(db_session)) -> object:
    return list_transfers(session, location_id=location_id, status=status_, limit=limit, offset=offset)


@router.get("/transfers/{transfer_id}", response_model=TransferOut, dependencies=VIEW)
def get_one_transfer(transfer_id: UUID, session: Session = Depends(db_session)) -> object:
    return _transfer_out(get_transfer(session, transfer_id))


@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferOut, dependencies=TRANSFER)
def post_dispatch(transfer_id: UUID, session: Session = Depends(db_session)) -> object:
    """Send the stock: it leaves the source location and is held in transit."""
    return _transfer_out(dispatch_transfer(session, transfer_id))


@router.post("/transfers/{transfer_id}/receive", response_model=TransferOut, dependencies=TRANSFER)
def post_receive(transfer_id: UUID, body: ReceiveIn | None = None, session: Session = Depends(db_session)) -> object:
    """Record what arrived. Differences need a reason and may need approval (status 'pending_approval')."""
    lines = [ReceivedLine(x.line_id, x.qty_received, x.reason_code_id) for x in body.lines] \
        if body and body.lines is not None else None
    return _transfer_out(receive_transfer(session, transfer_id, lines))


@router.post("/transfers/{transfer_id}/cancel", response_model=TransferOut, dependencies=TRANSFER)
def post_cancel_transfer(transfer_id: UUID, session: Session = Depends(db_session)) -> object:
    """Cancel a draft transfer."""
    return _transfer_out(cancel_transfer(session, transfer_id))


COUNT = [Depends(require_permission(STOCK_COUNT))]


@router.post("/counts", response_model=CountOut, status_code=status.HTTP_201_CREATED, dependencies=COUNT)
def post_count(body: CountStartIn, session: Session = Depends(db_session)) -> object:
    """Start counting a location: takes a snapshot of what the system holds."""
    return _count_out(start_count(session, company_id=body.company_id, location_id=body.location_id,
                                  product_ids=set(body.product_ids) if body.product_ids is not None else None))


@router.get("/counts", response_model=list[CountSummaryOut], dependencies=VIEW)
def get_counts(location_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
               limit: int = 100, offset: int = 0, session: Session = Depends(db_session)) -> object:
    return list_counts(session, location_id=location_id, status=status_, limit=limit, offset=offset)


@router.get("/counts/{count_id}", response_model=CountOut, dependencies=VIEW)
def get_one_count(count_id: UUID, session: Session = Depends(db_session)) -> object:
    return _count_out(get_count(session, count_id))


@router.post("/counts/{count_id}/entries", response_model=CountOut, dependencies=COUNT)
def post_count_entries(count_id: UUID, body: CountEntriesIn, session: Session = Depends(db_session)) -> object:
    """Enter counted quantities (again to correct). Each is compared with what the system held when it was counted."""
    return _count_out(record_counts(session, count_id, [
        CountEntry(e.product_id, e.counted_qty, e.batch_id, e.reason_code_id) for e in body.entries]))


@router.post("/counts/{count_id}/finish", response_model=CountOut, dependencies=COUNT)
def post_finish_count(count_id: UUID, body: CountFinishIn | None = None,
                      session: Session = Depends(db_session)) -> object:
    """End the counting and move the count to review."""
    return _count_out(finish_counting(session, count_id, uncounted_as_zero=bool(body and body.uncounted_as_zero)))


@router.post("/counts/{count_id}/submit", response_model=CountOut, dependencies=COUNT)
def post_submit_count(count_id: UUID, body: CountSubmitIn | None = None,
                      session: Session = Depends(db_session)) -> object:
    """Submit the reviewed count. Differences up to the company's threshold post at once; larger ones need approval."""
    return _count_out(submit_count(session, count_id, {r.line_id: r.reason_code_id for r in body.reasons}
                                   if body else None))


@router.post("/counts/{count_id}/cancel", response_model=CountOut, dependencies=COUNT)
def post_cancel_count(count_id: UUID, session: Session = Depends(db_session)) -> object:
    """Abandon a count that has not been posted."""
    return _count_out(cancel_count(session, count_id))


@router.get("/balances", response_model=list[BalanceOut], dependencies=VIEW)
def get_balances(location_id: UUID | None = None, product_id: UUID | None = None, branch_id: UUID | None = None,
                 include_zero: bool = False, limit: int = 100, offset: int = 0,
                 session: Session = Depends(db_session)) -> object:
    """Current stock per location, product and batch."""
    return [BalanceOut(location_id=b.location_id, location_code=loc.code, product_id=b.product_id, sku=sku,
                       product_name=name, batch_id=b.batch_id, quantity=b.quantity)
            for b, loc, sku, name in list_balances(session, location_id=location_id, product_id=product_id,
                                                   branch_id=branch_id, include_zero=include_zero, limit=limit,
                                                   offset=offset)]


@router.get("/movements", response_model=list[MovementOut], dependencies=VIEW)
def get_movements(location_id: UUID | None = None, product_id: UUID | None = None, source_id: UUID | None = None,
                  limit: int = 100, offset: int = 0, session: Session = Depends(db_session)) -> object:
    """The stock ledger, newest first. Costs and values need 'stock.cost'."""
    return [_movement_out(m) for m in list_movements(session, location_id=location_id, product_id=product_id,
                                                     source_id=source_id, limit=limit, offset=offset)]


@router.get("/products/{product_id}/stock", response_model=ProductStockOut, dependencies=VIEW)
def get_product_stock(product_id: UUID, session: Session = Depends(db_session)) -> object:
    """A product's total stock, with its average cost and value for users who may see costs."""
    s = product_stock(session, product_id)
    return ProductStockOut(product_id=s.product_id, company_id=s.company_id, quantity=s.quantity,
                           average_cost=s.average_cost, value=s.value)


def _movement_out(m: object) -> MovementOut:
    out = MovementOut.model_validate(m)
    if not can_see_cost(out.company_id, out.branch_id):
        out.unit_cost = out.value = None
    return out


def _adjustment_out(detail: AdjustmentDetail) -> AdjustmentOut:
    a = detail.adjustment
    return AdjustmentOut(
        id=a.id, number=a.number, company_id=a.company_id, location_id=a.location_id,
        reason_code_id=a.reason_code_id, note=a.note, status=a.status, created_by=a.created_by,
        approved_by=a.approved_by, posted_at=a.posted_at,
        lines=[AdjustmentLineOut.model_validate(x) for x in detail.lines])


def _transfer_out(detail: TransferDetail) -> TransferOut:
    t = detail.transfer
    return TransferOut(
        id=t.id, number=t.number, company_id=t.company_id, from_location_id=t.from_location_id,
        to_location_id=t.to_location_id, status=t.status, created_by=t.created_by, dispatched_at=t.dispatched_at,
        dispatched_by=t.dispatched_by, received_at=t.received_at, received_by=t.received_by,
        lines=[TransferLineOut.model_validate(x) for x in detail.lines])


def _count_out(detail: CountDetail) -> CountOut:
    c = detail.count
    return CountOut(
        id=c.id, number=c.number, company_id=c.company_id, location_id=c.location_id, status=c.status,
        snapshot_at=c.snapshot_at, created_by=c.created_by, approved_by=c.approved_by, posted_at=c.posted_at,
        lines=[CountLineOut.model_validate(x) for x in detail.lines])
