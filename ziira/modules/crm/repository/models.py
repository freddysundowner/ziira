"""SQLAlchemy mappings for tables in the `crm` schema."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantColumns:
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Audited(TenantColumns):
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]


class Customer(Audited, Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "crm"}

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    kind: Mapped[str] = mapped_column(server_default=text("'business'"))
    phone: Mapped[str | None]
    email: Mapped[str | None]
    tax_id: Mapped[str | None]
    customer_group: Mapped[str | None]
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    payment_terms_days: Mapped[int] = mapped_column(server_default=text("0"))
    owner_user_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))


class CustomerContact(TenantColumns, Base):
    __tablename__ = "customer_contact"
    __table_args__ = {"schema": "crm"}

    customer_id: Mapped[UUID]
    name: Mapped[str]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    role: Mapped[str | None]


class CreditVersion(Audited, Base):
    __tablename__ = "customer_credit_version"
    __table_args__ = {"schema": "crm"}

    customer_id: Mapped[UUID]
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    payment_terms_days: Mapped[int]
    valid_from: Mapped[datetime]
    reason: Mapped[str | None]
    approved_by: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    previous_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class LeadSource(Audited, Base):
    __tablename__ = "lead_source"
    __table_args__ = {"schema": "crm"}

    name: Mapped[str]


class Lead(Audited, Base):
    __tablename__ = "lead"
    __table_args__ = {"schema": "crm"}

    company_id: Mapped[UUID]
    name: Mapped[str]
    business_name: Mapped[str | None]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    source_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'new'"))
    owner_user_id: Mapped[UUID | None]
    converted_customer_id: Mapped[UUID | None]
    lost_reason: Mapped[str | None]
    customer_kind: Mapped[str | None]


class Activity(Audited, Base):
    __tablename__ = "activity"
    __table_args__ = {"schema": "crm"}

    related_type: Mapped[str]
    related_id: Mapped[UUID]
    kind: Mapped[str]
    due_at: Mapped[datetime | None]
    done_at: Mapped[datetime | None]
    owner_user_id: Mapped[UUID | None]
    note: Mapped[str | None]
