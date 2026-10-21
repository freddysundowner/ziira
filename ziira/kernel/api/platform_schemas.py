"""Request and reply shapes of the Super Admin's platform endpoints. Money is always a decimal string."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Interval = Literal["month", "year", "one_time"]
Reason = Field(min_length=5, max_length=500)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- plans
class PlatformPriceOut(BaseModel):
    id: UUID | None = None
    currency: str
    interval: str
    amount: Decimal
    tax_inclusive: bool
    withdrawn: bool = False
    effective_from: datetime
    created_by: str | None = None


class PlatformPlanOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str
    edition: str | None
    units: list[str]
    addon_units: list[str]
    max_users: int | None
    max_branches: int | None
    max_companies: int | None
    limits: dict[str, Any]
    highlights: list[str]
    trial_days: int
    intervals: list[str]
    sort_order: int
    is_public: bool
    status: str
    subscribers: int = 0
    updated_at: datetime


class PlanDetail(PlatformPlanOut):
    units_included: list[str]
    prices: list[PlatformPriceOut]
    current_prices: list[PlatformPriceOut]


class PlanIn(In):
    code: str = Field(max_length=40)
    name: str = Field(max_length=80)
    description: str = Field(default="", max_length=1000)
    edition: str | None = Field(default=None, max_length=40)
    units: list[str] = Field(default_factory=list, max_length=100)
    addon_units: list[str] = Field(default_factory=list, max_length=100)
    max_users: int | None = Field(default=None, ge=1, le=10_000_000)
    max_branches: int | None = Field(default=None, ge=1, le=10_000_000)
    max_companies: int | None = Field(default=None, ge=1, le=10_000_000)
    limits: dict[str, int | None] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list, max_length=12)
    trial_days: int = Field(default=0, ge=0, le=365)
    intervals: list[Interval] = Field(default=["month", "year"], min_length=1)
    sort_order: int = Field(default=100, ge=0, le=100000)
    is_public: bool = False


class PlanPatch(In):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    edition: str | None = Field(default=None, max_length=40)
    units: list[str] | None = Field(default=None, max_length=100)
    addon_units: list[str] | None = Field(default=None, max_length=100)
    max_users: int | None = Field(default=None, ge=1, le=10_000_000)
    max_branches: int | None = Field(default=None, ge=1, le=10_000_000)
    max_companies: int | None = Field(default=None, ge=1, le=10_000_000)
    limits: dict[str, int | None] | None = None
    highlights: list[str] | None = Field(default=None, max_length=12)
    trial_days: int | None = Field(default=None, ge=0, le=365)
    intervals: list[Interval] | None = Field(default=None, min_length=1)
    sort_order: int | None = Field(default=None, ge=0, le=100000)
    is_public: bool | None = None
    status: Literal["active", "retired"] | None = None


class PlatformPriceIn(In):
    currency: str = Field(min_length=3, max_length=3)
    interval: Interval
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    tax_inclusive: bool = False
    effective_from: datetime | None = Field(
        default=None, description="Default: now. A future date schedules the change."
    )
    withdrawn: bool = Field(default=False, description="Stop offering this currency and interval from the date")


class AddonOut(BaseModel):
    id: UUID
    code: str
    name: str
    description: str
    kind: str
    unit_name: str | None
    quantity: int
    is_public: bool
    status: str
    sort_order: int
    prices: list[PlatformPriceOut] = Field(default_factory=list)
    current_prices: list[PlatformPriceOut] = Field(default_factory=list)


class AddonIn(In):
    code: str = Field(max_length=40)
    name: str = Field(max_length=80)
    description: str = Field(default="", max_length=500)
    kind: Literal["unit", "users", "branches", "companies"]
    unit_name: str | None = Field(default=None, max_length=60)
    quantity: int = Field(default=1, ge=1, le=100000)
    is_public: bool = False
    sort_order: int = Field(default=100, ge=0, le=100000)


class AddonPatch(In):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    quantity: int | None = Field(default=None, ge=1, le=100000)
    is_public: bool | None = None
    status: Literal["active", "retired"] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)


class UnitSaleOut(BaseModel):
    unit: str
    offered: bool = Field(description="True: businesses outside the plan may buy it, once")
    prices: dict[str, Decimal] = Field(description="The one-time price in force, per currency")
    tax_inclusive: bool


class UnitSalesOut(BaseModel):
    currencies: list[str] = Field(description="The currencies the platform already sells in")
    units: list[UnitSaleOut]


class UnitSaleIn(In):
    offered: bool
    prices: dict[str, Annotated[Decimal | None, Field(ge=0, max_digits=14, decimal_places=2)]] = Field(
        default_factory=dict, max_length=20, description="One-time price per currency; null withdraws that currency"
    )
    tax_inclusive: bool = False


class SubscriberAddonOut(BaseModel):
    id: UUID
    unit_name: str
    title: str
    status: str
    price: Decimal
    currency: str | None
    invoice_id: UUID | None
    invoice_number: str | None
    payment_reference: str | None
    granted_by: str
    granted_by_name: str | None
    reason: str | None
    purchased_at: datetime | None
    revoked_at: datetime | None
    revoked_by: str | None
    revoke_reason: str | None
    created_at: datetime


class GrantAddonIn(In):
    unit: str = Field(max_length=60)
    reason: str = Reason


class CouponOut(BaseModel):
    id: UUID
    code: str
    description: str
    percent_off: Decimal | None
    amounts: dict[str, Decimal]
    duration: str
    duration_periods: int | None
    max_redemptions: int | None
    redeemed: int
    expires_at: datetime | None
    plan_codes: list[str]
    status: str


class CouponIn(In):
    code: str = Field(max_length=40)
    description: str = Field(default="", max_length=300)
    percent_off: Decimal | None = Field(default=None, gt=0, le=100)
    amounts: dict[str, Decimal] = Field(default_factory=dict, description="Fixed discount per currency")
    duration: Literal["once", "repeating", "forever"] = "once"
    duration_periods: int | None = Field(default=None, ge=1, le=120)
    max_redemptions: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    plan_codes: list[str] = Field(default_factory=list, max_length=50)


class StatusIn(In):
    status: Literal["active", "disabled"]


# --------------------------------------------------------------------------- settings
class SettingsOut(BaseModel):
    values: dict[str, Any]
    providers: list[str]
    mode: str


class SettingIn(In):
    value: Any


# --------------------------------------------------------------------------- subscribers
class SubscriberRow(BaseModel):
    id: UUID
    code: str
    name: str
    tenant_status: str
    created_at: datetime
    edition: str | None
    country: str | None
    status: str
    plan_code: str | None
    plan_name: str | None
    interval: str | None
    currency: str | None
    unit_amount: Decimal | None
    period_end: datetime | None
    trial_end: datetime | None
    cancel_at_period_end: bool
    is_comp: bool
    tags: list[str]
    users: int
    max_users: int | None
    branches: int
    max_branches: int | None
    last_activity: datetime | None
    outstanding: dict[str, Decimal]


class SubscriberList(BaseModel):
    total: int
    items: list[SubscriberRow]


class OwnerOut(BaseModel):
    name: str
    email: str | None
    phone: str | None


class SubscriptionOut(BaseModel):
    id: UUID
    plan_code: str
    plan_name: str
    status: str
    interval: str
    currency: str
    unit_amount: Decimal
    tax_inclusive: bool
    entitlements: dict[str, Any]
    period_start: datetime | None
    period_end: datetime | None
    trial_end: datetime | None
    cancel_at_period_end: bool
    coupon_periods_left: int | None
    pending_plan_id: UUID | None
    pending_interval: str | None
    is_comp: bool
    notes: str
    tags: list[str]
    status_reason: str | None
    status_changed_at: datetime
    created_at: datetime


class EventOut(BaseModel):
    occurred_at: datetime
    kind: str
    detail: dict[str, Any] | None
    by_name: str | None


class PlatformInvoiceOut(BaseModel):
    id: UUID
    number: str | None
    tenant_id: UUID | None
    licence_id: UUID | None
    tenant_code: str | None = None
    tenant_name: str | None = None
    bill_to: dict[str, Any]
    kind: str
    status: str
    currency: str
    lines: list[dict[str, Any]]
    tax_lines: list[dict[str, Any]]
    tax_inclusive: bool
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    balance: Decimal
    period_start: datetime | None
    period_end: datetime | None
    issue_date: date | None
    due_date: date | None
    notes: str
    vendor: dict[str, Any]
    created_at: datetime
    issued_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None


class PlatformPaymentOut(BaseModel):
    id: UUID
    invoice_id: UUID | None = None
    invoice_number: str | None = None
    method: str
    reference: str
    amount: Decimal
    currency: str
    paid_on: date
    recorded_by: str | None
    reversed_at: datetime | None


class PlatformRequestOut(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_code: str | None = None
    tenant_name: str | None = None
    plan_code: str
    plan_name: str
    interval: str
    currency: str
    coupon_code: str | None
    note: str
    status: str
    invoice_id: UUID | None
    requested_by: str | None
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None


class UsageOut(BaseModel):
    users: int
    branches: int
    companies: int
    storage_bytes: int
    failed_jobs: int


class LimitsOut(BaseModel):
    users: int | None
    branches: int | None
    companies: int | None


class TrailLine(BaseModel):
    id: int
    occurred_at: datetime
    operator_name: str
    action: str
    target: str | None
    outcome: str
    reason: str | None
    detail: dict[str, Any] | None


class DeletionOut(BaseModel):
    requested_at: datetime
    requested_by: str
    execute_after: datetime
    reason: str


class SubscriberDetail(SubscriberRow):
    owners: list[OwnerOut]
    subscription: SubscriptionOut | None
    timeline: list[EventOut]
    invoices: list[PlatformInvoiceOut]
    payments: list[PlatformPaymentOut]
    requests: list[PlatformRequestOut]
    addons: list[SubscriberAddonOut] = Field(description="Add-ons bought or given")
    usage: UsageOut
    limits: LimitsOut
    units: list[dict[str, Any]]
    grants: list[dict[str, Any]]
    sessions: list[dict[str, Any]]
    audit_trail: list[TrailLine]
    deletion: DeletionOut | None
    access: str
    message: str


class StartSubscriptionIn(In):
    plan_code: str = Field(max_length=40)
    mode: Literal["trial", "active", "comp"] = "trial"
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    interval: Interval | None = None
    comp_until: datetime | None = None


class ChangePlanIn(In):
    plan_code: str = Field(max_length=40)
    interval: Interval | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    effective: Literal["auto", "now", "period_end"] = "auto"
    bill_prorated: bool = Field(default=True, description="Issue an invoice for the pro rata difference of an upgrade")


class ExtendTrialIn(In):
    days: int = Field(ge=1, le=365)


class CompIn(In):
    plan_code: str | None = Field(default=None, max_length=40)
    until: datetime | None = None
    reason: str = Reason


class CouponApplyIn(In):
    code: str = Field(max_length=40)


class PlatformReasonIn(In):
    reason: str = Reason


class OptionalReasonIn(In):
    reason: str | None = Field(default=None, max_length=500)


class PlatformCancelIn(In):
    at_period_end: bool = True
    reason: str | None = Field(default=None, max_length=500)


class NotesIn(In):
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=12)


class DeleteIn(In):
    confirm: str = Field(max_length=60, description="The business's code, typed")
    reason: str = Field(min_length=10, max_length=500)
    early: bool = Field(
        default=False, description="Before the retention period ends (for example at the business's request)"
    )


class DeleteOut(BaseModel):
    code: str
    execute_after: datetime


class EmailIn(In):
    email: str = Field(max_length=200)


class ContactFound(BaseModel):
    email: str
    invoices: list[dict[str, Any]]
    registrations: int


class ErasedOut(BaseModel):
    invoices_anonymised: int
    registrations_deleted: int


# --------------------------------------------------------------------------- invoices
class LineIn(In):
    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(default=Decimal(1), gt=0, max_digits=12, decimal_places=3)
    unit_amount: Decimal = Field(max_digits=14, decimal_places=2, description="Negative for a discount")


class PlatformInvoiceIn(In):
    tenant_code: str | None = Field(default=None, max_length=40)
    licence_id: UUID | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lines: list[LineIn] = Field(min_length=1, max_length=50)
    tax_inclusive: bool = False
    notes: str = Field(default="", max_length=2000)
    due_date: date | None = None
    issue: bool = False


class InvoicePatch(In):
    lines: list[LineIn] | None = Field(default=None, min_length=1, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None
    tax_inclusive: bool | None = None


class PlatformPaymentIn(In):
    method: str = Field(min_length=1, max_length=60)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    reference: str = Field(default="", max_length=120)
    paid_on: date | None = None


class InvoiceDetail(PlatformInvoiceOut):
    payments: list[PlatformPaymentOut]


class DecideIn(In):
    approve: bool


class DecideOut(BaseModel):
    status: str
    invoice: PlatformInvoiceOut | None


class BillingRunOut(BaseModel):
    invoices: int
    cancelled: int
    reminders: int
    moved: int
    deletions: int


# --------------------------------------------------------------------------- licences
class LicenceOut(BaseModel):
    id: UUID
    licence_no: str
    customer: str
    contact_email: str | None
    plan_code: str | None
    entitlements: dict[str, Any]
    issued_at: datetime
    valid_until: datetime | None
    update_until: datetime | None
    grace_days: int
    instance_id: str | None
    status: str
    revoked_at: datetime | None
    revoked_reason: str | None
    notes: str
    issued_by: str | None


class LicenceIssueIn(In):
    customer: str = Field(min_length=2, max_length=160)
    contact_email: str | None = Field(default=None, max_length=200)
    plan_code: str | None = Field(default=None, max_length=40)
    edition: str | None = Field(default=None, max_length=40)
    units: list[str] = Field(default_factory=list, max_length=100)
    max_users: int | None = Field(default=None, ge=1)
    max_branches: int | None = Field(default=None, ge=1)
    max_companies: int | None = Field(default=None, ge=1)
    valid_until: datetime | None = Field(default=None, description="Empty: perpetual")
    update_until: datetime | None = Field(default=None, description="Empty: updates are not limited by the licence")
    grace_days: int = Field(default=30, ge=0, le=365)
    instance_id: str | None = Field(default=None, max_length=64)
    notes: str = Field(default="", max_length=1000)


class LicenceIssued(LicenceOut):
    token: str = Field(description="The licence file: give it to the customer")


class FileOut(BaseModel):
    filename: str
    content: str


# --------------------------------------------------------------------------- operators
class OperatorCreateIn(In):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=1024,
                                 description="Leave out to get a random temporary password; either way the person "
                                             "must choose their own at the first sign-in")
    role: Literal["superadmin", "billing", "support", "content", "readonly"] = "readonly"


class OperatorCreatedOut(BaseModel):
    id: UUID
    temporary_password: str | None = None
    mfa_secret: str | None = None
    otpauth_uri: str | None = None


class TemporaryPasswordOut(BaseModel):
    temporary_password: str


class OperatorSecretOut(BaseModel):
    id: UUID | None = None
    mfa_secret: str
    otpauth_uri: str


class OperatorPatch(In):
    role: Literal["superadmin", "billing", "support", "content", "readonly"] | None = None
    status: Literal["active", "disabled"] | None = None


class OperatorBrief(BaseModel):
    id: UUID
    name: str
    email: str
    status: str
    role: str


class PlatformRoleOut(BaseModel):
    role: str
    permissions: list[str]


class RolesOut(BaseModel):
    roles: list[PlatformRoleOut]
    permissions: dict[str, str]


# --------------------------------------------------------------------------- dashboard
class MrrRow(BaseModel):
    currency: str
    mrr: Decimal
    arr: Decimal
    subscribers: int


class TrialStats(BaseModel):
    in_progress: int
    ending_soon: int
    converted: int
    lapsed: int
    conversion_percent: int | None


class OwedRow(BaseModel):
    currency: str
    invoices: int
    owed: Decimal


class HotSpot(BaseModel):
    code: str
    name: str
    kind: str
    used: int
    limit: int


class RenewalRow(BaseModel):
    code: str
    name: str
    plan: str
    period_end: datetime
    amount: Decimal
    currency: str


class FailedJobsRow(BaseModel):
    code: str
    name: str
    failed_jobs: int


class DashboardOut(BaseModel):
    generated_at: datetime
    period_days: int
    mrr: list[MrrRow]
    new_subscribers: int
    churned: int
    trials: TrialStats
    past_due: list[OwedRow]
    by_status: dict[str, int]
    by_plan: dict[str, int]
    by_edition: dict[str, int]
    by_country: dict[str, int]
    unmanaged: int
    usage_hot_spots: list[HotSpot]
    upcoming_renewals: list[RenewalRow]
    failed_jobs: list[FailedJobsRow]
    pending_requests: int
    draft_invoices: int
    mode: str
