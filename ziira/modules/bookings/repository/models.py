"""SQLAlchemy mappings for tables in the `bookings` schema."""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantColumns:
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Audited(TenantColumns):
    created_by: Mapped[UUID | None]
    updated_at: Mapped[datetime | None]
    updated_by: Mapped[UUID | None]


def money() -> Mapped[Decimal]:
    return mapped_column(Numeric(18, 2), server_default=text("0"))


S = {"schema": "bookings"}


class BookingSettings(Audited, Base):
    __tablename__ = "booking_settings"
    __table_args__ = S

    company_id: Mapped[UUID]
    online_enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    slug: Mapped[str | None]
    auto_confirm: Mapped[bool] = mapped_column(server_default=text("false"))
    min_notice_minutes: Mapped[int] = mapped_column(server_default=text("120"))
    max_days_ahead: Mapped[int] = mapped_column(server_default=text("60"))
    cancel_window_hours: Mapped[int] = mapped_column(server_default=text("24"))
    reminders_enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    reminder_hours_before: Mapped[int] = mapped_column(server_default=text("24"))
    slot_granularity_minutes: Mapped[int] = mapped_column(server_default=text("15"))
    default_buffer_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    show_resources_publicly: Mapped[bool] = mapped_column(server_default=text("false"))
    invoice_on_completion: Mapped[bool] = mapped_column(server_default=text("false"))
    invoice_due_days: Mapped[int | None]
    quiet_start: Mapped[time] = mapped_column(server_default=text("'21:00'"))
    quiet_end: Mapped[time] = mapped_column(server_default=text("'07:00'"))
    consent_text: Mapped[str | None]
    public_name: Mapped[str | None]
    public_note: Mapped[str | None]
    late_cancel_fee_percent: Mapped[Decimal] = money()
    no_show_fee_percent: Mapped[Decimal] = money()
    waitlist_confirm_minutes: Mapped[int] = mapped_column(server_default=text("30"))
    rebook_prompt_hours: Mapped[int] = mapped_column(server_default=text("0"))
    recalls_enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    deposit_note: Mapped[str | None]
    patch_test_valid_days: Mapped[int | None]
    commission_excludes_tax: Mapped[bool] = mapped_column(server_default=text("true"))
    pack_name: Mapped[str | None]
    reminder_template: Mapped[str | None]
    recall_template: Mapped[str | None]
    rebook_template: Mapped[str | None]
    fee_product_id: Mapped[UUID | None]
    walkin_customer_id: Mapped[UUID | None]
    discount_limit_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class Resource(Audited, Base):
    __tablename__ = "resource"
    __table_args__ = S

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    name: Mapped[str]
    kind: Mapped[str] = mapped_column(server_default=text("'staff'"))
    user_id: Mapped[UUID | None]
    colour: Mapped[str | None]
    note: Mapped[str | None]
    show_publicly: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    level: Mapped[str | None]
    is_template: Mapped[bool] = mapped_column(server_default=text("false"))


class ResourceHours(Audited, Base):
    __tablename__ = "resource_hours"
    __table_args__ = S

    resource_id: Mapped[UUID]
    weekday: Mapped[int]
    start_time: Mapped[time]
    end_time: Mapped[time]


class ResourceTimeOff(Audited, Base):
    __tablename__ = "resource_time_off"
    __table_args__ = S

    resource_id: Mapped[UUID]
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    reason: Mapped[str | None]


class ServiceOffer(Audited, Base):
    __tablename__ = "service_offer"
    __table_args__ = S

    company_id: Mapped[UUID]
    product_id: Mapped[UUID | None]
    name: Mapped[str]
    description: Mapped[str | None]
    kind: Mapped[str] = mapped_column(server_default=text("'appointment'"))
    duration_minutes: Mapped[int]
    buffer_before_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    buffer_after_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    price: Mapped[Decimal] = money()
    resource_mode: Mapped[str] = mapped_column(server_default=text("'any'"))
    capacity: Mapped[int] = mapped_column(server_default=text("1"))
    show_publicly: Mapped[bool] = mapped_column(server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    processing_start_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    processing_minutes: Mapped[int] = mapped_column(server_default=text("0"))
    deposit_amount: Mapped[Decimal] = money()
    deposit_percent: Mapped[Decimal] = money()
    recall_days: Mapped[int | None]
    needs_patch_test: Mapped[bool] = mapped_column(server_default=text("false"))
    price_is_example: Mapped[bool] = mapped_column(server_default=text("false"))
    group_late_cancel_hours: Mapped[int | None]


class ServiceOfferResource(Audited, Base):
    __tablename__ = "service_offer_resource"
    __table_args__ = S

    offer_id: Mapped[UUID]
    resource_id: Mapped[UUID]


class Appointment(Audited, Base):
    __tablename__ = "appointment"
    __table_args__ = S

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    number: Mapped[str]
    offer_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(server_default=text("'appointment'"))
    capacity: Mapped[int] = mapped_column(server_default=text("1"))
    status: Mapped[str] = mapped_column(server_default=text("'confirmed'"))
    source: Mapped[str] = mapped_column(server_default=text("'staff'"))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    customer_id: Mapped[UUID | None]
    client_name: Mapped[str | None]
    client_phone: Mapped[str | None]
    client_email: Mapped[str | None]
    price: Mapped[Decimal] = money()
    note: Mapped[str | None]
    series_id: Mapped[UUID | None]
    series_index: Mapped[int | None]
    local_id: Mapped[str | None]
    cancel_reason_id: Mapped[UUID | None]
    cancel_note: Mapped[str | None]
    cancelled_at: Mapped[datetime | None]
    cancelled_by: Mapped[UUID | None]
    late_cancellation: Mapped[bool] = mapped_column(server_default=text("false"))
    checked_in_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    minutes_worked: Mapped[int | None]
    invoice_id: Mapped[UUID | None]
    invoice_number: Mapped[str | None]
    deposit_amount: Mapped[Decimal] = money()
    consent_given_at: Mapped[datetime | None]
    visit_id: Mapped[UUID | None]
    deposit_paid: Mapped[Decimal] = money()
    price_variant: Mapped[str | None]
    payer_customer_id: Mapped[UUID | None]
    payer_member_no: Mapped[str | None]
    preauth_ref: Mapped[str | None]
    copay_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    claim_id: Mapped[UUID | None]


class AppointmentAttendee(Audited, Base):
    __tablename__ = "appointment_attendee"
    __table_args__ = S

    appointment_id: Mapped[UUID]
    customer_id: Mapped[UUID | None]
    name: Mapped[str]
    phone: Mapped[str | None]
    email: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'booked'"))
    late_cancellation: Mapped[bool] = mapped_column(server_default=text("false"))
    cancelled_at: Mapped[datetime | None]
    checked_in_at: Mapped[datetime | None]
    source: Mapped[str] = mapped_column(server_default=text("'staff'"))
    credit_ref: Mapped[str | None]


class AppointmentMessage(Audited, Base):
    __tablename__ = "appointment_message"
    __table_args__ = S

    appointment_id: Mapped[UUID]
    kind: Mapped[str]
    queued_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class WaitlistEntry(Audited, Base):
    __tablename__ = "waitlist_entry"
    __table_args__ = S

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID]
    offer_id: Mapped[UUID]
    resource_id: Mapped[UUID | None]
    customer_id: Mapped[UUID | None]
    client_name: Mapped[str]
    client_phone: Mapped[str | None]
    client_email: Mapped[str | None]
    wanted_from: Mapped[date]
    wanted_to: Mapped[date]
    note: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'waiting'"))
    offered_starts_at: Mapped[datetime | None]
    offered_resource_id: Mapped[UUID | None]
    offered_at: Mapped[datetime | None]
    appointment_id: Mapped[UUID | None]


class BookingRefusal(Audited, Base):
    __tablename__ = "booking_refusal"
    __table_args__ = S

    company_id: Mapped[UUID]
    branch_id: Mapped[UUID | None]
    resource_id: Mapped[UUID | None]
    attempted_start: Mapped[datetime]
    source: Mapped[str] = mapped_column(server_default=text("'staff'"))
    reason: Mapped[str] = mapped_column(server_default=text("'conflict'"))
