"""SQLAlchemy mappings for tables in the `purchasing` schema."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import LargeBinary, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantColumns:
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Audited(TenantColumns):
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]


def money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 2))


class Supplier(Audited, Base):
    __tablename__ = "supplier"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    kra_pin: Mapped[str | None]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    payment_terms_days: Mapped[int] = mapped_column(server_default=text("0"))
    status: Mapped[str] = mapped_column(server_default=text("'active'"))


class SupplierBankAccount(Audited, Base):
    __tablename__ = "supplier_bank_account"
    __table_args__ = {"schema": "purchasing"}

    supplier_id: Mapped[UUID]
    method: Mapped[str]
    bank_name: Mapped[str | None]
    account_name: Mapped[str | None]
    account_no_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    account_no_masked: Mapped[str | None]
    valid_from: Mapped[datetime]
    valid_to: Mapped[datetime | None]
    approved_by: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    confirmation_method: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'pending_confirmation'"))
    confirmed_at: Mapped[datetime | None]


class PurchaseRequest(Audited, Base):
    __tablename__ = "purchase_request"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    needed_by: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]


class PurchaseRequestLine(TenantColumns, Base):
    __tablename__ = "purchase_request_line"
    __table_args__ = {"schema": "purchasing"}

    request_id: Mapped[UUID]
    product_id: Mapped[UUID]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    note: Mapped[str | None]


class PurchaseOrder(Audited, Base):
    __tablename__ = "purchase_order"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    supplier_id: Mapped[UUID]
    request_id: Mapped[UUID | None]
    deliver_to_location_id: Mapped[UUID | None]
    order_date: Mapped[date]
    expected_date: Mapped[date | None]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]


class PurchaseOrderLine(TenantColumns, Base):
    __tablename__ = "purchase_order_line"
    __table_args__ = {"schema": "purchasing"}

    order_id: Mapped[UUID]
    product_id: Mapped[UUID]
    uom_id: Mapped[UUID]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    tax_code_id: Mapped[UUID]
    qty_received: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    qty_billed: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))


class GoodsReceipt(Audited, Base):
    __tablename__ = "goods_receipt"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    order_id: Mapped[UUID | None]
    supplier_id: Mapped[UUID]
    location_id: Mapped[UUID | None]
    received_at: Mapped[datetime]
    delivery_note_no: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    landed_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))


class GoodsReceiptLine(TenantColumns, Base):
    __tablename__ = "goods_receipt_line"
    __table_args__ = {"schema": "purchasing"}

    receipt_id: Mapped[UUID]
    order_line_id: Mapped[UUID | None]
    product_id: Mapped[UUID]
    batch_no: Mapped[str | None]
    expiry_date: Mapped[date | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    landed_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))


class SupplierBill(Audited, Base):
    __tablename__ = "supplier_bill"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    supplier_id: Mapped[UUID]
    supplier_invoice_no: Mapped[str]
    bill_date: Mapped[date]
    due_date: Mapped[date]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    match_status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    etims_ref: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]
    match_notes: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    posted_at: Mapped[datetime | None]
    submitted_by: Mapped[UUID | None]
    credited: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    reversed_at: Mapped[datetime | None]
    reversed_by: Mapped[UUID | None]
    reverse_reason: Mapped[str | None]
    posted_figures: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SupplierBillLine(TenantColumns, Base):
    __tablename__ = "supplier_bill_line"
    __table_args__ = {"schema": "purchasing"}

    bill_id: Mapped[UUID]
    order_line_id: Mapped[UUID | None]
    receipt_line_id: Mapped[UUID | None]
    product_id: Mapped[UUID | None]
    expense_account_id: Mapped[UUID | None]
    description: Mapped[str | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    tax_code_id: Mapped[UUID | None]
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    landed_receipt_id: Mapped[UUID | None]


class SupplierPrice(TenantColumns, Base):
    __tablename__ = "supplier_price"
    __table_args__ = {"schema": "purchasing"}

    supplier_id: Mapped[UUID]
    product_id: Mapped[UUID]
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    effective_date: Mapped[date]
    source_type: Mapped[str]
    source_id: Mapped[UUID]


class PurchaseReturn(Audited, Base):
    __tablename__ = "purchase_return"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    supplier_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    location_id: Mapped[UUID]
    reason_code_id: Mapped[UUID]
    note: Mapped[str | None]
    returned_at: Mapped[datetime]


class PurchaseReturnLine(TenantColumns, Base):
    __tablename__ = "purchase_return_line"
    __table_args__ = {"schema": "purchasing"}

    return_id: Mapped[UUID]
    receipt_line_id: Mapped[UUID]
    product_id: Mapped[UUID]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    stock_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    qty_credited: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))


class SupplierCreditNote(Audited, Base):
    __tablename__ = "supplier_credit_note"
    __table_args__ = {"schema": "purchasing"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    supplier_id: Mapped[UUID]
    bill_id: Mapped[UUID]
    supplier_credit_no: Mapped[str]
    credit_date: Mapped[date]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class SupplierCreditNoteLine(TenantColumns, Base):
    __tablename__ = "supplier_credit_note_line"
    __table_args__ = {"schema": "purchasing"}

    credit_note_id: Mapped[UUID]
    return_line_id: Mapped[UUID | None]
    expense_account_id: Mapped[UUID | None]
    description: Mapped[str | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    tax_code_id: Mapped[UUID | None]
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
