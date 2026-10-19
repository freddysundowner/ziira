"""Request and response shapes for the Jobs API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount, Quantity

Qty = Annotated[Quantity, Field(gt=0)]
Price = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)]
Money = Annotated[Amount, Field(ge=0)]
Kind = Literal["open", "waiting", "done", "closed"]
Role = Literal["initial", "quoted", "approved", "ready", "collected", "closed", "cancelled"]


# --------------------------------------------------------------------------- stages and settings
class JobStatusIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=1, max_length=40, examples=["diagnosing"])
    name: str = Field(min_length=1, max_length=60)
    kind: Kind
    role: Role | None = None
    position: int | None = Field(default=None, ge=0, le=100000)


class StatusUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: Kind | None = None
    role: Role | None = None
    position: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class StatusOut(BaseModel):
    id: UUID
    company_id: UUID
    code: str
    name: str
    kind: str
    role: str | None
    position: int
    is_active: bool
    moves_to: list[UUID]


class StatusRef(BaseModel):
    id: UUID
    code: str
    name: str
    kind: str
    role: str | None


class MovesIn(BaseModel):
    to_status_ids: list[UUID] = Field(max_length=60)


class JobSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    company_id: UUID
    default_labour_rate: Decimal
    labour_product_id: UUID | None
    parts_product_id: UUID | None
    estimate_valid_days: int
    default_warranty_days: int
    tell_customer_when_ready: bool
    odometer_unit: str
    unapproved_work: str
    release_unpaid: str
    fees_product_id: UUID | None
    storage_fee_per_day: Decimal
    storage_grace_days: int
    remind_service_due: bool
    service_reminder_days: int
    ready_reminder_days: int
    required_photos: str
    labour_product_name: str | None = None
    parts_product_name: str | None = None
    fees_product_name: str | None = None
    invoicing_available: bool = False


class JobSettingsUpdate(BaseModel):
    default_labour_rate: Money | None = None
    labour_product_id: UUID | None = None
    parts_product_id: UUID | None = None
    estimate_valid_days: int | None = Field(default=None, ge=1, le=365)
    default_warranty_days: int | None = Field(default=None, ge=0, le=3650)
    tell_customer_when_ready: bool | None = None
    odometer_unit: Literal["km", "mi"] | None = None
    unapproved_work: Literal["off", "warn", "block"] | None = None
    release_unpaid: Literal["off", "warn", "block"] | None = None
    fees_product_id: UUID | None = None
    storage_fee_per_day: Money | None = None
    storage_grace_days: int | None = Field(default=None, ge=0, le=365)
    remind_service_due: bool | None = None
    service_reminder_days: int | None = Field(default=None, ge=1, le=120)
    ready_reminder_days: int | None = Field(default=None, ge=0, le=60)
    required_photos: Literal["off", "warn", "block"] | None = None


class TemplateIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=80)
    items: list[str] = Field(default_factory=list, max_length=60)
    asset_kind: str | None = Field(default=None, max_length=40)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    items: list[str] | None = Field(default=None, max_length=60)
    asset_kind: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class JobTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    name: str
    asset_kind: str | None
    items: list[str]
    is_active: bool


class PersonOut(BaseModel):
    id: UUID
    name: str


# --------------------------------------------------------------------------- assets
Identifiers = dict[Annotated[str, Field(max_length=40)], Annotated[str, Field(max_length=120)]]


class AssetIn(BaseModel):
    company_id: UUID
    label: str = Field(min_length=1, max_length=160, examples=["Toyota Corolla KAA 123B"])
    kind: str = Field(default="item", max_length=40, examples=["vehicle"])
    customer_id: UUID | None = None
    identifiers: Identifiers = Field(default_factory=dict, examples=[{"plate": "KAA 123B"}])
    notes: str | None = Field(default=None, max_length=1000)
    odometer: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None


class AssetUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    kind: str | None = Field(default=None, max_length=40)
    customer_id: UUID | None = None
    identifiers: Identifiers | None = None
    notes: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    next_service_date: date | None = None
    next_service_odometer: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    next_service_note: str | None = Field(default=None, max_length=200)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)
    id: UUID
    company_id: UUID
    customer_id: UUID | None
    kind: str
    label: str
    identifiers: dict[str, Any]
    notes: str | None
    is_active: bool
    odometer: Decimal | None = None
    odometer_at: datetime | None = None
    next_service_date: date | None = None
    next_service_odometer: Decimal | None = None
    next_service_note: str | None = None
    service_due_in_days: int | None = None
    service_due_in_odometer: Decimal | None = None


class AssetRef(BaseModel):
    id: UUID
    label: str
    kind: str


# --------------------------------------------------------------------------- jobs
class NewAssetIn(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    kind: str = Field(default="item", max_length=40)
    identifiers: Identifiers = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1000)


class JobIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    title: str = Field(min_length=1, max_length=200, examples=["Brake pads worn"])
    customer_id: UUID | None = None
    customer_name: str | None = Field(default=None, max_length=160)
    customer_phone: str | None = Field(default=None, max_length=40)
    asset_id: UUID | None = None
    new_asset: NewAssetIn | None = None
    description: str | None = Field(default=None, max_length=4000)
    condition_notes: str | None = Field(default=None, max_length=4000)
    assignee_id: UUID | None = None
    promised_at: date | None = None
    checklist_template_id: UUID | None = None
    checklist_items: list[str] | None = Field(default=None, max_length=60)
    job_type_code: str | None = Field(default=None, max_length=40)
    odometer_in: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    fuel_level: str | None = Field(default=None, max_length=40)
    key_tag: str | None = Field(default=None, max_length=40)
    belongings: str | None = Field(default=None, max_length=1000)
    acknowledged_by_name: str | None = Field(default=None, max_length=160)


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    condition_notes: str | None = Field(default=None, max_length=4000)
    customer_id: UUID | None = None
    customer_name: str | None = Field(default=None, max_length=160)
    customer_phone: str | None = Field(default=None, max_length=40)
    asset_id: UUID | None = None
    assignee_id: UUID | None = None
    promised_at: date | None = None
    warranty_days: int | None = Field(default=None, ge=0, le=3650)
    job_type_code: str | None = Field(default=None, max_length=40)
    odometer_in: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    odometer_out: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    fuel_level: str | None = Field(default=None, max_length=40)
    key_tag: str | None = Field(default=None, max_length=40)
    belongings: str | None = Field(default=None, max_length=1000)
    acknowledged_by_name: str | None = Field(default=None, max_length=160)
    next_service_date: date | None = None
    next_service_odometer: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    next_service_note: str | None = Field(default=None, max_length=200)


class StatusChangeIn(BaseModel):
    to_status_id: UUID
    note: str | None = Field(default=None, max_length=1000)
    collected_by_name: str | None = Field(default=None, max_length=160)
    acknowledge_unpaid: bool = False
    odometer_out: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None


class JobInvoiceIn(BaseModel):
    pay_method: Literal["cash", "mobile_money", "bank", "card", "cheque", "other"] | None = Field(
        default=None, description="The customer pays the whole invoice now, this way")
    pay_reference: str | None = Field(default=None, max_length=60)


class JobNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class CollectIn(BaseModel):
    collected_by_name: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    acknowledge_unpaid: bool = False
    odometer_out: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None


class ReturnVisitIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class ChecklistItemIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class ChecklistItemUpdate(BaseModel):
    state: Literal["pending", "ok", "issue", "na"] | None = None
    note: str | None = Field(default=None, max_length=500)
    label: str | None = Field(default=None, max_length=120)


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    assignee_id: UUID | None = None
    due_date: date | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    assignee_id: UUID | None = None
    due_date: date | None = None
    done: bool | None = None


class PartIn(BaseModel):
    product_id: UUID | None = None
    description: str | None = Field(default=None, max_length=300)
    quantity: Qty
    unit_price: Price | None = Field(default=None, description="Tax included. Blank: the product's selling price")
    tax_code_id: UUID | None = None
    location_id: UUID | None = Field(default=None, description="Where stock is taken from; blank: the branch's store")
    part_class: Literal["genuine", "aftermarket", "used"] | None = None
    category_code: str | None = Field(default=None, max_length=40, description="Prices it by the category's markup")
    customer_supplied: bool = False
    order_for_job: bool = False
    cost_price: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)] | None = None
    supplier_name: str | None = Field(default=None, max_length=160)
    supplier_id: UUID | None = None
    expected_on: date | None = None
    purchase_order_number: str | None = Field(default=None, max_length=40)
    keep_old_part: bool = False
    old_part_note: str | None = Field(default=None, max_length=300)


class JobPartOrderedIn(BaseModel):
    supplier_name: str | None = Field(default=None, max_length=160)
    supplier_id: UUID | None = None
    expected_on: date | None = None
    purchase_order_number: str | None = Field(default=None, max_length=40)


class JobPartArrivedIn(BaseModel):
    location_id: UUID | None = None


class JobPartReturnIn(BaseModel):
    quantity: Qty
    reason: str | None = Field(default=None, max_length=300)


class JobPartRemoveIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class LabourIn(BaseModel):
    hours: Annotated[Quantity, Field(gt=0, le=1000)] | None = Field(default=None, description="Blank: task's time")
    description: str | None = Field(default=None, max_length=300)
    rate: Money | None = Field(default=None, description="Per hour, tax included. Blank: work type, else company")
    assignee_id: UUID | None = None
    work_date: date | None = None
    work_type_code: str | None = Field(default=None, max_length=40)
    task_code: str | None = Field(default=None, max_length=40)
    booked_hours: Annotated[Quantity, Field(ge=0, le=1000)] | None = None


class JobBookedIn(BaseModel):
    booked_hours: Annotated[Quantity, Field(ge=0, le=1000)]


class JobChargeIn(BaseModel):
    kind: Literal["towing", "storage", "courtesy_car", "other"]
    description: str = Field(min_length=1, max_length=300)
    unit_price: Money
    quantity: Qty = Decimal(1)


class JobDepositIn(BaseModel):
    amount: Annotated[Amount, Field(gt=0)]
    method: Literal["cash", "mobile_money", "bank", "card", "cheque", "other"] = "cash"
    reference: str | None = Field(default=None, max_length=60)
    payment_account_id: UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class EstimateLineBody(BaseModel):
    kind: Literal["part", "labour", "other"]
    description: str | None = Field(default=None, max_length=300)
    quantity: Qty
    unit_price: Price | None = None
    product_id: UUID | None = None
    tax_code_id: UUID | None = None
    work_type_code: str | None = Field(default=None, max_length=40)
    part_class: Literal["genuine", "aftermarket", "used"] | None = None


class EstimateIn(BaseModel):
    lines: list[EstimateLineBody] = Field(default_factory=list, max_length=200)
    from_job: bool = False
    notes: str | None = Field(default=None, max_length=1000)
    valid_until: date | None = None
    kind: Literal["main", "additional"] = "main"


class EstimateUpdate(BaseModel):
    lines: list[EstimateLineBody] | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    valid_until: date | None = None


class EstimateSendIn(BaseModel):
    tell_customer: bool = False


class EstimateDecisionIn(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=1000)
    customer_name: str | None = Field(default=None, max_length=160)


class EstimateLineOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    kind: str
    product_id: UUID | None
    work_type_code: str | None = None
    part_class: str | None = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    net: Decimal
    tax: Decimal
    total: Decimal


class EstimateOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    job_id: UUID
    version: int
    kind: str = "main"
    status: str
    notes: str | None
    valid_until: date | None
    net: Decimal
    tax: Decimal
    total: Decimal
    sent_at: datetime | None
    decided_at: datetime | None
    decided_by_name: str | None
    decision_channel: str | None
    decision_note: str | None
    lines: list[EstimateLineOut]


class EstimateSentOut(BaseModel):
    estimate: EstimateOut
    link_path: str = Field(description="The page the customer opens; shown once")


class ChecklistItemOut(BaseModel):
    id: UUID
    position: int
    label: str
    state: str
    note: str | None


class JobEventOut(BaseModel):
    id: UUID
    kind: str
    note: str | None
    from_status: str | None
    to_status: str | None
    by: str | None
    created_at: datetime


class TaskOut(BaseModel):
    id: UUID
    title: str
    assignee_id: UUID | None
    assignee_name: str | None
    due_date: date | None
    done_at: datetime | None
    overdue: bool


class PartOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    product_id: UUID | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    tax: Decimal
    is_stock: bool
    unit_cost: Decimal | None = Field(description="Only for people who may see costs")
    cost_value: Decimal | None
    voided: bool
    source: str = "stock"
    part_class: str | None = None
    category_code: str | None = None
    order_status: str | None = None
    supplier_name: str | None = None
    purchase_order_number: str | None = None
    expected_on: date | None = None
    arrived_at: datetime | None = None
    keep_old_part: bool = False
    old_part_note: str | None = None
    void_reason: str | None = None


class LabourOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    description: str
    hours: Decimal
    rate: Decimal
    total: Decimal
    tax: Decimal
    assignee_id: UUID | None
    assignee_name: str | None
    work_date: date
    source: str
    voided: bool
    work_type_code: str | None = None
    task_code: str | None = None
    booked_hours: Decimal | None = None
    flat_price: Decimal | None = None


class JobChargeOut(BaseModel):
    id: UUID
    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    tax: Decimal
    voided: bool


class JobLoanOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    job_id: UUID
    asset_id: UUID
    asset_label: str
    borrower_name: str | None
    out_at: datetime
    due_at: date | None
    in_at: datetime | None
    odometer_out: Decimal | None
    odometer_in: Decimal | None
    fuel_out: str | None
    fuel_in: str | None
    note: str | None
    overdue: bool = False
    job_number: str | None = None


class JobLoanIn(BaseModel):
    asset_id: UUID
    borrower_name: str | None = Field(default=None, max_length=160)
    due_at: date | None = None
    odometer_out: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    fuel_out: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=300)


class JobLoanReturnIn(BaseModel):
    odometer_in: Annotated[Decimal, Field(ge=0, le=99999999, max_digits=12, decimal_places=1)] | None = None
    fuel_in: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=300)


class JobBayBookingOut(BaseModel):
    id: UUID
    job_id: UUID
    job_number: str | None = None
    job_title: str | None = None
    item: str | None = None
    status: str | None = None
    bay_id: UUID
    bay_name: str | None = None
    starts_at: datetime
    ends_at: datetime
    note: str | None


class JobBayBookingIn(BaseModel):
    bay_id: UUID
    starts_at: datetime
    ends_at: datetime
    note: str | None = Field(default=None, max_length=300)


class JobBayIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    name: str = Field(min_length=1, max_length=60)
    position: int = Field(default=0, ge=0, le=100000)


class JobBayUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    position: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class JobBayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    name: str
    position: int
    is_active: bool


class JobApprovalOut(BaseModel):
    """How much of the work the customer has agreed to."""

    mode: str
    quoted: bool
    approved_total: Decimal
    live_total: Decimal
    extra: Decimal


class JobReleaseOut(BaseModel):
    """Is the job paid for, before the item is handed back?"""

    mode: str
    ok: bool
    invoiced: bool
    balance: Decimal | None
    message: str | None


class TotalsOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    parts_total: Decimal
    labour_total: Decimal
    charges_total: Decimal = Decimal(0)
    tax: Decimal
    net: Decimal
    total: Decimal
    cost: Decimal | None = Field(description="Cost of the stock parts; only for people who may see costs")


class JobRef(BaseModel):
    id: UUID
    number: str
    in_warranty: bool | None = None


class JobSummaryOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    title: str
    status: StatusRef
    customer_id: UUID | None
    customer_name: str | None
    customer_phone: str | None
    asset: AssetRef | None
    assignee_id: UUID | None
    assignee_name: str | None
    received_at: datetime
    promised_at: date | None
    overdue: bool
    status_changed_at: datetime
    days_in_status: int
    is_rework: bool
    warranty_ends: date | None
    invoice_number: str | None
    locked: bool
    tasks_total: int
    tasks_done: int
    job_type_code: str | None = None
    waiting_on: list[str] = Field(default_factory=list, description="parts, approval or insurer")
    has_claim: bool = False
    invoiced: bool = False


class JobPhotoStatusOut(BaseModel):
    category: str
    name: str
    minimum: int
    before: str
    have: int
    ok: bool


class JobClaimLineOut(BaseModel):
    id: UUID
    description: str
    kind: str
    quantity: Decimal
    state: str
    work_authorised: bool
    payer_pays: Decimal | None
    customer_pays: Decimal | None
    asked_total: Decimal | None
    reason: str | None
    part_class: str | None
    waiting_on: str | None


class JobClaimGateOut(BaseModel):
    allowed: bool
    policy: str
    message: str
    state: str
    decision_recorded: bool


class JobClaimOut(BaseModel):
    """The insurer (or fleet) claim of the job: where it stands and what the workshop may do."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID
    number: str
    status: str
    closed_reason: str | None
    payer_id: UUID
    payer_name: str
    waiting_on: str | None
    policy_number: str | None
    claim_number: str | None
    excess: Decimal | None
    authorised_total: Decimal | None
    payer_pays: Decimal | None
    customer_pays: Decimal | None
    open_total: Decimal | None
    authority_ref: str | None
    completed: bool
    invoiced: bool
    gate: JobClaimGateOut | None
    lines: list[JobClaimLineOut]
    limited: bool = Field(description="True when the viewer sees only the work that is authorised, without prices")
    required_documents: list[str] = Field(default_factory=list)


class JobClaimOpenIn(BaseModel):
    payer_id: UUID
    policy_number: str | None = Field(default=None, max_length=80)
    claim_number: str | None = Field(default=None, max_length=80)
    excess_amount: Money = Decimal(0)
    loss_date: date | None = None


class JobClaimEstimateIn(BaseModel):
    kind: Literal["original", "supplementary"] = "original"


class JobClaimEstimateOut(BaseModel):
    claim_estimate_id: UUID


class JobClaimCompleteIn(BaseModel):
    signed_by: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)


class JobOut(JobSummaryOut):
    description: str | None
    condition_notes: str | None
    odometer_in: Decimal | None = None
    odometer_out: Decimal | None = None
    fuel_level: str | None = None
    key_tag: str | None = None
    belongings: str | None = None
    acknowledged_by_name: str | None = None
    acknowledged_at: datetime | None = None
    deposit_amount: Decimal | None = None
    deposit_at: datetime | None = None
    deposit_note: str | None = None
    claim_id: UUID | None = None
    storage_days: int = 0
    storage_fee: Decimal = Decimal(0)
    storage_fee_waived: bool = False
    asset_detail: AssetOut | None = None
    charges: list[JobChargeOut] = Field(default_factory=list)
    loans: list[JobLoanOut] = Field(default_factory=list)
    bay_bookings: list[JobBayBookingOut] = Field(default_factory=list)
    approval: JobApprovalOut | None = None
    claim: JobClaimOut | None = None
    photos: list[JobPhotoStatusOut] = Field(default_factory=list)
    photo_count: int = 0
    release: JobReleaseOut | None = None
    collected_at: datetime | None
    collected_by_name: str | None
    warranty_days: int
    rework_of: JobRef | None
    return_visits: list[JobRef]
    invoice_id: UUID | None
    checklist: list[ChecklistItemOut]
    events: list[JobEventOut]
    tasks: list[TaskOut]
    parts: list[PartOut]
    labour: list[LabourOut]
    estimates: list[EstimateOut]
    totals: TotalsOut
    next_status_ids: list[UUID]
    can_invoice: bool


class BoardOut(BaseModel):
    statuses: list[StatusRef]
    jobs: list[JobSummaryOut]
    truncated: bool


class AssetDetailOut(AssetOut):
    jobs: list[JobSummaryOut]


# --------------------------------------------------------------------------- the customer's page
class PublicLineOut(BaseModel):
    part_class: str | None = None
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


class PublicPhotoOut(BaseModel):
    """A photo the business chose to show on the customer's page (addresses end in minutes)."""

    id: UUID
    category: str
    caption: str
    kind: str
    name: str
    thumb_path: str | None
    web_path: str | None
    original_path: str


class PublicEstimateOut(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    photos: list[PublicPhotoOut] = Field(default_factory=list)
    business: str
    currency: str
    job_number: str
    item: str
    title: str
    version: int
    kind: str = "main"
    state: Literal["open", "expired", "approved", "declined", "superseded", "draft"]
    notes: str | None
    valid_until: date | None
    net: Decimal
    tax: Decimal
    total: Decimal
    lines: list[PublicLineOut]


class PublicAnswerIn(BaseModel):
    approve: bool
    name: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)


class PublicAnswerOut(BaseModel):
    state: str


# --------------------------------------------------------------------------- the workshop's catalogue
class JobWorkTypeIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=40)
    hourly_rate: Money | None = None
    position: int = Field(default=0, ge=0, le=100000)


class JobWorkTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    hourly_rate: Money | None = None
    position: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class JobWorkTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    hourly_rate: Decimal | None
    position: int
    is_active: bool


class JobTaskLibraryIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=40)
    standard_hours: Annotated[Decimal, Field(gt=0, le=500, max_digits=8, decimal_places=2)]
    work_type_code: str | None = Field(default=None, max_length=40)
    flat_price: Money | None = None
    asset_kind: str | None = Field(default=None, max_length=40)


class JobTaskLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    standard_hours: Annotated[Decimal, Field(gt=0, le=500, max_digits=8, decimal_places=2)] | None = None
    work_type_code: str | None = Field(default=None, max_length=40)
    flat_price: Money | None = None
    asset_kind: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class JobTaskLibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    work_type_code: str | None
    standard_hours: Decimal
    flat_price: Decimal | None
    asset_kind: str | None
    is_example: bool
    is_active: bool


class JobPartCategoryIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=40)
    markup_percent: Annotated[Decimal, Field(ge=0, le=1000, max_digits=7, decimal_places=2)] = Decimal(0)
    default_class: Literal["genuine", "aftermarket", "used"] | None = None
    position: int = Field(default=0, ge=0, le=100000)


class JobPartCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    markup_percent: Annotated[Decimal, Field(ge=0, le=1000, max_digits=7, decimal_places=2)] | None = None
    default_class: Literal["genuine", "aftermarket", "used"] | None = None
    position: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class JobPartCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    markup_percent: Decimal
    default_class: str | None
    position: int
    is_active: bool


class JobPhotoRule(BaseModel):
    """Photos a kind of job needs before it reaches a stage."""

    category: str = Field(min_length=1, max_length=40)
    min: int = Field(default=1, ge=1, le=20)
    before: Literal["quoted", "approved", "ready", "collected", "closed"]


class JobPhotoCategoryIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=40)
    position: int = Field(default=0, ge=0, le=100000)


class JobPhotoCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    position: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class JobPhotoCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    position: int
    is_active: bool


class JobTypeIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=60)
    code: str | None = Field(default=None, max_length=40)
    checklist_template_id: UUID | None = None
    default_warranty_days: int | None = Field(default=None, ge=0, le=3650)
    required_photos: list[JobPhotoRule] = Field(default_factory=list, max_length=20)
    position: int = Field(default=0, ge=0, le=100000)


class JobTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    checklist_template_id: UUID | None = None
    default_warranty_days: int | None = Field(default=None, ge=0, le=3650)
    required_photos: list[JobPhotoRule] | None = Field(default=None, max_length=20)
    position: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class JobTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    checklist_template_id: UUID | None
    default_warranty_days: int | None
    required_photos: list[JobPhotoRule]
    position: int
    is_active: bool


# ------------------------------------------------------------------------ the item's visits, service due, technicians
class JobVisitOut(BaseModel):
    job: JobSummaryOut
    odometer_in: Decimal | None
    work: list[str]
    total: Decimal


class JobServiceDueOut(BaseModel):
    asset: AssetOut
    customer_name: str | None = None
    overdue: bool


class JobTechnicianOut(BaseModel):
    user_id: UUID | None
    name: str | None
    lines: int
    booked_hours: Decimal
    billed_hours: Decimal
    lines_without_booked: int
    billed_value: Decimal
    jobs_open: int


class JobBayBoardOut(BaseModel):
    bays: list[JobBayOut]
    bookings: list[JobBayBookingOut]


# --------------------------------------------------------------------------- the pack's first-run steps and sample week
class JobPackStepOut(BaseModel):
    id: UUID
    pack: str
    step_id: str
    title: str
    hint: str | None
    to_path: str | None
    check_key: str | None
    done: bool
    hidden: bool


class JobSampleStatusOut(BaseModel):
    available: bool
    loaded: bool
    pack: str | None
    note: str | None


class JobSampleResultOut(BaseModel):
    counts: dict[str, int]
