"""HTTP endpoints of the Purchasing module. Routes only convert HTTP to service calls."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from ziira.modules.purchasing.api import schemas as sc
from ziira.modules.purchasing.permissions import (
    ALL,
    BILLS_APPROVE,
    BILLS_MANAGE,
    BILLS_PAY,
    GOODS_RECEIVE,
    GOODS_RETURN,
    PO_CREATE,
    SUPPLIER_BANK_CONFIRM,
    SUPPLIER_BANK_EDIT,
    SUPPLIERS_MANAGE,
)
from ziira.modules.purchasing.repository import purchasing_repo
from ziira.modules.purchasing.services import bills, credit_notes, orders, receipts, returns, suppliers
from ziira.sdk import (
    Forbidden,
    RequestContext,
    Session,
    db_session,
    page_limit,
    page_offset,
    request_context,
)

router = APIRouter()
CREATED = status.HTTP_201_CREATED


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(*ALL))]
SUPPLIER_ADMIN = [Depends(any_of(SUPPLIERS_MANAGE))]
BANK_EDIT = [Depends(any_of(SUPPLIER_BANK_EDIT))]
BANK_CONFIRM = [Depends(any_of(SUPPLIER_BANK_CONFIRM, SUPPLIER_BANK_EDIT))]
ORDERS = [Depends(any_of(PO_CREATE))]
RECEIVE = [Depends(any_of(GOODS_RECEIVE))]
RETURN = [Depends(any_of(GOODS_RETURN))]
BILLS = [Depends(any_of(BILLS_MANAGE))]
APPROVE_BILL = [Depends(any_of(BILLS_APPROVE))]
PAY = [Depends(any_of(BILLS_PAY))]


# --------------------------------------------------------------------------- suppliers
@router.post("/suppliers", response_model=sc.SupplierOut, status_code=CREATED, dependencies=SUPPLIER_ADMIN)
def post_supplier(body: sc.SupplierIn, session: Session = Depends(db_session)) -> object:
    return suppliers.create_supplier(session, **body.model_dump())


@router.get("/suppliers", response_model=list[sc.SupplierOut], dependencies=VIEW)
def get_suppliers(search: str | None = Query(default=None, max_length=100),
                  status_: str | None = Query(default=None, alias="status"), limit: int = page_limit(50),
                  offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return suppliers.list_suppliers(session, search=search, status=status_, limit=limit, offset=offset)


@router.get("/suppliers/{supplier_id}", response_model=sc.SupplierOut, dependencies=VIEW)
def get_supplier(supplier_id: UUID, session: Session = Depends(db_session)) -> object:
    return suppliers.get_supplier(session, supplier_id)


@router.patch("/suppliers/{supplier_id}", response_model=sc.SupplierOut, dependencies=SUPPLIER_ADMIN)
def patch_supplier(supplier_id: UUID, body: sc.SupplierUpdate, session: Session = Depends(db_session)) -> object:
    return suppliers.update_supplier(session, supplier_id, **body.model_dump(exclude_unset=True))


@router.get("/suppliers/{supplier_id}/bank-accounts", response_model=list[sc.BankOut], dependencies=VIEW)
def get_bank_accounts(supplier_id: UUID, session: Session = Depends(db_session)) -> object:
    """The supplier's bank details, masked. The full number is never shown."""
    return suppliers.list_bank_accounts(session, supplier_id)


@router.post("/suppliers/{supplier_id}/bank-accounts", response_model=sc.BankOut, status_code=CREATED,
             dependencies=BANK_EDIT)
def post_bank_account(supplier_id: UUID, body: sc.BankIn, session: Session = Depends(db_session)) -> object:
    """Propose new details. Nothing changes until someone else confirms them with the supplier and they are approved."""
    return suppliers.propose_bank_account(session, supplier_id, **body.model_dump())


@router.post("/bank-accounts/{bank_id}/confirm", response_model=sc.BankOut, dependencies=BANK_CONFIRM)
def post_confirm_bank(bank_id: UUID, body: sc.BankConfirmIn, session: Session = Depends(db_session)) -> object:
    """Confirm proposed details directly with the supplier (not the person who proposed them)."""
    return suppliers.confirm_bank_account(session, bank_id, confirmation_method=body.confirmation_method,
                                          note=body.note)


@router.post("/bank-accounts/{bank_id}/reject", response_model=sc.BankOut, dependencies=BANK_CONFIRM)
def post_reject_bank(bank_id: UUID, session: Session = Depends(db_session)) -> object:
    return suppliers.reject_bank_account(session, bank_id)


@router.get("/suppliers/{supplier_id}/prices", response_model=list[sc.PriceOut], dependencies=VIEW)
def get_supplier_prices(supplier_id: UUID, product_id: UUID | None = None, limit: int = page_limit(50),
                        offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    """What this supplier charged for each product over time."""
    suppliers.get_supplier(session, supplier_id)
    return purchasing_repo.prices_of(session, supplier_id, product_id, limit, offset)


# --------------------------------------------------------------------------- requests
def _request_out(view: orders.RequestView) -> sc.RequestOut:
    return sc.RequestOut(**sc.RequestSummaryOut.model_validate(view.request).model_dump(),
                         lines=[sc.RequestLineOut.model_validate(x) for x in view.lines])


@router.post("/requests", response_model=sc.RequestOut, status_code=CREATED, dependencies=ORDERS)
def post_request(body: sc.RequestIn, session: Session = Depends(db_session)) -> object:
    return _request_out(orders.create_request(
        session, company_id=body.company_id, branch_id=body.branch_id, needed_by=body.needed_by,
        lines=[(x.product_id, x.quantity, x.note) for x in body.lines]))


@router.get("/requests", response_model=list[sc.RequestSummaryOut], dependencies=VIEW)
def get_requests(status_: str | None = Query(default=None, alias="status"), limit: int = page_limit(50),
                 offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return orders.list_requests(session, status=status_, limit=limit, offset=offset)


@router.get("/requests/{request_id}", response_model=sc.RequestOut, dependencies=VIEW)
def get_request(request_id: UUID, session: Session = Depends(db_session)) -> object:
    return _request_out(orders.get_request(session, request_id))


@router.post("/requests/{request_id}/submit", response_model=sc.RequestOut, dependencies=ORDERS)
def post_submit_request(request_id: UUID, session: Session = Depends(db_session)) -> object:
    return _request_out(orders.submit_request(session, request_id))


# --------------------------------------------------------------------------- orders
def _order_out(view: orders.OrderView) -> sc.OrderOut:
    return sc.OrderOut(**sc.OrderSummaryOut.model_validate(view.order).model_dump(),
                       deliver_to_location_id=view.order.deliver_to_location_id,
                       lines=[sc.OrderLineOut.model_validate(x) for x in view.lines])


def _order_lines(items: list[sc.OrderLineIn]) -> list[orders.OrderLineIn]:
    return [orders.OrderLineIn(x.product_id, x.quantity, x.unit_cost, x.tax_code_id) for x in items]


@router.post("/orders", response_model=sc.OrderOut, status_code=CREATED, dependencies=ORDERS)
def post_order(body: sc.OrderIn, session: Session = Depends(db_session)) -> object:
    return _order_out(orders.create_order(
        session, company_id=body.company_id, supplier_id=body.supplier_id, lines=_order_lines(body.lines),
        branch_id=body.branch_id, deliver_to_location_id=body.deliver_to_location_id, order_date=body.order_date,
        expected_date=body.expected_date, request_id=body.request_id))


@router.get("/orders", response_model=list[sc.OrderSummaryOut], dependencies=VIEW)
def get_orders(supplier_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
               limit: int = page_limit(50), offset: int = page_offset(),
               session: Session = Depends(db_session)) -> object:
    return orders.list_orders(session, supplier_id=supplier_id, status=status_, limit=limit, offset=offset)


@router.get("/orders/{order_id}", response_model=sc.OrderOut, dependencies=VIEW)
def get_order(order_id: UUID, session: Session = Depends(db_session)) -> object:
    return _order_out(orders.get_order(session, order_id))


@router.put("/orders/{order_id}", response_model=sc.OrderOut, dependencies=ORDERS)
def put_order(order_id: UUID, body: sc.OrderUpdate, session: Session = Depends(db_session)) -> object:
    """Change a draft order."""
    return _order_out(orders.update_order(
        session, order_id, lines=_order_lines(body.lines) if body.lines is not None else None,
        expected_date=body.expected_date, deliver_to_location_id=body.deliver_to_location_id))


@router.post("/orders/{order_id}/submit", response_model=sc.OrderOut, dependencies=ORDERS)
def post_submit_order(order_id: UUID, session: Session = Depends(db_session)) -> object:
    """Send for approval (approved at once when no rule applies to its amount)."""
    return _order_out(orders.submit_order(session, order_id))


@router.post("/orders/{order_id}/send", response_model=sc.OrderOut, dependencies=ORDERS)
def post_send_order(order_id: UUID, session: Session = Depends(db_session)) -> object:
    return _order_out(orders.send_order(session, order_id))


@router.post("/orders/{order_id}/cancel", response_model=sc.OrderOut, dependencies=ORDERS)
def post_cancel_order(order_id: UUID, session: Session = Depends(db_session)) -> object:
    return _order_out(orders.cancel_order(session, order_id))


@router.post("/orders/{order_id}/close", response_model=sc.OrderOut, dependencies=ORDERS)
def post_close_order(order_id: UUID, session: Session = Depends(db_session)) -> object:
    """Stop waiting for the rest of a part-received order."""
    return _order_out(orders.close_order(session, order_id))


# --------------------------------------------------------------------------- receipts
def _receipt_out(view: receipts.ReceiptView) -> sc.ReceiptOut:
    return sc.ReceiptOut(**sc.ReceiptSummaryOut.model_validate(view.receipt).model_dump(),
                         lines=[sc.ReceiptLineOut.model_validate(x) for x in view.lines])


@router.post("/receipts", response_model=sc.ReceiptOut, status_code=CREATED, dependencies=RECEIVE)
def post_receipt(body: sc.ReceiptIn, session: Session = Depends(db_session)) -> object:
    """Receive goods, against an order (partial is fine) or on their own. The stock arrives in the same transaction."""
    return _receipt_out(receipts.receive_goods(
        session, lines=[receipts.ReceiptLineIn(x.quantity, x.order_line_id, x.product_id, x.unit_cost, x.batch_no,
                                               x.expiry_date) for x in body.lines],
        order_id=body.order_id, supplier_id=body.supplier_id, location_id=body.location_id,
        received_at=body.received_at, delivery_note_no=body.delivery_note_no, landed_cost=body.landed_cost))


@router.get("/receipts", response_model=list[sc.ReceiptSummaryOut], dependencies=VIEW)
def get_receipts(order_id: UUID | None = None, supplier_id: UUID | None = None, limit: int = page_limit(50),
                 offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return receipts.list_receipts(session, order_id=order_id, supplier_id=supplier_id, limit=limit, offset=offset)


@router.get("/receipts/{receipt_id}", response_model=sc.ReceiptOut, dependencies=VIEW)
def get_receipt(receipt_id: UUID, session: Session = Depends(db_session)) -> object:
    return _receipt_out(receipts.get_receipt(session, receipt_id))


# --------------------------------------------------------------------------- bills
def _bill_out(view: bills.BillView) -> sc.BillOut:
    return sc.BillOut(**sc.BillSummaryOut.model_validate(view.bill).model_dump(),
                      reverse_reason=view.bill.reverse_reason, match_notes=[str(x) for x in view.bill.match_notes],
                      lines=[sc.BillLineOut.model_validate(x) for x in view.lines])


def _bill_lines(items: list[sc.BillLineIn]) -> list[bills.BillLineIn]:
    return [bills.BillLineIn(x.quantity, x.unit_cost, x.receipt_line_id, x.expense_account_id, x.description,
                             x.tax_code_id, x.landed_receipt_id) for x in items]


@router.post("/bills", response_model=sc.BillOut, status_code=CREATED, dependencies=BILLS)
def post_bill(body: sc.BillIn, session: Session = Depends(db_session)) -> object:
    """Enter a supplier's invoice as a draft."""
    return _bill_out(bills.create_bill(
        session, supplier_id=body.supplier_id, supplier_invoice_no=body.supplier_invoice_no, bill_date=body.bill_date,
        lines=_bill_lines(body.lines), due_date=body.due_date, etims_ref=body.etims_ref))


@router.get("/bills", response_model=list[sc.BillSummaryOut], dependencies=VIEW)
def get_bills(supplier_id: UUID | None = None, status_: str | None = Query(default=None, alias="status"),
              due_before: date | None = None, limit: int = page_limit(50), offset: int = page_offset(),
              session: Session = Depends(db_session)) -> object:
    return bills.list_bills(session, supplier_id=supplier_id, status=status_, due_before=due_before, limit=limit,
                            offset=offset)


@router.get("/bills/{bill_id}", response_model=sc.BillOut, dependencies=VIEW)
def get_bill(bill_id: UUID, session: Session = Depends(db_session)) -> object:
    return _bill_out(bills.get_bill(session, bill_id))


@router.put("/bills/{bill_id}", response_model=sc.BillOut, dependencies=BILLS)
def put_bill(bill_id: UUID, body: sc.BillUpdate, session: Session = Depends(db_session)) -> object:
    return _bill_out(bills.update_bill(session, bill_id, due_date=body.due_date,
                                       lines=_bill_lines(body.lines) if body.lines is not None else None))


@router.post("/bills/{bill_id}/submit", response_model=sc.BillOut, dependencies=BILLS)
def post_submit_bill(bill_id: UUID, session: Session = Depends(db_session)) -> object:
    """Match the bill to its receipts and orders and post it, or raise it as an exception."""
    return _bill_out(bills.submit_bill(session, bill_id))


@router.post("/bills/{bill_id}/cancel", response_model=sc.BillOut, dependencies=BILLS)
def post_cancel_bill(bill_id: UUID, session: Session = Depends(db_session)) -> object:
    return _bill_out(bills.cancel_bill(session, bill_id))


@router.post("/bills/{bill_id}/approve-exception", response_model=sc.BillOut, dependencies=APPROVE_BILL)
def post_approve_exception(bill_id: UUID, body: sc.ExceptionApprovalIn,
                           session: Session = Depends(db_session)) -> object:
    """Accept a bill that did not match, with a reason. Not by the person who entered it."""
    return _bill_out(bills.approve_exception(session, bill_id, reason_code_id=body.reason_code_id, note=body.note))


@router.post("/bills/{bill_id}/reject-exception", response_model=sc.BillOut, dependencies=APPROVE_BILL)
def post_reject_exception(bill_id: UUID, body: sc.ExceptionRejectIn, session: Session = Depends(db_session)) -> object:
    return _bill_out(bills.reject_exception(session, bill_id, note=body.note))


@router.post("/bills/{bill_id}/pay", response_model=sc.BillOut, dependencies=PAY)
def post_pay_bill(bill_id: UUID, body: sc.PayBillIn, session: Session = Depends(db_session)) -> object:
    """Pay all or part of a posted bill (recorded through Payments, booked by Finance)."""
    return _bill_out(bills.pay_bill(session, bill_id, amount=body.amount, method=body.method,
                                    payment_account_id=body.payment_account_id, external_ref=body.external_ref,
                                    paid_on=body.paid_on))


@router.post("/bills/{bill_id}/reverse", response_model=sc.BillOut, dependencies=APPROVE_BILL)
def post_reverse_bill(bill_id: UUID, body: sc.ReverseIn, session: Session = Depends(db_session)) -> object:
    """Undo a posted bill that was entered wrongly (not while it has payments or credit notes)."""
    return _bill_out(bills.reverse_bill(session, bill_id, reason=body.reason))


@router.get("/bills/{bill_id}/payments", response_model=list[sc.BillPaymentOut], dependencies=VIEW)
def get_bill_payments(bill_id: UUID, session: Session = Depends(db_session)) -> object:
    return [sc.BillPaymentOut(**p.__dict__) for p in bills.list_bill_payments(session, bill_id)]


@router.post("/bills/{bill_id}/reverse-payment", response_model=sc.BillOut, dependencies=PAY)
def post_reverse_payment(bill_id: UUID, body: sc.ReversePaymentIn, session: Session = Depends(db_session)) -> object:
    """Cancel a payment made against the bill; it is owed again."""
    return _bill_out(bills.reverse_bill_payment(session, bill_id, payment_id=body.payment_id, reason=body.reason))


@router.get("/payables", response_model=sc.PayablesOut, dependencies=VIEW)
def get_payables(as_of: date | None = None, supplier_id: UUID | None = None,
                 session: Session = Depends(db_session)) -> object:
    """What is owed to suppliers on posted bills, aged by due date."""
    return bills.payables(session, as_of=as_of, supplier_id=supplier_id)




# --------------------------------------------------------------------------- returns to suppliers
def _return_out(view: returns.ReturnView) -> sc.ReturnOut:
    return sc.ReturnOut(**sc.ReturnSummaryOut.model_validate(view.purchase_return).model_dump(),
                        lines=[sc.ReturnLineOut.model_validate(x) for x in view.lines])


@router.post("/receipts/{receipt_id}/returns", response_model=sc.ReturnOut, status_code=CREATED, dependencies=RETURN)
def post_return(receipt_id: UUID, body: sc.ReturnIn, session: Session = Depends(db_session)) -> object:
    """Send received goods back to the supplier. The stock leaves in the same transaction."""
    return _return_out(returns.return_goods(
        session, receipt_id, lines=[(x.receipt_line_id, x.quantity) for x in body.lines],
        reason_code_id=body.reason_code_id, note=body.note, returned_at=body.returned_at))


@router.get("/returns", response_model=list[sc.ReturnSummaryOut], dependencies=VIEW)
def get_returns(supplier_id: UUID | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                session: Session = Depends(db_session)) -> object:
    return returns.list_returns(session, supplier_id=supplier_id, limit=limit, offset=offset)


@router.get("/returns/{return_id}", response_model=sc.ReturnOut, dependencies=VIEW)
def get_return(return_id: UUID, session: Session = Depends(db_session)) -> object:
    return _return_out(returns.get_return(session, return_id))


# --------------------------------------------------------------------------- supplier credit notes
def _credit_out(view: credit_notes.CreditNoteView) -> sc.CreditNoteOut:
    return sc.CreditNoteOut(**sc.CreditNoteSummaryOut.model_validate(view.credit_note).model_dump(),
                            lines=[sc.CreditLineOut.model_validate(x) for x in view.lines])


@router.post("/bills/{bill_id}/credit-notes", response_model=sc.CreditNoteOut, status_code=CREATED,
             dependencies=APPROVE_BILL)
def post_credit_note(bill_id: UUID, body: sc.CreditNoteIn, session: Session = Depends(db_session)) -> object:
    """Record a credit note the supplier gave against a posted bill (for goods sent back, or any allowance)."""
    return _credit_out(credit_notes.create_credit_note(
        session, bill_id, supplier_credit_no=body.supplier_credit_no, credit_date=body.credit_date,
        lines=[credit_notes.CreditLineIn(x.quantity, x.unit_cost, x.return_line_id, x.expense_account_id,
                                         x.description, x.tax_code_id) for x in body.lines]))


@router.get("/credit-notes", response_model=list[sc.CreditNoteSummaryOut], dependencies=VIEW)
def get_credit_notes(supplier_id: UUID | None = None, bill_id: UUID | None = None, limit: int = page_limit(50),
                     offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    return credit_notes.list_credit_notes(session, supplier_id=supplier_id, bill_id=bill_id, limit=limit,
                                          offset=offset)


@router.get("/credit-notes/{note_id}", response_model=sc.CreditNoteOut, dependencies=VIEW)
def get_credit_note(note_id: UUID, session: Session = Depends(db_session)) -> object:
    return _credit_out(credit_notes.get_credit_note(session, note_id))
