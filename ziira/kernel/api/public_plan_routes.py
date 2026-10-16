"""The public price list, for the website and the in-app plan page. No sign-in, no business data."""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ziira.kernel.platform import plans

router = APIRouter(prefix="/api/v1/public", tags=["Pricing"])


class PublicPrice(BaseModel):
    currency: str
    interval: str
    amount: str
    tax_inclusive: bool


class PublicPlan(BaseModel):
    code: str
    name: str
    description: str
    edition: str | None
    highlights: list[str]
    limits: dict[str, int | None]
    trial_days: int
    prices: list[PublicPrice]


class PublicAddon(BaseModel):
    code: str
    name: str
    description: str
    kind: str
    unit: str | None
    quantity: int
    prices: list[PublicPrice]


class PublicPlans(BaseModel):
    plans: list[PublicPlan]
    addons: list[PublicAddon]
    updated_at: str


@router.get("/plans", response_model=PublicPlans)
def public_plans(response: Response) -> object:
    """Public, active plans with the prices in force now, and public add-ons. Cached for a minute."""
    response.headers["Cache-Control"] = f"public, max-age={plans.PUBLIC_CACHE_SECONDS}"
    return plans.public_plans()
