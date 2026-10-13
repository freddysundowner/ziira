"""Database access for the pos schema. Row-level security scopes every query to the tenant."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, text, true
from sqlalchemy.orm import Session

from ziira.modules.pos.repository.models import (
    BRANCH,
    CustomerReceipt,
    CustomerReceiptAllocation,
    CustomerRefund,
    Device,
    InvoiceReminder,
    Sale,
    SaleLine,
    SalePayment,
    SalesDocument,
    SalesDocumentLine,
    SalesInvoice,
    SalesInvoiceLine,
    SalesReturn,
    SalesReturnLine,
    SyncRejection,
    TillSession,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None


def in_scope(scopes: Scopes, company_col: Any, branch_col: Any) -> ColumnElement[bool]:
    """Rows of the companies and branches the user may see (None means everywhere)."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(company_col == c, true() if b is None else branch_col == b) for c, b in scopes))


def add(session: Session, record: Any) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def branch_company(session: Session, branch_id: UUID) -> UUID | None:
    return session.execute(text("select company_id from kernel.branch where id = :b"),
                           {"b": str(branch_id)}).scalar_one_or_none()


def branch_code(session: Session, branch_id: UUID) -> str:
    return str(session.execute(text("select code from kernel.branch where id = :b"),
                               {"b": str(branch_id)}).scalar_one())


def location_branch(session: Session, location_id: UUID) -> tuple[UUID, UUID] | None:
    """(company, branch) of a stock location, read through the inventory schema's own table."""
    row = session.execute(text("select company_id, branch_id from inventory.location where id = :l"),
                          {"l": str(location_id)}).first()
    return (row.company_id, row.branch_id) if row else None


def lock_key(session: Session, key: str) -> None:
    """Serialise work on one key (a client-made id) until the transaction ends."""
    session.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": key})


# --------------------------------------------------------------------------- devices
def get_device(session: Session, device_id: UUID, *, lock: bool = False) -> Device | None:
    if lock:
        return session.scalars(select(Device).where(Device.id == device_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(Device, device_id)


def device_by_hash(session: Session, key_hash: str) -> Device | None:
    return session.scalar(select(Device).where(Device.device_key_hash == key_hash))


def device_code_exists(session: Session, branch_id: UUID, code: str) -> bool:
    return session.scalar(select(Device.id).where(Device.branch_id == branch_id, Device.code == code)) is not None


def list_devices(session: Session, scopes: Scopes, branch_id: UUID | None) -> list[Device]:
    query = select(Device).join(BRANCH, BRANCH.c.id == Device.branch_id).where(
        in_scope(scopes, BRANCH.c.company_id, Device.branch_id)).order_by(Device.branch_id, Device.code)
    if branch_id:
        query = query.where(Device.branch_id == branch_id)
    return list(session.scalars(query))


def next_sequence(session: Session, device_id: UUID) -> int:
    """The device's next sale number (the device row is locked until the sale commits, so numbers never repeat)."""
    return int(session.execute(text(
        "update pos.pos_device set last_seq = last_seq + 1 where id = :d returning last_seq"),
        {"d": str(device_id)}).scalar_one())


# --------------------------------------------------------------------------- tills
def get_till(session: Session, till_id: UUID, *, lock: bool = False, share: bool = False) -> TillSession | None:
    """A till session. `lock` takes it for update (closing); `share` stops it being closed until we commit (selling)."""
    if share:
        return session.scalars(select(TillSession).where(TillSession.id == till_id).with_for_update(read=True)
                               .execution_options(populate_existing=True)).first()
    if lock:
        return session.scalars(select(TillSession).where(TillSession.id == till_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(TillSession, till_id)


def till_by_local_id(session: Session, local_id: UUID) -> TillSession | None:
    return session.scalar(select(TillSession).where(TillSession.local_id == local_id))


def open_till_of_device(session: Session, device_id: UUID) -> TillSession | None:
    return session.scalar(select(TillSession).where(TillSession.device_id == device_id,
                                                    TillSession.status == "open"))


def open_till_of_user(session: Session, user_id: UUID) -> TillSession | None:
    return session.scalar(select(TillSession).where(TillSession.cashier_id == user_id, TillSession.status == "open"))


def list_tills(session: Session, scopes: Scopes, *, branch_id: UUID | None, status: str | None,
               business_date: date | None, cashier_id: UUID | None, limit: int, offset: int) -> list[TillSession]:
    query = select(TillSession).join(BRANCH, BRANCH.c.id == TillSession.branch_id).where(
        in_scope(scopes, BRANCH.c.company_id, TillSession.branch_id)).order_by(
        TillSession.opened_at.desc()).limit(limit).offset(offset)
    if branch_id:
        query = query.where(TillSession.branch_id == branch_id)
    if status:
        query = query.where(TillSession.status == status)
    if business_date:
        query = query.where(TillSession.business_date == business_date)
    if cashier_id:
        query = query.where(TillSession.cashier_id == cashier_id)
    return list(session.scalars(query))


def till_sale_figures(session: Session, till_id: UUID) -> dict[str, Any]:
    """What a till session sold: counts and totals of posted and voided sales, and takings by method."""
    sales = session.execute(text(
        "select status, count(*) as n, coalesce(sum(total), 0) as total, coalesce(sum(tax_total), 0) as tax, "
        "coalesce(sum(discount_total), 0) as discount from pos.sale where till_session_id = :t group by status"),
        {"t": str(till_id)}).all()
    methods = session.execute(text(
        "select p.method, coalesce(sum(p.amount), 0) as amount from pos.sale_payment p join pos.sale s on s.id = "
        "p.sale_id where s.till_session_id = :t and s.status = 'posted' group by p.method"), {"t": str(till_id)}).all()
    return {"sales": {r.status: {"count": r.n, "total": r.total, "tax": r.tax, "discount": r.discount} for r in sales},
            "by_method": {r.method: r.amount for r in methods}}


def open_tills_count(session: Session, branch_id: UUID, day: date) -> int:
    return int(session.scalar(select(func.count()).select_from(TillSession).where(
        TillSession.branch_id == branch_id, TillSession.business_date == day, TillSession.status == "open")) or 0)


# --------------------------------------------------------------------------- sales
def get_sale(session: Session, sale_id: UUID, *, lock: bool = False) -> Sale | None:
    if lock:
        return session.scalars(select(Sale).where(Sale.id == sale_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(Sale, sale_id)


def sale_by_local_id(session: Session, local_id: UUID) -> Sale | None:
    return session.scalar(select(Sale).where(Sale.local_id == local_id))


def number_taken(session: Session, company_id: UUID, number: str) -> Sale | None:
    return session.scalar(select(Sale).where(Sale.company_id == company_id, Sale.number == number))


def lines_of(session: Session, sale_id: UUID) -> list[SaleLine]:
    return list(session.scalars(select(SaleLine).where(SaleLine.sale_id == sale_id).order_by(SaleLine.line_no)))


def payments_of(session: Session, sale_id: UUID) -> list[SalePayment]:
    return list(session.scalars(select(SalePayment).where(SalePayment.sale_id == sale_id)
                                .order_by(SalePayment.created_at, SalePayment.id)))


def list_sales(session: Session, scopes: Scopes, *, branch_id: UUID | None, business_date: date | None,
               status: str | None, till_session_id: UUID | None, number: str | None, limit: int,
               offset: int) -> list[Sale]:
    query = select(Sale).where(in_scope(scopes, Sale.company_id, Sale.branch_id)).order_by(
        Sale.sold_at.desc(), Sale.id).limit(limit).offset(offset)
    if branch_id:
        query = query.where(Sale.branch_id == branch_id)
    if business_date:
        query = query.where(Sale.business_date == business_date)
    if status:
        query = query.where(Sale.status == status)
    if till_session_id:
        query = query.where(Sale.till_session_id == till_session_id)
    if number:
        query = query.where(Sale.number == number)
    return list(session.scalars(query))


def returned_quantities(session: Session, sale_id: UUID) -> dict[UUID, Decimal]:
    """Quantity already returned (or awaiting approval) per sale line."""
    rows = session.execute(text(
        "select l.sale_line_id, sum(l.quantity) as q from pos.sales_return_line l join pos.sales_return r on r.id = "
        "l.return_id where r.original_sale_id = :s and r.status in ('posted', 'pending_approval') "
        "group by l.sale_line_id"), {"s": str(sale_id)}).all()
    return {r.sale_line_id: Decimal(r.q) for r in rows}


def returns_of_sale(session: Session, sale_id: UUID) -> list[SalesReturn]:
    return list(session.scalars(select(SalesReturn).where(SalesReturn.original_sale_id == sale_id)
                                .order_by(SalesReturn.created_at)))


# --------------------------------------------------------------------------- returns
def get_return(session: Session, return_id: UUID, *, lock: bool = False) -> SalesReturn | None:
    if lock:
        return session.scalars(select(SalesReturn).where(SalesReturn.id == return_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(SalesReturn, return_id)


def return_lines(session: Session, return_id: UUID) -> list[SalesReturnLine]:
    return list(session.scalars(select(SalesReturnLine).where(SalesReturnLine.return_id == return_id)
                                .order_by(SalesReturnLine.created_at, SalesReturnLine.id)))


def list_returns(session: Session, scopes: Scopes, *, branch_id: UUID | None, status: str | None, limit: int,
                 offset: int) -> list[SalesReturn]:
    query = select(SalesReturn).where(in_scope(scopes, SalesReturn.company_id, SalesReturn.branch_id)).order_by(
        SalesReturn.created_at.desc()).limit(limit).offset(offset)
    if branch_id:
        query = query.where(SalesReturn.branch_id == branch_id)
    if status:
        query = query.where(SalesReturn.status == status)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- sync rejections
def rejection_by_local_id(session: Session, local_id: UUID) -> SyncRejection | None:
    return session.scalar(select(SyncRejection).where(SyncRejection.local_id == local_id))


def list_rejections(session: Session, scopes: Scopes, *, include_resolved: bool, limit: int,
                    offset: int) -> list[SyncRejection]:
    query = (select(SyncRejection).join(Device, Device.id == SyncRejection.device_id)
             .join(BRANCH, BRANCH.c.id == Device.branch_id)
             .where(in_scope(scopes, BRANCH.c.company_id, Device.branch_id))
             .order_by(SyncRejection.created_at.desc()).limit(limit).offset(offset))
    if not include_resolved:
        query = query.where(SyncRejection.resolved_at.is_(None))
    return list(session.scalars(query))


# --------------------------------------------------------------------------- invoices
OPEN_INVOICE = ("issued", "part_paid")


def get_invoice(session: Session, invoice_id: UUID, *, lock: bool = False) -> SalesInvoice | None:
    if lock:
        return session.scalars(select(SalesInvoice).where(SalesInvoice.id == invoice_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(SalesInvoice, invoice_id)


def invoice_for_sale(session: Session, sale_id: UUID, *, lock: bool = False) -> SalesInvoice | None:
    query = select(SalesInvoice).where(SalesInvoice.sale_id == sale_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def invoice_lines(session: Session, invoice_id: UUID) -> list[SalesInvoiceLine]:
    return list(session.scalars(select(SalesInvoiceLine).where(SalesInvoiceLine.invoice_id == invoice_id)
                                .order_by(SalesInvoiceLine.line_no, SalesInvoiceLine.created_at,
                                          SalesInvoiceLine.id)))


def list_invoices(session: Session, scopes: Scopes, *, customer_id: UUID | None, status: str | None,
                  due_before: date | None, number: str | None, limit: int, offset: int) -> list[SalesInvoice]:
    query = select(SalesInvoice).where(in_scope(scopes, SalesInvoice.company_id, SalesInvoice.branch_id)).order_by(
        SalesInvoice.issue_date.desc(), SalesInvoice.number.desc()).limit(limit).offset(offset)
    if customer_id:
        query = query.where(SalesInvoice.customer_id == customer_id)
    if status:
        query = query.where(SalesInvoice.status == status)
    if due_before:
        query = query.where(SalesInvoice.due_date <= due_before)
    if number:
        query = query.where(SalesInvoice.number == number)
    return list(session.scalars(query))


def open_invoices_of(session: Session, customer_id: UUID, *, lock: bool = False) -> list[SalesInvoice]:
    """A customer's unpaid invoices, oldest due first."""
    query = select(SalesInvoice).where(SalesInvoice.customer_id == customer_id,
                                       SalesInvoice.status.in_(OPEN_INVOICE)).order_by(
        SalesInvoice.due_date, SalesInvoice.issue_date, SalesInvoice.number)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(query))


def customer_exposure(session: Session, customer_id: UUID) -> Decimal:
    """What a customer owes on invoices that are not paid or cancelled."""
    return Decimal(session.scalar(select(func.coalesce(func.sum(
        SalesInvoice.total - SalesInvoice.amount_paid - SalesInvoice.credited), 0)).where(
        SalesInvoice.customer_id == customer_id, SalesInvoice.status.in_(OPEN_INVOICE))) or 0)


def all_open_invoices(session: Session, scopes: Scopes, as_of: date) -> list[SalesInvoice]:
    return list(session.scalars(select(SalesInvoice).where(
        in_scope(scopes, SalesInvoice.company_id, SalesInvoice.branch_id), SalesInvoice.status.in_(OPEN_INVOICE),
        SalesInvoice.issue_date <= as_of).order_by(SalesInvoice.due_date)))


def invoices_of_customer(session: Session, customer_id: UUID) -> list[SalesInvoice]:
    return list(session.scalars(select(SalesInvoice).where(
        SalesInvoice.customer_id == customer_id, SalesInvoice.status != "cancelled").order_by(
        SalesInvoice.issue_date, SalesInvoice.number)))


def invoice_returned_quantities(session: Session, invoice_id: UUID) -> dict[UUID, Decimal]:
    """Quantity already returned (or awaiting approval) per invoice line."""
    rows = session.execute(text(
        "select l.invoice_line_id, sum(l.quantity) as q from pos.sales_return_line l join pos.sales_return r on "
        "r.id = l.return_id where r.original_invoice_id = :i and r.status in ('posted', 'pending_approval') "
        "group by l.invoice_line_id"), {"i": str(invoice_id)}).all()
    return {r.invoice_line_id: Decimal(r.q) for r in rows}


def returns_of_invoice(session: Session, invoice_id: UUID) -> list[SalesReturn]:
    return list(session.scalars(select(SalesReturn).where(SalesReturn.original_invoice_id == invoice_id)
                                .order_by(SalesReturn.created_at)))


# --------------------------------------------------------------------------- receipts
def get_receipt(session: Session, receipt_id: UUID, *, lock: bool = False) -> CustomerReceipt | None:
    if lock:
        return session.scalars(select(CustomerReceipt).where(CustomerReceipt.id == receipt_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(CustomerReceipt, receipt_id)


def receipt_by_payment(session: Session, payment_id: UUID, *, lock: bool = False) -> CustomerReceipt | None:
    query = select(CustomerReceipt).where(CustomerReceipt.payment_id == payment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def receipt_allocations(session: Session, receipt_id: UUID) -> list[CustomerReceiptAllocation]:
    return list(session.scalars(select(CustomerReceiptAllocation).where(
        CustomerReceiptAllocation.receipt_id == receipt_id).order_by(CustomerReceiptAllocation.created_at,
                                                                     CustomerReceiptAllocation.id)))


def list_receipts(session: Session, scopes: Scopes, *, customer_id: UUID | None, limit: int,
                  offset: int) -> list[CustomerReceipt]:
    query = select(CustomerReceipt).where(in_scope(scopes, CustomerReceipt.company_id, CustomerReceipt.branch_id)
                                          ).order_by(CustomerReceipt.received_on.desc(), CustomerReceipt.number.desc()
                                                     ).limit(limit).offset(offset)
    if customer_id:
        query = query.where(CustomerReceipt.customer_id == customer_id)
    return list(session.scalars(query))


def receipts_of_customer(session: Session, customer_id: UUID) -> list[CustomerReceipt]:
    return list(session.scalars(select(CustomerReceipt).where(
        CustomerReceipt.customer_id == customer_id, CustomerReceipt.status == "posted").order_by(
        CustomerReceipt.received_on, CustomerReceipt.number)))


def receipts_on_invoice(session: Session, invoice_id: UUID) -> list[tuple[CustomerReceipt, CustomerReceiptAllocation]]:
    rows = session.execute(select(CustomerReceipt, CustomerReceiptAllocation).join(
        CustomerReceiptAllocation, CustomerReceiptAllocation.receipt_id == CustomerReceipt.id).where(
        CustomerReceiptAllocation.invoice_id == invoice_id).order_by(CustomerReceipt.received_on,
                                                                     CustomerReceipt.number))
    return [(r, a) for r, a in rows]


# --------------------------------------------------------------------------- quotations and orders
def get_document(session: Session, document_id: UUID, *, lock: bool = False) -> SalesDocument | None:
    if lock:
        return session.scalars(select(SalesDocument).where(SalesDocument.id == document_id).with_for_update()
                               .execution_options(populate_existing=True)).first()
    return session.get(SalesDocument, document_id)


def document_lines(session: Session, document_id: UUID, *, lock: bool = False) -> list[SalesDocumentLine]:
    query = select(SalesDocumentLine).where(SalesDocumentLine.document_id == document_id).order_by(
        SalesDocumentLine.line_no, SalesDocumentLine.created_at, SalesDocumentLine.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(query))


def delete_document_lines(session: Session, document_id: UUID) -> None:
    for line in document_lines(session, document_id):
        session.delete(line)
    session.flush()


def list_documents(session: Session, scopes: Scopes, *, kind: str | None, customer_id: UUID | None,
                   status: str | None, limit: int, offset: int) -> list[SalesDocument]:
    query = select(SalesDocument).where(in_scope(scopes, SalesDocument.company_id, SalesDocument.branch_id)).order_by(
        SalesDocument.doc_date.desc(), SalesDocument.number.desc()).limit(limit).offset(offset)
    if kind:
        query = query.where(SalesDocument.doc_kind == kind)
    if customer_id:
        query = query.where(SalesDocument.customer_id == customer_id)
    if status:
        query = query.where(SalesDocument.status == status)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- statements and reminders
def credit_notes_of_customer(session: Session, customer_id: UUID) -> list[SalesReturn]:
    """Posted returns that reduced what the customer owes (refunded as a credit note)."""
    return list(session.scalars(
        select(SalesReturn).join(SalesInvoice, (SalesInvoice.id == SalesReturn.original_invoice_id)
                                 | (SalesInvoice.sale_id == SalesReturn.original_sale_id)).where(
            SalesInvoice.customer_id == customer_id, SalesReturn.refund_method == "credit_note",
            SalesReturn.status == "posted").order_by(SalesReturn.business_date, SalesReturn.number)))


def last_reminders(session: Session, invoice_ids: list[UUID]) -> dict[UUID, Any]:
    if not invoice_ids:
        return {}
    rows = session.execute(select(InvoiceReminder.invoice_id, func.max(InvoiceReminder.created_at)).where(
        InvoiceReminder.invoice_id.in_(invoice_ids)).group_by(InvoiceReminder.invoice_id))
    return {i: t for i, t in rows}


def reminders_of(session: Session, invoice_id: UUID) -> list[InvoiceReminder]:
    return list(session.scalars(select(InvoiceReminder).where(InvoiceReminder.invoice_id == invoice_id)
                                .order_by(InvoiceReminder.created_at)))


# --------------------------------------------------------------------------- advances
def advances_of(session: Session, customer_id: UUID, *, lock: bool = False) -> list[CustomerReceipt]:
    """Receipts with money still held on the customer's account, oldest first."""
    query = select(CustomerReceipt).where(
        CustomerReceipt.customer_id == customer_id, CustomerReceipt.status == "posted",
        CustomerReceipt.unallocated > 0).order_by(CustomerReceipt.received_on, CustomerReceipt.number)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(query))


def customer_advances(session: Session, customer_id: UUID) -> Decimal:
    """Money the customer has paid in advance and not yet used or had back."""
    return Decimal(session.scalar(select(func.coalesce(func.sum(CustomerReceipt.unallocated), 0)).where(
        CustomerReceipt.customer_id == customer_id, CustomerReceipt.status == "posted")) or 0)


def refund_by_payment(session: Session, payment_id: UUID, *, lock: bool = False) -> CustomerRefund | None:
    query = select(CustomerRefund).where(CustomerRefund.payment_id == payment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def get_refund(session: Session, refund_id: UUID) -> CustomerRefund | None:
    return session.get(CustomerRefund, refund_id)


def refunds_of_receipt(session: Session, receipt_id: UUID) -> list[CustomerRefund]:
    return list(session.scalars(select(CustomerRefund).where(CustomerRefund.receipt_id == receipt_id)
                                .order_by(CustomerRefund.created_at)))


def list_refunds(session: Session, scopes: Scopes, *, customer_id: UUID | None, limit: int,
                 offset: int) -> list[CustomerRefund]:
    query = select(CustomerRefund).where(in_scope(scopes, CustomerRefund.company_id, CustomerRefund.branch_id)
                                         ).order_by(CustomerRefund.refunded_on.desc(), CustomerRefund.number.desc()
                                                    ).limit(limit).offset(offset)
    if customer_id:
        query = query.where(CustomerRefund.customer_id == customer_id)
    return list(session.scalars(query))
