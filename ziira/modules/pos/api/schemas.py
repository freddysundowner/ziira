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


# --------------------------------------------------------------------------- sales
class SaleLineIn(BaseModel):
    product_id: UUID
    quantity: Annotated[Quantity, Field(gt=0)]
    unit_price: NonNegative | None = Field(default=None, description="Tax-inclusive. Leave out to use the list price")
    discount: NonNegative = Decimal(0)
    reason_code_id: UUID | None = Field(default=None, description="From the 'price_override' list")
    batch_id: UUID | None = None


class SalePaymentIn(BaseModel):
    method: Literal["cash", "mpesa", "card", "other"]
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
    refund_method: Literal["cash", "mpesa", "exchange"]
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
