"""Request and response shapes for the Command Center API."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

Kind = Literal["daily", "weekly"]
Channel = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,39}$", description="in_app, or a channel the business has")]


class FigureOut(BaseModel):
    metric: str
    label: str
    kind: Literal["money", "count", "percent"]
    value: Decimal
    previous: Decimal | None
    branch_id: UUID | None
    branch_name: str | None
    higher_is_better: bool | None


class TopFindingOut(BaseModel):
    id: UUID
    severity: str
    area: str | None
    summary: str
    recommended_action: str | None
    status: str
    branch_id: UUID | None
    amount: Decimal | None
    reason: str | None = None   # why the AI layer put it here, when it ranked it (show it as AI-written)
    source: str = "ziira"       # "connected" (read from the system the business keeps) or "ziira"


class OverviewOut(BaseModel):
    company_id: UUID
    company_name: str
    currency: str
    day: date
    figures: list[FigureOut]
    refreshed_at: datetime | None
    open_findings: int
    findings_by_severity: dict[str, int]
    top_findings: list[TopFindingOut]


class ScheduleIn(BaseModel):
    channel: Channel = "in_app"
    send_time: time = Field(description="Local time in the company's time zone, e.g. 07:30")
    weekday: int | None = Field(default=None, ge=1, le=7, description="1 Monday to 7 Sunday: needed for a weekly brief")
    is_active: bool = True


class ScheduleOut(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    kind: Kind
    channel: Channel
    send_time: time
    weekday: int | None
    is_active: bool


class BriefSummaryOut(BaseModel):
    id: UUID
    company_id: UUID
    kind: Kind
    brief_date: date
    subject: str
    delivered_via: str
    read_at: datetime | None
    created_at: datetime


class BriefOut(BriefSummaryOut):
    body: str


class BriefPreviewOut(BaseModel):
    subject: str
    body: str
    short: str


class WidgetIn(BaseModel):
    widget_code: str = Field(max_length=60)
    settings: dict[str, object] = Field(default_factory=dict)


class WidgetOut(WidgetIn):
    position: int
