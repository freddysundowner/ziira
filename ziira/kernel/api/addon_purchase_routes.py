"""Buying one add-on for one payment, from the business's side (docs/subscription-payments.md, "Add-ons").

`GET /billing/addons` lists what can be bought and what was bought; `POST /billing/addons/{unit}/buy` makes the invoice
(one line) and returns it, ready to pay with the same payment calls as a plan (`/billing/pay/options`,
`/billing/payments`). The add-on is switched on for use only when that payment is confirmed (never from the browser
alone). Buying needs the owner's permissions: `units.manage` and `billing.manage`. Open when the account is suspended,
like the rest of `/api/v1/billing/`."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ziira.kernel import audit
from ziira.kernel.api.billing_routes import MyInvoice, _mine, _user_name
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import Forbidden
from ziira.kernel.platform import unit_addons
from ziira.sdk import DB_SESSION, Session, idempotency_key_header, request_context, require_permission

router = APIRouter(prefix="/api/v1/billing", tags=["Plan & billing"])


class AddonPurchase(BaseModel):
    id: UUID
    unit_name: str
    title: str
    status: str = Field(description="pending (waiting for payment), active, revoked or void")
    price: Decimal
    currency: str | None
    invoice_id: UUID | None
    invoice_number: str | None
    payment_reference: str | None
    granted_by: str = Field(description="payment, or operator (given free by the vendor)")
    purchased_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class AddonOffer(BaseModel):
    unit: str
    title: str
    state: str = Field(description="included, bought, for_sale or not_for_sale")
    price: Decimal | None = Field(description="One payment, in the business's billing currency (for_sale only)")
    currency: str | None
    tax_inclusive: bool
    purchase: AddonPurchase | None


class AddonShop(BaseModel):
    free_for_all: bool = Field(description="True: every add-on is included for now, nothing needs buying")
    currency: str | None = Field(description="The business's billing currency")
    can_buy: bool = Field(description="The signed-in person may buy now")
    units: list[AddonOffer]
    purchases: list[AddonPurchase]


class AddonBuyOut(BaseModel):
    purchase: AddonPurchase
    invoice: MyInvoice | None


def _view_or_deny(ctx: RequestContext) -> None:
    if not (ctx.has_anywhere("units.manage") or ctx.has_anywhere("billing.manage")):
        raise Forbidden("This needs permission to manage add-ons or billing")


@router.get("/addons", response_model=AddonShop)
def addon_shop(ctx: RequestContext = Depends(request_context)) -> object:
    """What this business can buy (with prices in its billing currency) and what it already bought."""
    _view_or_deny(ctx)
    can = ctx.has_anywhere("billing.manage") and ctx.has_anywhere("units.manage")
    return unit_addons.shop(ctx.tenant_id, can_buy=can)


@router.post(
    "/addons/{unit}/buy",
    response_model=AddonBuyOut,
    status_code=201,
    dependencies=[Depends(require_permission("billing.manage")), Depends(require_permission("units.manage"))],
)
def buy_addon(
    unit: str,
    ctx: RequestContext = Depends(request_context),
    s: Session = DB_SESSION,
    idempotency_key: str | None = Depends(idempotency_key_header),
) -> Any:
    """Start buying an add-on: its invoice is made at once and returned, ready to pay. Repeating the request (or sending
    the same Idempotency-Key) returns the same invoice; nobody is charged twice. Nothing is switched on until the
    payment is confirmed."""
    out = unit_addons.buy(ctx.tenant_id, unit, by_name=_user_name(s, ctx), idempotency_key=idempotency_key)
    audit.record(s, "addon_purchase_started", "kernel.tenant", ctx.tenant_id, {"unit": unit})
    return {"purchase": out["purchase"], "invoice": _mine(out["invoice"]) if out["invoice"] else None}
