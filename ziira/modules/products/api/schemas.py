"""Request and response shapes for the products API."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Quantity, Rate


class UomIn(BaseModel):
    code: str = Field(max_length=10, examples=["PCS"])
    name: str = Field(max_length=200, examples=["Pieces"])


class UomOut(UomIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class TaxCodeIn(BaseModel):
    code: str = Field(max_length=20, examples=["VAT16"])
    name: str = Field(max_length=200, examples=["Standard VAT"])
    vat_rate: Annotated[Rate, Field(ge=0, le=100, examples=["16"])]
    etims_tax_type: str = Field(examples=["B"])


class TaxCodeOut(TaxCodeIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class ProductIn(BaseModel):
    company_id: UUID
    sku: str = Field(examples=["CEM-50KG"])
    name: str = Field(min_length=1, max_length=200, examples=["Cement 50kg"])
    base_uom_id: UUID
    tax_code_id: UUID
    product_type: Literal["stock", "non_stock", "service"] = "stock"
    is_batch_tracked: bool = False
    reorder_level: Quantity | None = None
    etims_item_class: str | None = Field(default=None, max_length=20)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    sku: str
    name: str
    product_type: str
    base_uom_id: UUID
    tax_code_id: UUID
    is_batch_tracked: bool
    reorder_level: Decimal | None
    is_active: bool
