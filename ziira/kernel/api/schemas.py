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
    workspace: str = Field(max_length=100, examples=["demo-hardware"])
    login: str = Field(max_length=254, description="Email or phone", examples=["owner@demo.co.ke"])
    password: str
    device_id: str = Field(min_length=1, max_length=200, description="Stable id of this browser or device")
    device_name: str | None = Field(default=None, max_length=200, examples=["Thika till 2"])
    channel: Literal["web", "pos", "api", "whatsapp"] = "web"


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
    branches: list[BranchOut]


class CompanySettingsOut(Out):
    negative_stock_allowed: bool
    count_variance_threshold: Decimal


class CompanySettingsIn(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")
    negative_stock_allowed: bool | None = None
    count_variance_threshold: Annotated[Amount, Field(ge=0)] | None = None


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
