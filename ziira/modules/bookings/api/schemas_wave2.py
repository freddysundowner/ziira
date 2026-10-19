"""Request and response shapes for checkout, the front desk board, group sessions, recalls, commission, fees, rentals
and the day-end summary."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.modules.bookings.api.schemas import AppointmentOut, Price, PriceVariantIn
from ziira.sdk import Amount, Quantity


# --------------------------------------------------------------------------- front desk board
class BoardBriefOut(BaseModel):
    appointment_id: UUID
    number: str
    client_name: str | None
    service: str
    starts_at: datetime
    ends_at: datetime
    status: str
    customer_id: UUID | None
    checked_in_at: datetime | None
    source: str
    price: Decimal


class BoardPersonOut(BaseModel):
    resource_id: UUID
    name: str
    kind: str
    level: str | None
    colour: str | None
    state: Literal["free", "busy", "processing", "off"]
    until: datetime | None
    free_for_minutes: int | None
    current: BoardBriefOut | None
    next: BoardBriefOut | None


class BoardWaitingOut(BoardBriefOut):
    waited_minutes: int = 0
    resource_ids: list[UUID] = []


class FrontDeskBoardOut(BaseModel):
    day: date
    timezone: str
    now: datetime
    resources: list[BoardPersonOut]
    waiting: list[BoardWaitingOut]
    arriving: list[BoardBriefOut]
    in_service: list[BoardWaitingOut]
    to_bill: list[BoardWaitingOut]


class WalkInOut(BaseModel):
    appointment: AppointmentOut
    wait_minutes: int = Field(description="0: starts now; else the minutes until a person is free")


class VisitItemIn(BaseModel):
    offer_id: UUID
    resource_ids: list[UUID] | None = None
    price_variant: str | None = Field(default=None, max_length=80)


class VisitIn(BaseModel):
    items: list[VisitItemIn] = Field(min_length=1, max_length=8)
    starts_at: datetime
    branch_id: UUID | None = None
    customer_id: UUID | None = None
    client_name: str | None = Field(default=None, max_length=200)
    client_phone: str | None = Field(default=None, max_length=30)
    client_email: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    allow_outside_hours: bool = False
    payer_customer_id: UUID | None = None
    payer_member_no: str | None = Field(default=None, max_length=60)
    preauth_ref: str | None = Field(default=None, max_length=80)
    copay_amount: Price | None = None


class VisitOut(BaseModel):
    visit_id: UUID
    appointments: list[AppointmentOut]


class DepositIn(BaseModel):
    amount: Amount = Field(gt=0)
    method: Literal["cash", "mobile_money", "card", "bank", "cheque", "other"]
    reference: str | None = Field(default=None, max_length=80)


class ClaimOpenIn(BaseModel):
    payer_id: UUID
    policy_number: str | None = Field(default=None, max_length=80)
    member_number: str | None = Field(default=None, max_length=80)
    preauth_ref: str | None = Field(default=None, max_length=80)


# --------------------------------------------------------------------------- checkout
class CheckoutLineIn(BaseModel):
    kind: Literal["service", "product", "fee"]
    quantity: Quantity = Field(default=Decimal(1), gt=0)
    appointment_id: UUID | None = None
    offer_id: UUID | None = None
    product_id: UUID | None = None
    fee_id: UUID | None = None
    description: str | None = Field(default=None, max_length=300)
    unit_price: Price | None = Field(default=None, description="Left out: the list price")
    discount: Price = Decimal(0)
    resource_id: UUID | None = Field(default=None, description="Who gets the credit (and commission) for it")
    variant: str | None = Field(default=None, max_length=80)
    use_credit: bool = False


class CheckoutDraftIn(BaseModel):
    lines: list[CheckoutLineIn] = Field(min_length=1, max_length=60)
    discount_kind: Literal["amount", "percent"] = "amount"
    discount_value: Price = Decimal(0)
    discount_reason_id: UUID | None = None
    discount_note: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)
    payer_customer_id: UUID | None = None
    copay_amount: Price | None = None
    preauth_ref: str | None = Field(default=None, max_length=80)


class CheckoutOpenIn(BaseModel):
    appointment_ids: list[UUID] = Field(default=[], max_length=20)
    visit_id: UUID | None = None
    customer_id: UUID | None = None
    branch_id: UUID | None = None
    local_id: str | None = Field(default=None, max_length=100, description="Makes a retry safe")


class CheckoutCustomerIn(BaseModel):
    customer_id: UUID | None = None


class CheckoutPaymentIn(BaseModel):
    method: Literal["cash", "mobile_money", "card", "bank", "cheque", "other"]
    amount: Amount = Field(gt=0)
    reference: str | None = Field(default=None, max_length=80)


class CheckoutTipIn(BaseModel):
    resource_id: UUID
    amount: Amount = Field(gt=0)
    method: Literal["cash", "mobile_money", "card", "other"] = "cash"
    held: bool | None = Field(default=None, description="The business holds it to pay out (default: not for cash)")


class CheckoutTenderIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    amount: Amount = Field(gt=0)
    code: str | None = Field(default=None, max_length=80)


class CheckoutCompleteIn(BaseModel):
    payments: list[CheckoutPaymentIn] = Field(default=[], max_length=10)
    tips: list[CheckoutTipIn] = Field(default=[], max_length=10)
    tenders: list[CheckoutTenderIn] = Field(default=[], max_length=5)
    use_deposit: bool = True


class CheckoutDiscardIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class CheckoutLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    line_no: int
    kind: str
    appointment_id: UUID | None
    offer_id: UUID | None
    product_id: UUID | None
    fee_id: UUID | None
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    resource_id: UUID | None
    variant: str | None
    credit_quantity: Decimal
    credit_ref: str | None
    order_discount_share: Decimal = Decimal(0)
    net: Decimal = Decimal(0)


class CheckoutPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    method: str
    amount: Decimal
    reference: str | None
    receipt_number: str | None


class CheckoutTipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    resource_id: UUID
    amount: Decimal
    method: str
    held: bool
    paid_out_at: datetime | None


class CheckoutTotalsOut(BaseModel):
    subtotal: Decimal
    line_discounts: Decimal
    order_discount: Decimal
    credit_value: Decimal
    total: Decimal


class CheckoutOut(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    customer_id: UUID | None
    client_name: str | None
    visit_id: UUID | None
    status: Literal["open", "done", "void"]
    note: str | None
    discount_kind: str
    discount_value: Decimal
    discount_reason_id: UUID | None
    discount_note: str | None
    payer_customer_id: UUID | None
    copay_amount: Decimal | None
    preauth_ref: str | None
    total: Decimal
    paid_total: Decimal
    credit_total: Decimal
    tip_total: Decimal
    invoice_id: UUID | None
    invoice_number: str | None
    payer_invoice_id: UUID | None
    payer_invoice_number: str | None
    completed_at: datetime | None
    created_at: datetime
    lines: list[CheckoutLineOut]
    payments: list[CheckoutPaymentOut]
    tips: list[CheckoutTipOut]
    totals: CheckoutTotalsOut
    warnings: list[str] = []
    deposit_held: Decimal = Decimal(0)
    credit_on_account: Decimal = Decimal(0)


class CheckoutListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    branch_id: UUID
    number: str
    customer_id: UUID | None
    client_name: str | None
    status: str
    total: Decimal
    paid_total: Decimal
    credit_total: Decimal
    tip_total: Decimal
    invoice_number: str | None
    completed_at: datetime | None
    created_at: datetime


class TenderKindOut(BaseModel):
    kind: str
    label: str
    needs_code: bool


class TenderBalanceOut(BaseModel):
    kind: str
    available: Decimal
    description: str


# --------------------------------------------------------------------------- group sessions
class ClassSessionIn(BaseModel):
    offer_id: UUID
    starts_at: datetime
    branch_id: UUID | None = None
    resource_ids: list[UUID] | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)
    note: str | None = Field(default=None, max_length=500)
    weeks: int | None = Field(default=None, ge=1, le=52, description="Repeat each week for this many weeks")


class ClassSessionOut(BaseModel):
    id: UUID
    branch_id: UUID
    number: str
    offer_id: UUID
    name: str
    status: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    booked: int
    held: int
    waiting: int
    free: int
    resource_ids: list[UUID]


class ClassSessionSkippedOut(BaseModel):
    starts_at: datetime
    problem: str


class ClassSessionSeriesOut(BaseModel):
    created: list[ClassSessionOut]
    skipped: list[ClassSessionSkippedOut]


class ClassSessionBookIn(BaseModel):
    customer_id: UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    join_waitlist: bool = True


class ClassSessionWaitingOut(BaseModel):
    id: UUID
    customer_id: UUID | None
    name: str
    phone: str | None = None
    status: str
    joined_at: datetime
    confirm_by: datetime | None


class ClassSessionBookedOut(BaseModel):
    status: Literal["booked", "waitlisted"]
    attendee_id: UUID | None
    waitlist_id: UUID | None
    position: int | None


class ClassSessionCapacityIn(BaseModel):
    capacity: int = Field(ge=1, le=500)


class ClassSessionResourceIn(BaseModel):
    resource_id: UUID


class ClassSessionCancelIn(BaseModel):
    reason_code_id: UUID
    note: str | None = Field(default=None, max_length=500)


class ClosedDayIn(BaseModel):
    company_id: UUID
    day: date
    branch_id: UUID | None = None
    label: str | None = Field(default=None, max_length=100)


class ClosedDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID | None
    day: date
    label: str | None


# --------------------------------------------------------------------------- recalls, fees
class RecallOut(BaseModel):
    customer_id: UUID
    offer_id: UUID
    appointment_id: UUID
    branch_id: UUID
    client_name: str | None
    client_phone: str | None
    service: str
    recall_days: int
    visited_on: date
    due_on: date
    overdue_days: int
    last_contacted_at: datetime | None
    last_outcome: str | None


class RecallOutcomeIn(BaseModel):
    company_id: UUID
    customer_id: UUID
    offer_id: UUID
    outcome: Literal["called", "declined", "snoozed", "booked"]
    snooze_until: date | None = None
    note: str | None = Field(default=None, max_length=300)


class RecallSendIn(BaseModel):
    company_id: UUID
    customer_id: UUID
    offer_id: UUID


class RecallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    offer_id: UUID | None
    kind: str
    outcome: str
    created_at: datetime


class ClientFeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    appointment_id: UUID | None
    kind: str
    amount: Decimal
    status: str
    waived_reason: str | None
    created_at: datetime


class FeeWaiveIn(BaseModel):
    reason_code_id: UUID
    note: str | None = Field(default=None, max_length=300)


# --------------------------------------------------------------------------- commission, tips
class CommissionRuleIn(BaseModel):
    company_id: UUID
    applies_to: Literal["service", "product"] = "service"
    kind: Literal["percent", "fixed"] = "percent"
    value: Decimal = Field(ge=0, le=1000000)
    offer_id: UUID | None = None
    product_id: UUID | None = None
    resource_id: UUID | None = None
    level: str | None = Field(default=None, max_length=40)


class CommissionRuleUpdate(BaseModel):
    kind: Literal["percent", "fixed"] | None = None
    value: Decimal | None = Field(default=None, ge=0, le=1000000)
    offer_id: UUID | None = None
    product_id: UUID | None = None
    resource_id: UUID | None = None
    level: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None


class CommissionRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    applies_to: str
    kind: str
    value: Decimal
    offer_id: UUID | None
    product_id: UUID | None
    resource_id: UUID | None
    level: str | None
    is_active: bool


class CommissionPersonOut(BaseModel):
    resource_id: UUID
    name: str
    level: str | None
    user_id: UUID | None
    service_sales: Decimal
    service_commission: Decimal
    product_sales: Decimal
    product_commission: Decimal
    commission: Decimal
    tips_received: Decimal
    tips_owed: Decimal


class TipsOwedOut(BaseModel):
    resource_id: UUID
    name: str
    owed: Decimal
    tips: int


class TipsPayOutIn(BaseModel):
    company_id: UUID
    resource_id: UUID
    branch_id: UUID | None = None


class TipsPaidOut(BaseModel):
    amount: Decimal


class CommissionReverseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class PriceVariantsIn(BaseModel):
    variants: list[PriceVariantIn] = Field(max_length=20)


# --------------------------------------------------------------------------- rentals
class RentalIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    customer_id: UUID
    product_id: UUID
    amount: Amount = Field(gt=0)
    every: Literal["week", "month"] = "month"
    start_date: date
    resource_id: UUID | None = None
    description: str | None = Field(default=None, max_length=200)
    end_date: date | None = None


class RentalEndIn(BaseModel):
    end_date: date | None = None


class RentalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    resource_id: UUID | None
    customer_id: UUID
    product_id: UUID
    description: str
    amount: Decimal
    every: str
    start_date: date
    next_due: date
    end_date: date | None
    is_active: bool
    last_invoice_number: str | None


# --------------------------------------------------------------------------- day end, client card, pack steps
class DayEndMethodOut(BaseModel):
    kind: str
    method: str
    amount: Decimal
    n: int


class DayEndPersonOut(BaseModel):
    resource_id: UUID
    name: str
    amount: Decimal
    held_by_business: Decimal | None = None


class DayEndOwingOut(BaseModel):
    number: str
    client_name: str | None
    owes: Decimal


class DayEndOut(BaseModel):
    day: date
    branch_id: UUID
    visits: int
    billed: Decimal
    paid: Decimal
    discounts: Decimal
    credit_used: Decimal
    tips_total: Decimal
    services: Decimal
    products: Decimal
    fees: Decimal
    payments_by_method: list[DayEndMethodOut]
    tips: list[DayEndPersonOut]
    commission: list[DayEndPersonOut]
    completed: int
    no_shows: int
    late_cancellations: int
    walk_ins: int
    still_in: int
    not_billed: int
    owing: list[DayEndOwingOut]


class ClientHistoryOut(BaseModel):
    appointment_id: UUID
    number: str
    service: str
    status: str
    starts_at: datetime
    price: Decimal
    note: str | None


class ClientStaffOut(BaseModel):
    resource_id: UUID
    name: str
    visits: int


class ClientMembershipOut(BaseModel):
    plan: str
    credits: Decimal
    discount_percent: Decimal
    renews: date


class ClientCardOut(BaseModel):
    customer_id: UUID
    values: dict[str, object]
    history: list[ClientHistoryOut]
    usual_staff: list[ClientStaffOut]
    open_fees: list[ClientFeeOut]
    patch_test: str | None
    visits: int
    last_visit: datetime | None
    no_shows: int
    membership: ClientMembershipOut | None
    credit: Decimal | None
    on_account: Decimal | None = None


class PackStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pack: str
    step_id: str
    title: str
    hint: str | None
    to_path: str | None
    done: bool
    hidden: bool


class PackStepsHideIn(BaseModel):
    company_id: UUID
    hidden: bool


class RotaDayOut(BaseModel):
    weekday: int
    windows: list[str]


class RotaPersonOut(BaseModel):
    resource_id: UUID
    name: str
    kind: str
    level: str | None
    days: list[RotaDayOut]
    time_off: list[str]


class ClientFieldsIn(BaseModel):
    values: dict[str, object]
