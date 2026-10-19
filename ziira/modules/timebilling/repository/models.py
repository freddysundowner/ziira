"""SQLAlchemy mappings for tables in the `timebilling` schema."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Numeric, SmallInteger, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantColumns:
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    created_by: Mapped[UUID | None]


class Audited(TenantColumns):
    updated_at: Mapped[datetime | None] = mapped_column(onupdate=func.now())
    updated_by: Mapped[UUID | None]


def money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 2))


class Setting(Audited, Base):
    __tablename__ = "setting"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    minute_step: Mapped[int] = mapped_column(server_default=text("1"))
    timer_round_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    timer_round_mode: Mapped[str] = mapped_column(server_default=text("'nearest'"))
    week_starts_on: Mapped[int] = mapped_column(server_default=text("1"))
    capacity_minutes_week: Mapped[int] = mapped_column(server_default=text("2400"))
    approval_required: Mapped[bool] = mapped_column(server_default=text("true"))
    rates_include_tax: Mapped[bool] = mapped_column(server_default=text("false"))
    service_product_id: Mapped[UUID | None]
    expense_product_id: Mapped[UUID | None]
    invoice_round_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    default_group_by: Mapped[str] = mapped_column(server_default=text("'project'"))
    budget_alert_percent: Mapped[int] = mapped_column(server_default=text("80"))
    unsubmitted_after_days: Mapped[int] = mapped_column(server_default=text("3"))
    unbilled_after_days: Mapped[int] = mapped_column(server_default=text("30"))
    notes_retention_days: Mapped[int | None]
    partner_review: Mapped[bool] = mapped_column(server_default=text("false"))
    partner_review_above: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    default_markup_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default=text("0"))
    receipt_required_above: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    nudge_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    nudge_hour: Mapped[int] = mapped_column(server_default=text("9"))
    work_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default=text("'{1,2,3,4,5}'"))
    approval_reminder_days: Mapped[int] = mapped_column(server_default=text("2"))
    approval_escalate_days: Mapped[int] = mapped_column(server_default=text("5"))


class Staff(Audited, Base):
    __tablename__ = "staff"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    user_id: Mapped[UUID]
    title: Mapped[str | None]
    weekly_capacity_minutes: Mapped[int | None]
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    approver_id: Mapped[UUID | None]
    away_until: Mapped[date | None]
    nudges: Mapped[bool] = mapped_column(server_default=text("true"))


class ClientTerms(Audited, Base):
    __tablename__ = "client_terms"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    customer_id: Mapped[UUID]
    payment_terms_days: Mapped[int | None]
    invoice_group_by: Mapped[str | None]
    billing_notes: Mapped[str | None]
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    expense_markup_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))


class Project(Audited, Base):
    __tablename__ = "project"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    client_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    billing_mode: Mapped[str] = mapped_column(server_default=text("'time_and_materials'"))
    budget_minutes: Mapped[int | None]
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    fixed_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    fee_cap: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    service_product_id: Mapped[UUID | None]
    manager_id: Mapped[UUID | None]
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    notes: Mapped[str | None]


class Milestone(Audited, Base):
    __tablename__ = "milestone"
    __table_args__ = {"schema": "timebilling"}

    project_id: Mapped[UUID]
    name: Mapped[str]
    amount: Mapped[Decimal] = money()
    due_on: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default=text("'planned'"))
    batch_id: Mapped[UUID | None]
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class Rate(Audited, Base):
    __tablename__ = "rate"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    kind: Mapped[str]
    project_id: Mapped[UUID | None]
    client_id: Mapped[UUID | None]
    user_id: Mapped[UUID | None]
    service_product_id: Mapped[UUID | None]
    role_title: Mapped[str | None]
    rate: Mapped[Decimal] = money()
    effective_from: Mapped[date]
    effective_to: Mapped[date | None]
    note: Mapped[str | None]
    seq: Mapped[int] = mapped_column(server_default=text("0"))
    example: Mapped[bool] = mapped_column(server_default=text("false"))


class Week(Audited, Base):
    __tablename__ = "week"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    user_id: Mapped[UUID]
    week_start: Mapped[date]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    submitted_at: Mapped[datetime | None]
    decided_by: Mapped[UUID | None]
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None]
    approval_pending: Mapped[bool] = mapped_column(server_default=text("false"))
    minutes: Mapped[int] = mapped_column(server_default=text("0"))


class Entry(Audited, Base):
    __tablename__ = "entry"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    user_id: Mapped[UUID]
    project_id: Mapped[UUID]
    task: Mapped[str | None]
    work_date: Mapped[date]
    minutes: Mapped[int]
    billable: Mapped[bool] = mapped_column(server_default=text("true"))
    note: Mapped[str | None]
    service_product_id: Mapped[UUID | None]
    source: Mapped[str] = mapped_column(server_default=text("'manual'"))
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    week_id: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None]
    bill_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cost_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    retainer_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    rate_override: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    batch_id: Mapped[UUID | None]
    invoice_id: Mapped[UUID | None]
    invoiced_at: Mapped[datetime | None]
    written_off: Mapped[bool] = mapped_column(server_default=text("false"))


class Expense(Audited, Base):
    __tablename__ = "expense"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    user_id: Mapped[UUID]
    project_id: Mapped[UUID]
    expense_date: Mapped[date]
    description: Mapped[str]
    reference: Mapped[str | None]
    amount: Mapped[Decimal] = money()
    markup_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), server_default=text("0"))
    billable: Mapped[bool] = mapped_column(server_default=text("true"))
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    week_id: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    approved_at: Mapped[datetime | None]
    batch_id: Mapped[UUID | None]
    invoice_id: Mapped[UUID | None]
    invoiced_at: Mapped[datetime | None]
    category: Mapped[str | None]
    written_off: Mapped[bool] = mapped_column(server_default=text("false"))


class Timer(Audited, Base):
    __tablename__ = "timer"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    user_id: Mapped[UUID]
    project_id: Mapped[UUID]
    task: Mapped[str | None]
    note: Mapped[str | None]
    billable: Mapped[bool] = mapped_column(server_default=text("true"))
    service_product_id: Mapped[UUID | None]
    started_at: Mapped[datetime]
    resumed_at: Mapped[datetime | None]
    accumulated_seconds: Mapped[int] = mapped_column(server_default=text("0"))


class Retainer(Audited, Base):
    __tablename__ = "retainer"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    project_id: Mapped[UUID]
    kind: Mapped[str]
    monthly_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    balance_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    topped_up_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    expires_on: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    alert_percent: Mapped[int] = mapped_column(server_default=text("80"))
    note: Mapped[str | None]
    bill_day: Mapped[int] = mapped_column(server_default=text("1"))
    auto_draft: Mapped[bool] = mapped_column(server_default=text("true"))


class RetainerTxn(TenantColumns, Base):
    __tablename__ = "retainer_txn"
    __table_args__ = {"schema": "timebilling"}

    retainer_id: Mapped[UUID]
    kind: Mapped[str]
    minutes: Mapped[int] = mapped_column(server_default=text("0"))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    entry_id: Mapped[UUID | None]
    batch_id: Mapped[UUID | None]
    period: Mapped[str | None]
    occurred_on: Mapped[date]
    note: Mapped[str | None]


class InvoiceBatch(Audited, Base):
    __tablename__ = "invoice_batch"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    client_id: Mapped[UUID]
    project_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    group_by: Mapped[str] = mapped_column(server_default=text("'project'"))
    round_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    due_days: Mapped[int | None]
    memo: Mapped[str | None]
    invoice_id: Mapped[UUID | None]
    invoice_number: Mapped[str | None]
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    issued_by: Mapped[UUID | None]
    issued_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]
    review_status: Mapped[str] = mapped_column(server_default=text("'none'"))
    review_requested_by: Mapped[UUID | None]
    review_requested_at: Mapped[datetime | None]
    review_by: Mapped[UUID | None]
    review_at: Mapped[datetime | None]
    review_note: Mapped[str | None]
    narrative: Mapped[str | None]


class InvoiceBatchLine(TenantColumns, Base):
    __tablename__ = "invoice_batch_line"
    __table_args__ = {"schema": "timebilling"}

    batch_id: Mapped[UUID]
    line_no: Mapped[int]
    kind: Mapped[str]
    project_id: Mapped[UUID | None]
    description: Mapped[str]
    minutes: Mapped[int | None]
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    amount: Mapped[Decimal] = money()
    service_product_id: Mapped[UUID | None]
    entry_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"))
    expense_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PG_UUID(as_uuid=True)), server_default=text("'{}'"))
    milestone_id: Mapped[UUID | None]
    retainer_id: Mapped[UUID | None]
    period: Mapped[str | None]
    list_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    list_minutes: Mapped[int | None]
    write_down_reason: Mapped[str | None]
    automatic: Mapped[bool] = mapped_column(server_default=text("false"))


class Recurrence(Audited, Base):
    __tablename__ = "recurrence"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    project_id: Mapped[UUID]
    name: Mapped[str]
    frequency: Mapped[str]
    due_day: Mapped[int]
    due_month: Mapped[int | None]
    lead_days: Mapped[int] = mapped_column(server_default=text("14"))
    starts_on: Mapped[date]
    ends_on: Mapped[date | None]
    assignee_id: Mapped[UUID | None]
    checklist: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class EngagementTask(Audited, Base):
    __tablename__ = "engagement_task"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    project_id: Mapped[UUID]
    recurrence_id: Mapped[UUID | None]
    name: Mapped[str]
    period: Mapped[str | None]
    due_on: Mapped[date]
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    assignee_id: Mapped[UUID | None]
    items: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    note: Mapped[str | None]
    done_at: Mapped[datetime | None]
    done_by: Mapped[UUID | None]


class EngagementTemplate(Audited, Base):
    __tablename__ = "engagement_template"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    name: Mapped[str]
    description: Mapped[str | None]
    billing_mode: Mapped[str] = mapped_column(server_default=text("'time_and_materials'"))
    budget_minutes: Mapped[int | None]
    frequency: Mapped[str | None]
    due_day: Mapped[int | None]
    due_month: Mapped[int | None]
    lead_days: Mapped[int] = mapped_column(server_default=text("14"))
    checklist: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    milestones: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    source: Mapped[str] = mapped_column(server_default=text("'business'"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class Activity(Audited, Base):
    __tablename__ = "activity"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    name: Mapped[str]
    group_name: Mapped[str | None]
    billable: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    source: Mapped[str] = mapped_column(server_default=text("'business'"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class Snippet(Audited, Base):
    __tablename__ = "snippet"
    __table_args__ = {"schema": "timebilling"}

    company_id: Mapped[UUID]
    kind: Mapped[str]
    name: Mapped[str]
    language: Mapped[str] = mapped_column(server_default=text("'en'"))
    body: Mapped[str]
    source: Mapped[str] = mapped_column(server_default=text("'business'"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
