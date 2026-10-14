"""SQLAlchemy mappings for tables in the `finance` schema."""

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


class Account(TenantColumns, Base):
    __tablename__ = "account"
    __table_args__ = {"schema": "finance"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    type: Mapped[str]
    subtype: Mapped[str | None]
    parent_id: Mapped[UUID | None]
    is_control: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Period(TenantColumns, Base):
    __tablename__ = "period"
    __table_args__ = {"schema": "finance"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    start_date: Mapped[date]
    end_date: Mapped[date]
    status: Mapped[str] = mapped_column(server_default=text("'open'"))
    closed_by: Mapped[UUID | None]
    closed_at: Mapped[datetime | None]


class PostingRule(TenantColumns, Base):
    __tablename__ = "posting_rule"
    __table_args__ = {"schema": "finance"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    doc_type: Mapped[str]
    line_role: Mapped[str]
    account_id: Mapped[UUID]
    side: Mapped[str]
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    priority: Mapped[int] = mapped_column(server_default=text("100"))


class Journal(TenantColumns, Base):
    __tablename__ = "journal"
    __table_args__ = {"schema": "finance"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]


class JournalEntry(TenantColumns, Base):
    __tablename__ = "journal_entry"
    __table_args__ = {"schema": "finance"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    journal_id: Mapped[UUID]
    period_id: Mapped[UUID]
    number: Mapped[str]
    entry_date: Mapped[date]
    source_type: Mapped[str | None]
    source_id: Mapped[UUID | None]
    description: Mapped[str | None]
    is_manual: Mapped[bool] = mapped_column(server_default=text("false"))
    reversal_of_id: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    posted_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class JournalLine(TenantColumns, Base):
    __tablename__ = "journal_line"
    __table_args__ = {"schema": "finance"}

    entry_id: Mapped[UUID]
    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    account_id: Mapped[UUID]
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    party_type: Mapped[str | None]
    party_id: Mapped[UUID | None]
    description: Mapped[str | None]


class ManualJournal(TenantColumns, Base):
    __tablename__ = "manual_journal"
    __table_args__ = {"schema": "finance"}

    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    journal_id: Mapped[UUID]
    number: Mapped[str]
    entry_date: Mapped[date]
    description: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    entry_id: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]


class ManualJournalLine(TenantColumns, Base):
    __tablename__ = "manual_journal_line"
    __table_args__ = {"schema": "finance"}

    manual_journal_id: Mapped[UUID]
    line_no: Mapped[int]
    account_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    description: Mapped[str | None]


class AccountMapping(TenantColumns, Base):
    __tablename__ = "account_mapping"
    __table_args__ = {"schema": "finance"}
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    account_id: Mapped[UUID]
    external_code: Mapped[str | None]
    external_name: Mapped[str | None]


class Expense(TenantColumns, Base):
    __tablename__ = "expense"
    __table_args__ = {"schema": "finance"}
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    number: Mapped[str]
    expense_date: Mapped[date]
    payee: Mapped[str | None]
    description: Mapped[str]
    account_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    paid_from: Mapped[str]
    receipt_ref: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    approved_by: Mapped[UUID | None]
    entry_id: Mapped[UUID | None]
    reversed_at: Mapped[datetime | None]
    reverse_reason: Mapped[str | None]
