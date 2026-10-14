"""SQLAlchemy mappings for tables in the `people` schema."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import LargeBinary, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class Department(Audited, Base):
    __tablename__ = "department"
    __table_args__ = {"schema": "people"}
    company_id: Mapped[UUID]
    name: Mapped[str]


class Employee(Audited, Base):
    __tablename__ = "employee"
    __table_args__ = {"schema": "people"}
    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    department_id: Mapped[UUID | None]
    user_id: Mapped[UUID | None]
    employee_no: Mapped[str]
    full_name: Mapped[str]
    national_id_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    tax_id: Mapped[str | None]
    registrations: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    exempt_rules: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    phone: Mapped[str | None]
    email: Mapped[str | None]
    hire_date: Mapped[date]
    termination_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    residency: Mapped[str] = mapped_column(server_default=text("'resident'"))
    is_director: Mapped[bool] = mapped_column(server_default=text("false"))


class PayComponent(Audited, Base):
    __tablename__ = "pay_component"
    __table_args__ = {"schema": "people"}
    company_id: Mapped[UUID]
    code: Mapped[str]
    name: Mapped[str]
    kind: Mapped[str]
    is_taxable: Mapped[bool] = mapped_column(server_default=text("true"))
    is_statutory: Mapped[bool] = mapped_column(server_default=text("false"))
    statutory_code: Mapped[str | None]


class EmploymentTerms(Audited, Base):
    __tablename__ = "employment_terms"
    __table_args__ = {"schema": "people"}
    employee_id: Mapped[UUID]
    basic_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    pay_frequency: Mapped[str] = mapped_column(server_default=text("'monthly'"))
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    approved_by: Mapped[UUID | None]
    note: Mapped[str | None]
    rejected: Mapped[bool] = mapped_column(server_default=text("false"))


class EmployeePayItem(Audited, Base):
    __tablename__ = "employee_pay_item"
    __table_args__ = {"schema": "people"}
    employee_id: Mapped[UUID]
    component_id: Mapped[UUID]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    recurring: Mapped[bool] = mapped_column(server_default=text("true"))
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    description: Mapped[str | None]


class EmployeeBankAccount(Audited, Base):
    __tablename__ = "employee_bank_account"
    __table_args__ = {"schema": "people"}
    employee_id: Mapped[UUID]
    method: Mapped[str]
    bank_name: Mapped[str | None]
    account_no_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    account_no_masked: Mapped[str | None]
    valid_from: Mapped[datetime]
    valid_to: Mapped[datetime | None]
    approved_by: Mapped[UUID | None]
    rejected: Mapped[bool] = mapped_column(server_default=text("false"))


class Shift(Audited, Base):
    __tablename__ = "shift"
    __table_args__ = {"schema": "people"}
    branch_id: Mapped[UUID | None]
    name: Mapped[str]
    start_time: Mapped[time]
    end_time: Mapped[time]


class Attendance(Audited, Base):
    __tablename__ = "attendance"
    __table_args__ = {"schema": "people"}
    employee_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    work_date: Mapped[date]
    shift_id: Mapped[UUID | None]
    clock_in: Mapped[datetime | None]
    clock_out: Mapped[datetime | None]
    hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default=text("0"))
    source: Mapped[str]


class LeaveType(Audited, Base):
    __tablename__ = "leave_type"
    __table_args__ = {"schema": "people"}
    company_id: Mapped[UUID]
    name: Mapped[str]
    days_per_year: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_paid: Mapped[bool] = mapped_column(server_default=text("true"))


class LeaveRequest(Audited, Base):
    __tablename__ = "leave_request"
    __table_args__ = {"schema": "people"}
    employee_id: Mapped[UUID]
    leave_type_id: Mapped[UUID]
    start_date: Mapped[date]
    end_date: Mapped[date]
    days: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    approved_by: Mapped[UUID | None]
    reason: Mapped[str | None]
    decided_note: Mapped[str | None]


class RateTable(TenantColumns, Base):
    __tablename__ = "statutory_rate_table"
    __table_args__ = {"schema": "people"}
    created_by: Mapped[UUID | None]
    company_id: Mapped[UUID]
    payable_account_id: Mapped[UUID | None]
    code: Mapped[str]
    effective_from: Mapped[date]
    effective_to: Mapped[date | None]
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_reference: Mapped[str]
    verified_by: Mapped[str | None]
    verified_at: Mapped[datetime | None]
    is_verified: Mapped[bool] = mapped_column(server_default=text("false"))


class PayrollRun(Audited, Base):
    __tablename__ = "payroll_run"
    __table_args__ = {"schema": "people"}
    company_id: Mapped[UUID]
    period_start: Mapped[date]
    period_end: Mapped[date]
    pay_date: Mapped[date]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    prepared_by: Mapped[UUID | None]
    approved_by: Mapped[UUID | None]
    journal_entry_id: Mapped[UUID | None]
    exceptions: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    submitted_at: Mapped[datetime | None]
    approved_at: Mapped[datetime | None]
    paid_at: Mapped[datetime | None]
    paid_by: Mapped[UUID | None]
    reject_note: Mapped[str | None]
    unpaid_day_divisor: Mapped[int] = mapped_column(server_default=text("30"))


class Payslip(TenantColumns, Base):
    __tablename__ = "payslip"
    __table_args__ = {"schema": "people"}
    run_id: Mapped[UUID]
    employee_id: Mapped[UUID]
    gross_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    taxable_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_pay: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    employer_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    file_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(server_default=text("'calculated'"))
    branch_id: Mapped[UUID | None]
    benefits: Mapped[Decimal] = mapped_column(Numeric(18, 2), server_default=text("0"))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    pay_method: Mapped[str | None]


class PayslipLine(TenantColumns, Base):
    __tablename__ = "payslip_line"
    __table_args__ = {"schema": "people"}
    payslip_id: Mapped[UUID]
    component_code: Mapped[str]
    kind: Mapped[str]
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    rate_table_id: Mapped[UUID | None]
    description: Mapped[str | None]
