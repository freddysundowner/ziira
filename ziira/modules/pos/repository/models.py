"""SQLAlchemy mappings for tables in the `pos` schema."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Column, MetaData, Numeric, Table, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# Just enough of kernel.branch to find a branch's company (read-only; the kernel owns the table).
BRANCH = Table("branch", MetaData(), Column("id", Uuid), Column("company_id", Uuid), schema="kernel")


class TenantColumns:
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Audited(TenantColumns):
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]


class Device(Audited, Base):
    __tablename__ = "pos_device"
    __table_args__ = {"schema": "pos"}

    branch_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    location_id: Mapped[UUID | None]
    device_key_hash: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    last_sync_at: Mapped[datetime | None]
    last_seq: Mapped[int] = mapped_column(server_default=text("0"))


class TillSession(Audited, Base):
    __tablename__ = "till_session"
    __table_args__ = {"schema": "pos"}

    branch_id: Mapped[UUID]
    device_id: Mapped[UUID]
    cash_account_id: Mapped[UUID]
    cashier_id: Mapped[UUID]
    business_date: Mapped[date]
    opened_at: Mapped[datetime]
    opening_float: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    closed_at: Mapped[datetime | None]
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    counted_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    variance_reason_code_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    local_id: Mapped[UUID | None]
    closed_by: Mapped[UUID | None]
    close_note: Mapped[str | None]
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Sale(Audited, Base):
    __tablename__ = "sale"
    __table_args__ = {"schema": "pos"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    number: Mapped[str]
    device_id: Mapped[UUID | None]
    local_id: Mapped[UUID]
    till_session_id: Mapped[UUID | None]
    customer_id: Mapped[UUID | None]
    cashier_id: Mapped[UUID]
    business_date: Mapped[date]
    sold_at: Mapped[datetime]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    status: Mapped[str] = mapped_column(server_default=text("'posted'"))
    voided_by: Mapped[UUID | None]
    voided_at: Mapped[datetime | None]
    void_reason_code_id: Mapped[UUID | None]
    synced_offline: Mapped[bool] = mapped_column(server_default=text("false"))
    location_id: Mapped[UUID | None]
    voided_note: Mapped[str | None]


class SaleLine(TenantColumns, Base):
    __tablename__ = "sale_line"
    __table_args__ = {"schema": "pos"}

    sale_id: Mapped[UUID]
    line_no: Mapped[int]
    product_id: Mapped[UUID]
    uom_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    list_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    price_reason_code_id: Mapped[UUID | None]
    tax_code_id: Mapped[UUID]
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class SalePayment(TenantColumns, Base):
    __tablename__ = "sale_payment"
    __table_args__ = {"schema": "pos"}

    sale_id: Mapped[UUID]
    method: Mapped[str]
    payment_account_id: Mapped[UUID | None]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    external_ref: Mapped[str | None]
    payment_id: Mapped[UUID | None]


class SalesReturn(Audited, Base):
    __tablename__ = "sales_return"
    __table_args__ = {"schema": "pos"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    original_sale_id: Mapped[UUID | None]
    original_invoice_id: Mapped[UUID | None]
    reason_code_id: Mapped[UUID]
    refund_method: Mapped[str]
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    restock_location_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]
    refund_payment_id: Mapped[UUID | None]
    business_date: Mapped[date | None]
    net: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class SalesReturnLine(TenantColumns, Base):
    __tablename__ = "sales_return_line"
    __table_args__ = {"schema": "pos"}

    return_id: Mapped[UUID]
    product_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    sale_line_id: Mapped[UUID | None]
    invoice_line_id: Mapped[UUID | None]


class SyncRejection(TenantColumns, Base):
    __tablename__ = "sync_rejection"
    __table_args__ = {"schema": "pos"}

    updated_at: Mapped[datetime | None]
    device_id: Mapped[UUID]
    user_id: Mapped[UUID | None]
    local_id: Mapped[UUID]
    op_type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    error: Mapped[str]
    attempts: Mapped[int] = mapped_column(server_default=text("1"))
    resolved_at: Mapped[datetime | None]


class SalesInvoice(Audited, Base):
    __tablename__ = "sales_invoice"
    __table_args__ = {"schema": "pos"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    customer_id: Mapped[UUID]
    sale_id: Mapped[UUID | None]
    sales_order_id: Mapped[UUID | None]
    issue_date: Mapped[date]
    due_date: Mapped[date]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    status: Mapped[str] = mapped_column(server_default=text("'issued'"))
    kind: Mapped[str] = mapped_column(server_default=text("'invoice'"))
    location_id: Mapped[UUID | None]
    credited: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    cancelled_at: Mapped[datetime | None]
    cancelled_by: Mapped[UUID | None]
    cancel_reason: Mapped[str | None]
    notes: Mapped[str | None]


class SalesInvoiceLine(TenantColumns, Base):
    __tablename__ = "sales_invoice_line"
    __table_args__ = {"schema": "pos"}

    invoice_id: Mapped[UUID]
    product_id: Mapped[UUID]
    uom_id: Mapped[UUID]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax_code_id: Mapped[UUID]
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    line_no: Mapped[int | None]
    batch_id: Mapped[UUID | None]
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    order_line_id: Mapped[UUID | None]
    price_reason_code_id: Mapped[UUID | None]
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class SalesDocument(Audited, Base):
    __tablename__ = "sales_document"
    __table_args__ = {"schema": "pos"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    doc_kind: Mapped[str]
    number: Mapped[str]
    customer_id: Mapped[UUID | None]
    doc_date: Mapped[date]
    valid_until: Mapped[date | None]
    source_quotation_id: Mapped[UUID | None]
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]
    location_id: Mapped[UUID | None]
    terms_days: Mapped[int] = mapped_column(server_default=text("0"))
    notes: Mapped[str | None]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))


class SalesDocumentLine(TenantColumns, Base):
    __tablename__ = "sales_document_line"
    __table_args__ = {"schema": "pos"}

    document_id: Mapped[UUID]
    product_id: Mapped[UUID]
    uom_id: Mapped[UUID]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax_code_id: Mapped[UUID]
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    qty_delivered: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    line_no: Mapped[int | None]
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))


class CustomerReceipt(Audited, Base):
    __tablename__ = "customer_receipt"
    __table_args__ = {"schema": "pos"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    customer_id: Mapped[UUID]
    payment_id: Mapped[UUID | None]
    till_session_id: Mapped[UUID | None]
    method: Mapped[str]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    received_on: Mapped[date]
    reference: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'posted'"))
    reversed_at: Mapped[datetime | None]
    reverse_reason: Mapped[str | None]
    unallocated: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    refunded: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))


class CustomerReceiptAllocation(TenantColumns, Base):
    __tablename__ = "customer_receipt_allocation"
    __table_args__ = {"schema": "pos"}

    receipt_id: Mapped[UUID]
    invoice_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class InvoiceReminder(TenantColumns, Base):
    __tablename__ = "invoice_reminder"
    __table_args__ = {"schema": "pos"}

    created_by: Mapped[UUID | None]
    invoice_id: Mapped[UUID]
    channel: Mapped[str]
    note: Mapped[str | None]


class CustomerRefund(TenantColumns, Base):
    __tablename__ = "customer_refund"
    __table_args__ = {"schema": "pos"}

    created_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    receipt_id: Mapped[UUID]
    customer_id: Mapped[UUID]
    payment_id: Mapped[UUID | None]
    till_session_id: Mapped[UUID | None]
    method: Mapped[str]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refunded_on: Mapped[date]
    reason: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'posted'"))
