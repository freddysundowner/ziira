"""SQLAlchemy mappings for tables in the `inventory` schema."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Identity, Numeric, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantColumns:
    """Standard columns present on most tenant tables."""

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Location(TenantColumns, Base):
    __tablename__ = "location"
    __table_args__ = {"schema": "inventory"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    code: Mapped[str]
    name: Mapped[str]
    kind: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Batch(TenantColumns, Base):
    __tablename__ = "batch"
    __table_args__ = {"schema": "inventory"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    product_id: Mapped[UUID]
    batch_no: Mapped[str]
    expiry_date: Mapped[date | None]


class StockMovement(TenantColumns, Base):
    __tablename__ = "stock_movement"
    __table_args__ = {"schema": "inventory"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    location_id: Mapped[UUID]
    product_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    movement_type: Mapped[str]
    source_type: Mapped[str]
    source_id: Mapped[UUID]
    source_line_id: Mapped[UUID | None]
    reason_code_id: Mapped[UUID | None]
    business_date: Mapped[date]
    approved_by: Mapped[UUID | None]
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))


class StockBalance(TenantColumns, Base):
    __tablename__ = "stock_balance"
    __table_args__ = {"schema": "inventory"}

    location_id: Mapped[UUID]
    product_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ProductCost(TenantColumns, Base):
    __tablename__ = "product_cost"
    __table_args__ = {"schema": "inventory"}

    company_id: Mapped[UUID]
    product_id: Mapped[UUID]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), server_default=text("0"))
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class StockAdjustment(TenantColumns, Base):
    __tablename__ = "stock_adjustment"
    __table_args__ = {"schema": "inventory"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    number: Mapped[str]
    location_id: Mapped[UUID]
    reason_code_id: Mapped[UUID]
    note: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]
    posted_at: Mapped[datetime | None]


class StockAdjustmentLine(TenantColumns, Base):
    __tablename__ = "stock_adjustment_line"
    __table_args__ = {"schema": "inventory"}

    adjustment_id: Mapped[UUID]
    product_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    qty_change: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class Transfer(TenantColumns, Base):
    __tablename__ = "transfer"
    __table_args__ = {"schema": "inventory"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    number: Mapped[str]
    from_location_id: Mapped[UUID]
    to_location_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    dispatched_at: Mapped[datetime | None]
    dispatched_by: Mapped[UUID | None]
    received_at: Mapped[datetime | None]
    received_by: Mapped[UUID | None]


class TransferLine(TenantColumns, Base):
    __tablename__ = "transfer_line"
    __table_args__ = {"schema": "inventory"}

    transfer_id: Mapped[UUID]
    product_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    qty_sent: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    qty_received: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    variance_reason_code_id: Mapped[UUID | None]


class StockCount(TenantColumns, Base):
    __tablename__ = "stock_count"
    __table_args__ = {"schema": "inventory"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    number: Mapped[str]
    location_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(server_default=text("'counting'"))
    snapshot_at: Mapped[datetime]
    snapshot_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    approved_by: Mapped[UUID | None]
    posted_at: Mapped[datetime | None]


class StockCountLine(TenantColumns, Base):
    __tablename__ = "stock_count_line"
    __table_args__ = {"schema": "inventory"}

    count_id: Mapped[UUID]
    product_id: Mapped[UUID]
    batch_id: Mapped[UUID | None]
    expected_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    counted_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    variance_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    reason_code_id: Mapped[UUID | None]
    counted_seq: Mapped[int | None] = mapped_column(BigInteger)
    counted_at: Mapped[datetime | None]
