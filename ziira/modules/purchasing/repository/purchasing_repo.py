"""Database access for the purchasing schema. Row-level security scopes every query to the tenant."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, true
from sqlalchemy.orm import Session

from ziira.modules.purchasing.repository.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    Supplier,
    SupplierBankAccount,
    SupplierBill,
    SupplierBillLine,
    SupplierPrice,
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


def _locked(query: Any) -> Any:
    return query.with_for_update().execution_options(populate_existing=True)


# --------------------------------------------------------------------------- suppliers
def get_supplier(session: Session, supplier_id: UUID, *, lock: bool = False) -> Supplier | None:
    if lock:
        return session.scalars(_locked(select(Supplier).where(Supplier.id == supplier_id))).first()
    return session.get(Supplier, supplier_id)


def supplier_by_code(session: Session, company_id: UUID, code: str) -> Supplier | None:
    return session.scalar(select(Supplier).where(Supplier.company_id == company_id, Supplier.code == code))


def list_suppliers(session: Session, company_ids: set[UUID] | None, *, search: str | None, status: str | None,
                   limit: int, offset: int) -> list[Supplier]:
    query = select(Supplier).order_by(Supplier.name, Supplier.id).limit(limit).offset(offset)
    if company_ids is not None:
        query = query.where(Supplier.company_id.in_(company_ids))
    if status:
        query = query.where(Supplier.status == status)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(Supplier.name.ilike(pattern, escape="\\") | Supplier.code.ilike(pattern, escape="\\"))
    return list(session.scalars(query))


def bank_accounts(session: Session, supplier_id: UUID) -> list[SupplierBankAccount]:
    return list(session.scalars(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier_id)
                                .order_by(SupplierBankAccount.created_at.desc())))


def get_bank(session: Session, bank_id: UUID, *, lock: bool = False) -> SupplierBankAccount | None:
    if lock:
        return session.scalars(_locked(select(SupplierBankAccount).where(SupplierBankAccount.id == bank_id))).first()
    return session.get(SupplierBankAccount, bank_id)


def active_bank(session: Session, supplier_id: UUID) -> SupplierBankAccount | None:
    return session.scalar(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier_id,
                                                            SupplierBankAccount.status == "active"))


# --------------------------------------------------------------------------- requests
def get_request(session: Session, request_id: UUID, *, lock: bool = False) -> PurchaseRequest | None:
    if lock:
        return session.scalars(_locked(select(PurchaseRequest).where(PurchaseRequest.id == request_id))).first()
    return session.get(PurchaseRequest, request_id)


def request_lines(session: Session, request_id: UUID) -> list[PurchaseRequestLine]:
    return list(session.scalars(select(PurchaseRequestLine).where(PurchaseRequestLine.request_id == request_id)
                                .order_by(PurchaseRequestLine.created_at, PurchaseRequestLine.id)))


def list_requests(session: Session, scopes: Scopes, *, status: str | None, limit: int,
                  offset: int) -> list[PurchaseRequest]:
    query = select(PurchaseRequest).where(in_scope(scopes, PurchaseRequest.company_id, PurchaseRequest.branch_id)
                                          ).order_by(PurchaseRequest.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(PurchaseRequest.status == status)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- orders
def get_order(session: Session, order_id: UUID, *, lock: bool = False) -> PurchaseOrder | None:
    if lock:
        return session.scalars(_locked(select(PurchaseOrder).where(PurchaseOrder.id == order_id))).first()
    return session.get(PurchaseOrder, order_id)


def order_lines(session: Session, order_id: UUID, *, lock: bool = False) -> list[PurchaseOrderLine]:
    query = select(PurchaseOrderLine).where(PurchaseOrderLine.order_id == order_id).order_by(
        PurchaseOrderLine.created_at, PurchaseOrderLine.id)
    return list(session.scalars(_locked(query) if lock else query))


def get_order_line(session: Session, line_id: UUID, *, lock: bool = False) -> PurchaseOrderLine | None:
    if lock:
        return session.scalars(_locked(select(PurchaseOrderLine).where(PurchaseOrderLine.id == line_id))).first()
    return session.get(PurchaseOrderLine, line_id)


def delete_order_lines(session: Session, order_id: UUID) -> None:
    for line in order_lines(session, order_id):
        session.delete(line)
    session.flush()


def list_orders(session: Session, scopes: Scopes, *, supplier_id: UUID | None, status: str | None, limit: int,
                offset: int) -> list[PurchaseOrder]:
    query = select(PurchaseOrder).where(in_scope(scopes, PurchaseOrder.company_id, PurchaseOrder.branch_id)).order_by(
        PurchaseOrder.created_at.desc()).limit(limit).offset(offset)
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if status:
        query = query.where(PurchaseOrder.status == status)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- receipts
def get_receipt(session: Session, receipt_id: UUID) -> GoodsReceipt | None:
    return session.get(GoodsReceipt, receipt_id)


def receipt_lines(session: Session, receipt_id: UUID) -> list[GoodsReceiptLine]:
    return list(session.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == receipt_id)
                                .order_by(GoodsReceiptLine.created_at, GoodsReceiptLine.id)))


def get_receipt_line(session: Session, line_id: UUID) -> GoodsReceiptLine | None:
    return session.get(GoodsReceiptLine, line_id)


def list_receipts(session: Session, scopes: Scopes, *, order_id: UUID | None, supplier_id: UUID | None, limit: int,
                  offset: int) -> list[GoodsReceipt]:
    query = select(GoodsReceipt).where(in_scope(scopes, GoodsReceipt.company_id, GoodsReceipt.branch_id)).order_by(
        GoodsReceipt.received_at.desc(), GoodsReceipt.id).limit(limit).offset(offset)
    if order_id:
        query = query.where(GoodsReceipt.order_id == order_id)
    if supplier_id:
        query = query.where(GoodsReceipt.supplier_id == supplier_id)
    return list(session.scalars(query))


def receipt_has_lines_for_order(session: Session, order_id: UUID) -> bool:
    return session.scalar(select(GoodsReceipt.id).where(GoodsReceipt.order_id == order_id).limit(1)) is not None


# --------------------------------------------------------------------------- bills
def get_bill(session: Session, bill_id: UUID, *, lock: bool = False) -> SupplierBill | None:
    if lock:
        return session.scalars(_locked(select(SupplierBill).where(SupplierBill.id == bill_id))).first()
    return session.get(SupplierBill, bill_id)


def bill_lines(session: Session, bill_id: UUID) -> list[SupplierBillLine]:
    return list(session.scalars(select(SupplierBillLine).where(SupplierBillLine.bill_id == bill_id)
                                .order_by(SupplierBillLine.created_at, SupplierBillLine.id)))


def delete_bill_lines(session: Session, bill_id: UUID) -> None:
    for line in bill_lines(session, bill_id):
        session.delete(line)
    session.flush()


def bill_by_invoice(session: Session, supplier_id: UUID, invoice_no: str) -> SupplierBill | None:
    return session.scalar(select(SupplierBill).where(SupplierBill.supplier_id == supplier_id,
                                                     SupplierBill.supplier_invoice_no == invoice_no))


def list_bills(session: Session, scopes: Scopes, *, supplier_id: UUID | None, status: str | None,
               due_before: date | None, limit: int, offset: int) -> list[SupplierBill]:
    query = select(SupplierBill).where(in_scope(scopes, SupplierBill.company_id, SupplierBill.branch_id)).order_by(
        SupplierBill.due_date, SupplierBill.id).limit(limit).offset(offset)
    if supplier_id:
        query = query.where(SupplierBill.supplier_id == supplier_id)
    if status:
        query = query.where(SupplierBill.status == status)
    if due_before:
        query = query.where(SupplierBill.due_date <= due_before)
    return list(session.scalars(query))


def billed_on_receipt_line(session: Session, receipt_line_id: UUID, *, exclude_bill: UUID | None = None) -> Decimal:
    """Quantity of a receipt line already on bills that are posted, or that matched and wait only for an approval by
    amount. Drafts, cancelled bills and unresolved match exceptions do not count."""
    query = select(func.coalesce(func.sum(SupplierBillLine.quantity), 0)).join(
        SupplierBill, SupplierBill.id == SupplierBillLine.bill_id).where(
        SupplierBillLine.receipt_line_id == receipt_line_id,
        or_(SupplierBill.status.in_(["posted", "part_paid", "paid"]),
            and_(SupplierBill.status == "pending_approval", SupplierBill.match_status != "exception")))
    if exclude_bill is not None:
        query = query.where(SupplierBill.id != exclude_bill)
    return Decimal(session.scalar(query) or 0)


def open_bills(session: Session, scopes: Scopes, as_of: date) -> list[SupplierBill]:
    """Posted bills that still have something to pay, for the payables report."""
    return list(session.scalars(select(SupplierBill).where(
        in_scope(scopes, SupplierBill.company_id, SupplierBill.branch_id), SupplierBill.status.in_(
            ["posted", "part_paid"]), SupplierBill.bill_date <= as_of).order_by(SupplierBill.due_date)))


# --------------------------------------------------------------------------- prices
def last_price(session: Session, supplier_id: UUID, product_id: UUID) -> SupplierPrice | None:
    return session.scalars(select(SupplierPrice).where(
        SupplierPrice.supplier_id == supplier_id, SupplierPrice.product_id == product_id).order_by(
        SupplierPrice.effective_date.desc(), SupplierPrice.created_at.desc())).first()


def prices_of(session: Session, supplier_id: UUID, product_id: UUID | None, limit: int,
              offset: int) -> list[SupplierPrice]:
    query = select(SupplierPrice).where(SupplierPrice.supplier_id == supplier_id).order_by(
        SupplierPrice.effective_date.desc(), SupplierPrice.created_at.desc()).limit(limit).offset(offset)
    if product_id:
        query = query.where(SupplierPrice.product_id == product_id)
    return list(session.scalars(query))


def lock_receipt_lines(session: Session, line_ids: list[UUID]) -> list[GoodsReceiptLine]:
    """Take the receipt lines in a fixed order, so two bills for the same goods cannot both pass the match."""
    if not line_ids:
        return []
    return list(session.scalars(_locked(select(GoodsReceiptLine).where(GoodsReceiptLine.id.in_(line_ids))
                                        .order_by(GoodsReceiptLine.id))))
