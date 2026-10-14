"""Request and response shapes for the Intelligence API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RecordOut(BaseModel):
    type: str
    id: str | None
    label: str


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    check_code: str | None
    area: str | None
    company_id: UUID | None
    branch_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    period_start: date | None
    period_end: date | None
    value: Decimal | None
    expected_value: Decimal | None
    amount: Decimal | None
    severity: str
    summary: str | None
    recommended_action: str | None
    explanation: str | None
    status: str
    owner_user_id: UUID | None
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


class FindingEventOut(BaseModel):
    id: UUID
    created_at: datetime
    event: str
    user_id: UUID | None
    user_name: str | None
    channel: str | None
    note: str | None


class FindingDetailOut(FindingOut):
    records: list[RecordOut]
    figures: dict[str, str]
    events: list[FindingEventOut]


class FindingsSummaryOut(BaseModel):
    open: int
    by_severity: dict[str, int]
    by_area: dict[str, int]
    by_status: dict[str, int]
    amount_at_stake: Decimal


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ExplainIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000, description="What happened")


class DismissIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    user_id: UUID | None = None


class AskIn(BaseModel):
    user_id: UUID
    message: str = Field(default="", max_length=1000)


class CheckOut(BaseModel):
    code: str
    title: str
    area: str
    description: str
    severity: str
    enabled: bool
    auto_resolves: bool
    defaults: dict[str, Any]
    params: dict[str, Any]


class CheckUpdateIn(BaseModel):
    enabled: bool | None = None
    params: dict[str, Any] | None = None


class RunIn(BaseModel):
    company_id: UUID
    checks: list[str] | None = Field(default=None, description="Only these checks (all by default)")


class RunOut(BaseModel):
    checks_run: int
    created: int
    updated: int
    resolved: int
    reopened: int
    failed: list[str]
