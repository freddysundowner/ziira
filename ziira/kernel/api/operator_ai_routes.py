"""Super Admin: the AI providers (keys, models, default provider, spend cap, usage, quality check).

Same rules as the rest of the console: an operator token, `platform.ai` (superadmin only) on every route, a fresh
confirmation for every change and for every action that spends money, and a line in the operator trail without any
secret (it keeps which fields changed). Keys are write-only: never returned, logged or put in the trail."""

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operators
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.platform import admin
from ziira.kernel.platform import ai as platform_ai

router = APIRouter(prefix="/api/v1/operator/ai", tags=["Super Admin"])
Op = operators.Operator
Needs = Depends(require("platform.ai"))


class AiModelChoice(BaseModel):
    id: str
    title: str
    tiers: list[str] = Field(description="best_value, higher_quality and/or cheapest")
    notes: str
    input_per_mtok: str | None = Field(description="USD per million input tokens; null when no price is known")
    output_per_mtok: str | None
    price_overridden: bool
    in_catalog: bool
    live: bool | None = Field(description="In the provider's live list; null when the list was not fetched")


class AiProviderOut(BaseModel):
    name: str
    title: str
    capabilities: list[str]
    auth: str
    default_base_url: str
    base_url: str
    terms_url: str
    docs_url: str
    verified_on: str
    prices_updated: str
    price_source: str
    enabled: bool
    key_set: bool
    key_last4: str = Field(description="The last four characters of the saved key: all that is ever shown")
    models: dict[str, str] = Field(description="The model used for each feature: explain, rank, ask")
    model_choices: list[AiModelChoice]
    live_models_at: datetime | None
    last_tested_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    terms_ack_by: str | None
    terms_ack_at: datetime | None
    is_default: bool
    updated_at: datetime | None
    updated_by: str | None


class AiOverviewOut(BaseModel):
    providers: list[AiProviderOut]
    default_provider: str | None
    environment_provider: str | None = Field(description="With no default chosen here: the environment's provider")
    monthly_cap_usd: str | None
    month_spend_usd: str
    cap_reached: bool
    production: bool


class AiPriceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: str = Field(max_length=20)
    output: str = Field(max_length=20)


class AiProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    api_key: str | None = Field(default=None, max_length=500, description="Write-only; empty keeps the saved key")
    clear_key: bool | None = None
    base_url: str | None = Field(default=None, max_length=300)
    models: dict[str, str] | None = None
    price_overrides: dict[str, AiPriceIn | None] | None = Field(default=None, max_length=60)
    terms_acknowledged: bool | None = Field(
        default=None, description="The provider's data-use terms are accepted and a DPA is in place")


class AiModelRefreshOut(BaseModel):
    count: int
    missing_chosen: list[str]


class AiConnectionOut(BaseModel):
    ok: bool
    message: str
    latency_ms: int
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: str


class AiDefaultPreviewOut(BaseModel):
    from_provider: str | None
    to_provider: str
    consents_affected: int = Field(description="Companies whose consent ends if the default changes")


class AiDefaultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=40)
    confirm: str = Field(max_length=40, description="The provider's code, typed")
    reason: str = Field(min_length=3, max_length=300)


class AiDefaultOut(AiDefaultPreviewOut):
    provider: str


class AiCapIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cap_usd: str | None = Field(default=None, max_length=20, description="USD per month; null removes the cap")


class AiUsageProvider(BaseModel):
    provider: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: str


class AiUsageBusiness(BaseModel):
    code: str
    name: str
    calls: int
    tokens: int
    cost_usd: str


class AiUsageDay(BaseModel):
    day: date
    tokens: int
    cost_usd: str


class AiUsageOut(BaseModel):
    month: date
    providers: list[AiUsageProvider]
    top_businesses: list[AiUsageBusiness]
    days: list[AiUsageDay]
    cap_usd: str | None
    spend_usd: str
    cap_flag: str | None = Field(description="Set when the cap was reached this month")


class AiQualityEstimateOut(BaseModel):
    provider: str
    model: str
    level: str
    questions: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: str
    price_known: bool


class AiQualityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=40)
    model: str | None = Field(default=None, max_length=100)
    level: Literal["quick", "full"] = "quick"
    confirm_cost: bool = Field(description="The owner has seen the estimated cost and agrees to spend it")


class AiQualityOut(BaseModel):
    provider: str
    model: str
    level: str
    score: int
    verdict: str
    rates: dict[str, dict[str, int] | None]
    latency_ms_average: int
    latency_ms_slowest: int
    tokens_in: int
    tokens_out: int
    cost_usd: str
    price_known: bool
    questions: list[dict[str, Any]]


class AiTenantProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str | None = Field(description="Null puts the business back on the default")
    reason: str = Field(min_length=3, max_length=300)


class AiTenantProviderOut(BaseModel):
    code: str
    name: str
    provider: str
    reason: str
    set_by: str
    set_at: datetime


def _ip(request: Request) -> str | None:
    return client_ip(request)


@router.get("", response_model=AiOverviewOut)
def get_overview(_: Op = Needs) -> object:
    """Every installed AI provider with its settings (never its key), and the platform-wide settings."""
    return platform_ai.overview()


@router.put("/providers/{name}", response_model=AiProviderOut)
def put_provider(name: str, body: AiProviderIn, request: Request, operator: Op = Needs) -> object:
    fields = sorted(k for k in ("enabled", "api_key", "clear_key", "base_url", "models", "price_overrides",
                                "terms_acknowledged") if k in body.model_fields_set)
    return admin.act(
        operator, "ai_provider.save", name, _ip(request),
        lambda: platform_ai.save_provider(
            name, enabled=body.enabled, api_key=body.api_key, clear_key=bool(body.clear_key), base_url=body.base_url,
            models=body.models,
            price_overrides={k: (v.model_dump() if v else None) for k, v in (body.price_overrides or {}).items()}
            if body.price_overrides is not None else None,
            terms_acknowledged=body.terms_acknowledged, by=operator.name),
        summary=lambda r: {"provider": name, "fields": fields, "enabled": r["enabled"]},
    )


@router.post("/providers/{name}/refresh-models", response_model=AiModelRefreshOut)
def post_refresh_models(name: str, request: Request, operator: Op = Needs) -> object:
    """Ask the provider which models exist for the saved key. A cheap call; no model is run."""
    return admin.act(operator, "ai_provider.refresh_models", name, _ip(request),
                     lambda: platform_ai.refresh_models(name, operator.name),
                     summary=lambda r: {"provider": name, "count": r["count"]})


@router.post("/providers/{name}/test", response_model=AiConnectionOut)
def post_test(name: str, request: Request, operator: Op = Needs) -> object:
    """A tiny real call with the saved key and the Ask model; its estimated cost is counted in the usage."""
    return admin.act(operator, "ai_provider.test", name, _ip(request), lambda: platform_ai.check_connection(name),
                     summary=lambda r: {"provider": name, "ok": r["ok"]})


@router.get("/default-change", response_model=AiDefaultPreviewOut)
def get_default_change(provider: str = Query(max_length=40), _: Op = Needs) -> object:
    """What making this provider the default would do: how many businesses must agree again."""
    return platform_ai.default_change_preview(provider)


@router.put("/default", response_model=AiDefaultOut)
def put_default(body: AiDefaultIn, request: Request, operator: Op = Needs) -> object:
    """Change the default provider (typed confirmation and a reason). Consents given for the old one stop working."""
    return admin.act(
        operator, "ai_provider.default", body.provider, _ip(request),
        lambda: platform_ai.change_default(body.provider, confirm=body.confirm, reason=body.reason, by=operator.name),
        summary=lambda r: {"from": r["from_provider"], "to": r["provider"],
                           "consents_affected": r["consents_affected"]},
        reason=body.reason)


@router.put("/cap", response_model=AiOverviewOut)
def put_cap(body: AiCapIn, request: Request, operator: Op = Needs) -> object:
    return admin.act(operator, "ai_provider.cap", "monthly_cap", _ip(request),
                     lambda: platform_ai.set_cap(body.cap_usd, operator.name),
                     summary=lambda r: {"cap_usd": r["monthly_cap_usd"]})


@router.get("/usage", response_model=AiUsageOut)
def get_usage(_: Op = Needs) -> object:
    """This month's tokens and estimated spend per provider, the ten busiest businesses and spend per day."""
    return platform_ai.usage_report()


@router.get("/quality-check/estimate", response_model=AiQualityEstimateOut)
def get_quality_estimate(provider: str = Query(max_length=40), level: Literal["quick", "full"] = "quick",
                         model: str | None = Query(default=None, max_length=100), _: Op = Needs) -> object:
    return platform_ai.quality_estimate(provider, level, model)


@router.post("/quality-check", response_model=AiQualityOut)
def post_quality_check(body: AiQualityIn, request: Request, operator: Op = Needs) -> object:
    """Run the scored check with real provider calls (real spend). Refused unless the cost was confirmed."""
    if not body.confirm_cost:
        raise ValidationFailed("Confirm the estimated cost first")
    return admin.act(
        operator, "ai_provider.quality_check", body.provider, _ip(request),
        lambda: platform_ai.run_quality_check(body.provider, body.level, body.model),
        summary=lambda r: {"provider": body.provider, "model": r["model"], "level": body.level, "score": r["score"],
                           "cost_usd": r["cost_usd"]})


@router.get("/tenant-overrides", response_model=list[AiTenantProviderOut])
def get_tenant_overrides(_: Op = Needs) -> object:
    """Businesses an operator has put on a different provider than the default (none unless someone did)."""
    return platform_ai.tenant_overrides()


@router.put("/tenant-overrides/{code}", response_model=list[AiTenantProviderOut])
def put_tenant_override(code: str, body: AiTenantProviderIn, request: Request, operator: Op = Needs) -> object:
    admin.act(operator, "ai_provider.tenant_override", code, _ip(request),
              lambda: platform_ai.set_tenant_provider(code, body.provider, body.reason, operator.name),
              summary=lambda r: {"tenant": code, "provider": r["provider"]}, reason=body.reason)
    return platform_ai.tenant_overrides()
