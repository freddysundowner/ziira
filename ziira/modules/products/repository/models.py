"""SQLAlchemy mappings for tables in the `products` schema."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantColumns:
    """Standard columns present on every tenant table."""

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]


class Uom(TenantColumns, Base):
    __tablename__ = "uom"
    __table_args__ = {"schema": "products"}

    code: Mapped[str]
    name: Mapped[str]


class TaxCode(TenantColumns, Base):
    __tablename__ = "tax_code"
    __table_args__ = {"schema": "products"}

    code: Mapped[str]
    name: Mapped[str]
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    authority_code: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Product(TenantColumns, Base):
    __tablename__ = "product"
    __table_args__ = {"schema": "products"}

    company_id: Mapped[UUID]
    sku: Mapped[str]
    name: Mapped[str]
    category_id: Mapped[UUID | None]
    product_type: Mapped[str]
    base_uom_id: Mapped[UUID]
    tax_code_id: Mapped[UUID]
    authority_item_class: Mapped[str | None]
    is_batch_tracked: Mapped[bool]
    reorder_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ProductBarcode(TenantColumns, Base):
    __tablename__ = "product_barcode"
    __table_args__ = {"schema": "products"}

    company_id: Mapped[UUID]
    product_id: Mapped[UUID]
    barcode: Mapped[str]


class PriceList(TenantColumns, Base):
    __tablename__ = "price_list"
    __table_args__ = {"schema": "products"}

    company_id: Mapped[UUID]
    name: Mapped[str]
    branch_id: Mapped[UUID | None]
    customer_group: Mapped[str | None]
    currency: Mapped[str] = mapped_column(server_default=text("'KES'"))
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))


class PriceListItem(TenantColumns, Base):
    __tablename__ = "price_list_item"
    __table_args__ = {"schema": "products"}

    price_list_id: Mapped[UUID]
    product_id: Mapped[UUID]
    uom_id: Mapped[UUID]
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    approved_by: Mapped[UUID | None]
