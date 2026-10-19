"""SQLAlchemy mappings for tables in the `claims` schema."""

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
    return {"schema": "claims"}


def money() -> Any:
    return Numeric(18, 2)


class ClaimSetting(Audited, Base):
    __tablename__ = "setting"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    invoice_product_id: Mapped[UUID | None]
    unapproved_work: Mapped[str] = mapped_column(server_default=text("'warn'"))
    estimate_valid_days: Mapped[int] = mapped_column(server_default=text("14"))
    link_valid_days: Mapped[int] = mapped_column(server_default=text("14"))
    short_pay_tolerance: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))


class Payer(Audited, Base):
    __tablename__ = "payer"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    customer_id: Mapped[UUID | None]
    name: Mapped[str]
    kind: Mapped[str] = mapped_column(server_default=text("'insurer'"))
    labour_rates: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    parts_discount_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), server_default=text("0"))
    parts_markup_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), server_default=text("0"))
    paint_rate: Mapped[Decimal | None] = mapped_column(money())
    approval_limit: Mapped[Decimal | None] = mapped_column(money())
    payment_days: Mapped[int] = mapped_column(server_default=text("30"))
    required_documents: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'"))
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    estimate_email: Mapped[str | None]
    notes: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Claim(Audited, Base):
    __tablename__ = "claim"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    number: Mapped[str]
    payer_id: Mapped[UUID]
    customer_id: Mapped[UUID | None]
    insured_name: Mapped[str | None]
    insured_phone: Mapped[str | None]
    source_type: Mapped[str | None]
    source_id: Mapped[UUID | None]
    source_number: Mapped[str | None]
    subject: Mapped[str | None]
    policy_number: Mapped[str | None]
    claim_number: Mapped[str | None]
    member_number: Mapped[str | None]
    preauth_ref: Mapped[str | None]
    loss_date: Mapped[date | None]
    loss_description: Mapped[str | None]
    assessor_name: Mapped[str | None]
    assessor_phone: Mapped[str | None]
    excess_amount: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    closed_reason: Mapped[str | None]
    closed_note: Mapped[str | None]
    closed_amount: Mapped[Decimal | None] = mapped_column(money())
    closed_at: Mapped[datetime | None]
    authority_ref: Mapped[str | None]
    authority_amount: Mapped[Decimal | None] = mapped_column(money())
    authority_by: Mapped[str | None]
    authority_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    completion_signed_by: Mapped[str | None]
    completion_signed_at: Mapped[datetime | None]
    completion_note: Mapped[str | None]
    invoiced_at: Mapped[datetime | None]


class Estimate(Audited, Base):
    __tablename__ = "estimate"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    seq: Mapped[int]
    lineage_id: Mapped[UUID]
    lineage_kind: Mapped[str]
    lineage_no: Mapped[int] = mapped_column(server_default=text("0"))
    version: Mapped[int] = mapped_column(server_default=text("1"))
    previous_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    title: Mapped[str | None]
    notes: Mapped[str | None]
    revision_note: Mapped[str | None]
    valid_until: Mapped[date | None]
    total: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))
    submitted_at: Mapped[datetime | None]
    submitted_by: Mapped[UUID | None]
    submitted_via: Mapped[str | None]
    answered_at: Mapped[datetime | None]
    response: Mapped[str | None]


class EstimateLine(TenantColumns, Base):
    __tablename__ = "estimate_line"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    estimate_id: Mapped[UUID]
    position: Mapped[int]
    kind: Mapped[str]
    work_type: Mapped[str | None]
    part_class: Mapped[str | None]
    description: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    asked_total: Mapped[Decimal] = mapped_column(money())
    product_id: Mapped[UUID | None]
    carried_from_id: Mapped[UUID | None]
    locked: Mapped[bool] = mapped_column(server_default=text("false"))
    payer_state: Mapped[str] = mapped_column(server_default=text("'pending'"))
    payer_amount: Mapped[Decimal | None] = mapped_column(money())
    payer_reason: Mapped[str | None]
    responded_at: Mapped[datetime | None]
    our_decision: Mapped[str | None]
    customer_decision: Mapped[str | None]
    customer_decision_by: Mapped[str | None]
    customer_decision_at: Mapped[datetime | None]
    shortfall_to: Mapped[str | None]
    invoiced_run_id: Mapped[UUID | None]


class LineResponse(TenantColumns, Base):
    __tablename__ = "line_response"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    estimate_id: Mapped[UUID]
    line_id: Mapped[UUID]
    round: Mapped[int]
    state: Mapped[str]
    amount: Mapped[Decimal | None] = mapped_column(money())
    reason: Mapped[str | None]
    by_name: Mapped[str | None]
    by_user: Mapped[UUID | None]
    channel: Mapped[str]
    via: Mapped[str | None]
    answered_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class EstimateResponse(TenantColumns, Base):
    __tablename__ = "estimate_response"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    estimate_id: Mapped[UUID]
    round: Mapped[int]
    response: Mapped[str]
    by_name: Mapped[str]
    by_user: Mapped[UUID | None]
    channel: Mapped[str]
    via: Mapped[str | None]
    occurred_at: Mapped[datetime]
    note: Mapped[str | None]
    authority_ref: Mapped[str | None]
    authority_amount: Mapped[Decimal | None] = mapped_column(money())


class ClaimEvent(TenantColumns, Base):
    __tablename__ = "claim_event"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    estimate_id: Mapped[UUID | None]
    kind: Mapped[str]
    note: Mapped[str | None]
    occurred_on: Mapped[date | None]
    actor_name: Mapped[str | None]
    actor_id: Mapped[UUID | None]
    channel: Mapped[str | None]


class EstimateLink(TenantColumns, Base):
    __tablename__ = "estimate_link"
    __table_args__ = _schema()

    created_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    estimate_id: Mapped[UUID]
    token_hash: Mapped[str]
    expires_at: Mapped[datetime]
    sent_via: Mapped[str | None]
    sent_to: Mapped[str | None]
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None]
    signed_off_at: Mapped[datetime | None]
    signer_name: Mapped[str | None]
    view_count: Mapped[int] = mapped_column(server_default=text("0"))
    last_accessed_at: Mapped[datetime | None]


class LinkAccess(TenantColumns, Base):
    __tablename__ = "link_access"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    link_id: Mapped[UUID]
    action: Mapped[str]
    outcome: Mapped[str]
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]


class WorkDecision(TenantColumns, Base):
    __tablename__ = "work_decision"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    estimate_id: Mapped[UUID | None]
    decided_by: Mapped[UUID | None]
    note: Mapped[str]


class InvoiceRun(TenantColumns, Base):
    __tablename__ = "invoice_run"
    __table_args__ = _schema()

    created_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    seq: Mapped[int]
    payer_invoice_id: Mapped[UUID | None]
    payer_invoice_number: Mapped[str | None]
    payer_amount: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))
    excess_applied: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))
    customer_invoice_id: Mapped[UUID | None]
    customer_invoice_number: Mapped[str | None]
    customer_amount: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))


class InvoiceLine(TenantColumns, Base):
    __tablename__ = "invoice_line"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    run_id: Mapped[UUID]
    side: Mapped[str]
    kind: Mapped[str]
    estimate_line_id: Mapped[UUID | None]
    invoice_line_id: Mapped[UUID | None]
    amount: Mapped[Decimal] = mapped_column(money())
    discount: Mapped[Decimal] = mapped_column(money(), server_default=text("0"))
    credited_at: Mapped[datetime | None]
    credit_number: Mapped[str | None]


class PayerReceipt(TenantColumns, Base):
    __tablename__ = "payer_receipt"
    __table_args__ = _schema()

    created_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    payer_id: Mapped[UUID]
    pos_receipt_id: Mapped[UUID | None]
    pos_receipt_number: Mapped[str | None]
    amount: Mapped[Decimal] = mapped_column(money())
    method: Mapped[str]
    reference: Mapped[str | None]
    received_on: Mapped[date]
    note: Mapped[str | None]


class ReceiptAllocation(TenantColumns, Base):
    __tablename__ = "payer_receipt_allocation"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    receipt_id: Mapped[UUID]
    run_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    invoice_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(money())
    closes_invoice: Mapped[bool] = mapped_column(server_default=text("false"))


class ShortPay(Audited, Base):
    __tablename__ = "short_pay"
    __table_args__ = _schema()

    company_id: Mapped[UUID]
    claim_id: Mapped[UUID]
    payer_id: Mapped[UUID]
    run_id: Mapped[UUID]
    invoice_id: Mapped[UUID]
    expected: Mapped[Decimal] = mapped_column(money())
    paid: Mapped[Decimal] = mapped_column(money())
    difference: Mapped[Decimal] = mapped_column(money())
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    note: Mapped[str | None]
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[UUID | None]
    recharge_invoice_number: Mapped[str | None]
