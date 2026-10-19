"""Request and response shapes for the Claims API. Every class is prefixed `Claims` (names must be unique API-wide)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount, Quantity

Qty = Annotated[Quantity, Field(gt=0)]
Price = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4, allow_inf_nan=False)]
Money = Annotated[Amount, Field(ge=0)]
Pct = Annotated[Decimal, Field(ge=0, le=1000, max_digits=8, decimal_places=4, allow_inf_nan=False)]
LineKind = Literal["labour", "parts", "paint", "sundries", "other"]
Answer = Literal["approved", "countered", "rejected", "needs_information"]
Via = Literal["phone", "email", "portal", "in_person", "message", "letter", "other"]


# --------------------------------------------------------------------------- settings and payers
class ClaimsSettingsIn(BaseModel):
    invoice_product_id: UUID | None = None
    unapproved_work: Literal["warn", "block"] | None = None
    estimate_valid_days: int | None = Field(default=None, ge=1, le=365)
    link_valid_days: int | None = Field(default=None, ge=1, le=90)
    short_pay_tolerance: Money | None = None


class ClaimsSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    invoice_product_id: UUID | None
    invoice_product_name: str | None = None
    unapproved_work: str
    estimate_valid_days: int
    link_valid_days: int
    short_pay_tolerance: Decimal


class ClaimsContact(BaseModel):
    name: str = Field(max_length=160)
    role: str = Field(default="", max_length=160)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=200)


class ClaimsNewCustomer(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)


class ClaimsPayerIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["insurer", "scheme", "fleet", "employer", "other"] = "insurer"
    customer_id: UUID | None = None
    new_customer: ClaimsNewCustomer | None = None
    labour_rates: dict[str, Money] = Field(default_factory=dict, max_length=30)
    parts_discount_pct: Pct = Decimal(0)
    parts_markup_pct: Pct = Decimal(0)
    paint_rate: Money | None = None
    approval_limit: Money | None = None
    payment_days: int = Field(default=30, ge=0, le=365)
    required_documents: list[str] = Field(default_factory=list, max_length=30)
    contacts: list[ClaimsContact] = Field(default_factory=list, max_length=30)
    estimate_email: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class ClaimsPayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    kind: Literal["insurer", "scheme", "fleet", "employer", "other"] | None = None
    customer_id: UUID | None = None
    labour_rates: dict[str, Money] | None = Field(default=None, max_length=30)
    parts_discount_pct: Pct | None = None
    parts_markup_pct: Pct | None = None
    paint_rate: Money | None = None
    approval_limit: Money | None = None
    payment_days: int | None = Field(default=None, ge=0, le=365)
    required_documents: list[str] | None = Field(default=None, max_length=30)
    contacts: list[ClaimsContact] | None = Field(default=None, max_length=30)
    estimate_email: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class ClaimsPayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    customer_id: UUID | None
    customer_name: str | None = None
    name: str
    kind: str
    labour_rates: dict[str, Any]
    parts_discount_pct: Decimal
    parts_markup_pct: Decimal
    paint_rate: Decimal | None
    approval_limit: Decimal | None
    payment_days: int
    required_documents: list[str]
    contacts: list[dict[str, Any]]
    estimate_email: str | None
    notes: str | None
    is_active: bool


# --------------------------------------------------------------------------- claims
class ClaimsClaimIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = None
    payer_id: UUID
    customer_id: UUID | None = None
    insured_name: str | None = Field(default=None, max_length=160)
    insured_phone: str | None = Field(default=None, max_length=40)
    source_type: Literal["job", "appointment"] | None = None
    source_id: UUID | None = None
    subject: str | None = Field(default=None, max_length=200)
    policy_number: str | None = Field(default=None, max_length=80)
    claim_number: str | None = Field(default=None, max_length=80)
    member_number: str | None = Field(default=None, max_length=80)
    preauth_ref: str | None = Field(default=None, max_length=80)
    loss_date: date | None = None
    loss_description: str | None = Field(default=None, max_length=2000)
    assessor_name: str | None = Field(default=None, max_length=160)
    assessor_phone: str | None = Field(default=None, max_length=40)
    excess_amount: Money = Decimal(0)


class ClaimsClaimUpdate(BaseModel):
    customer_id: UUID | None = None
    insured_name: str | None = Field(default=None, max_length=160)
    insured_phone: str | None = Field(default=None, max_length=40)
    subject: str | None = Field(default=None, max_length=200)
    policy_number: str | None = Field(default=None, max_length=80)
    claim_number: str | None = Field(default=None, max_length=80)
    member_number: str | None = Field(default=None, max_length=80)
    preauth_ref: str | None = Field(default=None, max_length=80)
    loss_date: date | None = None
    loss_description: str | None = Field(default=None, max_length=2000)
    assessor_name: str | None = Field(default=None, max_length=160)
    assessor_phone: str | None = Field(default=None, max_length=40)
    excess_amount: Money | None = None


class ClaimsNoteIn(BaseModel):
    kind: Literal["note", "assessor_visit", "reinspection"] = "note"
    note: str = Field(min_length=1, max_length=2000)
    occurred_on: date | None = None
    by: str | None = Field(default=None, max_length=160)


class ClaimsAuthorityIn(BaseModel):
    reference: str = Field(min_length=1, max_length=80)
    amount: Money | None = None
    by_name: str | None = Field(default=None, max_length=160)
    at: datetime | None = None


class ClaimsCompletionIn(BaseModel):
    signed_by: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=1000)
    signed_at: datetime | None = None


class ClaimsCloseIn(BaseModel):
    reason: Literal["total_loss", "salvage", "cash_in_lieu", "rejected", "withdrawn", "cancelled", "written_off"]
    note: str | None = Field(default=None, max_length=1000)
    amount: Money | None = None


class ClaimsWorkDecisionIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)


class ClaimsTotalsOut(BaseModel):
    asked: Decimal
    payer_pays: Decimal
    customer_pays: Decimal
    open: Decimal
    absorbed: Decimal


class ClaimsSummaryOut(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    payer_id: UUID
    payer_name: str
    customer_id: UUID | None
    insured_name: str | None
    subject: str | None
    source_type: str | None
    source_id: UUID | None
    source_number: str | None
    policy_number: str | None
    claim_number: str | None
    status: str
    closed_reason: str | None
    waiting_on: str | None
    excess_amount: Decimal
    totals: ClaimsTotalsOut
    created_at: datetime


class ClaimsLineHistoryOut(BaseModel):
    round: int
    state: str
    amount: Decimal | None
    reason: str | None
    by_name: str | None
    channel: str
    via: str | None
    answered_at: datetime


class ClaimsLineOut(BaseModel):
    id: UUID
    position: int
    kind: str
    work_type: str | None
    part_class: str | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    asked_total: Decimal
    locked: bool
    payer_state: str
    payer_amount: Decimal | None
    payer_reason: str | None
    responded_at: datetime | None
    our_decision: str | None
    customer_decision: str | None
    customer_decision_by: str | None
    shortfall_to: str | None
    invoiced: bool
    payer_pays: Decimal
    customer_pays: Decimal
    waiting_on: str | None
    history: list[ClaimsLineHistoryOut]


class ClaimsResponseOut(BaseModel):
    round: int
    response: str
    by_name: str
    channel: str
    via: str | None
    occurred_at: datetime
    note: str | None
    authority_ref: str | None
    authority_amount: Decimal | None


class ClaimsLinkOut(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    state: str
    sent_via: str | None
    sent_to: str | None
    view_count: int
    last_accessed_at: datetime | None
    signer_name: str | None
    signed_off_at: datetime | None


class ClaimsEstimateOut(BaseModel):
    id: UUID
    claim_id: UUID
    seq: int
    label: str
    lineage_id: UUID
    lineage_kind: str
    lineage_no: int
    version: int
    previous_id: UUID | None
    status: str
    in_play: bool
    title: str | None
    notes: str | None
    revision_note: str | None
    valid_until: date | None
    total: Decimal
    submitted_at: datetime | None
    submitted_via: str | None
    answered_at: datetime | None
    response: str | None
    over_approval_limit: bool
    lines: list[ClaimsLineOut]
    responses: list[ClaimsResponseOut]
    links: list[ClaimsLinkOut]


class ClaimsEventOut(BaseModel):
    id: UUID
    created_at: datetime
    kind: str
    note: str | None
    occurred_on: date | None
    actor_name: str | None
    channel: str | None
    estimate_id: UUID | None


class ClaimsInvoiceRunOut(BaseModel):
    id: UUID
    seq: int
    created_at: datetime
    payer_invoice_id: UUID | None
    payer_invoice_number: str | None
    payer_amount: Decimal
    payer_outstanding: Decimal | None
    payer_status: str | None
    excess_applied: Decimal
    customer_invoice_id: UUID | None
    customer_invoice_number: str | None
    customer_amount: Decimal
    customer_outstanding: Decimal | None
    customer_status: str | None


class ClaimsShortPayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    payer_id: UUID
    run_id: UUID
    invoice_id: UUID
    expected: Decimal
    paid: Decimal
    difference: Decimal
    status: str
    note: str | None
    created_at: datetime
    resolved_at: datetime | None
    recharge_invoice_number: str | None


class ClaimsGateOut(BaseModel):
    has_claim: bool
    state: str
    allowed: bool
    policy: str
    authorised_total: Decimal
    unapproved_total: Decimal
    decision_recorded: bool
    message: str


class ClaimsClaimOut(ClaimsSummaryOut):
    insured_phone: str | None
    member_number: str | None
    preauth_ref: str | None
    loss_date: date | None
    loss_description: str | None
    assessor_name: str | None
    assessor_phone: str | None
    closed_note: str | None
    closed_amount: Decimal | None
    closed_at: datetime | None
    authority_ref: str | None
    authority_amount: Decimal | None
    authority_by: str | None
    authority_at: datetime | None
    completed_at: datetime | None
    completion_signed_by: str | None
    completion_signed_at: datetime | None
    completion_note: str | None
    invoiced_at: datetime | None
    required_documents: list[str]
    estimates: list[ClaimsEstimateOut]
    events: list[ClaimsEventOut]
    runs: list[ClaimsInvoiceRunOut]
    short_pays: list[ClaimsShortPayOut]
    gate: ClaimsGateOut
    can_invoice: bool
    blockers: list[str]


# --------------------------------------------------------------------------- estimates
class ClaimsLineIn(BaseModel):
    line_id: UUID | None = None
    kind: LineKind
    description: str | None = Field(default=None, max_length=300)
    quantity: Qty
    unit_price: Price | None = None
    work_type: str | None = Field(default=None, max_length=40)
    part_class: Literal["genuine", "aftermarket", "used"] | None = None
    product_id: UUID | None = None


class ClaimsEstimateIn(BaseModel):
    kind: Literal["original", "supplementary", "revision"] = "original"
    from_estimate_id: UUID | None = None
    lines: list[ClaimsLineIn] = Field(default_factory=list, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    valid_until: date | None = None
    title: str | None = Field(default=None, max_length=120)
    revision_note: str | None = Field(default=None, max_length=1000)
    apply_payer_terms: bool = False


class ClaimsEstimateUpdate(BaseModel):
    lines: list[ClaimsLineIn] | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    valid_until: date | None = None
    title: str | None = Field(default=None, max_length=120)
    revision_note: str | None = Field(default=None, max_length=1000)
    apply_payer_terms: bool = False


class ClaimsSubmitIn(BaseModel):
    channel: str | None = Field(default=None, max_length=40)
    recipient: str | None = Field(default=None, max_length=200)
    make_link: bool = True
    link_days: int | None = Field(default=None, ge=1, le=90)


class ClaimsSubmitOut(BaseModel):
    estimate: ClaimsEstimateOut
    link_path: str | None
    queued: bool


class ClaimsLinkMadeOut(BaseModel):
    link: ClaimsLinkOut
    link_path: str


class ClaimsLinkAccessOut(BaseModel):
    created_at: datetime
    action: str
    outcome: str
    ip_address: str | None
    user_agent: str | None


class ClaimsAnswerIn(BaseModel):
    line_id: UUID
    state: Answer
    amount: Money | None = None
    reason: str | None = Field(default=None, max_length=500)


class ClaimsResponseIn(BaseModel):
    by_name: str = Field(min_length=1, max_length=160)
    via: Via
    occurred_at: datetime | None = None
    answers: list[ClaimsAnswerIn] = Field(min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=1000)
    authority_ref: str | None = Field(default=None, max_length=80)
    authority_amount: Money | None = None


class ClaimsWithdrawIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ClaimsCounterDecisionIn(BaseModel):
    accept: bool
    shortfall_to: Literal["customer", "business"] | None = None
    customer_agreed_by: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=500)


class ClaimsCustomerDecisionIn(BaseModel):
    pays: bool
    by_name: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- billing and money
class ClaimsBillingPartOut(BaseModel):
    description: str
    amount: Decimal
    discount: Decimal = Decimal(0)
    kind: str = "line"


class ClaimsBillingOut(BaseModel):
    payer_parts: list[ClaimsBillingPartOut]
    customer_parts: list[ClaimsBillingPartOut]
    payer_gross: Decimal
    excess_applied: Decimal
    payer_net: Decimal
    customer_total: Decimal
    absorbed: Decimal
    waiting_lines: int
    blockers: list[str]


class ClaimsReductionIn(BaseModel):
    line_id: UUID
    new_amount: Money
    reason: str = Field(min_length=1, max_length=500)
    by_name: str = Field(min_length=1, max_length=160)
    shortfall_to: Literal["customer", "business"] = "business"
    customer_agreed_by: str | None = Field(default=None, max_length=160)


class ClaimsAllocationIn(BaseModel):
    run_id: UUID
    amount: Money
    closes_invoice: bool = False


class ClaimsReceiptIn(BaseModel):
    branch_id: UUID
    amount: Annotated[Amount, Field(gt=0)]
    method: Literal["cash", "mobile_money", "bank", "card", "cheque", "other"] = "bank"
    reference: str | None = Field(default=None, max_length=60)
    received_on: date | None = None
    allocations: list[ClaimsAllocationIn] = Field(default_factory=list, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class ClaimsReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payer_id: UUID
    pos_receipt_number: str | None
    amount: Decimal
    method: str
    reference: str | None
    received_on: date
    note: str | None
    created_at: datetime


class ClaimsReceiptResultOut(BaseModel):
    receipt: ClaimsReceiptOut
    created: bool


class ClaimsShortPayResolveIn(BaseModel):
    resolution: Literal["recharge", "accept", "dispute"]
    note: str | None = Field(default=None, max_length=500)


class ClaimsOwedOut(BaseModel):
    payer_id: UUID
    payer_name: str
    claim_id: UUID
    claim_number: str
    run_id: UUID
    invoice_id: UUID
    invoice_number: str
    issue_date: date
    due_date: date
    total: Decimal
    outstanding: Decimal
    days_late: int
    bucket: str


class ClaimsAgeingRowOut(BaseModel):
    payer_id: UUID
    payer: str
    buckets: dict[str, Decimal]
    total: Decimal
    invoices: int


class ClaimsPayerStatementOut(BaseModel):
    payer: ClaimsPayerOut
    owed: list[ClaimsOwedOut]
    receipts: list[ClaimsReceiptOut]
    short_pays: list[ClaimsShortPayOut]


# --------------------------------------------------------------------------- the payer's page (no sign-in)
class ClaimsPublicLineOut(BaseModel):
    id: UUID
    position: int
    kind: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    part_class: str | None
    locked: bool
    state: str
    amount: Decimal | None
    reason: str | None


class ClaimsPublicPhotoOut(BaseModel):
    id: str
    category: str
    caption: str
    kind: str
    name: str
    thumb: str | None
    web: str | None
    original: str


class ClaimsPublicEstimateOut(BaseModel):
    state: str
    business: str
    currency: str
    payer: str
    label: str | None = None
    claim_number: str | None = None
    policy_number: str | None = None
    reference: str | None = None
    subject: str | None = None
    loss_date: date | None = None
    notes: str | None = None
    revision_note: str | None = None
    valid_until: date | None = None
    total: Decimal | None = None
    link_expires_at: datetime | None = None
    answered_by: str | None = None
    photos: list[ClaimsPublicPhotoOut] = Field(default_factory=list)
    lines: list[ClaimsPublicLineOut] = Field(default_factory=list)


class ClaimsPublicAnswerLineIn(BaseModel):
    line_id: UUID
    state: Answer
    amount: Money | None = None
    reason: str | None = Field(default=None, max_length=500)


class ClaimsPublicAnswerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    role: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)
    authority_ref: str | None = Field(default=None, max_length=80)
    authority_amount: Money | None = None
    lines: list[ClaimsPublicAnswerLineIn] = Field(min_length=1, max_length=300)


class ClaimsPublicAnswerOut(BaseModel):
    state: str
    response: str | None = None
