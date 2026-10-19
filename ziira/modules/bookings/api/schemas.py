"""Request and response shapes for the Bookings API."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Price = Annotated[Amount, Field(ge=0)]
Kind = Literal["staff", "room", "chair", "equipment"]


# --------------------------------------------------------------------------- settings
class BookingSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    company_id: UUID
    online_enabled: bool
    slug: str | None
    auto_confirm: bool
    min_notice_minutes: int
    max_days_ahead: int
    cancel_window_hours: int
    reminders_enabled: bool
    reminder_hours_before: int
    slot_granularity_minutes: int
    default_buffer_minutes: int
    show_resources_publicly: bool
    invoice_on_completion: bool
    invoice_due_days: int | None
    quiet_start: time
    quiet_end: time
    consent_text: str | None
    public_name: str | None
    public_note: str | None
    late_cancel_fee_percent: Decimal
    no_show_fee_percent: Decimal
    waitlist_confirm_minutes: int
    rebook_prompt_hours: int
    recalls_enabled: bool
    deposit_note: str | None
    patch_test_valid_days: int | None
    commission_excludes_tax: bool
    fee_product_id: UUID | None
    walkin_customer_id: UUID | None
    discount_limit_percent: Decimal | None
    reminder_template: str | None
    recall_template: str | None
    rebook_template: str | None
    pack_name: str | None
    invoicing_available: bool = False


class BookingSettingsUpdate(BaseModel):
    slug: str | None = Field(default=None, max_length=60, description="Booking address; empty frees it")
    online_enabled: bool | None = None
    auto_confirm: bool | None = None
    min_notice_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    max_days_ahead: int | None = Field(default=None, ge=1, le=365)
    cancel_window_hours: int | None = Field(default=None, ge=0, le=24 * 30)
    reminders_enabled: bool | None = None
    reminder_hours_before: int | None = Field(default=None, ge=1, le=168)
    slot_granularity_minutes: int | None = None
    default_buffer_minutes: int | None = Field(default=None, ge=0, le=240)
    show_resources_publicly: bool | None = None
    invoice_on_completion: bool | None = None
    invoice_due_days: int | None = Field(default=None, ge=0, le=365)
    quiet_start: str | None = Field(default=None, examples=["21:00"])
    quiet_end: str | None = Field(default=None, examples=["07:00"])
    consent_text: str | None = Field(default=None, max_length=600)
    public_name: str | None = Field(default=None, max_length=120)
    public_note: str | None = Field(default=None, max_length=600)
    late_cancel_fee_percent: Decimal | None = Field(default=None, ge=0, le=100)
    no_show_fee_percent: Decimal | None = Field(default=None, ge=0, le=100)
    waitlist_confirm_minutes: int | None = Field(default=None, ge=0, le=1440)
    rebook_prompt_hours: int | None = Field(default=None, ge=0, le=720)
    recalls_enabled: bool | None = None
    deposit_note: str | None = Field(default=None, max_length=300)
    patch_test_valid_days: int | None = Field(default=None, ge=1, le=1000)
    commission_excludes_tax: bool | None = None
    fee_product_id: UUID | None = None
    walkin_customer_id: UUID | None = None
    discount_limit_percent: Decimal | None = Field(default=None, ge=0, le=100)
    reminder_template: str | None = Field(default=None, max_length=60)
    recall_template: str | None = Field(default=None, max_length=60)
    rebook_template: str | None = Field(default=None, max_length=60)


# --------------------------------------------------------------------------- resources
class HoursIn(BaseModel):
    weekday: int = Field(ge=0, le=6, description="Monday is 0")
    start_time: time
    end_time: time


class HoursOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    weekday: int
    start_time: time
    end_time: time


class ResourceIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    name: str = Field(min_length=1, max_length=200)
    kind: Kind = "staff"
    user_id: UUID | None = None
    colour: str | None = Field(default=None, max_length=7)
    note: str | None = Field(default=None, max_length=500)
    show_publicly: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)
    level: str | None = Field(default=None, max_length=40, description="Staff level, for prices by level")
    hours: list[HoursIn] | None = None


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Kind | None = None
    user_id: UUID | None = None
    colour: str | None = Field(default=None, max_length=7)
    note: str | None = Field(default=None, max_length=500)
    show_publicly: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    is_active: bool | None = None
    level: str | None = Field(default=None, max_length=40)


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    name: str
    kind: str
    user_id: UUID | None
    colour: str | None
    note: str | None
    show_publicly: bool
    sort_order: int
    is_active: bool
    level: str | None = None
    is_template: bool = False
    hours: list[HoursOut] = []


class TimeOffIn(BaseModel):
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=200)


class TimeOffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    resource_id: UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None
    affected_appointments: int = 0


# --------------------------------------------------------------------------- service offers
class PriceVariantIn(BaseModel):
    label: str = Field(min_length=1, max_length=80, description="For example 'Senior stylist' or 'Long hair'")
    price: Price
    level: str | None = Field(default=None, max_length=40, description="Staff level this price applies to")
    is_active: bool = True


class PriceVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    label: str
    level: str | None
    price: Decimal
    is_active: bool


class OfferIn(BaseModel):
    company_id: UUID
    product_id: UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=600)
    kind: Literal["appointment", "class"] = "appointment"
    duration_minutes: int = Field(ge=5, le=1440)
    buffer_before_minutes: int | None = Field(default=None, ge=0, le=240)
    buffer_after_minutes: int | None = Field(default=None, ge=0, le=240)
    price: Price | None = None
    resource_mode: Literal["any", "all"] = "any"
    capacity: int = Field(default=1, ge=1, le=500)
    show_publicly: bool = True
    resource_ids: list[UUID] = []
    processing_start_minutes: int = Field(default=0, ge=0, le=1440)
    processing_minutes: int = Field(default=0, ge=0, le=1440)
    deposit_amount: Price = Decimal(0)
    deposit_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    recall_days: int | None = Field(default=None, ge=1, le=730)
    needs_patch_test: bool = False
    group_late_cancel_hours: int | None = Field(default=None, ge=0, le=720)


class OfferUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    product_id: UUID | None = None
    description: str | None = Field(default=None, max_length=600)
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    buffer_before_minutes: int | None = Field(default=None, ge=0, le=240)
    buffer_after_minutes: int | None = Field(default=None, ge=0, le=240)
    price: Price | None = None
    resource_mode: Literal["any", "all"] | None = None
    capacity: int | None = Field(default=None, ge=1, le=500)
    show_publicly: bool | None = None
    is_active: bool | None = None
    resource_ids: list[UUID] | None = None
    processing_start_minutes: int | None = Field(default=None, ge=0, le=1440)
    processing_minutes: int | None = Field(default=None, ge=0, le=1440)
    deposit_amount: Price | None = None
    deposit_percent: Decimal | None = Field(default=None, ge=0, le=100)
    recall_days: int | None = Field(default=None, ge=1, le=730)
    needs_patch_test: bool | None = None
    group_late_cancel_hours: int | None = Field(default=None, ge=0, le=720)


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    product_id: UUID | None
    name: str
    description: str | None
    kind: str
    duration_minutes: int
    buffer_before_minutes: int
    buffer_after_minutes: int
    price: Decimal
    resource_mode: str
    capacity: int
    show_publicly: bool
    is_active: bool
    resource_ids: list[UUID] = []
    processing_start_minutes: int = 0
    processing_minutes: int = 0
    deposit_amount: Decimal = Decimal(0)
    deposit_percent: Decimal = Decimal(0)
    recall_days: int | None = None
    needs_patch_test: bool = False
    group_late_cancel_hours: int | None = None
    price_is_example: bool = False
    variants: list[PriceVariantOut] = []


class ServiceItemOut(BaseModel):
    id: UUID
    sku: str
    name: str
    price: Decimal | None = None


# --------------------------------------------------------------------------- availability
class SlotOut(BaseModel):
    start: datetime
    end: datetime
    resource_ids: list[UUID]


# --------------------------------------------------------------------------- appointments
class AppointmentIn(BaseModel):
    offer_id: UUID
    starts_at: datetime
    branch_id: UUID | None = None
    resource_ids: list[UUID] | None = None
    customer_id: UUID | None = None
    client_name: str | None = Field(default=None, max_length=200)
    client_phone: str | None = Field(default=None, max_length=30)
    client_email: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    local_id: str | None = Field(default=None, max_length=100, description="Makes a retry safe")
    allow_outside_hours: bool = False
    price_variant: str | None = Field(default=None, max_length=80)
    payer_customer_id: UUID | None = None
    payer_member_no: str | None = Field(default=None, max_length=60)
    preauth_ref: str | None = Field(default=None, max_length=80)
    copay_amount: Price | None = None


class WalkInIn(BaseModel):
    offer_id: UUID
    branch_id: UUID | None = None
    resource_ids: list[UUID] | None = None
    customer_id: UUID | None = None
    client_name: str | None = Field(default=None, max_length=200)
    client_phone: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=500)
    local_id: str | None = Field(default=None, max_length=100)


class SeriesIn(AppointmentIn):
    frequency: Literal["weekly", "biweekly", "monthly"]
    count: int | None = Field(default=None, ge=1, le=52)
    until: date | None = None


class RescheduleIn(BaseModel):
    starts_at: datetime
    resource_ids: list[UUID] | None = None
    reason_code_id: UUID
    note: str | None = Field(default=None, max_length=500)
    allow_outside_hours: bool = False


class BookingCancelIn(BaseModel):
    reason_code_id: UUID
    note: str | None = Field(default=None, max_length=500)


class NoShowIn(BaseModel):
    reason_code_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class AppointmentOut(BaseModel):
    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    offer_id: UUID
    service: str
    kind: str
    capacity: int
    attendees: int = 0
    status: str
    source: str
    starts_at: datetime
    ends_at: datetime
    customer_id: UUID | None
    client_name: str | None
    client_phone: str | None
    client_email: str | None
    price: Decimal
    note: str | None
    series_id: UUID | None
    series_index: int | None
    late_cancellation: bool
    cancelled_at: datetime | None
    checked_in_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    minutes_worked: int | None
    invoice_id: UUID | None
    invoice_number: str | None
    resource_ids: list[UUID]
    waitlist_matches: int = 0
    visit_id: UUID | None = None
    deposit_amount: Decimal = Decimal(0)
    deposit_paid: Decimal = Decimal(0)
    price_variant: str | None = None
    payer_customer_id: UUID | None = None
    payer_member_no: str | None = None
    preauth_ref: str | None = None
    copay_amount: Decimal | None = None
    claim_id: UUID | None = None
    warnings: list[str] = []


class SeriesConflict(BaseModel):
    index: int
    starts_at: datetime
    problem: str


class BookingSeriesOut(BaseModel):
    series_id: UUID
    created: list[AppointmentOut]
    conflicts: list[SeriesConflict]


class AttendeeIn(BaseModel):
    customer_id: UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)


class AttendeeUpdate(BaseModel):
    status: Literal["booked", "attended", "no_show", "cancelled"]


class AttendeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    appointment_id: UUID
    customer_id: UUID | None
    name: str
    phone: str | None
    email: str | None
    status: str
    late_cancellation: bool = False
    source: str = "staff"
    checked_in_at: datetime | None = None


class CalendarOut(BaseModel):
    resources: list[ResourceOut]
    time_off: list[TimeOffOut]
    appointments: list[AppointmentOut]
    timezone: str


class FrontDeskOut(BaseModel):
    day: date
    timezone: str
    appointments: list[AppointmentOut]


# --------------------------------------------------------------------------- waitlist
class WaitlistIn(BaseModel):
    offer_id: UUID
    branch_id: UUID
    wanted_from: date
    wanted_to: date
    customer_id: UUID | None = None
    client_name: str | None = Field(default=None, max_length=200)
    client_phone: str | None = Field(default=None, max_length=30)
    client_email: str | None = Field(default=None, max_length=200)
    resource_id: UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class WaitlistOfferIn(BaseModel):
    starts_at: datetime
    resource_id: UUID | None = None


class WaitlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    offer_id: UUID
    resource_id: UUID | None
    customer_id: UUID | None
    client_name: str
    client_phone: str | None
    client_email: str | None
    wanted_from: date
    wanted_to: date
    note: str | None
    status: str
    offered_starts_at: datetime | None
    offered_resource_id: UUID | None
    appointment_id: UUID | None
    created_at: datetime


class WaitlistAcceptOut(BaseModel):
    entry: WaitlistOut
    appointment: AppointmentOut


# --------------------------------------------------------------------------- public booking page
class PublicService(BaseModel):
    id: UUID
    name: str
    description: str | None
    duration_minutes: int
    price: str
    mode: str
    resource_ids: list[UUID]


class PublicResource(BaseModel):
    id: UUID
    name: str
    kind: str


class PublicPageOut(BaseModel):
    business: str
    note: str | None
    currency: str
    timezone: str
    consent_text: str
    max_days_ahead: int
    services: list[PublicService]
    resources: list[PublicResource]


class PublicSlot(BaseModel):
    start: str
    end: str


class PublicBookingIn(BaseModel):
    service_id: UUID
    start: datetime
    resource_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=300)
    consent: bool = False
    website: str | None = Field(default=None, max_length=200, description="Leave empty (a trap for robots)")


class PublicBookingOut(BaseModel):
    status: str
    number: str | None
    starts_at: str
    service: str
    deposit_due: str | None = None
    deposit_note: str | None = None
