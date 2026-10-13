"""Request and response shapes for the CRM API."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.sdk import Amount

Limit = Annotated[Amount, Field(ge=0, le=Decimal("1000000000"))]
Kind = Literal["individual", "business"]


class CustomerIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=20, description="Made for you when left out")
    kind: Kind = "business"
    phone: str | None = Field(default=None, max_length=30, examples=["0712345678"])
    email: str | None = Field(default=None, max_length=200)
    kra_pin: str | None = Field(default=None, max_length=11)
    customer_group: str | None = Field(default=None, max_length=60, description="Used by price lists")
    payment_terms_days: int = Field(default=0, ge=0, le=365)
    owner_user_id: UUID | None = None


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Kind | None = None
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    kra_pin: str | None = Field(default=None, max_length=11)
    customer_group: str | None = Field(default=None, max_length=60)
    owner_user_id: UUID | None = None
    status: Literal["active", "on_hold", "inactive"] | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    kind: str
    phone: str | None
    email: str | None
    kra_pin: str | None
    customer_group: str | None
    credit_limit: Decimal
    payment_terms_days: int
    owner_user_id: UUID | None
    status: str


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=60)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    name: str
    phone: str | None
    email: str | None
    role: str | None


class CreditChangeIn(BaseModel):
    credit_limit: Limit
    payment_terms_days: int = Field(ge=0, le=365)
    reason: str = Field(min_length=1, max_length=500)


class CreditVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    credit_limit: Decimal
    previous_limit: Decimal | None
    payment_terms_days: int
    status: str
    reason: str | None
    valid_from: datetime
    created_by: UUID | None
    approved_by: UUID | None


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class SourceOut(SourceIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class LeadIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    source_id: UUID | None = None
    owner_user_id: UUID | None = None
    customer_kind: Kind | None = None


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=200)
    owner_user_id: UUID | None = None
    source_id: UUID | None = None


class LeadStatusIn(BaseModel):
    status: Literal["new", "contacted", "qualified", "lost"]
    lost_reason: str | None = Field(default=None, max_length=300)


class LeadConvertIn(BaseModel):
    code: str | None = Field(default=None, max_length=20)
    customer_group: str | None = Field(default=None, max_length=60)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    name: str
    business_name: str | None
    phone: str | None
    email: str | None
    source_id: UUID | None
    status: str
    owner_user_id: UUID | None
    converted_customer_id: UUID | None
    lost_reason: str | None


class ConvertedOut(BaseModel):
    lead: LeadOut
    customer: CustomerOut


class ActivityIn(BaseModel):
    related_type: Literal["lead", "customer"]
    related_id: UUID
    kind: Literal["call", "visit", "message", "meeting", "task"]
    due_at: datetime | None = None
    owner_user_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class ActivityDoneIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    related_type: str
    related_id: UUID
    kind: str
    due_at: datetime | None
    done_at: datetime | None
    owner_user_id: UUID | None
    note: str | None


class DoNotContactIn(BaseModel):
    channel: Literal["email", "sms"] | None = Field(default=None, description="Default: every channel")
    reason: str | None = Field(default=None, max_length=300)


class DoNotContactOut(BaseModel):
    recorded: list[str]
