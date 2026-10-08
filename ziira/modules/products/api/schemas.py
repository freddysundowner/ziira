"""Request and response shapes for the products API."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UomIn(BaseModel):
    code: str = Field(examples=["PCS"])
    name: str = Field(examples=["Pieces"])


class UomOut(UomIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class TaxCodeIn(BaseModel):
    code: str = Field(examples=["VAT16"])
    name: str = Field(examples=["Standard VAT"])
    vat_rate: Decimal = Field(examples=["16"])
    etims_tax_type: str = Field(examples=["B"])


class TaxCodeOut(TaxCodeIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class ProductIn(BaseModel):
    company_id: UUID
    sku: str = Field(examples=["CEM-50KG"])
    name: str = Field(min_length=1, examples=["Cement 50kg"])
    base_uom_id: UUID
    tax_code_id: UUID
    product_type: Literal["stock", "non_stock", "service"] = "stock"
    is_batch_tracked: bool = False
    reorder_level: Decimal | None = None
    etims_item_class: str | None = None


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
