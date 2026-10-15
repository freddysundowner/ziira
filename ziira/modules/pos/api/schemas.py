"""Request and response shapes for the POS API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount, Quantity

Money = Annotated[Amount, Field(gt=0)]
NonNegative = Annotated[Amount, Field(ge=0)]


# --------------------------------------------------------------------------- devices
class DeviceIn(BaseModel):
    branch_id: UUID
    code: str = Field(min_length=1, max_length=8, examples=["D1"])
    name: str = Field(min_length=1, max_length=100, examples=["Counter 1"])
    location_id: UUID | None = Field(default=None, description="The store this device's sales take stock from")


class DeviceStatusIn(BaseModel):
    status: Literal["active", "blocked"]


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    branch_id: UUID
    code: str
    name: str
    location_id: UUID | None
    status: str
    last_sync_at: datetime | None


class DeviceKeyOut(DeviceOut):
    key: str = Field(description="Shown once: the device keeps it and sends it as X-Device-Key when syncing")


# --------------------------------------------------------------------------- tills
class TillOpenIn(BaseModel):
    device_id: UUID
    opening_float: NonNegative = Decimal(0)
    local_id: UUID | None = Field(default=None, description="Makes a retry safe: the same id opens the till once")


class TillCloseIn(BaseModel):
    counted_cash: NonNegative
    reason_code_id: UUID | None = Field(default=None, description="From the 'till_variance' list; needed if short/over")
    note: str | None = Field(default=None, max_length=500)


class TillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    branch_id: UUID
    device_id: UUID
    cashier_id: UUID
    business_date: date
    opened_at: datetime
    opening_float: Decimal
    closed_at: datetime | None
    expected_cash: Decimal | None
    counted_cash: Decimal | None
    variance: Decimal | None
    status: str


class TillReportOut(BaseModel):
    till_session_id: UUID
    business_date: date
    status: str
    opening_float: Decimal
    sales_count: int
    sales_total: Decimal
    tax_total: Decimal
    discount_total: Decimal
    voided_count: int
    voided_total: Decimal
    takings_by_method: dict[str, Decimal]
    cash_refunded: Decimal
    expected_cash: Decimal
    counted_cash: Decimal | None
    variance: Decimal | None
    held_expired: int = Field(default=0, description="Sales still on hold when the till closed (they ended with it)")


# --------------------------------------------------------------------------- held sales
class HeldLine(BaseModel):
    """One line of a parked cart, as the terminal shows it."""

    product_id: UUID
    sku: str = Field(max_length=60)
    name: str = Field(max_length=200)
    quantity: Annotated[Quantity, Field(gt=0)]
    list_price: NonNegative | None = Field(default=None, description="The price list's price when it was parked")
    price: NonNegative | None = Field(default=None, description="The price charged (differs when overridden)")
    discount: NonNegative = Decimal(0)
    reason_code_id: UUID | None = None


class HeldSaleIn(BaseModel):
    local_id: UUID | None = Field(default=None, description="Made by the terminal: holding twice keeps one")
    label: str = Field(default="", max_length=120)
    customer_id: UUID | None = None
    customer_name: str = Field(default="", max_length=200)
    customer_phone: str = Field(default="", max_length=40)
    note: str | None = Field(default=None, max_length=500)
    lines: Annotated[list[HeldLine], Field(min_length=1, max_length=200)]


class HeldSaleOut(BaseModel):
    id: UUID
    local_id: UUID
    till_session_id: UUID
    label: str
    customer_id: UUID | None
    customer_name: str
    customer_phone: str
    note: str | None
    lines: list[HeldLine]
    status: Literal["held", "resumed", "discarded", "expired"]
    created_at: datetime


# --------------------------------------------------------------------------- sales
class SaleLineIn(BaseModel):
    product_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]
    unit_price: NonNegative | None = Field(default=None, description="Tax-inclusive. Leave out to use the list price")
    discount: NonNegative = Decimal(0)
    reason_code_id: UUID | None = Field(default=None, description="From the 'price_override' list")
    batch_id: UUID | None = None


class SalePaymentIn(BaseModel):
    method: Literal["cash", "mobile_money", "card", "other", "credit"]
    amount: Money = Field(description="What was handed over. Cash may be more than is due: the rest is change")
    external_ref: str | None = Field(default=None, max_length=60, description="M-Pesa code or card slip number")
    payment_account_id: UUID | None = None


class SaleIn(BaseModel):
    till_session_id: UUID
    lines: Annotated[list[SaleLineIn], Field(min_length=1, max_length=200)]
    payments: Annotated[list[SalePaymentIn], Field(min_length=1, max_length=10)]
    customer_id: UUID | None = None
    local_id: UUID | None = Field(default=None, description="Makes a retry safe: the same id records the sale once")


class SaleLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    line_no: int
    product_id: UUID
    quantity: Decimal
    list_price: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    cost_amount: Decimal | None


class SalePaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    method: str
    amount: Decimal
    external_ref: str | None
    payment_id: UUID | None


class SaleSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: str
    company_id: UUID
    branch_id: UUID
    till_session_id: UUID | None
    cashier_id: UUID
    business_date: date
    sold_at: datetime
    total: Decimal
    tax_total: Decimal
    discount_total: Decimal
    status: str
    synced_offline: bool


class SaleOut(SaleSummaryOut):
    subtotal: Decimal
    customer_id: UUID | None
    lines: list[SaleLineOut]
    payments: list[SalePaymentOut]
    change: Decimal = Decimal(0)
    warnings: list[str] = []
    replayed: bool = False


class VoidIn(BaseModel):
    reason_code_id: UUID
    note: str | None = Field(default=None, max_length=500)


class ReturnLineIn(BaseModel):
    sale_line_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]


class ReturnIn(BaseModel):
    lines: Annotated[list[ReturnLineIn], Field(min_length=1, max_length=200)]
    reason_code_id: UUID
    refund_method: Literal["cash", "mobile_money", "exchange", "credit_note"]
    note: str | None = Field(default=None, max_length=500)
    restock_location_id: UUID | None = None


class ReturnLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sale_line_id: UUID | None
    product_id: UUID
    quantity: Decimal
    line_total: Decimal
    tax_amount: Decimal


class ReturnSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: str
    company_id: UUID
    branch_id: UUID | None
    original_sale_id: UUID | None
    original_invoice_id: UUID | None
    refund_method: str
    total: Decimal
    status: str
    business_date: date | None


class ReturnOut(ReturnSummaryOut):
    lines: list[ReturnLineOut]


class CatalogItemOut(BaseModel):
    product_id: UUID
    sku: str
    name: str
    product_type: str
    vat_rate: Decimal
    is_batch_tracked: bool
    uom_id: UUID
    price: Decimal | None
    stock: Decimal | None
    barcodes: list[str] = []


class ReceiptSettingsOut(BaseModel):
    header: list[str] = Field(description="Company, branch, address, phone and tax number lines, top of a receipt")
    footer: list[str] = Field(description="The company's receipt footer")


# --------------------------------------------------------------------------- offline sync
class TillRefIn(BaseModel):
    till_session_id: UUID | None = None
    till_local_id: UUID | None = Field(default=None, description="The id the device made when it opened the till")


class TillOpenOp(TillRefIn):
    type: Literal["till_open"]
    local_id: UUID
    at: datetime
    opening_float: NonNegative = Decimal(0)


class SaleOp(TillRefIn):
    type: Literal["sale"]
    local_id: UUID
    at: datetime
    number: str | None = Field(default=None, max_length=60,
                               description="The device's own number: POS-<branch>-<device>-L000123")
    lines: Annotated[list[SaleLineIn], Field(min_length=1, max_length=200)]
    payments: Annotated[list[SalePaymentIn], Field(min_length=1, max_length=10)]
    customer_id: UUID | None = None


class TillCloseOp(TillRefIn):
    type: Literal["till_close"]
    local_id: UUID
    at: datetime
    counted_cash: NonNegative
    reason_code_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


SyncOpIn = Annotated[TillOpenOp | SaleOp | TillCloseOp, Field(discriminator="type")]


class UploadIn(BaseModel):
    ops: Annotated[list[SyncOpIn], Field(max_length=200)]


class OpResultOut(BaseModel):
    local_id: UUID
    type: str
    status: Literal["ok", "duplicate", "rejected"]
    id: UUID | None = None
    number: str | None = None
    warnings: list[str] = []
    error: str | None = None


class UploadOut(BaseModel):
    results: list[OpResultOut]
    server_time: datetime


class RejectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    device_id: UUID
    local_id: UUID
    op_type: str
    error: str
    attempts: int
    created_at: datetime
    resolved_at: datetime | None
    payload: dict[str, Any]


class SnapshotOut(BaseModel):
    device_id: UUID
    branch_id: UUID
    location_id: UUID | None
    server_time: datetime
    items: list[CatalogItemOut]
    has_more: bool


# --------------------------------------------------------------------------- invoices and receipts
class InvoiceLineIn(BaseModel):
    product_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]
    unit_price: NonNegative | None = Field(default=None, description="Tax-inclusive; leave out for their price")
    discount: NonNegative = Decimal(0)
    reason_code_id: UUID | None = Field(default=None, description="From the 'price_override' list")
    batch_id: UUID | None = None
    order_line_id: UUID | None = None


class InvoiceIn(BaseModel):
    customer_id: UUID
    lines: Annotated[list[InvoiceLineIn], Field(min_length=1, max_length=200)]
    branch_id: UUID | None = None
    location_id: UUID | None = Field(default=None, description="The store the goods leave from")
    issue_date: date | None = None
    terms_days: int | None = Field(default=None, ge=0, le=365, description="Default: the customer's terms")
    notes: str | None = Field(default=None, max_length=500)


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    line_no: int | None
    product_id: UUID
    quantity: Decimal
    list_price: Decimal | None
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    cost_amount: Decimal | None


class InvoiceSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    customer_id: UUID
    sale_id: UUID | None
    sales_order_id: UUID | None
    kind: str
    issue_date: date
    due_date: date
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    credited: Decimal
    status: str


class InvoiceOut(InvoiceSummaryOut):
    notes: str | None
    cancel_reason: str | None
    lines: list[InvoiceLineOut]


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AllocationIn(BaseModel):
    invoice_id: UUID
    amount: Money


class ReceiptIn(BaseModel):
    customer_id: UUID
    amount: Money
    method: Literal["cash", "mobile_money", "bank", "card", "cheque", "other"]
    branch_id: UUID | None = None
    payment_account_id: UUID | None = None
    external_ref: str | None = Field(default=None, max_length=60, description="M-Pesa code, bank ref, cheque no.")
    received_on: date | None = None
    allocations: list[AllocationIn] | None = Field(default=None, description="Default: the oldest invoices first")
    till_session_id: UUID | None = Field(default=None, description="Cash taken at your till")
    hold_balance: bool = Field(default=False, description="Keep what is not needed for invoices on the customer's "
                                                          "account as an advance")


class AllocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    invoice_id: UUID
    amount: Decimal


class ReceiptSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    customer_id: UUID
    payment_id: UUID | None
    method: str
    amount: Decimal
    received_on: date
    reference: str | None
    status: str
    unallocated: Decimal
    refunded: Decimal


class ReceiptOut(ReceiptSummaryOut):
    allocations: list[AllocationOut]


# --------------------------------------------------------------------------- quotations and orders
class DocLineIn(BaseModel):
    product_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]
    unit_price: NonNegative | None = Field(default=None, description="Tax-inclusive; leave out for their price")
    discount: NonNegative = Decimal(0)
    reason_code_id: UUID | None = Field(default=None, description="From the 'price_override' list")


class QuotationIn(BaseModel):
    customer_id: UUID
    lines: Annotated[list[DocLineIn], Field(min_length=1, max_length=200)]
    branch_id: UUID | None = None
    location_id: UUID | None = None
    valid_until: date | None = Field(default=None, description="Default: 14 days from today")
    terms_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = Field(default=None, max_length=500)


class OrderIn(BaseModel):
    customer_id: UUID
    lines: Annotated[list[DocLineIn], Field(min_length=1, max_length=200)]
    branch_id: UUID | None = None
    location_id: UUID | None = None
    terms_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = Field(default=None, max_length=500)


class DocUpdate(BaseModel):
    lines: Annotated[list[DocLineIn], Field(min_length=1, max_length=200)] | None = None
    notes: str | None = Field(default=None, max_length=500)
    valid_until: date | None = None


class DeliverLineIn(BaseModel):
    order_line_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]


class DeliverIn(BaseModel):
    lines: list[DeliverLineIn] | None = Field(default=None, description="Default: everything left to deliver")
    location_id: UUID | None = None
    issue_date: date | None = None


class DocLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    line_no: int | None
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    qty_delivered: Decimal


class DocSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    doc_kind: str
    number: str
    customer_id: UUID | None
    doc_date: date
    valid_until: date | None
    source_quotation_id: UUID | None
    location_id: UUID | None
    terms_days: int
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    status: str


class DocOut(DocSummaryOut):
    notes: str | None
    lines: list[DocLineOut]


class InvoiceReturnLineIn(BaseModel):
    invoice_line_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]


class InvoiceReturnIn(BaseModel):
    lines: Annotated[list[InvoiceReturnLineIn], Field(min_length=1, max_length=200)]
    reason_code_id: UUID
    refund_method: Literal["credit_note", "cash", "mobile_money", "exchange"]
    note: str | None = Field(default=None, max_length=500)
    restock_location_id: UUID | None = None


# --------------------------------------------------------------------------- receivables
class AgeingRowOut(BaseModel):
    customer_id: UUID
    customer: str
    total: Decimal
    not_due: Decimal
    d1_30: Decimal = Field(alias="1_30")
    d31_60: Decimal = Field(alias="31_60")
    d61_90: Decimal = Field(alias="61_90")
    over_90: Decimal

    model_config = ConfigDict(populate_by_name=True)


class AgeingOut(BaseModel):
    as_of: date
    total: Decimal
    buckets: dict[str, Decimal]
    customers: list[AgeingRowOut]


class StatementLineOut(BaseModel):
    date: date
    kind: str
    number: str
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


class StatementOut(BaseModel):
    customer_id: UUID
    customer: str
    code: str
    date_from: date | None
    date_to: date | None
    opening_balance: Decimal
    closing_balance: Decimal
    owed_now: Decimal
    lines: list[StatementLineOut]


class BalanceOut(BaseModel):
    customer_id: UUID
    customer: str
    owes: Decimal = Field(description="Owed on invoices less money held on account (negative: in credit)")
    invoices_owed: Decimal
    credit_on_account: Decimal
    credit_limit: Decimal
    available: Decimal
    terms_days: int
    status: str


class ReminderDueOut(BaseModel):
    invoice_id: UUID
    number: str
    customer_id: UUID
    customer: str
    phone: str | None
    due_date: date
    days_overdue: int
    outstanding: Decimal
    last_reminder: datetime | None


class ReminderIn(BaseModel):
    channel: Literal["sms", "email", "call", "visit"]
    note: str | None = Field(default=None, max_length=300)


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    invoice_id: UUID
    channel: str
    note: str | None
    created_at: datetime


class ApplyCreditIn(BaseModel):
    allocations: list[AllocationIn] | None = Field(default=None, description="Default: the oldest invoices first")


class AppliedOut(BaseModel):
    receipt: str
    invoice: str
    amount: Decimal


class RefundIn(BaseModel):
    amount: Money
    method: Literal["cash", "mobile_money", "bank"]
    reason: str = Field(min_length=1, max_length=300)
    payment_account_id: UUID | None = None
    external_ref: str | None = Field(default=None, max_length=60)


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    receipt_id: UUID
    customer_id: UUID
    payment_id: UUID | None
    method: str
    amount: Decimal
    refunded_on: date
    reason: str
    status: str


class SendReminderIn(BaseModel):
    channel: Literal["sms", "email"] | None = Field(default=None, description="Default: the company's")


class ReminderSentOut(BaseModel):
    invoice_id: UUID
    notification_id: UUID
    channel: str
    status: str


class SendRemindersIn(BaseModel):
    channel: Literal["sms", "email"] | None = None
    min_days_overdue: int = Field(default=1, ge=0, le=3650)
    repeat_days: int = Field(default=7, ge=0, le=365)
    limit: int = Field(default=200, ge=1, le=500)


class RemindersSentOut(BaseModel):
    sent: int
    skipped: int
    no_contact: int
    failed: int


# --------------------------------------------------------------------------- printing
class PrintLineOut(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class PrintVatOut(BaseModel):
    rate: Decimal
    net: Decimal
    tax: Decimal


class PrintLabelOut(BaseModel):
    label: str
    amount: Decimal


class PrintOut(BaseModel):
    """A document ready to print. `format=text` or `html` returns the same thing as ready-made text."""

    title: str
    number: str
    header: list[str]
    meta: list[list[str]]
    lines: list[PrintLineOut]
    vat: list[PrintVatOut]
    totals: list[PrintLabelOut]
    payments: list[PrintLabelOut]
    notes: list[str]
    footer: list[str]
    is_copy: bool
