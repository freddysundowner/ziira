"""Request and response shapes for members' profiles, households, waivers, dues, check-in and the access decision API.
Class names are unique across the whole API (tests/test_openapi_names.py)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Day = Annotated[date, Field(ge=date(1900, 1, 1), le=date(2100, 12, 31))]
Money = Annotated[Amount, Field(ge=0, le=Decimal("1000000000"))]
Method = Literal["desk", "scan", "card", "kiosk", "api", "class"]


class GymOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- profiles
class MemberProfileUpdate(BaseModel):
    branch_id: UUID | None = None
    date_of_birth: Day | None = None
    emergency_name: str | None = Field(default=None, max_length=200)
    emergency_phone: str | None = Field(default=None, max_length=40)
    emergency_relation: str | None = Field(default=None, max_length=60)
    photo_file_id: UUID | None = None
    source: str | None = Field(default=None, max_length=100)
    referred_by_customer_id: UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=1000)
    card_number: str | None = Field(default=None, max_length=40, description="Card, tag or wristband number; empty clears")  # noqa: E501


class MemberProfileBlockIn(BaseModel):
    blocked: bool
    reason: str | None = Field(default=None, max_length=300)


class MemberProfileOut(GymOut):
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    customer_id: UUID
    number: str
    card_number: str | None
    lifecycle: str
    trial_started_on: date | None
    trial_ends_on: date | None
    date_of_birth: date | None
    emergency_name: str | None
    emergency_phone: str | None
    emergency_relation: str | None
    photo_file_id: UUID | None
    source: str | None
    referred_by_customer_id: UUID | None
    group_id: UUID | None
    tags: list[str]
    access_blocked: bool
    block_reason: str | None
    notes: str | None
    last_visit_on: date | None
    customer_name: str | None = None
    customer_code: str | None = None
    phone: str | None = None
    email: str | None = None


class MemberGroupIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["household", "corporate"] = "household"
    payer_customer_id: UUID
    notes: str | None = Field(default=None, max_length=500)


class MemberGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    payer_customer_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=500)
    status: Literal["active", "closed"] | None = None


class MemberGroupSetIn(BaseModel):
    group_id: UUID | None = None


class MemberGroupOut(GymOut):
    id: UUID
    company_id: UUID
    name: str
    kind: str
    payer_customer_id: UUID
    payer_name: str | None = None
    notes: str | None
    status: str
    member_count: int = 0
    members: list[MemberProfileOut] = []


# --------------------------------------------------------------------------- waiver
class WaiverVersionIn(BaseModel):
    company_id: UUID
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class WaiverVersionOut(GymOut):
    id: UUID
    company_id: UUID
    version: int
    title: str
    body: str
    created_at: datetime


class WaiverAcceptIn(BaseModel):
    accepted_name: str = Field(min_length=1, max_length=200, description="The name typed by the person accepting")
    method: Literal["desk", "kiosk", "online"] = "desk"
    note: str | None = Field(default=None, max_length=300)
    version: int | None = Field(default=None, ge=1, description="Left out: the current version")


class WaiverAcceptanceOut(GymOut):
    id: UUID
    version: int
    accepted_at: datetime
    accepted_name: str
    method: str
    note: str | None
    recorded_by_name: str | None = None


class WaiverStatusOut(BaseModel):
    customer_id: UUID
    current_version: int | None
    current_title: str | None
    accepted_current: bool
    acceptances: list[WaiverAcceptanceOut]


# --------------------------------------------------------------------------- dues
class MemberDueOut(GymOut):
    id: UUID
    owner_type: str
    period_start: date
    period_end: date | None
    invoice_number: str | None
    total: Decimal | None
    outstanding: Decimal | None
    due_date: date | None
    settle_state: str
    status: str
    dunning_paused: bool
    message: str | None


class MemberPaymentIn(BaseModel):
    amount: Annotated[Amount, Field(gt=0, le=Decimal("1000000000"))]
    method: Literal["cash", "mobile_money", "bank", "card", "cheque", "other"]
    reference: str | None = Field(default=None, max_length=60)


class MemberPaymentOut(BaseModel):
    receipt_id: UUID
    receipt_number: str
    amount: Decimal
    method: str


class InvoiceCreditIn(BaseModel):
    reason_code_id: UUID = Field(description="One of Sales' 'sale_return' reasons")
    refund_method: Literal["credit_note", "cash", "mobile_money"]
    amount: Annotated[Amount, Field(gt=0, le=Decimal("1000000000"))] | None = Field(
        default=None, description="Left out: everything still to be credited")
    note: str = Field(min_length=1, max_length=300)


class InvoiceCreditOut(BaseModel):
    id: UUID
    status: str
    credit_number: str
    credit_total: Decimal
    credit_status: str
    message: str | None


class DunningPauseIn(BaseModel):
    paused: bool


class ArrearsMemberOut(BaseModel):
    number: str
    plan_name: str
    status: str
    customer_id: UUID


class ArrearsOut(BaseModel):
    customer_id: UUID
    customer_name: str | None
    phone: str | None
    email: str | None
    owed: Decimal
    oldest_due: date
    days_late: int
    invoices: int
    invoice_numbers: list[str]
    last_reminder: datetime | None
    members: list[ArrearsMemberOut]


class DuesRefreshOut(BaseModel):
    changed: int
    frozen: int
    resumed: int
    reminders_queued: int


# --------------------------------------------------------------------------- check-in
class CheckinReasonOut(BaseModel):
    code: str
    message: str
    level: str


class CheckinPersonOut(BaseModel):
    customer_id: UUID
    profile_id: UUID
    number: str
    name: str | None
    phone: str | None
    photo_file_id: UUID | None
    photo_link: str | None = None
    lifecycle: str
    plan_name: str | None
    membership_status: str | None
    next_renewal_date: date | None
    owed: Decimal


class CheckinIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    identifier: str | None = Field(default=None, max_length=80, description="Member number, card number or QR text")
    customer_id: UUID | None = Field(default=None, description="The person the desk picked from a search")
    method: Method = "desk"
    device: str | None = Field(default=None, max_length=80)
    local_id: str | None = Field(default=None, max_length=80, description="Makes a retry or an offline sync safe")
    override_reason: str | None = Field(default=None, max_length=300)
    record: bool = True


class CheckinResultOut(BaseModel):
    outcome: str
    allowed: bool
    code: str
    message: str
    reasons: list[CheckinReasonOut]
    duplicate: bool
    overridden: bool
    can_override: bool
    checkin_id: UUID | None
    occurred_at: datetime | None
    entitlement: str | None
    credits_left: Decimal | None
    person: CheckinPersonOut | None
    classes_today: list[dict[str, Any]] = []


class OfflineCheckinIn(BaseModel):
    local_id: str = Field(min_length=1, max_length=80)
    identifier: str | None = Field(default=None, max_length=80)
    customer_id: UUID | None = None
    method: Method = "desk"
    occurred_at: datetime
    device: str | None = Field(default=None, max_length=80)


class CheckinSyncIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    items: list[OfflineCheckinIn] = Field(min_length=1, max_length=500)


class CheckinSyncItemOut(BaseModel):
    local_id: str
    outcome: str
    code: str
    message: str
    recorded: bool


class CheckinSyncOut(BaseModel):
    results: list[CheckinSyncItemOut]


class CheckinSearchOut(BaseModel):
    customer_id: UUID
    number: str
    name: str | None
    phone: str | None
    photo_file_id: UUID | None
    plan_name: str | None
    membership_status: str | None
    arrears: Decimal | None
    next_renewal_date: date | None


class CheckinRowOut(GymOut):
    id: UUID
    branch_id: UUID
    customer_id: UUID
    customer_name: str | None = None
    member_number: str | None = None
    occurred_at: datetime
    business_date: date
    method: str
    decision: str
    reasons: list[CheckinReasonOut]
    overridden: bool
    override_reason: str | None
    counted: bool
    holder_type: str | None
    offline: bool
    device: str | None


class CheckinCountsOut(BaseModel):
    visits: int
    refused: int
    overridden: int


class CheckinGiveBackIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class CheckinGiveBackOut(BaseModel):
    visits_given_back: Decimal


class RosterEntryOut(BaseModel):
    number: str
    card_number: str | None
    outcome: str
    code: str
    message: str
    plan: str | None
    customer_id: UUID | None = None
    name: str | None = None
    phone: str | None = None
    photo_file_id: UUID | None = None


class RosterOut(BaseModel):
    generated_at: datetime
    valid_hours: int
    branch_id: UUID
    entries: list[RosterEntryOut]


# --------------------------------------------------------------------------- access decision API (door controllers)
class AccessDecisionIn(BaseModel):
    branch_id: UUID
    identifier: str = Field(min_length=1, max_length=80, description="Member number, card/tag/wristband number or QR text")  # noqa: E501
    device: str | None = Field(default=None, max_length=80, description="Which door or turnstile asks")
    record: bool = Field(default=True, description="False: only answer, write nothing (a dry run)")
    local_id: str | None = Field(default=None, max_length=80)


class AccessDecisionOut(BaseModel):
    allowed: bool
    decision: str
    code: str
    message: str
    member_number: str | None
    first_name: str | None
    checkin_id: UUID | None
    reasons: list[CheckinReasonOut]


class AccessAllowedOut(BaseModel):
    generated_at: datetime
    branch_id: UUID
    members: list[RosterEntryOut]
