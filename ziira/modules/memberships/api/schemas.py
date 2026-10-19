"""Request and response shapes for the Memberships API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount, Rate

Day = Annotated[date, Field(ge=date(2000, 1, 1), le=date(2100, 12, 31))]
Credits = Annotated[Amount, Field(ge=0, le=Decimal("1000000"))]
Money = Annotated[Amount, Field(ge=0, le=Decimal("1000000000"))]
Interval = Literal["month", "quarter", "year"]
ScheduleInterval = Literal["week", "month", "quarter", "year"]
HolderType = Literal["membership", "package"]
Services = Annotated[list[str], Field(max_length=200)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- settings
class MembershipSettingsUpdate(BaseModel):
    allow_overdraw: bool | None = None
    catch_up_max_periods: int | None = Field(default=None, ge=1, le=24)
    prorate_first_period: bool | None = None
    reminders_enabled: bool | None = None
    renewal_reminder_days: int | None = Field(default=None, ge=0, le=60)
    expiry_reminder_days: int | None = Field(default=None, ge=0, le=120)
    quiet_start: int | None = Field(default=None, ge=0, le=23)
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    message_language: Literal["en", "sw"] | None = None
    grace_days: int | None = Field(default=None, ge=0, le=90)
    dunning_days: str | None = Field(default=None, max_length=60, pattern=r"^\s*(\d{1,3}\s*(,\s*\d{1,3}\s*)*)?$")
    auto_freeze_days: int | None = Field(default=None, ge=0, le=365)
    inactive_weeks: int | None = Field(default=None, ge=0, le=52)
    birthday_messages: bool | None = None
    waiver_required: bool | None = None
    repeat_window_minutes: int | None = Field(default=None, ge=0, le=720)
    expiry_warning_days: int | None = Field(default=None, ge=0, le=60)
    late_cancel_hours: int | None = Field(default=None, ge=0, le=168)
    late_cancel_consumes: bool | None = None
    no_show_consumes: bool | None = None
    points_per_unit: Annotated[Amount, Field(ge=0, le=Decimal("1000"))] | None = None
    point_value: Annotated[Amount, Field(ge=0, le=Decimal("100000"))] | None = None
    referral_reward: Money | None = None
    auto_apply_credit: bool | None = None
    voucher_product_id: UUID | None = None
    offline_valid_hours: int | None = Field(default=None, ge=1, le=168)


class MembershipSettingsOut(Out):
    company_id: UUID
    allow_overdraw: bool
    catch_up_max_periods: int
    prorate_first_period: bool
    reminders_enabled: bool
    renewal_reminder_days: int
    expiry_reminder_days: int
    quiet_start: int
    quiet_end: int
    message_language: str
    grace_days: int
    dunning_days: str
    auto_freeze_days: int
    inactive_weeks: int
    birthday_messages: bool
    waiver_required: bool
    repeat_window_minutes: int
    expiry_warning_days: int
    late_cancel_hours: int
    late_cancel_consumes: bool
    no_show_consumes: bool
    points_per_unit: Decimal
    point_value: Decimal
    referral_reward: Decimal
    auto_apply_credit: bool
    voucher_product_id: UUID | None
    offline_valid_hours: int


# --------------------------------------------------------------------------- plans and packages
class MembershipPlanIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    fee: Money
    billing_interval: Interval = "month"
    credits_per_period: Credits = Decimal(0)
    discount_percent: Rate = Field(default=Decimal(0), ge=0, le=100)
    covered_services: Services = []
    rollover: bool = False
    service_product_id: UUID | None = Field(default=None, description="The service item the fee is invoiced as")
    terms: str | None = Field(default=None, max_length=4000)
    kind: Literal["recurring", "fixed_term", "pass"] | None = None
    valid_days: int | None = Field(default=None, ge=1, le=3660, description="A pass: days it is valid")
    is_trial: bool | None = None
    term_periods: int | None = Field(default=None, ge=1, le=120, description="Fixed term: periods in the contract")
    notice_days: int | None = Field(default=None, ge=0, le=365)
    early_exit_fee: Money | None = None
    joining_fee: Money | None = None
    joining_fee_product_id: UUID | None = None
    freeze_max_days: int | None = Field(default=None, ge=0, le=366, description="Days a year; 0 none; left out: no limit")  # noqa: E501
    freeze_fee: Money | None = None
    prorate: bool | None = None
    access_rules: list[dict[str, Any]] | None = Field(default=None, max_length=14)
    branch_ids: list[UUID] | None = Field(default=None, max_length=200)
    gym_access: bool | None = None
    classes_mode: Literal["included", "credits", "none"] | None = None
    guest_passes_per_period: int | None = Field(default=None, ge=0, le=100)
    description: str | None = Field(default=None, max_length=1000)
    is_example: bool | None = None


class MembershipPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    fee: Money | None = None
    credits_per_period: Credits | None = None
    discount_percent: Rate | None = Field(default=None, ge=0, le=100)
    covered_services: Services | None = None
    rollover: bool | None = None
    service_product_id: UUID | None = None
    terms: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "retired"] | None = None
    kind: Literal["recurring", "fixed_term", "pass"] | None = None
    valid_days: int | None = Field(default=None, ge=1, le=3660, description="A pass: days it is valid")
    is_trial: bool | None = None
    term_periods: int | None = Field(default=None, ge=1, le=120, description="Fixed term: periods in the contract")
    notice_days: int | None = Field(default=None, ge=0, le=365)
    early_exit_fee: Money | None = None
    joining_fee: Money | None = None
    joining_fee_product_id: UUID | None = None
    freeze_max_days: int | None = Field(default=None, ge=0, le=366, description="Days a year; 0 none; left out: no limit")  # noqa: E501
    freeze_fee: Money | None = None
    prorate: bool | None = None
    access_rules: list[dict[str, Any]] | None = Field(default=None, max_length=14)
    branch_ids: list[UUID] | None = Field(default=None, max_length=200)
    gym_access: bool | None = None
    classes_mode: Literal["included", "credits", "none"] | None = None
    guest_passes_per_period: int | None = Field(default=None, ge=0, le=100)
    description: str | None = Field(default=None, max_length=1000)
    is_example: bool | None = None


class MembershipPlanOut(Out):
    id: UUID
    company_id: UUID
    code: str
    name: str
    fee: Decimal
    billing_interval: str
    credits_per_period: Decimal
    discount_percent: Decimal
    covered_services: list[str]
    rollover: bool
    service_product_id: UUID | None
    terms: str | None
    status: str
    kind: str
    valid_days: int | None
    is_trial: bool
    term_periods: int | None
    notice_days: int
    early_exit_fee: Decimal
    joining_fee: Decimal
    joining_fee_product_id: UUID | None
    freeze_max_days: int | None
    freeze_fee: Decimal
    prorate: bool | None
    access_rules: list[dict[str, Any]]
    branch_ids: list[UUID]
    gym_access: bool
    classes_mode: str
    guest_passes_per_period: int
    description: str | None
    is_example: bool
    current_fee: Decimal
    next_fee: Decimal | None = None
    next_fee_from: date | None = None
    next_fee_applies_to_existing: bool = False


class MembershipPriceChangeIn(BaseModel):
    effective_from: Day
    fee: Money
    apply_to_existing: bool = False
    note: str | None = Field(default=None, max_length=300)


class MembershipPriceChangeOut(Out):
    id: UUID
    plan_id: UUID
    effective_from: date
    fee: Decimal
    apply_to_existing: bool
    note: str | None
    status: str
    members_affected: int = 0


class SessionPackageIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    credits: Annotated[Amount, Field(gt=0, le=Decimal("1000000"))]
    price: Money
    expiry_days: int | None = Field(default=None, ge=1, le=3650)
    covered_services: Services = []
    product_id: UUID | None = Field(default=None, description="The service item the sale is invoiced as")
    terms: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=1000)
    is_example: bool = False


class SessionPackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    credits: Annotated[Amount, Field(gt=0, le=Decimal("1000000"))] | None = None
    price: Money | None = None
    expiry_days: int | None = Field(default=None, ge=1, le=3650)
    covered_services: Services | None = None
    product_id: UUID | None = None
    terms: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "retired"] | None = None
    description: str | None = Field(default=None, max_length=1000)
    is_example: bool | None = None


class SessionPackageOut(Out):
    id: UUID
    company_id: UUID
    code: str
    name: str
    credits: Decimal
    price: Decimal
    expiry_days: int | None
    covered_services: list[str]
    product_id: UUID | None
    terms: str | None
    status: str
    description: str | None = None
    is_example: bool = False


# --------------------------------------------------------------------------- members
class MembershipSignUpIn(BaseModel):
    plan_id: UUID
    customer_id: UUID
    branch_id: UUID
    start_date: Day | None = None
    end_date: Day | None = None
    auto_invoice: bool | None = Field(default=None, description="Left out: invoice when the plan can be invoiced")
    notes: str | None = Field(default=None, max_length=1000)
    billing_customer_id: UUID | None = Field(default=None, description="Who is invoiced, if not the member")
    waive_joining_fee: bool = False
    price: Money | None = Field(default=None, description="An agreed price instead of the plan's (needs credits right)")
    voucher_code: str | None = Field(default=None, max_length=30)


class MembershipUpdate(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)
    auto_invoice: bool | None = None
    price_locked: bool | None = None
    billing_customer_id: UUID | None = None
    clear_billing_customer: bool = False


class MembershipHoldIn(BaseModel):
    resume_on: Day | None = None
    frozen: bool = False
    note: str | None = Field(default=None, max_length=300)
    waive_fee: bool = False


class MembershipResumeIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class MembershipCancelIn(BaseModel):
    reason_code_id: UUID | None = Field(default=None, description="From the 'membership_cancel' reasons")
    note: str | None = Field(default=None, max_length=300)
    at_period_end: bool = True
    waive_exit_fee: bool = False


class MembershipPlanChangeIn(BaseModel):
    plan_id: UUID
    when: Literal["now", "next_renewal"] = "now"
    note: str | None = Field(default=None, max_length=300)


class MembershipPlanChangeQuoteOut(BaseModel):
    member_id: UUID
    from_plan: str
    to_plan: str
    period_fraction_left: Decimal
    old_price: Decimal
    new_price: Decimal
    charge_now: Decimal
    can_start_now: bool
    extra_credits_now: Decimal
    starts_on: date
    reason: str | None = None


class MembershipFreezeOut(Out):
    id: UUID
    kind: str
    started_on: date
    planned_resume_on: date | None
    ended_on: date | None
    days: int | None
    fee: Decimal
    reason: str | None


class MembershipAllowanceOut(BaseModel):
    limit: int | None
    used: int
    left: int | None
    fee: Decimal
    allowed: bool


class MembershipOut(Out):
    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    customer_id: UUID
    customer_name: str | None = None
    customer_code: str | None = None
    plan_id: UUID
    plan_name: str
    status: str
    start_date: date
    current_period_start: date
    next_renewal_date: date
    end_date: date | None
    paused_from: date | None
    resume_on: date | None
    cancel_at: date | None
    cancelled_on: date | None
    cancel_note: str | None
    price: Decimal
    billing_interval: str
    credits_per_period: Decimal
    discount_percent: Decimal
    covered_services: list[str]
    rollover: bool
    auto_invoice: bool
    notes: str | None
    balance: Decimal = Decimal(0)
    plan_kind: str = "recurring"
    billing_customer_id: UUID | None = None
    billing_customer_name: str | None = None
    term_end: date | None = None
    price_locked: bool = False
    pending_plan_id: UUID | None = None
    pending_plan_name: str | None = None
    pending_from: date | None = None
    past_due_since: date | None = None
    arrears: Decimal = Decimal(0)
    days_late: int = 0
    hold_kind: str | None = None
    is_trial: bool = False


class MembershipHistoryOut(Out):
    id: UUID
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    happened_on: date
    created_at: datetime


# --------------------------------------------------------------------------- sold packages
class SellPackageIn(BaseModel):
    package_id: UUID
    customer_id: UUID
    branch_id: UUID
    purchased_on: Day | None = None
    price: Money | None = Field(default=None, description="Left out: the catalogue price")
    invoice: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)
    billing_customer_id: UUID | None = None
    voucher_code: str | None = Field(default=None, max_length=30)


class SoldPackageOut(Out):
    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    customer_id: UUID
    customer_name: str | None = None
    customer_code: str | None = None
    package_id: UUID
    name: str
    credits: Decimal
    price: Decimal
    covered_services: list[str]
    purchased_on: date
    expires_on: date | None
    status: str
    notes: str | None
    balance: Decimal = Decimal(0)
    billing_customer_id: UUID | None = None


class PackageRefundIn(BaseModel):
    note: str = Field(min_length=1, max_length=300)


# --------------------------------------------------------------------------- credits
class CreditAdjustIn(BaseModel):
    holder_type: HolderType
    holder_id: UUID
    quantity: Annotated[Amount, Field(ge=Decimal("-1000000"), le=Decimal("1000000"))]
    note: str = Field(min_length=1, max_length=300)


class CreditEntryOut(Out):
    id: UUID
    holder_type: str
    holder_id: UUID
    entry_type: str
    quantity: Decimal
    service_ref: str | None
    source_type: str | None
    source_id: UUID | None
    reverses_id: UUID | None
    period_start: date | None
    business_date: date
    note: str | None
    created_at: datetime


class CreditConsumeIn(BaseModel):
    customer_id: UUID
    service_ref: str | None = Field(default=None, max_length=100)
    quantity: Annotated[Amount, Field(gt=0, le=Decimal("1000000"))] = Decimal(1)
    source_type: str = Field(default="manual", min_length=1, max_length=60)
    source_id: UUID = Field(description="Makes a retry safe: the same source uses the credits once")


class CreditConsumeOut(BaseModel):
    covered: Decimal
    remaining: Decimal
    discount_percent: Decimal
    replayed: bool
    covered_by: list[dict[str, Any]]


class CreditReleaseIn(BaseModel):
    source_type: str = Field(min_length=1, max_length=60)
    source_id: UUID


class CreditReleaseOut(BaseModel):
    released: Decimal


class CustomerCreditsOut(BaseModel):
    customer_id: UUID
    discount_percent: Decimal
    memberships: list[MembershipOut]
    packages: list[SoldPackageOut]


# --------------------------------------------------------------------------- recurring invoices
class RecurringLineIn(BaseModel):
    product_id: UUID
    description: str | None = Field(default=None, max_length=300)
    quantity: Annotated[Amount, Field(gt=0, le=Decimal("1000000"))] = Decimal(1)
    unit_price: Money
    discount: Money = Decimal(0)


class RecurringLineOut(BaseModel):
    product_id: UUID
    description: str | None
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal


class RecurringInvoiceIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    name: str = Field(min_length=1, max_length=200)
    lines: list[RecurringLineIn] = Field(min_length=1, max_length=50)
    billing_interval: ScheduleInterval = "month"
    interval_count: int = Field(default=1, ge=1, le=52)
    anchor_day: int | None = Field(default=None, ge=1, le=31, description="Day of the month; left out: the start day")
    start_date: Day
    end_date: Day | None = None
    max_runs: int | None = Field(default=None, ge=1, le=1000)
    mode: Literal["issue", "draft"] = "issue"
    due_days: int | None = Field(default=None, ge=0, le=365)
    memo: str | None = Field(default=None, max_length=300)
    for_customer_id: UUID | None = Field(default=None, description="Whom the invoice is for, if not the customer billed")  # noqa: E501
    for_label: str | None = Field(default=None, max_length=200)


class RecurringInvoiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    lines: list[RecurringLineIn] | None = Field(default=None, min_length=1, max_length=50)
    end_date: Day | None = None
    max_runs: int | None = Field(default=None, ge=1, le=1000)
    mode: Literal["issue", "draft"] | None = None
    due_days: int | None = Field(default=None, ge=0, le=365)
    memo: str | None = Field(default=None, max_length=300)
    branch_id: UUID | None = None


class RecurringPauseIn(BaseModel):
    resume_on: Day | None = None


class RecurringInvoiceOut(Out):
    id: UUID
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    customer_name: str | None = None
    customer_code: str | None = None
    name: str
    lines: list[RecurringLineOut]
    total: Decimal
    billing_interval: str
    interval_count: int
    anchor_day: int | None
    start_date: date
    next_index: int
    next_run: date
    end_date: date | None
    max_runs: int | None
    mode: str
    status: str
    resume_on: date | None
    due_days: int | None
    memo: str | None
    last_run_at: datetime | None
    last_run_status: str | None
    last_run_message: str | None
    last_invoice_number: str | None
    for_customer_id: UUID | None = None
    for_label: str | None = None


class InvoiceRunOut(Out):
    id: UUID
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    customer_name: str | None = None
    owner_type: str
    owner_id: UUID
    period_start: date
    period_end: date | None
    status: str
    attempts: int
    total: Decimal | None
    invoice_id: UUID | None
    invoice_number: str | None
    message: str | None
    lines: list[RecurringLineOut]
    created_at: datetime
    due_date: date | None = None
    settle_state: str = "open"
    outstanding: Decimal | None = None
    dunning_paused: bool = False
    for_customer_id: UUID | None = None
    for_label: str | None = None


class InvoiceRunDiscardIn(BaseModel):
    note: str = Field(min_length=1, max_length=300)


class InvoicingAvailableOut(BaseModel):
    available: bool


class MembershipSummaryOut(BaseModel):
    active_members: int
    paused_members: int
    renewals_this_month: int
    renewals_next_7_days: int
    packages_expiring_30_days: int
    failed_runs: int
    drafts_waiting: int
    members_late: int = 0
    trials_running: int = 0
    visits_today: int = 0


class MembershipSetupStepOut(BaseModel):
    id: str
    done: bool
