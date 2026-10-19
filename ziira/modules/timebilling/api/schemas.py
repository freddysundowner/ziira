"""Request and response shapes for the Time and Billing API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Money = Annotated[Amount, Field(ge=0)]
Positive = Annotated[Amount, Field(gt=0)]
Minutes = Annotated[int, Field(gt=0, le=1440)]
BilledMinutes = Annotated[int, Field(ge=0, le=1_000_000)]      # a grouped invoice line can run past a day
Mode = Literal["time_and_materials", "fixed_fee", "capped_fee", "retainer"]
GroupBy = Literal["project", "person", "task", "day"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- settings, staff, clients
class TimeBillingSettingsOut(Out):
    company_id: UUID
    minute_step: int
    timer_round_minutes: int
    timer_round_mode: str
    week_starts_on: int
    capacity_minutes_week: int
    approval_required: bool
    rates_include_tax: bool
    service_product_id: UUID | None
    expense_product_id: UUID | None
    invoice_round_minutes: int
    default_group_by: str
    budget_alert_percent: int
    unsubmitted_after_days: int
    unbilled_after_days: int
    notes_retention_days: int | None
    partner_review: bool
    partner_review_above: Decimal
    default_markup_percent: Decimal
    receipt_required_above: Decimal | None
    nudge_minutes: int
    nudge_hour: int
    work_days: list[int]
    approval_reminder_days: int
    approval_escalate_days: int


class TimeBillingSettingsUpdate(BaseModel):
    company_id: UUID
    minute_step: Literal[1, 5, 6, 10, 15, 30, 60] | None = None
    timer_round_minutes: Literal[0, 1, 5, 6, 10, 15, 30, 60] | None = None
    timer_round_mode: Literal["up", "nearest", "down"] | None = None
    week_starts_on: int | None = Field(default=None, ge=1, le=7)
    capacity_minutes_week: int | None = Field(default=None, ge=0, le=10080)
    approval_required: bool | None = None
    rates_include_tax: bool | None = None
    service_product_id: UUID | None = None
    expense_product_id: UUID | None = None
    invoice_round_minutes: Literal[0, 5, 6, 10, 15, 30, 60] | None = None
    default_group_by: GroupBy | None = None
    budget_alert_percent: int | None = Field(default=None, ge=1, le=100)
    unsubmitted_after_days: int | None = Field(default=None, ge=0, le=60)
    unbilled_after_days: int | None = Field(default=None, ge=1, le=365)
    notes_retention_days: int | None = Field(default=None, ge=30)
    partner_review: bool | None = None
    partner_review_above: Money | None = None
    default_markup_percent: Decimal | None = Field(default=None, ge=0, le=1000, max_digits=7, decimal_places=2)
    receipt_required_above: Money | None = None
    nudge_minutes: int | None = Field(default=None, ge=0, le=1440)
    nudge_hour: int | None = Field(default=None, ge=0, le=23)
    work_days: list[int] | None = Field(default=None, min_length=1, max_length=7)
    approval_reminder_days: int | None = Field(default=None, ge=0, le=60)
    approval_escalate_days: int | None = Field(default=None, ge=0, le=60)


class StaffOut(BaseModel):
    user_id: UUID
    name: str
    email: str | None
    title: str | None
    weekly_capacity_minutes: int | None
    active: bool
    approver_id: UUID | None = None
    away_until: date | None = None
    nudges: bool = True


class StaffIn(BaseModel):
    company_id: UUID
    title: str | None = Field(default=None, max_length=80)
    weekly_capacity_minutes: int | None = Field(default=None, ge=0, le=10080)
    active: bool = True
    approver_id: UUID | None = None
    away_until: date | None = None
    nudges: bool = True


class ClientTermsIn(BaseModel):
    company_id: UUID
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    invoice_group_by: GroupBy | None = None
    billing_notes: str | None = Field(default=None, max_length=2000)
    active: bool = True
    expense_markup_percent: Decimal | None = Field(default=None, ge=0, le=1000, max_digits=7, decimal_places=2)


class ClientOut(BaseModel):
    customer_id: UUID
    name: str
    payment_terms_days: int | None
    invoice_group_by: str | None
    billing_notes: str | None
    expense_markup_percent: Decimal | None = None
    active: bool
    projects: int
    unbilled_amount: Decimal


# --------------------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    company_id: UUID
    client_id: UUID
    code: str = Field(min_length=1, max_length=20, examples=["WEB-01"])
    name: str = Field(min_length=1, max_length=200)
    branch_id: UUID | None = None
    billing_mode: Mode = "time_and_materials"
    budget_minutes: int | None = Field(default=None, gt=0)
    budget_amount: Positive | None = None
    fixed_fee: Money | None = None
    fee_cap: Positive | None = None
    service_product_id: UUID | None = None
    manager_id: UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    template_id: UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "on_hold", "completed", "archived"] | None = None
    billing_mode: Mode | None = None
    budget_minutes: int | None = Field(default=None, gt=0)
    budget_amount: Positive | None = None
    fixed_fee: Money | None = None
    fee_cap: Positive | None = None
    service_product_id: UUID | None = None
    manager_id: UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ProjectOut(Out):
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    client_id: UUID
    client_name: str = ""
    code: str
    name: str
    status: str
    billing_mode: str
    budget_minutes: int | None
    budget_amount: Decimal | None
    fixed_fee: Decimal | None
    fee_cap: Decimal | None
    service_product_id: UUID | None
    manager_id: UUID | None
    starts_on: date | None
    ends_on: date | None
    notes: str | None


class ProjectSummaryOut(BaseModel):
    project: ProjectOut
    logged_minutes: int
    billable_minutes: int
    unapproved_minutes: int
    budget_minutes_percent: Decimal | None
    budget_amount_percent: Decimal | None
    budget_state: str
    billed_amount: Decimal
    unbilled_amount: Decimal
    cost: Decimal | None
    margin: Decimal | None
    margin_percent: Decimal | None
    unpriced_cost_minutes: int
    fee_cap_percent: Decimal | None = None
    over_cap_amount: Decimal = Decimal(0)


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: Money
    due_on: date | None = None
    sort_order: int = 0


class MilestoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Money | None = None
    due_on: date | None = None
    status: Literal["planned", "ready"] | None = None
    sort_order: int | None = None


class MilestoneOut(Out):
    id: UUID
    project_id: UUID
    name: str
    amount: Decimal
    due_on: date | None
    status: str
    sort_order: int


# --------------------------------------------------------------------------- rates
class RateIn(BaseModel):
    company_id: UUID
    kind: Literal["bill", "cost"]
    rate: Money
    effective_from: date
    effective_to: date | None = None
    project_id: UUID | None = None
    client_id: UUID | None = None
    user_id: UUID | None = None
    service_product_id: UUID | None = None
    role_title: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class RateUpdate(BaseModel):
    rate: Money | None = None
    effective_to: date | None = None
    note: str | None = Field(default=None, max_length=500)
    example: Literal[False] | None = Field(default=None, description="False makes an example row from a pack real")


class RateOut(Out):
    id: UUID
    company_id: UUID
    kind: str
    rate: Decimal
    effective_from: date
    effective_to: date | None
    project_id: UUID | None
    client_id: UUID | None
    user_id: UUID | None
    service_product_id: UUID | None
    role_title: str | None
    note: str | None
    example: bool = False


# --------------------------------------------------------------------------- time
class EntryIn(BaseModel):
    project_id: UUID
    work_date: date
    minutes: Minutes
    task: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    billable: bool = True
    service_product_id: UUID | None = None


class EntryUpdate(BaseModel):
    project_id: UUID | None = None
    work_date: date | None = None
    minutes: Minutes | None = None
    task: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    billable: bool | None = None
    service_product_id: UUID | None = None


class TimeBillingEntryOut(Out):
    id: UUID
    company_id: UUID
    user_id: UUID
    user_name: str = ""
    project_id: UUID
    project_code: str = ""
    project_name: str = ""
    task: str | None
    work_date: date
    minutes: int
    billable: bool
    note: str | None
    source: str
    started_at: datetime | None
    ended_at: datetime | None
    status: str
    week_id: UUID | None
    bill_rate: Decimal | None
    cost_rate: Decimal | None = None
    retainer_minutes: int
    invoice_id: UUID | None
    in_review: bool = False
    written_off: bool = False


class GridCellIn(BaseModel):
    project_id: UUID
    work_date: date
    minutes: int = Field(ge=0, le=1440)
    task: str | None = Field(default=None, max_length=120)
    billable: bool = True


class GridIn(BaseModel):
    cells: list[GridCellIn] = Field(max_length=500)


class TimerStartIn(BaseModel):
    project_id: UUID
    task: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    billable: bool = True
    service_product_id: UUID | None = None


class TimerUpdateIn(BaseModel):
    task: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    billable: bool | None = None


class TimerStopIn(BaseModel):
    minutes: Minutes | None = Field(default=None, description="Replaces the counted time (a forgotten timer)")


class TimerOut(BaseModel):
    project_id: UUID
    project_code: str
    project_name: str
    task: str | None
    note: str | None
    billable: bool
    started_at: datetime
    running: bool
    elapsed_seconds: int


class TimeBillingExpenseIn(BaseModel):
    project_id: UUID
    expense_date: date
    description: str = Field(min_length=1, max_length=300)
    amount: Positive
    markup_percent: Decimal | None = Field(default=None, ge=0, le=1000, max_digits=7, decimal_places=2,
                                           description="Left out: the client's usual markup, else the company's")
    billable: bool = True
    reference: str | None = Field(default=None, max_length=60)
    category: str | None = Field(default=None, max_length=60)


class ExpenseUpdate(BaseModel):
    expense_date: date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=300)
    amount: Positive | None = None
    markup_percent: Decimal | None = Field(default=None, ge=0, le=1000, max_digits=7, decimal_places=2)
    billable: bool | None = None
    reference: str | None = Field(default=None, max_length=60)
    category: str | None = Field(default=None, max_length=60)


class TimeBillingExpenseOut(Out):
    id: UUID
    company_id: UUID
    user_id: UUID
    user_name: str = ""
    project_id: UUID
    project_code: str = ""
    project_name: str = ""
    expense_date: date
    description: str
    reference: str | None
    amount: Decimal
    markup_percent: Decimal
    billable: bool
    status: str
    week_id: UUID | None
    invoice_id: UUID | None
    category: str | None = None
    written_off: bool = False


class WeekOut(BaseModel):
    week_id: UUID | None
    company_id: UUID
    user_id: UUID
    user_name: str
    week_start: date
    status: str
    approval_pending: bool
    decision_note: str | None
    minutes: int
    billable_minutes: int
    submitted_at: datetime | None
    entries: list[TimeBillingEntryOut]
    expenses: list[TimeBillingExpenseOut]


class WeekRow(BaseModel):
    id: UUID
    company_id: UUID
    user_id: UUID
    user_name: str
    week_start: date
    status: str
    approval_pending: bool
    minutes: int
    submitted_at: datetime | None
    decision_note: str | None


class WeekSubmitIn(BaseModel):
    company_id: UUID
    week_start: date


class TimeBillingNoteIn(BaseModel):
    note: str = Field(default="", max_length=500)


# --------------------------------------------------------------------------- billing
class UnbilledOut(BaseModel):
    project_id: UUID
    project_code: str
    project_name: str
    client_id: UUID
    client_name: str
    billing_mode: str
    minutes: int
    time_amount: Decimal
    expense_amount: Decimal
    milestone_amount: Decimal
    amount: Decimal
    unpriced_minutes: int
    in_review_minutes: int
    oldest: date | None
    age_days: int | None
    buckets: dict[str, Decimal]


class ReviewCreateIn(BaseModel):
    company_id: UUID
    client_id: UUID
    project_id: UUID | None = None
    branch_id: UUID | None = None
    group_by: GroupBy | None = None
    date_to: date | None = None
    include_expenses: bool = True
    include_milestones: bool = True
    memo: str | None = Field(default=None, max_length=500)


class ReviewUpdateIn(BaseModel):
    group_by: GroupBy | None = None
    round_minutes: Literal[0, 5, 6, 10, 15, 30, 60] | None = None
    memo: str | None = Field(default=None, max_length=500)
    due_days: int | None = Field(default=None, ge=0, le=365)
    narrative: str | None = Field(default=None, max_length=4000)


class LineUpdateIn(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=300)
    minutes: BilledMinutes | None = Field(default=None, description="Billed minutes of a time line")
    rate: Money | None = None
    amount: Money | None = Field(default=None, description="Amount of a line that is not time")
    write_down_reason: str | None = Field(default=None, max_length=300,
                                          description="Why a line is billed for less than the work is worth")


class TimeBillingNarrativeIn(BaseModel):
    into_lines: bool = False


class TimeBillingReviewDecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=500)


class TimeBillingManualLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    amount: Positive
    service_product_id: UUID | None = None


class ReviewLineOut(Out):
    id: UUID
    line_no: int
    kind: str
    project_id: UUID | None
    description: str
    minutes: int | None
    rate: Decimal | None
    amount: Decimal
    service_product_id: UUID | None
    entry_count: int = 0
    expense_count: int = 0
    list_amount: Decimal | None = None
    list_minutes: int | None = None
    write_down_reason: str | None = None
    automatic: bool = False


class TimeBillingProblemOut(BaseModel):
    code: str
    line_no: int | None = None


class ReviewOut(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    client_id: UUID
    client_name: str
    project_id: UUID | None
    status: str
    group_by: str
    round_minutes: int
    due_days: int | None
    memo: str | None
    invoice_id: UUID | None
    invoice_number: str | None
    total: Decimal | None
    tax_total: Decimal | None
    net_total: Decimal
    estimated_tax: Decimal
    created_at: datetime
    lines: list[ReviewLineOut]
    problems: list[str]
    problem_items: list[TimeBillingProblemOut] = []
    write_down: Decimal = Decimal(0)
    review_status: str = "none"
    review_note: str | None = None
    review_by: UUID | None = None
    review_needed: bool = False
    narrative: str | None = None


class ReviewRow(Out):
    id: UUID
    client_id: UUID
    status: str
    invoice_number: str | None
    total: Decimal | None
    memo: str | None
    created_at: datetime
    review_status: str = "none"


# --------------------------------------------------------------------------- retainers
class RetainerIn(BaseModel):
    kind: Literal["hours", "monthly_fee"]
    monthly_fee: Positive | None = None
    expires_on: date | None = None
    alert_percent: int = Field(default=80, ge=1, le=100)
    opening_minutes: int = Field(default=0, ge=0)
    note: str | None = Field(default=None, max_length=500)
    bill_day: int = Field(default=1, ge=1, le=28)
    auto_draft: bool = True


class RetainerUpdate(BaseModel):
    expires_on: date | None = None
    alert_percent: int | None = Field(default=None, ge=1, le=100)
    monthly_fee: Positive | None = None
    note: str | None = Field(default=None, max_length=500)
    status: Literal["active", "closed"] | None = None
    bill_day: int | None = Field(default=None, ge=1, le=28)
    auto_draft: bool | None = None


class RetainerOut(Out):
    id: UUID
    company_id: UUID
    project_id: UUID
    project_code: str = ""
    project_name: str = ""
    kind: str
    monthly_fee: Decimal | None
    balance_minutes: int
    topped_up_minutes: int
    used_percent: int = 0
    expires_on: date | None
    status: str
    alert_percent: int
    note: str | None
    bill_day: int = 1
    auto_draft: bool = True


class RetainerTxnOut(Out):
    id: UUID
    kind: str
    minutes: int
    amount: Decimal | None
    entry_id: UUID | None
    occurred_on: date
    note: str | None


class TopupIn(BaseModel):
    minutes: int = Field(gt=0, le=1_000_000)
    amount: Positive
    branch_id: UUID | None = None
    memo: str | None = Field(default=None, max_length=500)


class FeeIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-03"])
    branch_id: UUID | None = None


# --------------------------------------------------------------------------- reports
class UtilisationOut(BaseModel):
    user_id: UUID
    name: str
    logged_minutes: int
    billable_minutes: int
    capacity_minutes: int
    percent: Decimal


class MissingWeekOut(BaseModel):
    user_id: UUID
    name: str
    week_start: date
    minutes: int


class ExplainOut(BaseModel):
    rate: RateOut | None


# --------------------------------------------------------------------------- recurring work, templates, wording
class TimeBillingRecurrenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    frequency: Literal["monthly", "quarterly", "annual"]
    due_day: int = Field(ge=1, le=31)
    due_month: int | None = Field(default=None, ge=1, le=12)
    lead_days: int = Field(default=14, ge=0, le=120)
    starts_on: date | None = None
    ends_on: date | None = None
    assignee_id: UUID | None = None
    checklist: list[str] = Field(default_factory=list, max_length=40)


class TimeBillingRecurrenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    frequency: Literal["monthly", "quarterly", "annual"] | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)
    due_month: int | None = Field(default=None, ge=1, le=12)
    lead_days: int | None = Field(default=None, ge=0, le=120)
    ends_on: date | None = None
    assignee_id: UUID | None = None
    checklist: list[str] | None = Field(default=None, max_length=40)
    active: bool | None = None


class TimeBillingRecurrenceOut(Out):
    id: UUID
    company_id: UUID
    project_id: UUID
    project_code: str = ""
    project_name: str = ""
    name: str
    frequency: str
    due_day: int
    due_month: int | None
    lead_days: int
    starts_on: date
    ends_on: date | None
    assignee_id: UUID | None
    checklist: list[str]
    active: bool


class TimeBillingTaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    due_on: date
    assignee_id: UUID | None = None
    checklist: list[str] = Field(default_factory=list, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


class TimeBillingTaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    due_on: date | None = None
    assignee_id: UUID | None = None
    checklist: list[str] | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


class TimeBillingTickIn(BaseModel):
    index: int = Field(ge=0, le=39)
    done: bool = True


class TimeBillingFinishIn(BaseModel):
    skipped: bool = False
    note: str | None = Field(default=None, max_length=1000)


class TimeBillingTaskItem(BaseModel):
    label: str
    done: bool
    by: str | None = None
    at: str | None = None


class TimeBillingTaskOut(BaseModel):
    id: UUID
    company_id: UUID
    project_id: UUID
    project_code: str = ""
    project_name: str = ""
    client_name: str = ""
    recurrence_id: UUID | None
    name: str
    period: str | None
    due_on: date
    status: str
    assignee_id: UUID | None
    assignee_name: str = ""
    items: list[TimeBillingTaskItem]
    note: str | None
    done_at: datetime | None
    overdue: bool = False


class TimeBillingTemplateMilestone(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    percent: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)


class TimeBillingTemplateIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    billing_mode: Mode = "time_and_materials"
    budget_minutes: int | None = Field(default=None, gt=0)
    frequency: Literal["monthly", "quarterly", "annual"] | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)
    due_month: int | None = Field(default=None, ge=1, le=12)
    lead_days: int = Field(default=14, ge=0, le=120)
    checklist: list[str] = Field(default_factory=list, max_length=40)
    milestones: list[TimeBillingTemplateMilestone] = Field(default_factory=list, max_length=20)
    active: bool = True


class TimeBillingTemplateOut(Out):
    id: UUID
    company_id: UUID
    name: str
    description: str | None
    billing_mode: str
    budget_minutes: int | None
    frequency: str | None
    due_day: int | None
    due_month: int | None
    lead_days: int
    checklist: list[str]
    milestones: list[TimeBillingTemplateMilestone]
    source: str
    active: bool


class TimeBillingActivityIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=120)
    group_name: str | None = Field(default=None, max_length=80)
    billable: bool = True
    sort_order: int = 0
    active: bool = True


class TimeBillingActivityOut(Out):
    id: UUID
    company_id: UUID
    name: str
    group_name: str | None
    billable: bool
    sort_order: int
    source: str
    active: bool


class TimeBillingSnippetIn(BaseModel):
    company_id: UUID
    kind: Literal["invoice_note", "engagement_note"] = "invoice_note"
    name: str = Field(min_length=1, max_length=120)
    language: str = Field(default="en", max_length=8)
    body: str = Field(min_length=1, max_length=500)
    active: bool = True


class TimeBillingSnippetOut(Out):
    id: UUID
    company_id: UUID
    kind: str
    name: str
    language: str
    body: str
    source: str
    active: bool


# --------------------------------------------------------------------------- owner reports
class TimeBillingRealisationRow(BaseModel):
    key: str
    code: str
    name: str
    standard: Decimal
    billed: Decimal
    written_down: Decimal
    written_off: Decimal
    percent: Decimal | None


class TimeBillingRealisationOut(BaseModel):
    total: TimeBillingRealisationRow
    clients: list[TimeBillingRealisationRow]
    projects: list[TimeBillingRealisationRow]


class TimeBillingRiskOut(BaseModel):
    project_id: UUID
    code: str
    name: str
    client_id: UUID
    client_name: str = ""
    state: str
    percent: Decimal
    reason: str
    logged_minutes: int
    budget_minutes: int | None
    over_cap_amount: Decimal


class TimeBillingBucketTotal(BaseModel):
    label: str
    amount: Decimal


class TimeBillingOwnerOut(BaseModel):
    """What an owner or partner acts on, in one call."""

    wip_total: Decimal
    wip_buckets: list[TimeBillingBucketTotal]
    realisation: TimeBillingRealisationRow
    utilisation_percent: Decimal | None
    at_risk: list[TimeBillingRiskOut]
    retainers: list[RetainerOut]
    tasks_overdue: int
    weeks_waiting: int
    reviews_waiting: int
    written_off_unsettled: int = 0


class TimeBillingMissingDayOut(BaseModel):
    day: date
    logged_minutes: int
    wanted_minutes: int


# --------------------------------------------------------------------------- getting started and sample data
class TimeBillingStepOut(BaseModel):
    key: str
    done: bool


class TimeBillingSampleOut(BaseModel):
    available: bool
    note: str | None = None
    loaded: bool


class TimeBillingSetupOut(BaseModel):
    steps: list[TimeBillingStepOut]
    example_rates: int
    sample: TimeBillingSampleOut


class TimeBillingSampleResult(BaseModel):
    counts: dict[str, int]
