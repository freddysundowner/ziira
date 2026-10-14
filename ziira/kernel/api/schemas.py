"""Request and response shapes for the kernel API (auth, users, roles, settings, approvals)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel.numbers import Amount


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- auth
class SignInIn(BaseModel):
    workspace: str | None = Field(default=None, max_length=100, examples=["demo-hardware"],
                                  description="Only needed when the same login is in several businesses")
    login: str = Field(max_length=254, description="Email or phone", examples=["owner@demo.co.ke"])
    password: str
    device_id: str = Field(min_length=1, max_length=200, description="Stable id of this browser or device")
    device_name: str | None = Field(default=None, max_length=200, examples=["Thika till 2"])
    channel: Literal["web", "pos", "api"] = "web"


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=500)
    device_id: str = Field(max_length=200)


class TokensOut(Out):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: UUID
    user_id: UUID
    tenant_id: UUID


class RegisterIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120, examples=["Acme Traders"])
    owner_name: str = Field(min_length=2, max_length=120, examples=["Jane Doe"])
    email: str = Field(max_length=200, examples=["jane@acme.test"])
    password: str = Field(max_length=200, description="At least 8 characters")
    currency: str = Field(min_length=3, max_length=3, examples=["USD"], description="The business's base currency")
    phone_country_code: str = Field(default="", max_length=4, examples=["44"],
                                    description="Calling code used to read national phone numbers")
    country: str | None = Field(default=None, min_length=2, max_length=2, examples=["GB"],
                                description="The business's country (two-letter code)")
    tax_id: str | None = Field(default=None, max_length=40)
    invite_code: str | None = Field(default=None, max_length=40,
                                    description="Needed when registration is by invitation")


class RegisterOut(BaseModel):
    message: str
    dev_token: str | None = Field(default=None, description="Outside production only: the token the email carries")


class RegisterVerifyIn(BaseModel):
    token: str = Field(max_length=200)
    device_id: str = Field(min_length=1, max_length=200)
    device_name: str | None = Field(default=None, max_length=200)


class RegisteredOut(TokensOut):
    workspace: str
    business_name: str


class AssignmentOut(Out):
    role_id: UUID | None
    role_name: str
    scope: str
    company_id: UUID | None
    branch_id: UUID | None
    permissions: list[str]


class MeOut(BaseModel):
    tenant_id: UUID
    user_id: UUID | None
    session_id: UUID | None
    channel: str
    full_name: str | None = None
    email: str | None = None
    roles: list[AssignmentOut]


class SessionOut(Out):
    id: UUID
    channel: str
    device_id: str
    device_name: str | None
    created_at: datetime
    last_used_at: datetime
    current: bool = False


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=1024)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=1024)


# --------------------------------------------------------------------------- organisation
class BranchOut(Out):
    id: UUID
    code: str
    name: str


class CompanyOut(Out):
    id: UUID
    name: str
    currency: str
    country: str | None = None
    branches: list[BranchOut]


Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class CompanySettingsOut(Out):
    negative_stock_allowed: bool
    count_variance_threshold: Decimal
    late_posting: Literal["redirect", "reject"]
    bill_match_tolerance_percent: Decimal
    reminder_channel: Literal["off", "sms", "email"]
    reminder_min_days_overdue: int
    reminder_repeat_days: int
    phone_country_code: str
    weekend_days: list[str]
    payroll_unpaid_day_divisor: int
    overtime_multiplier: Decimal
    overtime_hours_per_month: Decimal
    receipt_footer: str
    invoice_footer: str
    timezone: str
    intel_alert_channel: Literal["off", "sms", "email"]
    intel_alert_min_severity: Literal["low", "medium", "high", "critical"]
    intel_action_level: int


class CompanySettingsIn(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    negative_stock_allowed: bool | None = None
    count_variance_threshold: Annotated[Amount, Field(ge=0)] | None = None
    late_posting: Literal["redirect", "reject"] | None = None
    bill_match_tolerance_percent: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None = None
    reminder_channel: Literal["off", "sms", "email"] | None = None
    reminder_min_days_overdue: Annotated[int, Field(ge=0, le=365)] | None = None
    reminder_repeat_days: Annotated[int, Field(ge=0, le=365)] | None = None
    phone_country_code: Annotated[str, Field(max_length=4, pattern=r"^\+?[0-9]{0,3}$")] | None = None
    weekend_days: Annotated[list[Weekday], Field(max_length=3)] | None = None
    payroll_unpaid_day_divisor: Annotated[int, Field(ge=20, le=31)] | None = None
    overtime_multiplier: Annotated[Decimal, Field(ge=1, le=5, max_digits=4, decimal_places=2)] | None = None
    overtime_hours_per_month: Annotated[Decimal, Field(ge=1, le=400, max_digits=6, decimal_places=2)] | None = None
    receipt_footer: Annotated[str, Field(max_length=200, pattern=r"^[^\n\r]*$")] | None = None
    invoice_footer: Annotated[str, Field(max_length=200, pattern=r"^[^\n\r]*$")] | None = None
    timezone: Annotated[str, Field(max_length=64)] | None = None
    intel_alert_channel: Literal["off", "sms", "email"] | None = None
    intel_alert_min_severity: Literal["low", "medium", "high", "critical"] | None = None
    intel_action_level: Annotated[int, Field(ge=1, le=4)] | None = None


# --------------------------------------------------------------------------- users and roles
class UserIn(BaseModel):
    full_name: str = Field(max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    password: str | None = Field(default=None, max_length=1024,
                                 description="Leave empty to invite without a password")


class UserOut(Out):
    id: UUID
    full_name: str
    email: str | None
    phone: str | None
    status: str


class UserStatusIn(BaseModel):
    active: bool


class RoleIn(BaseModel):
    name: str = Field(max_length=100)
    permissions: list[str] = Field(max_length=500)


class RolePermissionsIn(BaseModel):
    permissions: list[str] = Field(max_length=500)


class RoleOut(Out):
    id: UUID
    name: str
    is_system: bool
    permissions: list[str]


class GrantIn(BaseModel):
    role_id: UUID
    scope: Literal["tenant", "company", "branch", "own"]
    company_id: UUID | None = None
    branch_id: UUID | None = None


class GrantOut(Out):
    id: UUID
    user_id: UUID
    role_id: UUID
    role_name: str
    scope: str
    company_id: UUID | None
    branch_id: UUID | None


class PermissionOut(Out):
    code: str
    unit_name: str
    description: str


class ApiKeyIn(BaseModel):
    name: str
    scopes: list[str] = Field(description="Permission codes the key may use")
    expires_at: datetime | None = None


class ApiKeyCreatedOut(BaseModel):
    id: UUID
    key: str = Field(description="Shown only once; store it safely")


class ApiKeyOut(Out):
    id: UUID
    name: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


# --------------------------------------------------------------------------- settings
class SeriesOut(Out):
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    doc_type: str
    prefix: str
    next_number: int
    padding: int


class SeriesUpdateIn(BaseModel):
    prefix: str | None = None
    padding: int | None = None
    next_number: int | None = None


class ReasonIn(BaseModel):
    category: str = Field(examples=["stock_adjustment"])
    code: str = Field(max_length=30, examples=["DAMAGED"])
    label: str = Field(max_length=200, examples=["Damaged in store"])
    requires_note: bool = False


class ReasonOut(Out):
    id: UUID
    category: str
    code: str
    label: str
    requires_note: bool
    is_active: bool


class ActiveIn(BaseModel):
    active: bool


# --------------------------------------------------------------------------- exceptions inbox
class ExceptionItemOut(Out):
    id: UUID
    created_at: datetime
    unit_name: str
    kind: str
    severity: str
    company_id: UUID | None
    branch_id: UUID | None
    ref_type: str | None
    ref_id: UUID | None
    amount: Decimal | None
    message: str
    status: str
    assigned_to: UUID | None
    resolution_note: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None


class ExceptionStatusIn(BaseModel):
    status: Literal["explained", "resolved", "dismissed"]
    note: str = Field(min_length=1, max_length=2000)


class ExceptionAssignIn(BaseModel):
    user_id: UUID | None = None


# --------------------------------------------------------------------------- approvals
class RuleIn(BaseModel):
    company_id: UUID
    doc_type: str = Field(examples=["stock_adjustment"])
    approver_role_id: UUID
    step: int = 1
    min_amount: Annotated[Amount, Field(ge=0)] = Decimal("0")
    max_amount: Annotated[Amount, Field(ge=0)] | None = None
    forbid_creator: bool = True


class RuleOut(Out):
    id: UUID
    company_id: UUID
    doc_type: str
    min_amount: Decimal
    max_amount: Decimal | None
    step: int
    approver_role_id: UUID
    forbid_creator: bool
    is_active: bool


class RequestOut(Out):
    id: UUID
    company_id: UUID | None
    doc_type: str
    doc_id: UUID
    amount: Decimal | None
    step: int
    status: str
    requested_by: UUID | None
    decided_by: UUID | None
    note: str | None


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)
