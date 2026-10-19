"""Request and response shapes for lockers, guests, vouchers and credit, points, measurements, trainers and reports."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Day = Annotated[date, Field(ge=date(1900, 1, 1), le=date(2100, 12, 31))]
Money = Annotated[Amount, Field(ge=0, le=Decimal("1000000000"))]
Interval = Literal["week", "month", "quarter", "year"]


class XOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- lockers
class LockersIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    codes: list[str] = Field(min_length=1, max_length=500)
    kind: Literal["locker", "towel", "other"] = "locker"
    fee: Money = Decimal(0)
    deposit: Money = Decimal(0)
    billing_interval: Interval = "month"
    product_id: UUID | None = Field(default=None, description="The service item the rent and deposit are invoiced as")


class LockerAssignIn(BaseModel):
    customer_id: UUID
    start_date: Day | None = None


class LockerOut(XOut):
    id: UUID
    company_id: UUID
    branch_id: UUID
    code: str
    kind: str
    fee: Decimal
    deposit: Decimal
    billing_interval: str
    product_id: UUID | None
    status: str
    customer_id: UUID | None
    customer_name: str | None = None
    assigned_on: date | None
    schedule_id: UUID | None
    deposit_run_id: UUID | None


# --------------------------------------------------------------------------- guests
class GuestIn(BaseModel):
    guest_name: str = Field(min_length=1, max_length=200)
    guest_phone: str | None = Field(default=None, max_length=40)
    branch_id: UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class GuestOut(XOut):
    id: UUID
    guest_name: str
    guest_phone: str | None
    visited_on: date
    period_start: date
    note: str | None


class GuestPassesOut(BaseModel):
    left: int


# --------------------------------------------------------------------------- vouchers, credit and points
class VoucherSellIn(BaseModel):
    company_id: UUID
    branch_id: UUID
    amount: Annotated[Amount, Field(gt=0, le=Decimal("1000000000"))]
    purchaser_customer_id: UUID | None = None
    recipient_customer_id: UUID | None = None
    expires_on: Day | None = None
    note: str | None = Field(default=None, max_length=300)
    invoice: bool | None = None


class VoucherVoidIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class ValueAccountOut(XOut):
    id: UUID
    company_id: UUID
    kind: str
    customer_id: UUID | None
    customer_name: str | None = None
    purchaser_customer_id: UUID | None
    purchaser_name: str | None = None
    code: str | None
    initial: Decimal
    expires_on: date | None
    status: str
    note: str | None
    balance: Decimal = Decimal(0)
    created_at: datetime


class ValueEntryOut(XOut):
    id: UUID
    entry_type: str
    quantity: Decimal
    source_type: str | None
    business_date: date
    note: str | None
    created_at: datetime


class CreditGiveIn(BaseModel):
    customer_id: UUID
    amount: Annotated[Amount, Field(gt=0, le=Decimal("1000000000"))]
    note: str = Field(min_length=1, max_length=300)
    kind: Literal["promo", "referral"] = "promo"


class PointsRedeemIn(BaseModel):
    points: Annotated[Amount, Field(gt=0, le=Decimal("100000000"))]
    note: str | None = Field(default=None, max_length=300)


class CustomerValueOut(BaseModel):
    customer_id: UUID
    credit: Decimal
    points: Decimal
    accounts: list[ValueAccountOut]


# --------------------------------------------------------------------------- measurements
class MeasurementIn(BaseModel):
    metric: str = Field(min_length=1, max_length=60)
    value: Annotated[Decimal, Field(ge=Decimal("-1000000"), le=Decimal("1000000"), max_digits=12, decimal_places=3)]
    taken_on: Day | None = None
    unit: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=300)


class MeasurementOut(XOut):
    id: UUID
    taken_on: date
    metric: str
    value: Decimal
    unit: str | None
    note: str | None


# --------------------------------------------------------------------------- trainers
class TrainerRateIn(BaseModel):
    company_id: UUID
    trainer_ref: UUID = Field(description="The trainer's id in the calendar (a Bookings resource) or a user")
    trainer_name: str = Field(min_length=1, max_length=200)
    service_ref: str | None = Field(default=None, max_length=100, description="Left out: every service")
    basis: Literal["fixed", "percent"]
    amount: Money


class TrainerRateOut(XOut):
    id: UUID
    trainer_ref: UUID
    trainer_name: str
    service_ref: str | None
    basis: str
    amount: Decimal
    status: str


class TrainerEarningsOut(BaseModel):
    trainer_ref: UUID
    trainer_name: str
    sessions: int
    earned: Decimal
    paid: Decimal
    session_value: Decimal


class TrainerEarningRowOut(XOut):
    id: UUID
    trainer_ref: UUID
    trainer_name: str
    customer_id: UUID | None
    service_ref: str | None
    source_type: str
    session_value: Decimal
    amount: Decimal
    basis: str
    earned_on: date
    status: str


class TrainerPaidIn(BaseModel):
    through: Day


class TrainerPaidOut(BaseModel):
    rows: int


# --------------------------------------------------------------------------- reports
class MembershipOwnerReportOut(BaseModel):
    """The owner's overview; sections are described in docs/memberships.md."""

    company_id: UUID
    start: date
    end: date
    branch_id: UUID | None
    members: dict[str, int]
    mrr: Decimal
    revenue_at_risk: Decimal
    revenue_at_risk_percent: int
    by_plan: list[dict[str, Any]]
    flow: list[dict[str, Any]]
    retention: list[dict[str, Any]]
    attendance: list[dict[str, Any]]
    visits: int
    visitors: int
    arrears: dict[str, Any]
    freezes: dict[str, Any]
    trials: dict[str, int]
    leaving: list[dict[str, Any]]
    class_fill: list[dict[str, Any]] = []
    trainers: list[dict[str, Any]]
