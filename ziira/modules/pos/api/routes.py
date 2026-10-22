"""HTTP endpoints of the POS module. Routes only convert HTTP to service calls."""

import uuid
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import PlainTextResponse

from ziira.modules.pos.api import schemas as sc
from ziira.modules.pos.permissions import (
    DEVICES_MANAGE,
    INVOICES_MANAGE,
    RECEIVABLES_MANAGE,
    RECEIVABLES_VIEW,
    SALES_REFUND,
    SALES_SELL,
    SALES_VOID,
    TILL_MANAGE,
    TILL_REVIEW,
)
from ziira.modules.pos.repository.models import HeldSale
from ziira.modules.pos.services import (
    catalog,
    customer_receipts,
    devices,
    documents,
    invoices,
    printing,
    receivables,
    returns,
    sales,
    sync,
    tills,
)
from ziira.modules.pos.services import (
    held as held_sales,
)
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    RequestContext,
    Session,
    ValidationFailed,
    current_context,
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
INVOICE = [Depends(any_of(INVOICES_MANAGE))]
RECEIVABLES = [Depends(any_of(INVOICES_MANAGE, RECEIVABLES_VIEW))]
BALANCE = [Depends(any_of(INVOICES_MANAGE, RECEIVABLES_VIEW, RECEIVABLES_MANAGE))]
RECEIVE = [Depends(any_of(RECEIVABLES_MANAGE))]


# --------------------------------------------------------------------------- devices
@router.post("/devices", response_model=sc.DeviceKeyOut, status_code=status.HTTP_201_CREATED, dependencies=DEVICE_ADMIN)
def post_device(body: sc.DeviceIn, session: Session = DB_SESSION) -> object:
    """Register a till, tablet or phone. The key in the answer is shown once."""
    device, key = devices.register_device(session, branch_id=body.branch_id, code=body.code, name=body.name,
                                          location_id=body.location_id)
    return sc.DeviceKeyOut.model_validate({**sc.DeviceOut.model_validate(device).model_dump(), "key": key})


@router.get("/devices", response_model=list[sc.DeviceOut], dependencies=[Depends(any_of(DEVICES_MANAGE, SALES_SELL))])
def get_devices(branch_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    return devices.list_devices(session, branch_id)


@router.patch("/devices/{device_id}", response_model=sc.DeviceOut, dependencies=DEVICE_ADMIN)
def patch_device(device_id: UUID, body: sc.DeviceUpdateIn, session: Session = DB_SESSION) -> object:
    """Change the store a device sells from (not while a till is open on it)."""
    return devices.set_location(session, device_id, body.location_id)


@router.patch("/devices/{device_id}/status", response_model=sc.DeviceOut, dependencies=DEVICE_ADMIN)
def patch_device_status(device_id: UUID, body: sc.DeviceStatusIn, session: Session = DB_SESSION) -> object:
    """Block a lost device or let it work again."""
    return devices.set_status(session, device_id, body.status)


@router.post("/devices/{device_id}/rotate-key", response_model=sc.DeviceKeyOut, dependencies=DEVICE_ADMIN)
def post_rotate_key(device_id: UUID, session: Session = DB_SESSION) -> object:
    """Give a device a new key; the old one stops working."""
    device, key = devices.rotate_key(session, device_id)
    return sc.DeviceKeyOut.model_validate({**sc.DeviceOut.model_validate(device).model_dump(), "key": key})


# --------------------------------------------------------------------------- tills
@router.post("/tills", response_model=sc.TillOut, status_code=status.HTTP_201_CREATED, dependencies=TILL)
def post_till(body: sc.TillOpenIn, response: Response, session: Session = DB_SESSION) -> object:
    """Open your till on a device with a cash float."""
    till, existed = tills.open_till(session, body.device_id, body.opening_float, local_id=body.local_id, resume=True)
    if existed:
        response.status_code = status.HTTP_200_OK
    return till


@router.get("/tills", response_model=list[sc.TillOut], dependencies=TILL)
def get_tills(branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
              business_date: date | None = None, limit: int = page_limit(50), offset: int = page_offset(),
              session: Session = DB_SESSION) -> object:
    return tills.list_tills(session, branch_id=branch_id, status=status_, business_date=business_date, limit=limit,
                            offset=offset)


@router.get("/tills/{till_id}", response_model=sc.TillOut, dependencies=TILL)
def get_till(till_id: UUID, session: Session = DB_SESSION) -> object:
    return tills.get_till(session, till_id)


@router.get("/tills/{till_id}/report", response_model=sc.TillReportOut, dependencies=TILL)
def get_till_report(till_id: UUID, session: Session = DB_SESSION) -> object:
    """The till's figures so far (the X report; after closing, the Z report)."""
    return tills.report(session, tills.get_till(session, till_id))


@router.post("/tills/{till_id}/close", response_model=sc.TillReportOut, dependencies=TILL)
def post_close_till(till_id: UUID, body: sc.TillCloseIn, session: Session = DB_SESSION) -> object:
    """Count the drawer and close the till. A difference needs a reason."""
    till = tills.close_till(session, till_id, body.counted_cash, reason_code_id=body.reason_code_id, note=body.note)
    return tills.report(session, till)


# --------------------------------------------------------------------------- held sales
def _held_out(held: HeldSale) -> sc.HeldSaleOut:
    data = held.payload
    return sc.HeldSaleOut(
        id=held.id, local_id=held.local_id, till_session_id=held.till_session_id, label=held.label,
        customer_id=held.customer_id, customer_name=data.get("customer_name", ""),
        customer_phone=data.get("customer_phone", ""), note=held.note,
        lines=[sc.HeldLine.model_validate(x) for x in data.get("lines", [])],
        status=held.status, created_at=held.created_at)  # type: ignore[arg-type]


@router.post("/tills/{till_id}/held", response_model=sc.HeldSaleOut, status_code=status.HTTP_201_CREATED,
             dependencies=SELL)
def post_held(till_id: UUID, body: sc.HeldSaleIn, response: Response, session: Session = DB_SESSION) -> object:
    """Park the cart on your open till. A draft: no stock moves and nothing is booked. Sending the same `local_id`
    again returns the held sale already kept."""
    payload = {"lines": [x.model_dump() for x in body.lines], "customer_name": body.customer_name,
               "customer_phone": body.customer_phone}
    held, existed = held_sales.hold(session, till_id, local_id=body.local_id, label=body.label,
                                    customer_id=body.customer_id, note=body.note, payload=payload)
    if existed:
        response.status_code = status.HTTP_200_OK
    return _held_out(held)


@router.get("/tills/{till_id}/held", response_model=list[sc.HeldSaleOut], dependencies=SELL)
def get_held_sales(till_id: UUID, status_: Literal["held", "resumed", "discarded", "expired", "all"] = Query(
        default="held", alias="status"), session: Session = DB_SESSION) -> object:
    """The sales on hold at a till (or `status=all`)."""
    return [_held_out(h) for h in held_sales.list_held(session, till_id, status_)]


@router.post("/held/{held_id}/resume", response_model=sc.HeldSaleOut, dependencies=SELL)
def post_resume_held(held_id: UUID, session: Session = DB_SESSION) -> object:
    """Take a held sale back to the screen; it is no longer on hold. Safe to repeat. `held_id` may also be the
    `local_id` the terminal made when it held the sale."""
    return _held_out(held_sales.resume(session, held_id))


@router.post("/held/{held_id}/discard", response_model=sc.HeldSaleOut, dependencies=SELL)
def post_discard_held(held_id: UUID, session: Session = DB_SESSION) -> object:
    """Throw a held sale away. Safe to repeat. `held_id` may also be the terminal's `local_id`."""
    return _held_out(held_sales.discard(session, held_id))


# --------------------------------------------------------------------------- catalog
@router.get("/catalog", response_model=list[sc.CatalogItemOut], dependencies=SELL)
def get_catalog(branch_id: UUID, location_id: UUID | None = None,
                search: str | None = Query(default=None, max_length=100), limit: int = page_limit(50),
                offset: int = page_offset(), barcode: str | None = Query(default=None, max_length=64),
                session: Session = DB_SESSION) -> object:
    """Products a till can sell, with today's price and (given a location) the stock. `barcode` keeps only the
    product with that scanned code. Page size up to 500 (the whole list, for a device that keeps a copy)."""
    return catalog.catalog(session, branch_id, location_id=location_id, search=search, limit=limit, offset=offset,
                           barcode=barcode)


@router.get("/receipt-settings", response_model=sc.ReceiptSettingsOut, dependencies=SELL)
def get_receipt_settings(branch_id: UUID, session: Session = DB_SESSION) -> object:
    """The lines a till receipt has at the top and the foot, for a terminal that prints receipts while offline."""
    header, footer = printing.receipt_template(session, branch_id)
    return sc.ReceiptSettingsOut(header=header, footer=footer)


# --------------------------------------------------------------------------- sales
def _sale_out(view: sales.SaleView) -> sc.SaleOut:
    base = sc.SaleSummaryOut.model_validate(view.sale).model_dump()
    return sc.SaleOut(**base, subtotal=view.sale.subtotal, customer_id=view.sale.customer_id,
                      lines=[sc.SaleLineOut.model_validate(x) for x in view.lines],
                      payments=[sc.SalePaymentOut.model_validate(x) for x in view.payments], change=view.change,
                      warnings=view.warnings, replayed=view.replayed)


def _line(x: sc.SaleLineIn) -> sales.LineIn:
    return sales.LineIn(x.product_id, x.quantity, x.unit_price, x.discount, x.reason_code_id, x.batch_id,
                         x.reference)


def _payment(x: sc.SalePaymentIn) -> sales.PaymentIn:
    return sales.PaymentIn(x.method, x.amount, x.external_ref, x.payment_account_id)


@router.post("/sales", response_model=sc.SaleOut, status_code=status.HTTP_201_CREATED, dependencies=SELL)
def post_sale(body: sc.SaleIn, response: Response, key: str | None = Depends(idempotency_key_header),
              session: Session = DB_SESSION) -> object:
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
              offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    return sales.list_sales(session, branch_id=branch_id, business_date=business_date, status=status_,
                            till_session_id=till_session_id, number=number, limit=limit, offset=offset)


@router.get("/sales/{sale_id}", response_model=sc.SaleOut, dependencies=LOOK)
def get_sale(sale_id: UUID, session: Session = DB_SESSION) -> object:
    return _sale_out(sales.get_sale(session, sale_id))


@router.post("/sales/{sale_id}/void", response_model=sc.SaleOut, dependencies=VOID)
def post_void(sale_id: UUID, body: sc.VoidIn, session: Session = DB_SESSION) -> object:
    """Cancel a sale while its till is open: payments, stock and books are reversed."""
    return _sale_out(sales.void_sale(session, sale_id, body.reason_code_id, body.note))


def _return_out(view: returns.ReturnView) -> sc.ReturnOut:
    base = sc.ReturnSummaryOut.model_validate(view.sales_return).model_dump()
    return sc.ReturnOut(**base, lines=[sc.ReturnLineOut.model_validate(x) for x in view.lines])


@router.post("/sales/{sale_id}/returns", response_model=sc.ReturnOut, status_code=status.HTTP_201_CREATED,
             dependencies=REFUND)
def post_return(sale_id: UUID, body: sc.ReturnIn, session: Session = DB_SESSION) -> object:
    """Take goods back and refund them. Large refunds wait for approval (status 'pending_approval')."""
    view = returns.create_return(
        session, sale_id, lines=[(x.sale_line_id, x.quantity) for x in body.lines],
        reason_code_id=body.reason_code_id, refund_method=body.refund_method, note=body.note,
        restock_location_id=body.restock_location_id)
    return _return_out(view)


@router.get("/returns", response_model=list[sc.ReturnSummaryOut], dependencies=LOOK)
def get_returns(branch_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                limit: int = page_limit(50), offset: int = page_offset(),
                session: Session = DB_SESSION) -> object:
    return returns.list_returns(session, branch_id=branch_id, status=status_, limit=limit, offset=offset)


@router.get("/returns/{return_id}", response_model=sc.ReturnOut, dependencies=LOOK)
def get_return(return_id: UUID, session: Session = DB_SESSION) -> object:
    return _return_out(returns.get_return(session, return_id))


# --------------------------------------------------------------------------- offline sync
DeviceKey = Header(default=None, alias="X-Device-Key", description="The device's key; the cashier also signs in")


@router.get("/sync/snapshot", response_model=sc.SnapshotOut, dependencies=SELL)
def get_snapshot(x_device_key: str | None = DeviceKey, limit: int = Query(500, ge=1, le=1000),
                 offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    """Products, prices and stock for a device to sell from while offline. Page through with offset until
    `has_more` is false."""
    device = devices.authenticate(session, x_device_key)
    items = catalog.catalog(session, device.branch_id, location_id=device.location_id, limit=limit + 1, offset=offset)
    return sc.SnapshotOut(
        device_id=device.id, branch_id=device.branch_id, location_id=device.location_id, server_time=datetime.now(UTC),
        items=[sc.CatalogItemOut.model_validate(i) for i in items[:limit]], has_more=len(items) > limit)


@router.post("/sync/upload", response_model=sc.UploadOut, dependencies=SELL)
def post_upload(body: sc.UploadIn, x_device_key: str | None = DeviceKey,
                session: Session = DB_SESSION) -> object:
    """Send what happened offline, in order. Safe to repeat: operations already accepted are answered, not redone.
    With the device key anything goes; without it (a browser terminal) only sales for the cashier's own till, named by
    `till_session_id`, are accepted."""
    ops = [_op(x) for x in body.ops]
    if x_device_key:
        device = devices.authenticate(session, x_device_key)
    else:       # a browser terminal has no device key: it may send sales for its own till (named by id)
        only_sales = all(isinstance(x, sc.SaleOp) and x.till_session_id is not None for x in body.ops)
        device = devices.of_own_till(session, {x.till_session_id for x in body.ops if x.till_session_id}
                                     if only_sales and body.ops else set())
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
                   session: Session = DB_SESSION) -> object:
    """Offline operations the server could not accept (kept whole, so nothing is lost)."""
    return sync.list_rejections(session, include_resolved=include_resolved, limit=limit, offset=offset)




# --------------------------------------------------------------------------- invoices
def _invoice_out(view: invoices.InvoiceView) -> sc.InvoiceOut:
    return sc.InvoiceOut(**sc.InvoiceSummaryOut.model_validate(view.invoice).model_dump(), notes=view.invoice.notes,
                         cancel_reason=view.invoice.cancel_reason,
                         lines=[sc.InvoiceLineOut.model_validate(x) for x in view.lines])


@router.post("/invoices", response_model=sc.InvoiceOut, status_code=status.HTTP_201_CREATED, dependencies=INVOICE)
def post_invoice(body: sc.InvoiceIn, session: Session = DB_SESSION) -> object:
    """Invoice a business customer and deliver the goods (stock leaves; the books debit accounts receivable)."""
    return _invoice_out(invoices.issue_invoice(
        session, customer_id=body.customer_id, branch_id=body.branch_id, location_id=body.location_id,
        issue_date=body.issue_date, terms_days=body.terms_days, notes=body.notes,
        lines=[invoices.InvoiceLineIn(x.product_id, x.quantity, x.unit_price, x.discount, x.reason_code_id,
                                      x.batch_id, x.order_line_id) for x in body.lines]))


@router.get("/invoices", response_model=list[sc.InvoiceSummaryOut], dependencies=RECEIVABLES)
def get_invoices(customer_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                 due_before: date | None = None, number: str | None = Query(default=None, max_length=60),
                 limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    return invoices.list_invoices(session, customer_id=customer_id, status=status_, due_before=due_before,
                                  number=number, limit=limit, offset=offset)


@router.get("/invoices/{invoice_id}", response_model=sc.InvoiceOut, dependencies=RECEIVABLES)
def get_invoice(invoice_id: UUID, session: Session = DB_SESSION) -> object:
    return _invoice_out(invoices.get_invoice(session, invoice_id))


@router.post("/invoices/{invoice_id}/cancel", response_model=sc.InvoiceOut, dependencies=INVOICE)
def post_cancel_invoice(invoice_id: UUID, body: sc.ReasonIn, session: Session = DB_SESSION) -> object:
    """Cancel an invoice nothing has been paid or credited on; the goods return to stock."""
    return _invoice_out(invoices.cancel_invoice(session, invoice_id, body.reason))


# --------------------------------------------------------------------------- receipts from customers
def _receipt_out(view: customer_receipts.ReceiptView) -> sc.ReceiptOut:
    return sc.ReceiptOut(**sc.ReceiptSummaryOut.model_validate(view.receipt).model_dump(),
                         allocations=[sc.AllocationOut.model_validate(x) for x in view.allocations])


@router.post("/receipts", response_model=sc.ReceiptOut, status_code=status.HTTP_201_CREATED, dependencies=RECEIVE)
def post_receipt(body: sc.ReceiptIn, session: Session = DB_SESSION) -> object:
    """Record a customer's payment against their invoices (the oldest first unless you name them)."""
    return _receipt_out(customer_receipts.receive_payment(
        session, customer_id=body.customer_id, amount=body.amount, method=body.method, branch_id=body.branch_id,
        payment_account_id=body.payment_account_id, external_ref=body.external_ref, received_on=body.received_on,
        allocations=[(x.invoice_id, x.amount) for x in body.allocations] if body.allocations is not None else None,
        till_session_id=body.till_session_id, hold_balance=body.hold_balance))


@router.get("/receipts", response_model=list[sc.ReceiptSummaryOut], dependencies=RECEIVABLES)
def get_receipts(customer_id: UUID | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                 session: Session = DB_SESSION) -> object:
    return customer_receipts.list_receipts(session, customer_id=customer_id, limit=limit, offset=offset)


@router.get("/receipts/{receipt_id}", response_model=sc.ReceiptOut, dependencies=RECEIVABLES)
def get_receipt(receipt_id: UUID, session: Session = DB_SESSION) -> object:
    return _receipt_out(customer_receipts.get_receipt(session, receipt_id))


@router.post("/receipts/{receipt_id}/reverse", response_model=sc.ReceiptOut, dependencies=RECEIVE)
def post_reverse_receipt(receipt_id: UUID, body: sc.ReasonIn, session: Session = DB_SESSION) -> object:
    """Cancel a customer's payment (recorded wrongly, or bounced): the invoices are owed again."""
    return _receipt_out(customer_receipts.reverse_receipt(session, receipt_id, body.reason))


@router.post("/invoices/{invoice_id}/returns", response_model=sc.ReturnOut, status_code=status.HTTP_201_CREATED,
             dependencies=REFUND)
def post_invoice_return(invoice_id: UUID, body: sc.InvoiceReturnIn, session: Session = DB_SESSION) -> object:
    """Take goods back from an invoice. A credit note while the invoice is unpaid; a refund once it is paid."""
    return _return_out(returns.create_invoice_return(
        session, invoice_id, lines=[(x.invoice_line_id, x.quantity) for x in body.lines],
        reason_code_id=body.reason_code_id, refund_method=body.refund_method, note=body.note,
        restock_location_id=body.restock_location_id))


# --------------------------------------------------------------------------- quotations and sales orders
def _doc_out(view: documents.DocView) -> sc.DocOut:
    return sc.DocOut(**sc.DocSummaryOut.model_validate(view.document).model_dump(), notes=view.document.notes,
                     lines=[sc.DocLineOut.model_validate(x) for x in view.lines])


def _doc_lines(items: list[sc.DocLineIn]) -> list[documents.DocLineIn]:
    return [documents.DocLineIn(x.product_id, x.quantity, x.unit_price, x.discount, x.reason_code_id) for x in items]


@router.post("/quotations", response_model=sc.DocOut, status_code=status.HTTP_201_CREATED, dependencies=INVOICE)
def post_quotation(body: sc.QuotationIn, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.create_quotation(
        session, customer_id=body.customer_id, lines=_doc_lines(body.lines), branch_id=body.branch_id,
        location_id=body.location_id, valid_until=body.valid_until, terms_days=body.terms_days, notes=body.notes))


@router.get("/quotations", response_model=list[sc.DocSummaryOut], dependencies=RECEIVABLES)
def get_quotations(customer_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
                   limit: int = page_limit(50), offset: int = page_offset(),
                   session: Session = DB_SESSION) -> object:
    return documents.list_documents(session, kind="quotation", customer_id=customer_id, status=status_, limit=limit,
                                    offset=offset)


@router.get("/quotations/{document_id}", response_model=sc.DocOut, dependencies=RECEIVABLES)
def get_quotation(document_id: UUID, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.get_document(session, document_id, "quotation"))


@router.put("/quotations/{document_id}", response_model=sc.DocOut, dependencies=INVOICE)
def put_quotation(document_id: UUID, body: sc.DocUpdate, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.update_document(
        session, document_id, lines=_doc_lines(body.lines) if body.lines is not None else None, notes=body.notes,
        valid_until=body.valid_until))


@router.post("/quotations/{document_id}/send", response_model=sc.DocOut, dependencies=INVOICE)
def post_send_quotation(document_id: UUID, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.send_quotation(session, document_id))


@router.post("/quotations/{document_id}/accept", response_model=sc.DocOut, dependencies=INVOICE)
def post_accept_quotation(document_id: UUID, session: Session = DB_SESSION) -> object:
    """The customer accepted: returns the sales order made from it."""
    return _doc_out(documents.confirm_quotation(session, document_id))


@router.post("/quotations/{document_id}/cancel", response_model=sc.DocOut, dependencies=INVOICE)
def post_cancel_quotation(document_id: UUID, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.cancel_document(session, document_id))


@router.post("/orders", response_model=sc.DocOut, status_code=status.HTTP_201_CREATED, dependencies=INVOICE)
def post_order(body: sc.OrderIn, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.create_order(
        session, customer_id=body.customer_id, lines=_doc_lines(body.lines), branch_id=body.branch_id,
        location_id=body.location_id, terms_days=body.terms_days, notes=body.notes))


@router.get("/orders", response_model=list[sc.DocSummaryOut], dependencies=RECEIVABLES)
def get_orders(customer_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
               limit: int = page_limit(50), offset: int = page_offset(),
               session: Session = DB_SESSION) -> object:
    return documents.list_documents(session, kind="order", customer_id=customer_id, status=status_, limit=limit,
                                    offset=offset)


@router.get("/orders/{document_id}", response_model=sc.DocOut, dependencies=RECEIVABLES)
def get_order(document_id: UUID, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.get_document(session, document_id, "order"))


@router.put("/orders/{document_id}", response_model=sc.DocOut, dependencies=INVOICE)
def put_order(document_id: UUID, body: sc.DocUpdate, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.update_document(
        session, document_id, lines=_doc_lines(body.lines) if body.lines is not None else None, notes=body.notes))


@router.post("/orders/{document_id}/submit", response_model=sc.DocOut, dependencies=INVOICE)
def post_submit_order(document_id: UUID, session: Session = DB_SESSION) -> object:
    """Confirm the order (an approver may need to agree first)."""
    return _doc_out(documents.submit_order(session, document_id))


@router.post("/orders/{document_id}/cancel", response_model=sc.DocOut, dependencies=INVOICE)
def post_cancel_order(document_id: UUID, session: Session = DB_SESSION) -> object:
    return _doc_out(documents.cancel_document(session, document_id))


@router.post("/orders/{document_id}/deliver", response_model=sc.InvoiceOut, status_code=status.HTTP_201_CREATED,
             dependencies=INVOICE)
def post_deliver_order(document_id: UUID, body: sc.DeliverIn, session: Session = DB_SESSION) -> object:
    """Deliver the order (all that is left, or the quantities named) and invoice it at the agreed prices."""
    return _invoice_out(documents.invoice_order(
        session, document_id, lines=[(x.order_line_id, x.quantity) for x in body.lines] if body.lines is not None
        else None, location_id=body.location_id, issue_date=body.issue_date))


# --------------------------------------------------------------------------- what customers owe
@router.get("/receivables/ageing", response_model=sc.AgeingOut, dependencies=RECEIVABLES)
def get_ageing(as_of: date | None = None, customer_id: UUID | None = None,
               session: Session = DB_SESSION) -> object:
    """What customers owe on unpaid invoices, aged by due date."""
    return receivables.ageing(session, as_of=as_of, customer_id=customer_id)


@router.get("/receivables/reminders", response_model=list[sc.ReminderDueOut], dependencies=RECEIVABLES)
def get_reminders_due(as_of: date | None = None, min_days_overdue: int = Query(1, ge=0, le=3650),
                      repeat_days: int = Query(7, ge=0, le=365), limit: int = Query(100, ge=1, le=500),
                      session: Session = DB_SESSION) -> object:
    """Overdue invoices that have not been chased lately."""
    return receivables.due_reminders(session, as_of=as_of, min_days_overdue=min_days_overdue,
                                     repeat_days=repeat_days, limit=limit)


@router.post("/invoices/{invoice_id}/reminders", response_model=sc.ReminderOut,
             status_code=status.HTTP_201_CREATED, dependencies=RECEIVABLES)
def post_reminder(invoice_id: UUID, body: sc.ReminderIn, session: Session = DB_SESSION) -> object:
    """Note that the customer was reminded about this invoice."""
    return receivables.record_reminder(session, invoice_id, channel=body.channel, note=body.note)


@router.post("/invoices/{invoice_id}/send-reminder", response_model=sc.ReminderSentOut,
             status_code=status.HTTP_201_CREATED, dependencies=BALANCE)
def post_send_reminder(invoice_id: UUID, body: sc.SendReminderIn, session: Session = DB_SESSION) -> object:
    """Message the customer about this invoice now (SMS or email)."""
    return receivables.send_reminder(session, invoice_id, channel=body.channel)


@router.post("/receivables/send-reminders", response_model=sc.RemindersSentOut, dependencies=RECEIVABLES)
def post_send_reminders(body: sc.SendRemindersIn, session: Session = DB_SESSION) -> object:
    """Chase every overdue invoice that has not been chased lately."""
    return receivables.send_due_reminders(session, channel=body.channel, min_days_overdue=body.min_days_overdue,
                                          repeat_days=body.repeat_days, limit=body.limit)


@router.get("/customers/{customer_id}/statement", response_model=sc.StatementOut, dependencies=RECEIVABLES)
def get_statement(customer_id: UUID, date_from: date | None = None, date_to: date | None = None,
                  session: Session = DB_SESSION) -> object:
    """A customer's account: invoices, payments and credit notes with a running balance."""
    return receivables.statement(session, customer_id, date_from=date_from, date_to=date_to)


@router.get("/customers/{customer_id}/balance", response_model=sc.BalanceOut, dependencies=BALANCE)
def get_balance(customer_id: UUID, session: Session = DB_SESSION) -> object:
    """What the customer owes, their credit limit and what they can still take on account."""
    return receivables.balance(session, customer_id)


# --------------------------------------------------------------------------- money held on account
@router.post("/customers/{customer_id}/apply-credit", response_model=list[sc.AppliedOut], dependencies=RECEIVE)
def post_apply_credit(customer_id: UUID, body: sc.ApplyCreditIn, session: Session = DB_SESSION) -> object:
    """Use money the customer paid in advance to pay their invoices (the oldest first unless you name them)."""
    done = customer_receipts.apply_credit(
        session, customer_id,
        allocations=[(x.invoice_id, x.amount) for x in body.allocations] if body.allocations is not None else None)
    return [sc.AppliedOut(**x) for x in done]  # type: ignore[arg-type]


@router.post("/receipts/{receipt_id}/refund", response_model=sc.RefundOut, status_code=status.HTTP_201_CREATED,
             dependencies=RECEIVE)
def post_refund_advance(receipt_id: UUID, body: sc.RefundIn, session: Session = DB_SESSION) -> object:
    """Give back money the customer paid in advance and has not used."""
    return customer_receipts.refund_advance(
        session, receipt_id, amount=body.amount, method=body.method, reason=body.reason,
        payment_account_id=body.payment_account_id, external_ref=body.external_ref).refund


@router.get("/refunds", response_model=list[sc.RefundOut], dependencies=RECEIVABLES)
def get_refunds(customer_id: UUID | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                session: Session = DB_SESSION) -> object:
    return customer_receipts.list_refunds(session, customer_id=customer_id, limit=limit, offset=offset)


@router.get("/refunds/{refund_id}", response_model=sc.RefundOut, dependencies=RECEIVABLES)
def get_refund(refund_id: UUID, session: Session = DB_SESSION) -> object:
    return customer_receipts.get_refund(session, refund_id).refund


@router.post("/refunds/{refund_id}/reverse", response_model=sc.RefundOut, dependencies=RECEIVE)
def post_reverse_refund(refund_id: UUID, body: sc.ReasonIn, session: Session = DB_SESSION) -> object:
    """Cancel a refund: the customer holds that money on account again."""
    return customer_receipts.reverse_refund(session, refund_id, body.reason).refund


# --------------------------------------------------------------------------- printing
Format = Query(default="json", pattern="^(json|text|html)$", description="json, text (thermal printer) or html")
Width = Query(default=40, description="Characters across for text: 32, 40 or 48")
PRINTED: dict[int | str, dict[str, object]] = {200: {"model": sc.PrintOut}}


def _printed(doc, fmt: str, width: int) -> Response:  # type: ignore[no-untyped-def]
    if fmt == "json":
        return Response(sc.PrintOut(
            title=doc.title, number=doc.number, header=doc.header, meta=[[a, b] for a, b in doc.meta],
            lines=[sc.PrintLineOut(**vars(x)) for x in doc.lines], vat=[sc.PrintVatOut(**vars(x)) for x in doc.vat],
            totals=[sc.PrintLabelOut(label=a, amount=b) for a, b in doc.totals],
            payments=[sc.PrintLabelOut(label=a, amount=b) for a, b in doc.payments], notes=doc.notes,
            footer=doc.footer, is_copy=doc.copy).model_dump_json(), media_type="application/json")
    if width not in (32, 40, 48):
        raise ValidationFailed("width must be 32, 40 or 48")
    body = printing.render(doc, fmt, width)
    return PlainTextResponse(body) if fmt == "text" else Response(body, media_type="text/html; charset=utf-8")


@router.get("/sales/{sale_id}/receipt", response_model=None, responses=PRINTED, dependencies=LOOK)
def print_sale(sale_id: UUID, format: str = Format, width: int = Width, copy: bool = False,
               session: Session = DB_SESSION) -> Response:
    return _printed(printing.sale_document(session, sale_id, copy=copy), format, width)


@router.get("/invoices/{invoice_id}/print", response_model=None, responses=PRINTED, dependencies=RECEIVABLES)
def print_invoice(invoice_id: UUID, format: str = Format, width: int = Width, copy: bool = False,
                  session: Session = DB_SESSION) -> Response:
    return _printed(printing.invoice_document(session, invoice_id, copy=copy), format, width)


@router.get("/receipts/{receipt_id}/print", response_model=None, responses=PRINTED, dependencies=RECEIVABLES)
def print_receipt(receipt_id: UUID, format: str = Format, width: int = Width, copy: bool = False,
                  session: Session = DB_SESSION) -> Response:
    return _printed(printing.receipt_document(session, receipt_id, copy=copy), format, width)
