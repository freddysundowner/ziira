"""Request and response shapes for the people API."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Money = Annotated[Amount, Field(ge=0)]
Positive = Annotated[Amount, Field(gt=0)]


class DepartmentIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=100)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    name: str


class EmployeeIn(BaseModel):
    company_id: UUID
    full_name: str = Field(min_length=1, max_length=200)
    hire_date: date
    branch_id: UUID | None = None
    department_id: UUID | None = None
    user_id: UUID | None = Field(default=None, description="The system or POS user this person signs in as")
    employee_no: str | None = Field(default=None, max_length=30, description="Generated when left out")
    national_id: str | None = Field(default=None, max_length=40)
    tax_id: str | None = Field(default=None, max_length=40, description="The employee's tax number")
    registrations: dict[str, str] | None = Field(default=None, description="Numbers by rule code, {'PENSION': '123'}")
    exempt_rules: list[str] | None = Field(default=None, max_length=30, description="Rule codes that do not apply")
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    residency: Literal["resident", "non_resident"] = "resident"
    is_director: bool = False


class EmployeeUpdateIn(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    branch_id: UUID | None = None
    department_id: UUID | None = None
    user_id: UUID | None = None
    national_id: str | None = Field(default=None, max_length=40)
    tax_id: str | None = Field(default=None, max_length=40)
    registrations: dict[str, str] | None = None
    exempt_rules: list[str] | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    residency: Literal["resident", "non_resident"] | None = None
    is_director: bool | None = None


class EmployeeOut(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    department_id: UUID | None
    user_id: UUID | None
    employee_no: str
    full_name: str
    national_id_masked: str | None
    tax_id: str | None
    registrations: dict[str, str]
    exempt_rules: list[str]
    phone: str | None
    email: str | None
    hire_date: date
    termination_date: date | None
    status: str
    residency: str
    is_director: bool


class TerminateIn(BaseModel):
    termination_date: date
    reason: str | None = Field(default=None, max_length=300)


class ComponentIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=1, max_length=20, examples=["HOUSE"])
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["earning", "deduction", "benefit", "employer_contribution"]
    is_taxable: bool = True


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    kind: str
    is_taxable: bool


class TermsIn(BaseModel):
    basic_pay: Money
    valid_from: date
    note: str | None = Field(default=None, max_length=300)


class TermsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    basic_pay: Decimal
    valid_from: date
    valid_to: date | None
    approved_by: UUID | None
    rejected: bool
    note: str | None
    created_by: UUID | None


class PayItemIn(BaseModel):
    component_id: UUID
    amount: Positive
    valid_from: date
    recurring: bool = True
    valid_to: date | None = None
    description: str | None = Field(default=None, max_length=200)


class PayItemEndIn(BaseModel):
    valid_to: date


class PayItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    component_id: UUID
    amount: Decimal
    recurring: bool
    valid_from: date
    valid_to: date | None
    description: str | None


class BankIn(BaseModel):
    method: Literal["bank", "mobile_money"]
    account_no: str = Field(min_length=1, max_length=60, description="The account or mobile money number")
    bank_name: str | None = Field(default=None, max_length=100)


class BankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    method: str
    bank_name: str | None
    account_no_masked: str | None
    valid_from: datetime
    valid_to: datetime | None
    approved_by: UUID | None
    rejected: bool
    created_by: UUID | None


class RuleIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=1, max_length=20, examples=["INCOME_TAX"])
    effective_from: date
    effective_to: date | None = None
    definition: dict[str, Any] = Field(description="See the rule format in the people README")
    source_reference: str = Field(min_length=3, max_length=500, description="The law or notice it comes from")
    payable_account_id: UUID | None = Field(default=None, description="The ledger account the amount is owed through")


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    effective_from: date
    effective_to: date | None
    definition: dict[str, Any]
    source_reference: str
    payable_account_id: UUID | None
    is_verified: bool
    verified_by: str | None
    verified_at: datetime | None
    created_by: UUID | None


class VerifyIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


# --------------------------------------------------------------------------- shifts, attendance, leave
class ShiftIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = None
    name: str = Field(min_length=1, max_length=60)
    start_time: time
    end_time: time


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    name: str
    start_time: time
    end_time: time


class AttendanceIn(BaseModel):
    employee_id: UUID
    work_date: date
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=5, decimal_places=2)] | None = None
    overtime_hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=5, decimal_places=2)] | None = None
    shift_id: UUID | None = None


class AttendanceUpdateIn(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    clock_in: datetime | None = None
    clock_out: datetime | None = None
    hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=5, decimal_places=2)] | None = None
    overtime_hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=5, decimal_places=2)] | None = None


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    branch_id: UUID | None
    work_date: date
    shift_id: UUID | None
    clock_in: datetime | None
    clock_out: datetime | None
    hours: Decimal | None
    overtime_hours: Decimal
    source: str


class AttendanceSummaryOut(BaseModel):
    employee_id: UUID
    employee_no: str
    full_name: str
    days: int
    hours: Decimal
    overtime_hours: Decimal


class LeaveTypeIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=60)
    days_per_year: Annotated[Decimal, Field(gt=0, le=366, max_digits=6, decimal_places=2)] | None = None
    is_paid: bool = True


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    name: str
    days_per_year: Decimal | None
    is_paid: bool


class LeaveIn(BaseModel):
    employee_id: UUID | None = Field(default=None, description="Left out: the person's own employee record")
    leave_type_id: UUID
    start_date: date
    end_date: date
    days: Annotated[Decimal, Field(gt=0, le=366, max_digits=6, decimal_places=2)] | None = Field(
        default=None, description="Left out: the working days from start to end. Half days allowed.")
    reason: str | None = Field(default=None, max_length=300)


class LeaveDecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class LeaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    employee_id: UUID
    leave_type_id: UUID
    start_date: date
    end_date: date
    days: Decimal
    status: str
    approved_by: UUID | None
    reason: str | None
    decided_note: str | None


class LeaveBalanceOut(BaseModel):
    leave_type_id: UUID
    leave_type: str
    is_paid: bool
    days_per_year: Decimal | None
    taken: Decimal
    left: Decimal | None
