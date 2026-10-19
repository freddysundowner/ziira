"""SQLAlchemy mappings for tables in the `jobs` schema."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
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


def _schema() -> dict[str, str]:
    return {"schema": "jobs"}


class JobSetting(Audited, Base):
    __tablename__ = "setting"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    default_labour_rate: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    labour_product_id: Mapped[UUID | None]
    parts_product_id: Mapped[UUID | None]
    estimate_valid_days: Mapped[int] = mapped_column(server_default=text("14"))
    default_warranty_days: Mapped[int] = mapped_column(server_default=text("0"))
    tell_customer_when_ready: Mapped[bool] = mapped_column(server_default=text("true"))
    odometer_unit: Mapped[str] = mapped_column(server_default=text("'km'"))
    unapproved_work: Mapped[str] = mapped_column(server_default=text("'warn'"))
    release_unpaid: Mapped[str] = mapped_column(server_default=text("'off'"))
    fees_product_id: Mapped[UUID | None]
    storage_fee_per_day: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    storage_grace_days: Mapped[int] = mapped_column(server_default=text("7"))
    remind_service_due: Mapped[bool] = mapped_column(server_default=text("false"))
    service_reminder_days: Mapped[int] = mapped_column(server_default=text("14"))
    ready_reminder_days: Mapped[int] = mapped_column(server_default=text("0"))
    required_photos: Mapped[str] = mapped_column(server_default=text("'warn'"))
    pack_name: Mapped[str | None]


class JobStatus(Audited, Base):
    __tablename__ = "job_status"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    kind: Mapped[str]
    role: Mapped[str | None]
    position: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class JobStatusMove(Audited, Base):
    __tablename__ = "job_status_move"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    from_status_id: Mapped[UUID]
    to_status_id: Mapped[UUID]


class ChecklistTemplate(Audited, Base):
    __tablename__ = "checklist_template"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    name: Mapped[str]
    asset_kind: Mapped[str | None]
    items: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Asset(Audited, Base):
    __tablename__ = "asset"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    customer_id: Mapped[UUID | None]
    kind: Mapped[str] = mapped_column(server_default=text("'item'"))
    label: Mapped[str]
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    notes: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    odometer_at: Mapped[datetime | None]
    next_service_date: Mapped[date | None]
    next_service_odometer: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    next_service_note: Mapped[str | None]
    service_reminded_for: Mapped[date | None]


class Job(Audited, Base):
    __tablename__ = "job"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    number: Mapped[str]
    customer_id: Mapped[UUID | None]
    customer_name: Mapped[str | None]
    customer_phone: Mapped[str | None]
    asset_id: Mapped[UUID | None]
    status_id: Mapped[UUID]
    status_changed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    title: Mapped[str]
    description: Mapped[str | None]
    condition_notes: Mapped[str | None]
    assignee_id: Mapped[UUID | None]
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    promised_at: Mapped[date | None]
    estimate_sent_at: Mapped[datetime | None]
    ready_at: Mapped[datetime | None]
    collected_at: Mapped[datetime | None]
    collected_by_name: Mapped[str | None]
    closed_at: Mapped[datetime | None]
    warranty_days: Mapped[int] = mapped_column(server_default=text("0"))
    warranty_ends: Mapped[date | None]
    is_rework: Mapped[bool] = mapped_column(server_default=text("false"))
    rework_of_id: Mapped[UUID | None]
    rework_in_warranty: Mapped[bool | None]
    invoice_id: Mapped[UUID | None]
    invoice_number: Mapped[str | None]
    invoiced_at: Mapped[datetime | None]
    job_type_code: Mapped[str | None]
    odometer_in: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    odometer_out: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    fuel_level: Mapped[str | None]
    key_tag: Mapped[str | None]
    belongings: Mapped[str | None]
    acknowledged_by_name: Mapped[str | None]
    acknowledged_at: Mapped[datetime | None]
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    deposit_payment_id: Mapped[UUID | None]
    deposit_at: Mapped[datetime | None]
    deposit_note: Mapped[str | None]
    claim_id: Mapped[UUID | None]
    storage_fee_waived: Mapped[bool] = mapped_column(server_default=text("false"))


class JobChecklistItem(TenantColumns, Base):
    __tablename__ = "job_checklist_item"
    __table_args__ = _schema()

    job_id: Mapped[UUID]
    position: Mapped[int]
    label: Mapped[str]
    state: Mapped[str] = mapped_column(server_default=text("'pending'"))
    note: Mapped[str | None]


class JobEvent(TenantColumns, Base):
    __tablename__ = "job_event"
    __table_args__ = _schema()

    job_id: Mapped[UUID]
    kind: Mapped[str]
    from_status_id: Mapped[UUID | None]
    to_status_id: Mapped[UUID | None]
    note: Mapped[str | None]
    created_by: Mapped[UUID | None]


class JobTask(Audited, Base):
    __tablename__ = "job_task"
    __table_args__ = _schema()

    job_id: Mapped[UUID]
    title: Mapped[str]
    assignee_id: Mapped[UUID | None]
    due_date: Mapped[date | None]
    done_at: Mapped[datetime | None]
    done_by: Mapped[UUID | None]
    position: Mapped[int] = mapped_column(server_default=text("0"))


class JobPart(Audited, Base):
    __tablename__ = "job_part"
    __table_args__ = _schema()

    job_id: Mapped[UUID]
    product_id: Mapped[UUID | None]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_code_id: Mapped[UUID | None]
    location_id: Mapped[UUID | None]
    is_stock: Mapped[bool] = mapped_column(server_default=text("false"))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    cost_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    voided_at: Mapped[datetime | None]
    voided_by: Mapped[UUID | None]
    part_class: Mapped[str | None]
    category_code: Mapped[str | None]
    source: Mapped[str] = mapped_column(server_default=text("'stock'"))
    order_status: Mapped[str | None]
    supplier_id: Mapped[UUID | None]
    supplier_name: Mapped[str | None]
    purchase_order_id: Mapped[UUID | None]
    purchase_order_number: Mapped[str | None]
    expected_on: Mapped[date | None]
    ordered_at: Mapped[datetime | None]
    arrived_at: Mapped[datetime | None]
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    keep_old_part: Mapped[bool] = mapped_column(server_default=text("false"))
    old_part_note: Mapped[str | None]
    void_reason: Mapped[str | None]


class JobLabour(Audited, Base):
    __tablename__ = "job_labour"
    __table_args__ = _schema()

    job_id: Mapped[UUID]
    description: Mapped[str]
    hours: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    assignee_id: Mapped[UUID | None]
    work_date: Mapped[date]
    source: Mapped[str] = mapped_column(server_default=text("'manual'"))
    source_id: Mapped[UUID | None]
    voided_at: Mapped[datetime | None]
    voided_by: Mapped[UUID | None]
    work_type_code: Mapped[str | None]
    task_code: Mapped[str | None]
    booked_hours: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    flat_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class Estimate(Audited, Base):
    __tablename__ = "estimate"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    job_id: Mapped[UUID]
    version: Mapped[int]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    notes: Mapped[str | None]
    valid_until: Mapped[date | None]
    net: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    sent_at: Mapped[datetime | None]
    decided_at: Mapped[datetime | None]
    decided_by: Mapped[UUID | None]
    decided_by_name: Mapped[str | None]
    decision_channel: Mapped[str | None]
    decision_note: Mapped[str | None]
    link_hash: Mapped[str | None]
    kind: Mapped[str] = mapped_column(server_default=text("'main'"))


class EstimateLine(TenantColumns, Base):
    __tablename__ = "estimate_line"
    __table_args__ = _schema()

    estimate_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(server_default=text("0"))
    kind: Mapped[str]
    product_id: Mapped[UUID | None]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_code_id: Mapped[UUID | None]
    net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    work_type_code: Mapped[str | None]
    part_class: Mapped[str | None]


class JobType(Audited, Base):
    __tablename__ = "job_type"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    checklist_template_id: Mapped[UUID | None]
    default_warranty_days: Mapped[int | None]
    required_photos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    position: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class PhotoCategory(Audited, Base):
    __tablename__ = "photo_category"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    position: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class WorkType(Audited, Base):
    __tablename__ = "work_type"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    position: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class LabourTask(Audited, Base):
    __tablename__ = "labour_task"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    work_type_code: Mapped[str | None]
    standard_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    flat_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    asset_kind: Mapped[str | None]
    is_example: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class PartCategory(Audited, Base):
    __tablename__ = "part_category"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    markup_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default=text("0"))
    default_class: Mapped[str | None]
    position: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class JobCharge(TenantColumns, Base):
    __tablename__ = "job_charge"
    __table_args__ = _schema()

    created_by: Mapped[UUID | None]
    job_id: Mapped[UUID]
    kind: Mapped[str]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    tax_code_id: Mapped[UUID | None]
    voided_at: Mapped[datetime | None]
    voided_by: Mapped[UUID | None]


class Bay(Audited, Base):
    __tablename__ = "bay"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    name: Mapped[str]
    position: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class BayBooking(TenantColumns, Base):
    __tablename__ = "bay_booking"
    __table_args__ = _schema()

    created_by: Mapped[UUID | None]
    job_id: Mapped[UUID]
    bay_id: Mapped[UUID]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    note: Mapped[str | None]
    cancelled_at: Mapped[datetime | None]
    cancelled_by: Mapped[UUID | None]


class Loan(TenantColumns, Base):
    __tablename__ = "loan"
    __table_args__ = _schema()

    created_by: Mapped[UUID | None]
    job_id: Mapped[UUID]
    asset_id: Mapped[UUID]
    borrower_name: Mapped[str | None]
    out_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    due_at: Mapped[date | None]
    in_at: Mapped[datetime | None]
    odometer_out: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    odometer_in: Mapped[Decimal | None] = mapped_column(Numeric(12, 1))
    fuel_out: Mapped[str | None]
    fuel_in: Mapped[str | None]
    note: Mapped[str | None]
