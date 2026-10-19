"""Super Admin: the website assistant's switch, spend cap, visitor limits, greeting and quick replies.

Same rules as the AI page it sits on: an operator token, `platform.ai` (superadmin only), a fresh confirmation for every
change, and a line in the operator trail (which fields changed, never the greeting's words)."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operators
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import admin
from ziira.kernel.platform import site_assistant as settings

router = APIRouter(prefix="/api/v1/operator/site-assistant", tags=["Super Admin"])
Op = operators.Operator
Needs = Depends(require("platform.ai"))


class SiteAssistantUsage(BaseModel):
    label: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: str


class SiteAssistantDefaults(BaseModel):
    per_minute: int
    per_day: int
    daily_total: int


class SiteAssistantOut(BaseModel):
    enabled: bool
    monthly_cap_usd: str | None = Field(description="USD per month; null means no cap of its own")
    per_minute: int
    per_day: int
    daily_total: int
    greeting: str
    suggestions: list[str]
    provider: str | None = Field(description="The platform's active AI provider the assistant would use")
    model: str | None
    available: bool = Field(description="The site shows the chat button")
    blocked_reason: str | None = Field(description="off or budget when it is not available")
    month_spend_usd: str
    cap_reached: bool
    usage: SiteAssistantUsage
    defaults: SiteAssistantDefaults


class SiteAssistantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    monthly_cap_usd: str | None = Field(default=None, max_length=20, description="Empty or null: no cap of its own")
    per_minute: int | None = Field(default=None, ge=1, le=60)
    per_day: int | None = Field(default=None, ge=1, le=2000)
    daily_total: int | None = Field(default=None, ge=1, le=1_000_000)
    greeting: str | None = Field(default=None, max_length=300)
    suggestions: list[str] | None = Field(default=None, max_length=6)


@router.get("", response_model=SiteAssistantOut)
def get_site_assistant(_: Op = Needs) -> object:
    """The website assistant's settings and this month's use."""
    return settings.overview()


@router.put("", response_model=SiteAssistantOut)
def put_site_assistant(body: SiteAssistantIn, request: Request, operator: Op = Needs) -> object:
    """Change the given settings (only the fields sent)."""
    changes: dict[str, Any] = {k: getattr(body, k) for k in sorted(body.model_fields_set)}
    return admin.act(
        operator,
        "site_assistant.save",
        "settings",
        client_ip(request),
        lambda: settings.save(changes, operator.name),
        summary=lambda r: {"fields": sorted(changes), "enabled": r["enabled"], "monthly_cap_usd": r["monthly_cap_usd"]},
    )
