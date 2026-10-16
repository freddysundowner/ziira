"""SQLAlchemy mappings for tables in the `payments` schema."""

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


class PaymentAccount(Audited, Base):
    __tablename__ = "payment_account"
    __table_args__ = {"schema": "payments"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    kind: Mapped[str]
    name: Mapped[str]
    shortcode: Mapped[str | None]
    bank_account_masked: Mapped[str | None]
    credential_id: Mapped[UUID | None]
    ledger_account_id: Mapped[UUID | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    provider: Mapped[str] = mapped_column(server_default=text("'manual'"))
    callback_token_hash: Mapped[str | None]
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class ExternalTransaction(Audited, Base):
    __tablename__ = "external_transaction"
    __table_args__ = {"schema": "payments"}

    payment_account_id: Mapped[UUID]
    source: Mapped[str]
    external_ref: Mapped[str]
    txn_time: Mapped[datetime]
    direction: Mapped[str]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    bill_ref: Mapped[str | None]
    counterparty_name: Mapped[str | None]
    counterparty_phone_masked: Mapped[str | None]
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    match_status: Mapped[str] = mapped_column(server_default=text("'unmatched'"))
    phone_hash: Mapped[str | None]


class PaymentIntent(Audited, Base):
    __tablename__ = "payment_intent"
    __table_args__ = {"schema": "payments"}

    payment_account_id: Mapped[UUID]
    kind: Mapped[str]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    phone_masked: Mapped[str]
    provider_request_id: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    result_code: Mapped[str | None]
    external_transaction_id: Mapped[UUID | None]
    doc_type: Mapped[str | None]
    doc_id: Mapped[UUID | None]
    phone_hash: Mapped[str | None]
    account_reference: Mapped[str | None]
    expires_at: Mapped[datetime | None]
    company_id: Mapped[UUID | None]
    branch_id: Mapped[UUID | None]


class Payment(Audited, Base):
    __tablename__ = "payment"
    __table_args__ = {"schema": "payments"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    direction: Mapped[str]
    method: Mapped[str]
    payment_account_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    business_date: Mapped[date]
    party_type: Mapped[str | None]
    party_id: Mapped[UUID | None]
    external_ref: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'posted'"))
    phone_hash: Mapped[str | None]
    till_session_id: Mapped[UUID | None]


class PaymentAllocation(TenantColumns, Base):
    __tablename__ = "payment_allocation"
    __table_args__ = {"schema": "payments"}

    payment_id: Mapped[UUID]
    doc_type: Mapped[str]
    doc_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class Match(Audited, Base):
    __tablename__ = "match"
    __table_args__ = {"schema": "payments"}

    external_transaction_id: Mapped[UUID]
    payment_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    stage: Mapped[str]
    rule_code: Mapped[str | None]
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(server_default=text("'applied'"))
    undone_by: Mapped[UUID | None]
    undone_at: Mapped[datetime | None]


class DailyClose(Audited, Base):
    __tablename__ = "daily_close"
    __table_args__ = {"schema": "payments"}

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    business_date: Mapped[date]
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    variance: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    submitted_by: Mapped[UUID | None]
    submitted_at: Mapped[datetime | None]
    locked_at: Mapped[datetime | None]
    explanation: Mapped[str | None]
    cash_banked: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    reopened_by: Mapped[UUID | None]
