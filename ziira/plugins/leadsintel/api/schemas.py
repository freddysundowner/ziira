"""Request and reply shapes of the Lead Intel plugin. No reply ever holds a key or a secret."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class LeadIntelCompanyIn(BaseModel):
    company_id: UUID


class LeadIntelKeyIn(BaseModel):
    company_id: UUID
    platform_key: str = Field(min_length=8, max_length=300, description="Stored encrypted; never shown again")


class LeadIntelNumberIn(BaseModel):
    company_id: UUID
    country_code: str = Field(min_length=1, max_length=4, description="Calling code digits, for example 44")
    phone_number: str = Field(min_length=5, max_length=20, description="The number without the country code")


class LeadIntelConnectIn(LeadIntelNumberIn):
    business_name: str = Field(min_length=1, max_length=100, description="Your business name, shown to Meta")
    display_name: str = Field(min_length=1, max_length=100, description="The name customers see on WhatsApp; Meta "
                                                                          "reviews it and it cannot be changed here")
    about: str | None = Field(default=None, max_length=139)
    description: str | None = Field(default=None, max_length=512)
    address: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=200)
    websites: list[str] = Field(default_factory=list, max_length=2)
    profile_image_url: str | None = Field(default=None, max_length=500, pattern=r"^https://")


class LeadIntelCodeIn(BaseModel):
    company_id: UUID
    code: str = Field(min_length=4, max_length=10, pattern=r"^\d+$")


class LeadIntelWhatsAppState(BaseModel):
    status: str
    display_phone: str | None
    error_code: str | None
    error_message: str | None


class LeadIntelStateOut(BaseModel):
    key_saved: bool
    whatsapp: LeadIntelWhatsAppState | None
    warning: str | None = None
    sent_to: str | None = None
    expires_at: str | None = None


class LeadIntelExistingOut(BaseModel):
    connected: bool
    claimable: bool
    reason: str | None


class LeadIntelCheckOut(BaseModel):
    ok: bool
    message: str


class LeadIntelInboundOut(BaseModel):
    id: UUID
    created_at: str
    sender: str = Field(description="Masked")
    kind: str
    body: str | None
    button_id: str | None
    outcome: str
    read: bool


def state_out(data: dict[str, Any]) -> LeadIntelStateOut:
    return LeadIntelStateOut(**data)
