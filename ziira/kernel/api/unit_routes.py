"""Apps & plugins: see what the business can switch on, and switch units on, off or remove their data.
Needs 'units.manage' (the Owner by default). Installing units on the platform stays a command-line job."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import unit_admin
from ziira.kernel.context import RequestContext
from ziira.kernel.platform import entitlements
from ziira.kernel.registry import Registry, discover
from ziira.sdk import DB_SESSION, Session, request_context, require_permission

router = APIRouter(prefix="/api/v1/units", tags=["Apps & plugins"],
                   dependencies=[Depends(require_permission(unit_admin.PERMISSION))])


class UnitCard(BaseModel):
    name: str
    title: str
    description: str
    category: str = Field(description="How the screen groups it (sales, stock, payments, tax, ...); empty if none")
    countries: list[str] = Field(description="Plugins: countries it is meant for; empty means worldwide")
    editions: list[str] = Field(default_factory=list, description="Industry packs: the editions it is recommended for")
    kind: str = Field(description="module or plugin")
    version: str
    requires: list[str]
    optional: list[str]
    dependants: list[str] = Field(description="Enabled units that need this one")
    installed: bool = Field(description="False: the platform does not offer it yet (an operator installs it)")
    enabled: bool
    has_data: bool = Field(description="The unit's tables exist in this business's database")
    will_also_enable: list[str] = Field(description="Units that switching this on will switch on too")
    can_enable: bool
    in_plan: bool = Field(default=True, description="False: the business's plan (or licence) does not include it")
    why_not_enable: str | None = Field(default=None, description="Why it cannot be switched on (for example: the plan)")
    sale_state: str = Field(
        default="included",
        description="included (in the plan, or everything is free), bought, for_sale (one payment) or not_for_sale",
    )
    sale_price: Decimal | None = Field(default=None, description="The one-time price when for_sale")
    sale_currency: str | None = None
    sale_tax_inclusive: bool = False
    bought_at: datetime | None = Field(default=None, description="When it was bought or given")
    receipt_invoice_id: UUID | None = Field(default=None, description="The invoice (receipt) of the purchase")
    bought_free: bool = Field(default=False, description="True: given by the vendor, nothing was paid")
    can_buy: bool = Field(default=False, description="The signed-in person may buy it now (owner, account in order)")
    can_disable: bool
    why_not_disable: str | None
    can_remove: bool
    why_not_remove: str | None


class UnitChange(BaseModel):
    enabled: list[str] = Field(description="Units newly switched on by this change")
    unit: UnitCard


class RemoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Annotated[str, Field(max_length=100, description="The unit's name, typed to confirm the data is deleted")]


def _registry() -> Registry:
    return Registry(discover())


def _card(s: Session, reg: Registry, name: str, ctx: RequestContext) -> UnitCard:
    return UnitCard(**next(c for c in unit_admin.catalog(s, reg, can_buy=_can_buy(ctx)) if c["name"] == name))


def _can_buy(ctx: RequestContext) -> bool:
    return ctx.has_anywhere("billing.manage")


@router.get("/catalog", response_model=list[UnitCard])
def unit_catalog(ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Every module and plugin with its state for this business and what can be done with it now. A unit outside the
    plan shows whether it is for sale (one payment) and its price in the business's billing currency."""
    return unit_admin.catalog(s, _registry(), can_buy=_can_buy(ctx))


@router.post("/{name}/enable", response_model=UnitChange)
def enable(name: str, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Switch a unit on, together with the units it requires. Reports everything newly switched on."""
    reg = _registry()
    if name in reg.units:
        entitlements.check_unit(ctx.tenant_id, name, reg.units[name].title)      # 402 not_in_plan: upgrade
    newly = unit_admin.enable_unit(s, reg, ctx.tenant_id, name)
    return {"enabled": newly, "unit": _card(s, reg, name, ctx)}


@router.post("/{name}/disable", response_model=UnitChange)
def disable(name: str, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Switch a unit off. Its data is kept. Refused while another switched-on unit needs it."""
    reg = _registry()
    unit_admin.disable_unit(s, reg, ctx.tenant_id, name)
    return {"enabled": [], "unit": _card(s, reg, name, ctx)}


@router.post("/{name}/remove", response_model=UnitChange)
def remove(name: str, body: RemoveIn, ctx: RequestContext = Depends(request_context),
           s: Session = DB_SESSION) -> object:
    """Delete a switched-off unit's data for this business (cannot be undone). `confirm` must be the unit's name."""
    reg = _registry()
    unit_admin.remove_unit(s, reg, ctx.tenant_id, name, body.confirm)
    return {"enabled": [], "unit": _card(s, reg, name, ctx)}
