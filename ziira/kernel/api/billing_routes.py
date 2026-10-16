"""Plan & billing, from the business's side: its own plan, usage against the limits, invoices, a request for another
plan,
cancelling, and (on a self-hosted copy) the licence. A business only ever sees its own records; nothing here reads
another subscriber. These calls stay open when the account is suspended (so the owner can see what to pay)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ziira.kernel import audit
from ziira.kernel.context import RequestContext
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound
from ziira.kernel.platform import billing, licences, plans, settings, subscriptions
from ziira.kernel.platform import entitlements as ent
from ziira.kernel.registry import discover
from ziira.sdk import DB_SESSION, Session, request_context, require_permission

router = APIRouter(prefix="/api/v1/billing", tags=["Plan & billing"])
PERMISSION = "billing.manage"
MANAGE = [Depends(require_permission(PERMISSION))]


class UsageLine(BaseModel):
    used: int
    limit: int | None = Field(description="Null: no limit")


class PendingChange(BaseModel):
    plan_code: str
    plan_name: str
    interval: str | None
    currency: str | None


class MyRequest(BaseModel):
    id: UUID
    plan_code: str
    plan_name: str
    interval: str
    currency: str
    status: str
    invoice_id: UUID | None
    note: str
    created_at: datetime


class MyPlan(BaseModel):
    mode: str = Field(description="saas or selfhosted")
    managed: bool = Field(description="False: this business has no subscription (no limits, no billing)")
    status: str
    access: str = Field(description="full, warning, billing_only or read_only")
    message: str
    plan_code: str | None
    plan_name: str | None
    edition: str | None
    interval: str | None
    currency: str | None
    unit_amount: Decimal | None
    tax_inclusive: bool
    period_start: datetime | None
    period_end: datetime | None
    trial_end: datetime | None
    cancel_at_period_end: bool
    is_comp: bool
    coupon_code: str | None
    pending_change: PendingChange | None
    usage: dict[str, UsageLine]
    units_in_plan: list[str] | None = Field(description="Null: every unit")
    units_over_plan: list[str] = Field(
        description="Switched on but not in the plan (kept; cannot be switched on again)"
    )
    payment_instructions: str
    request: MyRequest | None
    owed: dict[str, Decimal]
    can_manage_billing: bool


def _tenant(ctx: RequestContext) -> UUID:
    return ctx.tenant_id


def _my_request(tenant_id: UUID) -> dict[str, Any] | None:
    pending = billing.list_requests(tenant_id=tenant_id, status="pending")
    return pending[0] if pending else None


@router.get("/plan", response_model=MyPlan, dependencies=MANAGE)
def my_plan(ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Where this business stands: plan, status, usage against limits, what is owed."""
    e = ent.for_tenant(ctx.tenant_id, use_cache=False)
    sub = subscriptions.get(ctx.tenant_id) if ent.mode() == "saas" else None
    used = ent.usage(s)
    enabled = {r[0] for r in s.execute(text("select unit_name from kernel.tenant_unit where status = 'enabled'"))}
    over = sorted(u for u in enabled if e.units is not None and u not in e.units and u in discover())
    owed: dict[str, Decimal] = {}
    for inv in billing.list_invoices(tenant_id=ctx.tenant_id, status="issued", include_drafts=False):
        owed[inv["currency"].strip()] = owed.get(inv["currency"].strip(), Decimal(0)) + inv["balance"]
    coupon = None
    if sub is not None and sub["coupon_id"] is not None:
        with master_session() as m:
            row = m.execute(text("select code from master.coupon where id = :i"), {"i": str(sub["coupon_id"])}).first()
            coupon = row.code if row else None
    pending = None
    if sub is not None and sub["pending_plan_id"] is not None:
        p = plans.plan_by_id(sub["pending_plan_id"])
        pending = {
            "plan_code": p["code"],
            "plan_name": p["name"],
            "interval": sub["pending_interval"],
            "currency": sub["pending_currency"],
        }
    req = _my_request(ctx.tenant_id)
    return {
        "mode": ent.mode(),
        "managed": e.managed,
        "status": e.status,
        "access": e.access,
        "message": e.message,
        "plan_code": e.plan_code,
        "plan_name": e.plan_name,
        "edition": (sub["entitlements"] or {}).get("edition") if sub else None,
        "interval": sub["interval"] if sub else None,
        "currency": sub["currency"].strip() if sub else None,
        "unit_amount": sub["unit_amount"] if sub else None,
        "tax_inclusive": bool(sub and sub["tax_inclusive"]),
        "period_start": sub["period_start"] if sub else None,
        "period_end": e.period_end,
        "trial_end": sub["trial_end"] if sub else None,
        "cancel_at_period_end": bool(sub and sub["cancel_at_period_end"]),
        "is_comp": bool(sub and sub["is_comp"]),
        "coupon_code": coupon,
        "pending_change": pending,
        "usage": {k: {"used": used[k], "limit": e.limit(k)} for k in ("users", "branches", "companies")},
        "units_in_plan": sorted(e.units) if e.units is not None else None,
        "units_over_plan": over,
        "payment_instructions": settings.get("billing.payment_instructions"),
        "request": ({**req, "plan_code": req["plan_code"], "plan_name": req["plan_name"]} if req else None),
        "owed": owed,
        "can_manage_billing": True,
    }


class Banner(BaseModel):
    level: str = Field(description="info, warning or blocked")
    message: str
    status: str
    kind: str = Field(
        default="other",
        description="trial (running), trial_ended, past_due, grace, suspended or other: how the screen words it",
    )
    date: datetime | None = Field(default=None, description="When the trial or period ended, or will end")
    days_left: int | None = Field(default=None, description="Whole days until a running trial ends")


class MyStatus(BaseModel):
    banner: Banner | None = Field(description="Shown to owners only; null when all is well")


@router.get("/status", response_model=MyStatus)
def my_status(ctx: RequestContext = Depends(request_context)) -> object:
    """A light read for the app shell: is there something the owner should see (trial ending, overdue, suspended)?"""
    if not ctx.has_anywhere(PERMISSION):
        return {"banner": None}
    e = ent.for_tenant(ctx.tenant_id)
    if e.access == ent.FULL and e.status != "trialing":
        return {"banner": None}
    level = {ent.FULL: "info", ent.WARNING: "warning"}.get(e.access, "blocked")
    if not e.message:
        return {"banner": None}
    return {"banner": {"level": level, "message": e.message, "status": e.status, **_banner_facts(ctx, e.status)}}


def _banner_facts(ctx: RequestContext, status: str) -> dict[str, Any]:
    """Which story the banner tells, and its date, so the screen can word it (the trial ended on ..., N days left)."""
    sub = subscriptions.get(ctx.tenant_id) if ent.mode() == "saas" else None
    if sub is None:
        return {}
    trial_end, period_end = sub["trial_end"], sub["period_end"]
    if status == "trialing" and trial_end is not None:
        left = max(0, (trial_end - datetime.now(trial_end.tzinfo)).days)
        return {"kind": "trial", "date": trial_end, "days_left": left}
    if status == "suspended":
        return {"kind": "trial_ended" if trial_end is not None else "suspended", "date": trial_end or period_end}
    if status in ("past_due", "grace"):
        return {"kind": status, "date": period_end}
    return {"kind": "other", "date": period_end}


class MyInvoice(BaseModel):
    id: UUID
    number: str | None
    status: str
    kind: str
    currency: str
    total: Decimal
    amount_paid: Decimal
    balance: Decimal
    issue_date: str | None
    due_date: str | None
    period_start: datetime | None
    period_end: datetime | None
    lines: list[dict[str, Any]]
    tax_lines: list[dict[str, Any]]
    tax_total: Decimal
    discount_total: Decimal
    subtotal: Decimal


def _mine(inv: dict[str, Any]) -> dict[str, Any]:
    out = dict(inv)
    out["issue_date"] = inv["issue_date"].isoformat() if inv["issue_date"] else None
    out["due_date"] = inv["due_date"].isoformat() if inv["due_date"] else None
    return out


@router.get("/invoices", response_model=list[MyInvoice], dependencies=MANAGE)
def my_invoices(ctx: RequestContext = Depends(request_context)) -> object:
    """This business's invoices (drafts the vendor is still preparing are not shown)."""
    return [_mine(i) for i in billing.list_invoices(tenant_id=ctx.tenant_id, include_drafts=False)]


@router.get("/invoices/{invoice_id}", response_model=MyInvoice, dependencies=MANAGE)
def my_invoice(invoice_id: UUID, ctx: RequestContext = Depends(request_context)) -> object:
    inv = billing.get_invoice(invoice_id, tenant_id=ctx.tenant_id)
    if inv["status"] == "draft":
        raise NotFound("No such invoice")
    return _mine(inv)


@router.get("/invoices/{invoice_id}/html", response_class=HTMLResponse, dependencies=MANAGE)
def my_invoice_page(invoice_id: UUID, ctx: RequestContext = Depends(request_context)) -> HTMLResponse:
    """The printable invoice (open it and print or save as PDF)."""
    inv = billing.get_invoice(invoice_id, tenant_id=ctx.tenant_id)
    if inv["status"] == "draft":
        raise NotFound("No such invoice")
    return HTMLResponse(billing.invoice_html(inv))


class ChangeRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(max_length=40)
    interval: str | None = Field(default=None, pattern="^(month|year|one_time)$")
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    coupon_code: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=1000)


def _user_name(s: Session, ctx: RequestContext) -> str:
    name = (
        s.execute(text("select full_name from kernel.app_user where id = :i"), {"i": str(ctx.user_id)}).scalar()
        if ctx.user_id
        else None
    )
    return str(name or "A user")


def _require_saas() -> None:
    if ent.mode() != "saas":
        raise Conflict("This copy of Ziira is self-hosted: plans and invoices do not apply. See the licence.")


@router.post("/change-request", response_model=MyRequest, status_code=201, dependencies=MANAGE)
def request_change(
    body: ChangeRequestIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION
) -> object:
    """Ask for another plan. The vendor is told and prepares an invoice; the plan changes when it is paid (or the vendor
    applies it). Nothing is charged by asking."""
    _require_saas()
    by = _user_name(s, ctx)
    out = billing.request_plan_change(
        ctx.tenant_id,
        body.plan_code,
        interval=body.interval,
        currency=body.currency,
        coupon_code=body.coupon_code,
        note=body.note,
        by_name=by,
    )
    audit.record(s, "plan_requested", "kernel.tenant", ctx.tenant_id, {"plan": body.plan_code})
    return out


@router.delete("/change-request/{request_id}", status_code=204, dependencies=MANAGE)
def withdraw_request(request_id: UUID, ctx: RequestContext = Depends(request_context)) -> None:
    _require_saas()
    billing.cancel_request(ctx.tenant_id, request_id)


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


@router.post("/cancel", response_model=MyPlan, dependencies=MANAGE)
def cancel(body: CancelIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Cancel at the end of the period already paid for. Everything keeps working until then, and the data is kept."""
    _require_saas()
    subscriptions.cancel(ctx.tenant_id, at_period_end=True, reason=body.reason, by=_user_name(s, ctx))
    audit.record(s, "subscription_cancel_requested", "kernel.tenant", ctx.tenant_id, {"reason": body.reason})
    return my_plan(ctx, s)


@router.post("/resume", response_model=MyPlan, dependencies=MANAGE)
def resume(ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """Take back a cancellation that has not happened yet."""
    _require_saas()
    subscriptions.uncancel(ctx.tenant_id, by=_user_name(s, ctx))
    return my_plan(ctx, s)


# --------------------------------------------------------------------------- licence (self-hosted copies)
class LicenceInfo(BaseModel):
    mode: str
    instance_id: str
    installed: bool
    required: bool
    status: str
    access: str
    message: str
    customer: str | None = None
    licence_no: str | None = None
    issued_at: str | None = None
    valid_until: str | None = None
    update_until: str | None = None
    days_left: int | None = None
    grace_ends: datetime | None = None
    renewal_due: bool = False
    updates_ended: bool = False
    installed_at: datetime | None = None
    entitlements: dict[str, Any] | None = None
    usage: dict[str, UsageLine] | None = None


@router.get("/licence", response_model=LicenceInfo, dependencies=MANAGE)
def my_licence(ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """On a self-hosted copy: what the installed licence allows, its expiry and the limits against use."""
    info = licences.describe()
    e = ent.for_tenant(ctx.tenant_id, use_cache=False)
    used = ent.usage(s)
    return {**info, "mode": ent.mode(), "usage": {k: {"used": used[k], "limit": e.limit(k)} for k in used}}


class LicenceFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = Field(min_length=10, max_length=20000, description="The text of the licence file")


@router.post("/licence", response_model=LicenceInfo, dependencies=MANAGE)
def install_licence(
    body: LicenceFileIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION
) -> object:
    """Install (or renew with) a licence file from the vendor. It is checked against the vendor's public key."""
    if ent.mode() != "selfhosted":
        raise Conflict("Licences are for self-hosted copies; this business is on a subscription")
    licences.install(body.file, by=_user_name(s, ctx))
    audit.record(s, "licence_installed", "kernel.tenant", ctx.tenant_id, None)
    return my_licence(ctx, s)
