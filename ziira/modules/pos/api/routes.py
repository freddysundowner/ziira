"""HTTP endpoints of the POS module. Routes only convert HTTP to service calls."""

import uuid
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from ziira.modules.pos.api import schemas as sc
from ziira.modules.pos.permissions import (
    DEVICES_MANAGE,
    SALES_REFUND,
    SALES_SELL,
    SALES_VOID,
    TILL_MANAGE,
    TILL_REVIEW,
)
from ziira.modules.pos.services import catalog, devices, returns, sales, sync, tills
from ziira.sdk import (
    Forbidden,
    RequestContext,
    Session,
    current_context,
    db_session,
    idempotency_key_header,
    page_limit,
    page_offset,
    request_context,
)

router = APIRouter()


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


SELL = [Depends(any_of(SALES_SELL))]
TILL = [Depends(any_of(TILL_MANAGE, TILL_REVIEW))]
REVIEW = [Depends(any_of(TILL_REVIEW))]
DEVICE_ADMIN = [Depends(any_of(DEVICES_MANAGE))]
LOOK = [Depends(any_of(SALES_SELL, SALES_VOID, SALES_REFUND, TILL_REVIEW))]
VOID = [Depends(any_of(SALES_VOID))]
REFUND = [Depends(any_of(SALES_REFUND))]


# --------------------------------------------------------------------------- devices
@router.post("/devices", response_model=sc.DeviceKeyOut, status_code=status.HTTP_201_CREATED, dependencies=DEVICE_ADMIN)
def post_device(body: sc.DeviceIn, session: Session = Depends(db_session)) -> object:
    """Register a till, tablet or phone. The key in the answer is shown once."""
    device, key = devices.register_device(session, branch_id=body.branch_id, code=body.code, name=body.name,
                                          location_id=body.location_id)
    return sc.DeviceKeyOut.model_validate({**sc.DeviceOut.model_validate(device).model_dump(), "key": key})


@router.get("/devices", response_model=list[sc.DeviceOut], dependencies=[Depends(any_of(DEVICES_MANAGE, SALES_SELL))])
def get_devices(branch_id: UUID | None = None, session: Session = Depends(db_session)) -> object:
    return devices.list_devices(session, branch_id)


@router.patch("/devices/{device_id}/status", response_model=sc.DeviceOut, dependencies=DEVICE_ADMIN)
def patch_device_status(device_id: UUID, body: sc.DeviceStatusIn, session: Session = Depends(db_session)) -> object:
    """Block a lost device or let it work again."""
    return devices.set_status(session, device_id, body.status)


@router.post("/devices/{device_id}/rotate-key", response_model=sc.DeviceKeyOut, dependencies=DEVICE_ADMIN)
def post_rotate_key(device_id: UUID, session: Session = Depends(db_session)) -> object:
    """Give a device a new key; the old one stops working."""
    device, key = devices.rotate_key(session, device_id)
    return sc.DeviceKeyOut.model_validate({**sc.DeviceOut.model_validate(device).model_dump(), "key": key})


# --------------------------------------------------------------------------- tills
@router.post("/tills", response_model=sc.TillOut, status_code=status.HTTP_201_CREATED, dependencies=TILL)
def post_till(body: sc.TillOpenIn, response: Response, session: Session = Depends(db_session)) -> object:
    """Open your till on a device with a cash float."""
    till, existed = tills.open_till(session, body.device_id, body.opening_float, local_id=body.local_id)
    if existed:
        response.status_code = status.HTTP_200_OK
    return till


@router.get("/tills", response_model=list[sc.TillOut], dependencies=TILL)
def get_tills(branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
              business_date: date | None = None, limit: int = page_limit(50), offset: int = page_offset(),
              session: Session = Depends(db_session)) -> object:
    return tills.list_tills(session, branch_id=branch_id, status=status_, business_date=business_date, limit=limit,
                            offset=offset)


@router.get("/tills/{till_id}", response_model=sc.TillOut, dependencies=TILL)
def get_till(till_id: UUID, session: Session = Depends(db_session)) -> object:
    return tills.get_till(session, till_id)


@router.get("/tills/{till_id}/report", response_model=sc.TillReportOut, dependencies=TILL)
def get_till_report(till_id: UUID, session: Session = Depends(db_session)) -> object:
    """The till's figures so far (the X report; after closing, the Z report)."""
    return tills.report(session, tills.get_till(session, till_id))


@router.post("/tills/{till_id}/close", response_model=sc.TillReportOut, dependencies=TILL)
def post_close_till(till_id: UUID, body: sc.TillCloseIn, session: Session = Depends(db_session)) -> object:
    """Count the drawer and close the till. A difference needs a reason."""
    till = tills.close_till(session, till_id, body.counted_cash, reason_code_id=body.reason_code_id, note=body.note)
    return tills.report(session, till)


# --------------------------------------------------------------------------- catalog
@router.get("/catalog", response_model=list[sc.CatalogItemOut], dependencies=SELL)
def get_catalog(branch_id: UUID, location_id: UUID | None = None,
                search: str | None = Query(default=None, max_length=100), limit: int = page_limit(50),
                offset: int = page_offset(),
                session: Session = Depends(db_session)) -> object:
    """Products a till can sell, with today's price and (given a location) the stock."""
    return catalog.catalog(session, branch_id, location_id=location_id, search=search, limit=limit, offset=offset)


# --------------------------------------------------------------------------- sales
def _sale_out(view: sales.SaleView) -> sc.SaleOut:
    base = sc.SaleSummaryOut.model_validate(view.sale).model_dump()
    return sc.SaleOut(**base, subtotal=view.sale.subtotal, customer_id=view.sale.customer_id,
                      lines=[sc.SaleLineOut.model_validate(x) for x in view.lines],
                      payments=[sc.SalePaymentOut.model_validate(x) for x in view.payments], change=view.change,
                      warnings=view.warnings, replayed=view.replayed)


def _line(x: sc.SaleLineIn) -> sales.LineIn:
    return sales.LineIn(x.product_id, x.quantity, x.unit_price, x.discount, x.reason_code_id, x.batch_id)


def _payment(x: sc.SalePaymentIn) -> sales.PaymentIn:
    return sales.PaymentIn(x.method, x.amount, x.external_ref, x.payment_account_id)


@router.post("/sales", response_model=sc.SaleOut, status_code=status.HTTP_201_CREATED, dependencies=SELL)
def post_sale(body: sc.SaleIn, response: Response, key: str | None = Depends(idempotency_key_header),
              session: Session = Depends(db_session)) -> object:
    """Ring up a sale on your open till. A retry with the same `local_id` (or Idempotency-Key) returns the sale that
    was recorded the first time."""
    local_id = body.local_id
    if local_id is None and key is not None:
        local_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{current_context().tenant_id}:sale:{key}")
    view = sales.post_sale(session, till_session_id=body.till_session_id, lines=[_line(x) for x in body.lines],
                           payments=[_payment(x) for x in body.payments], local_id=local_id,
                           customer_id=body.customer_id)
    if view.replayed:
        response.status_code = status.HTTP_200_OK
    return _sale_out(view)


@router.get("/sales", response_model=list[sc.SaleSummaryOut], dependencies=LOOK)
def get_sales(branch_id: UUID | None = None, business_date: date | None = None,
              status_: str | None = Query(default=None, alias="status"), till_session_id: UUID | None = None,
              number: str | None = Query(default=None, max_length=60), limit: int = page_limit(50),
              offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return sales.list_sales(session, branch_id=branch_id, business_date=business_date, status=status_,
                            till_session_id=till_session_id, number=number, limit=limit, offset=offset)


@router.get("/sales/{sale_id}", response_model=sc.SaleOut, dependencies=LOOK)
def get_sale(sale_id: UUID, session: Session = Depends(db_session)) -> object:
    return _sale_out(sales.get_sale(session, sale_id))


@router.post("/sales/{sale_id}/void", response_model=sc.SaleOut, dependencies=VOID)
def post_void(sale_id: UUID, body: sc.VoidIn, session: Session = Depends(db_session)) -> object:
    """Cancel a sale while its till is open: payments, stock and books are reversed."""
    return _sale_out(sales.void_sale(session, sale_id, body.reason_code_id, body.note))


def _return_out(view: returns.ReturnView) -> sc.ReturnOut:
    base = sc.ReturnSummaryOut.model_validate(view.sales_return).model_dump()
    return sc.ReturnOut(**base, lines=[sc.ReturnLineOut.model_validate(x) for x in view.lines])


@router.post("/sales/{sale_id}/returns", response_model=sc.ReturnOut, status_code=status.HTTP_201_CREATED,
             dependencies=REFUND)
def post_return(sale_id: UUID, body: sc.ReturnIn, session: Session = Depends(db_session)) -> object:
    """Take goods back and refund them. Large refunds wait for approval (status 'pending_approval')."""
    view = returns.create_return(
        session, sale_id, lines=[(x.sale_line_id, x.quantity) for x in body.lines],
        reason_code_id=body.reason_code_id, refund_method=body.refund_method, note=body.note,
        restock_location_id=body.restock_location_id)
    return _return_out(view)


@router.get("/returns", response_model=list[sc.ReturnSummaryOut], dependencies=LOOK)
def get_returns(branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                limit: int = page_limit(50), offset: int = page_offset(),
                session: Session = Depends(db_session)) -> object:
    return returns.list_returns(session, branch_id=branch_id, status=status_, limit=limit, offset=offset)


@router.get("/returns/{return_id}", response_model=sc.ReturnOut, dependencies=LOOK)
def get_return(return_id: UUID, session: Session = Depends(db_session)) -> object:
    return _return_out(returns.get_return(session, return_id))


# --------------------------------------------------------------------------- offline sync
DeviceKey = Header(default=None, alias="X-Device-Key", description="The device's key; the cashier also signs in")


@router.get("/sync/snapshot", response_model=sc.SnapshotOut, dependencies=SELL)
def get_snapshot(x_device_key: str | None = DeviceKey, limit: int = Query(500, ge=1, le=1000),
                 offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    """Products, prices and stock for a device to sell from while offline. Page through with offset until
    `has_more` is false."""
    device = devices.authenticate(session, x_device_key)
    items = catalog.catalog(session, device.branch_id, location_id=device.location_id, limit=limit + 1, offset=offset)
    return sc.SnapshotOut(
        device_id=device.id, branch_id=device.branch_id, location_id=device.location_id, server_time=datetime.now(UTC),
        items=[sc.CatalogItemOut.model_validate(i) for i in items[:limit]], has_more=len(items) > limit)


@router.post("/sync/upload", response_model=sc.UploadOut, dependencies=SELL)
def post_upload(body: sc.UploadIn, x_device_key: str | None = DeviceKey,
                session: Session = Depends(db_session)) -> object:
    """Send what happened offline, in order. Safe to repeat: operations already accepted are answered, not redone."""
    device = devices.authenticate(session, x_device_key)
    ops = [_op(x) for x in body.ops]
    results = sync.upload(session, device, ops)
    return sc.UploadOut(results=[sc.OpResultOut(**r.__dict__) for r in results], server_time=datetime.now(UTC))


def _op(x: sc.TillOpenOp | sc.SaleOp | sc.TillCloseOp) -> sync.SyncOp:
    ref = sync.TillRef(x.till_session_id, x.till_local_id)
    raw = x.model_dump(mode="json")
    if isinstance(x, sc.TillOpenOp):
        return sync.SyncOp("till_open", x.local_id, x.at, ref, opening_float=x.opening_float, raw=raw)
    if isinstance(x, sc.SaleOp):
        return sync.SyncOp("sale", x.local_id, x.at, ref, lines=[_line(i) for i in x.lines],
                           payments=[_payment(i) for i in x.payments], number=x.number, customer_id=x.customer_id,
                           raw=raw)
    return sync.SyncOp("till_close", x.local_id, x.at, ref, counted_cash=x.counted_cash,
                       reason_code_id=x.reason_code_id, note=x.note, raw=raw)


@router.get("/sync/rejections", response_model=list[sc.RejectionOut], dependencies=REVIEW)
def get_rejections(include_resolved: bool = False, limit: int = page_limit(50), offset: int = page_offset(),
                   session: Session = Depends(db_session)) -> object:
    """Offline operations the server could not accept (kept whole, so nothing is lost)."""
    return sync.list_rejections(session, include_resolved=include_resolved, limit=limit, offset=offset)


