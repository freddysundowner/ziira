"""Paying the vendor's invoices by oneself (docs/subscription-payments.md): choose a plan, see how an invoice can be
paid, start a payment, follow it, and the providers' notifications.

A business sees only its own invoices and attempts. Like the rest of `/api/v1/billing/` these stay open when the account
is suspended, so an owner whose trial ended can always pay. The notification endpoint is public: it is trusted only
after the provider's signature on the raw body checks out, and even then it only makes us ask the provider."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from ziira.kernel import audit
from ziira.kernel.api.billing_routes import ChangeRequestIn, MyInvoice, _mine, _require_saas, _user_name
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import Unauthorized, ValidationFailed
from ziira.kernel.platform import billing, payments
from ziira.sdk import DB_SESSION, Session, request_context, require_permission

router = APIRouter(prefix="/api/v1/billing", tags=["Plan & billing"])
MANAGE = [Depends(require_permission("billing.manage"))]
POLL_AFTER_SECONDS = 10


class PayerFieldOut(BaseModel):
    name: str
    label: str
    kind: str
    help: str
    required: bool


class PayOption(BaseModel):
    provider: str
    label: str
    flow: str = Field(description="prompt (a prompt on the payer's phone) or redirect (the provider's page)")
    methods: list[str]
    payer_fields: list[PayerFieldOut]
    preferred: bool


class PayOptions(BaseModel):
    invoice_id: UUID
    currency: str
    options: list[PayOption]
    hints: list[str] = Field(description="Plain reasons a payment method was left out (for example the currency)")
    payment_instructions: str = Field(description="How to pay by hand when no option fits")


class PaymentAttemptOut(BaseModel):
    id: UUID
    invoice_id: UUID
    invoice_number: str | None
    provider: str
    provider_label: str
    flow: str
    status: str
    open: bool
    amount: Decimal
    currency: str
    redirect_url: str | None
    payment_reference: str | None
    result_desc: str | None
    payer_phone_last4: str | None
    created_at: datetime
    completed_at: datetime | None
    seconds_open: int


@router.get("/pay/options", response_model=PayOptions, dependencies=MANAGE)
def pay_options(invoice_id: UUID, ctx: RequestContext = Depends(request_context)) -> object:
    """How this invoice can be paid now: the payment methods that serve its currency and the business's country."""
    _require_saas()
    invoice = billing.get_invoice(invoice_id, tenant_id=ctx.tenant_id)
    return payments.options_for(ctx.tenant_id, invoice)


class SubscribeOut(BaseModel):
    waiting_for_vendor: bool = Field(description="True: nothing is due now, so the vendor applies the change")
    invoice: MyInvoice | None


@router.post("/subscribe", response_model=SubscribeOut, status_code=201, dependencies=MANAGE)
def subscribe(
    body: ChangeRequestIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION
) -> object:
    """Choose a plan and interval (and a coupon): the invoice is made at once, ready to pay."""
    _require_saas()
    out = payments.subscribe(
        ctx.tenant_id, body.plan_code, interval=body.interval, currency=body.currency, coupon_code=body.coupon_code,
        by_name=_user_name(s, ctx),
    )
    audit.record(s, "plan_chosen", "kernel.tenant", ctx.tenant_id, {"plan": body.plan_code})
    invoice = _mine(out["invoice"]) if out["invoice"] else None
    return {"waiting_for_vendor": out["waiting_for_vendor"], "invoice": invoice}


class StartPaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_id: UUID
    provider: str = Field(max_length=40)
    payer: dict[str, str] = Field(default_factory=dict, description="What the method asks for: a phone, an email")


def _owner_email(s: Session, ctx: RequestContext) -> str | None:
    if ctx.user_id is None:
        return None
    value = s.execute(text("select email from kernel.app_user where id = :i"), {"i": str(ctx.user_id)}).scalar()
    return str(value) if value else None


@router.post("/payments", response_model=PaymentAttemptOut, status_code=201, dependencies=MANAGE)
def start_payment(
    body: StartPaymentIn, ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION
) -> object:
    """Start paying an invoice. A second call while an attempt is open returns that attempt: nobody is charged twice."""
    _require_saas()
    if any(len(k) > 20 or len(v) > 300 for k, v in body.payer.items()):
        raise ValidationFailed("That is too long")
    out = payments.start_payment(
        ctx.tenant_id, body.invoice_id, body.provider, body.payer, by=_user_name(s, ctx),
        contact_email=_owner_email(s, ctx),
    )
    audit.record(s, "payment_started", "kernel.tenant", ctx.tenant_id, {"provider": body.provider})
    return out


def _fresh(attempt_id: UUID, tenant_id: UUID, *, after: int) -> dict[str, Any]:
    attempt = payments.get_attempt(attempt_id, tenant_id=tenant_id)
    if attempt["open"]:
        last = attempt["last_checked_at"]
        if last is None or (datetime.now(UTC) - last).total_seconds() >= after:
            attempt = payments.settle(attempt_id, source="status_poll")
    return attempt


@router.get("/payments/{attempt_id}", response_model=PaymentAttemptOut, dependencies=MANAGE)
def payment_status(attempt_id: UUID, ctx: RequestContext = Depends(request_context)) -> object:
    """Where a payment stands. While it is open, the provider is asked at most every few seconds."""
    return _fresh(attempt_id, ctx.tenant_id, after=POLL_AFTER_SECONDS)


@router.post("/payments/{attempt_id}/check", response_model=PaymentAttemptOut, dependencies=MANAGE)
def check_payment(attempt_id: UUID, ctx: RequestContext = Depends(request_context)) -> object:
    """"Check again": ask the provider now."""
    return _fresh(attempt_id, ctx.tenant_id, after=2)


@router.get("/payments", response_model=list[PaymentAttemptOut], dependencies=MANAGE)
def my_payments(
    invoice_id: UUID | None = None, limit: int = Query(default=50, ge=1, le=200),
    ctx: RequestContext = Depends(request_context),
) -> object:
    return payments.list_attempts(tenant_id=ctx.tenant_id, invoice_id=invoice_id, limit=limit)


class ReceivedOut(BaseModel):
    handled: int


@router.post("/webhooks/{provider}", response_model=ReceivedOut)
async def provider_webhook(provider: str, request: Request) -> object:
    """A payment provider's notification (public). The signature on the raw body is checked first; the notification then
    only makes us ask the provider. Not genuine: 401. Our own failure: 500, so the provider tries again."""
    body = await request.body()
    headers = dict(request.headers)
    try:
        return await run_in_threadpool(payments.handle_webhook, provider, headers, body)
    except ValidationFailed:
        raise Unauthorized("The notification is not genuine") from None
