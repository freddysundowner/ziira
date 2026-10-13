"""Request and response shapes for the inventory API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LocationIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = Field(default=None, description="Required for a store or warehouse")
    code: str = Field(examples=["MAIN"])
    name: str = Field(examples=["Main shop floor"])
    kind: Literal["store", "warehouse", "transit", "virtual"] = "store"


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    code: str
    name: str
    kind: str
    is_active: bool


class OpeningLineIn(BaseModel):
    product_id: UUID
    quantity: Decimal = Field(gt=0, examples=["100"])
    unit_cost: Decimal = Field(ge=0, examples=["650.00"])
    batch_no: str | None = None
    expiry_date: date | None = None


class OpeningStockIn(BaseModel):
    company_id: UUID
    location_id: UUID
    business_date: date | None = None
    lines: list[OpeningLineIn] = Field(min_length=1)


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    location_id: UUID
    product_id: UUID
    batch_id: UUID | None
    quantity: Decimal
    unit_cost: Decimal | None = Field(description="Hidden without the 'stock.cost' permission")
    value: Decimal | None = Field(description="Hidden without the 'stock.cost' permission")
    movement_type: str
    source_type: str
    source_id: UUID
    reason_code_id: UUID | None
    business_date: date
    created_at: datetime


class BalanceOut(BaseModel):
    location_id: UUID
    location_code: str
    product_id: UUID
    sku: str | None
    product_name: str | None
    batch_id: UUID | None
    quantity: Decimal


class ProductStockOut(BaseModel):
    """A product's stock across the company's locations, with its cost (if the user may see costs)."""

    product_id: UUID
    company_id: UUID
    quantity: Decimal
    average_cost: Decimal | None
    value: Decimal | None


class AdjustmentLineIn(BaseModel):
    product_id: UUID
    qty_change: Decimal = Field(description="+ adds stock, - removes it (base unit)", examples=["-3"])
    batch_id: UUID | None = Field(default=None, description="Needed to add to a batch-tracked product")


class AdjustmentIn(BaseModel):
    company_id: UUID
    location_id: UUID
    reason_code_id: UUID = Field(description="A reason of category 'stock_adjustment'")
    note: str | None = None
    lines: list[AdjustmentLineIn] = Field(min_length=1)


class AdjustmentLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    batch_id: UUID | None
    qty_change: Decimal


class AdjustmentOut(BaseModel):
    id: UUID
    number: str
    company_id: UUID
    location_id: UUID
    reason_code_id: UUID
    note: str | None
    status: str
    created_by: UUID | None
    approved_by: UUID | None
    posted_at: datetime | None
    lines: list[AdjustmentLineOut]


class AdjustmentSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: str
    company_id: UUID
    location_id: UUID
    reason_code_id: UUID
    status: str
    created_by: UUID | None
    posted_at: datetime | None


class TransferLineIn(BaseModel):
    product_id: UUID
    quantity: Decimal = Field(gt=0, examples=["10"])
    batch_id: UUID | None = Field(default=None, description="Required for a batch-tracked product")


class TransferIn(BaseModel):
    company_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    lines: list[TransferLineIn] = Field(min_length=1)


class ReceivedLineIn(BaseModel):
    line_id: UUID
    qty_received: Decimal = Field(ge=0, description="What actually arrived, in the base unit")
    reason_code_id: UUID | None = Field(
        default=None, description="Required when it differs from what was sent (category 'transfer_variance')")


class ReceiveIn(BaseModel):
    lines: list[ReceivedLineIn] | None = Field(default=None, description="Leave out if everything arrived as sent")


class TransferLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    batch_id: UUID | None
    qty_sent: Decimal
    qty_received: Decimal | None
    variance_reason_code_id: UUID | None


class TransferOut(BaseModel):
    id: UUID
    number: str
    company_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    status: str
    created_by: UUID | None
    dispatched_at: datetime | None
    dispatched_by: UUID | None
    received_at: datetime | None
    received_by: UUID | None
    lines: list[TransferLineOut]


class TransferSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: str
    company_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    status: str
    dispatched_at: datetime | None
    received_at: datetime | None


class CountStartIn(BaseModel):
    company_id: UUID
    location_id: UUID
    product_ids: list[UUID] | None = Field(default=None, description="Count only these products; all stock if omitted")


class CountEntryIn(BaseModel):
    product_id: UUID
    counted_qty: Decimal = Field(ge=0, description="What is on the shelf, in the base unit")
    batch_id: UUID | None = Field(default=None, description="Required for a batch-tracked product")
    reason_code_id: UUID | None = Field(default=None, description="Why it differs (category 'count_variance')")


class CountEntriesIn(BaseModel):
    entries: list[CountEntryIn] = Field(min_length=1)


class CountFinishIn(BaseModel):
    uncounted_as_zero: bool = Field(default=False, description="Treat lines nobody counted as zero on the shelf")


class CountReasonIn(BaseModel):
    line_id: UUID
    reason_code_id: UUID


class CountSubmitIn(BaseModel):
    reasons: list[CountReasonIn] = Field(default_factory=list)


class CountLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    batch_id: UUID | None
    expected_qty: Decimal = Field(description="What the system held when the count started")
    counted_qty: Decimal | None
    variance_qty: Decimal | None = Field(description="Counted minus what the system held when it was counted")
    reason_code_id: UUID | None


class CountOut(BaseModel):
    id: UUID
    number: str
    company_id: UUID
    location_id: UUID
    status: str
    snapshot_at: datetime
    created_by: UUID | None
    approved_by: UUID | None
    posted_at: datetime | None
    lines: list[CountLineOut]


class CountSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: str
    company_id: UUID
    location_id: UUID
    status: str
    snapshot_at: datetime
    posted_at: datetime | None
