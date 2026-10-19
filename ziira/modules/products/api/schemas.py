"""Request and response shapes for the products API."""

from datetime import date
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
    authority_code: str | None = Field(default=None, max_length=20, examples=["B"],
                                       description="The code the tax authority uses for this tax, if there is one")


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
    authority_item_class: str | None = Field(default=None, max_length=20)


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
    service_minutes: int | None = Field(default=None, description="Services: how long it usually takes, in minutes")
    is_active: bool
    barcodes: list[str] = Field(default_factory=list, description="Codes a scanner reads for this product")


class BarcodesIn(BaseModel):
    barcodes: list[Annotated[str, Field(max_length=64)]] = Field(
        max_length=20, description="The product's complete list of codes; the ones left out are removed")


class PriceListIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200, examples=["Retail prices"])
    branch_id: UUID | None = None
    is_default: bool = False
    customer_group: str | None = Field(default=None, max_length=60, description="Prices for customers of this group")


class PriceListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    name: str
    branch_id: UUID | None
    currency: str
    is_default: bool
    customer_group: str | None


class PriceIn(BaseModel):
    product_id: UUID
    price: Annotated[Decimal, Field(ge=0, le=Decimal("100000000"), decimal_places=2, examples=["1160.00"])]
    valid_from: date | None = None


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    price_list_id: UUID
    product_id: UUID
    price: Decimal
    valid_from: date
    valid_to: date | None
