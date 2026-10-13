"""Request and response shapes for the Purchasing API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount, Quantity, UnitCost

Qty = Annotated[Quantity, Field(gt=0)]
Cost = Annotated[UnitCost, Field(ge=0)]
Money = Annotated[Amount, Field(gt=0)]
NonNegative = Annotated[Amount, Field(ge=0)]


class SupplierIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=1, max_length=20, examples=["TOTAL01"])
    name: str = Field(min_length=1, max_length=200)
    kra_pin: str | None = Field(default=None, max_length=11, examples=["P051234567A"])
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    payment_terms_days: int = Field(default=0, ge=0, le=365)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kra_pin: str | None = Field(default=None, max_length=11)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    status: Literal["active", "on_hold", "inactive"] | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    kra_pin: str | None
    phone: str | None
    email: str | None
    payment_terms_days: int
    status: str


class BankIn(BaseModel):
    method: Literal["bank", "mpesa"]
    account_no: str = Field(min_length=1, max_length=40)
    bank_name: str | None = Field(default=None, max_length=100)
    account_name: str | None = Field(default=None, max_length=200)


class BankConfirmIn(BaseModel):
    confirmation_method: Literal["phone_callback", "in_person", "signed_letter"]
    note: str | None = Field(default=None, max_length=500)


class BankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    supplier_id: UUID
    method: str
    bank_name: str | None
    account_name: str | None
    account_no_masked: str | None
    status: str
    valid_from: datetime
    valid_to: datetime | None
    created_by: UUID | None
    confirmed_by: UUID | None
    confirmation_method: str | None
    approved_by: UUID | None


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: UUID
    unit_cost: Decimal
    effective_date: date
    source_type: str


# --------------------------------------------------------------------------- requests and orders
class RequestLineIn(BaseModel):
    product_id: UUID
    quantity: Qty
    note: str | None = Field(default=None, max_length=200)


class RequestIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = None
    needed_by: date | None = None
    lines: Annotated[list[RequestLineIn], Field(min_length=1, max_length=200)]


class RequestLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    quantity: Decimal
    note: str | None


class RequestSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    needed_by: date | None
    status: str


class RequestOut(RequestSummaryOut):
    lines: list[RequestLineOut]


class OrderLineIn(BaseModel):
    product_id: UUID
    quantity: Qty
    unit_cost: Cost = Field(description="Before VAT")
    tax_code_id: UUID | None = Field(default=None, description="Default: the product's tax code")


class OrderIn(BaseModel):
    company_id: UUID
    supplier_id: UUID
    lines: Annotated[list[OrderLineIn], Field(min_length=1, max_length=200)]
    branch_id: UUID | None = None
    deliver_to_location_id: UUID | None = None
    order_date: date | None = None
    expected_date: date | None = None
    request_id: UUID | None = None


class OrderUpdate(BaseModel):
    lines: Annotated[list[OrderLineIn], Field(min_length=1, max_length=200)] | None = None
    expected_date: date | None = None
    deliver_to_location_id: UUID | None = None


class OrderLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    tax_code_id: UUID
    qty_received: Decimal
    qty_billed: Decimal


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    supplier_id: UUID
    order_date: date
    expected_date: date | None
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    status: str


class OrderOut(OrderSummaryOut):
    deliver_to_location_id: UUID | None
    lines: list[OrderLineOut]


# --------------------------------------------------------------------------- receipts
class ReceiptLineIn(BaseModel):
    quantity: Qty
    order_line_id: UUID | None = None
    product_id: UUID | None = None
    unit_cost: Cost | None = None
    batch_no: str | None = Field(default=None, max_length=60)
    expiry_date: date | None = None


class ReceiptIn(BaseModel):
    lines: Annotated[list[ReceiptLineIn], Field(min_length=1, max_length=200)]
    order_id: UUID | None = None
    supplier_id: UUID | None = None
    location_id: UUID | None = None
    received_at: datetime | None = None
    delivery_note_no: str | None = Field(default=None, max_length=60)
    landed_cost: NonNegative = Decimal(0)


class ReceiptLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_line_id: UUID | None
    product_id: UUID
    batch_no: str | None
    expiry_date: date | None
    quantity: Decimal
    unit_cost: Decimal


class ReceiptSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    order_id: UUID | None
    supplier_id: UUID
    location_id: UUID | None
    received_at: datetime
    delivery_note_no: str | None
    status: str
    landed_cost: Decimal


class ReceiptOut(ReceiptSummaryOut):
    lines: list[ReceiptLineOut]


# --------------------------------------------------------------------------- bills
class BillLineIn(BaseModel):
    quantity: Qty
    unit_cost: Cost = Field(description="Before VAT")
    receipt_line_id: UUID | None = Field(default=None, description="Goods: the receipt line being billed")
    expense_account_id: UUID | None = Field(default=None, description="Anything else: its expense account")
    description: str | None = Field(default=None, max_length=200)
    tax_code_id: UUID | None = None


class BillIn(BaseModel):
    supplier_id: UUID
    supplier_invoice_no: str = Field(min_length=1, max_length=60)
    bill_date: date
    due_date: date | None = None
    etims_ref: str | None = Field(default=None, max_length=60)
    lines: Annotated[list[BillLineIn], Field(min_length=1, max_length=200)]


class BillUpdate(BaseModel):
    due_date: date | None = None
    lines: Annotated[list[BillLineIn], Field(min_length=1, max_length=200)] | None = None


class ExceptionApprovalIn(BaseModel):
    reason_code_id: UUID
    note: str | None = Field(default=None, max_length=500)


class ExceptionRejectIn(BaseModel):
    note: str = Field(min_length=1, max_length=500)


class PayBillIn(BaseModel):
    amount: Money
    method: Literal["cash", "mpesa", "bank", "card", "cheque", "other"]
    payment_account_id: UUID | None = None
    external_ref: str | None = Field(default=None, max_length=60)
    paid_on: date | None = None


class BillLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    receipt_line_id: UUID | None
    product_id: UUID | None
    expense_account_id: UUID | None
    description: str | None
    quantity: Decimal
    unit_cost: Decimal
    tax_amount: Decimal
    line_total: Decimal


class BillSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    number: str
    supplier_id: UUID
    supplier_invoice_no: str
    bill_date: date
    due_date: date
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    match_status: str
    status: str


class BillOut(BillSummaryOut):
    match_notes: list[str]
    lines: list[BillLineOut]


class PayablesOut(BaseModel):
    as_of: date
    total: Decimal
    buckets: dict[str, Decimal]
    suppliers: list[dict[str, Any]]
