"""Super Admin: the payment methods businesses can pay with (settings, secrets, test) and the payment attempts.

Same rules as the rest of the operator console: an operator token, a permission per route, a fresh second-factor code
for every change or action, and a line in the operator trail. Secrets are write-only: never returned, logged or put in
the trail (the trail keeps only which fields changed)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operators
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import admin, payments

router = APIRouter(prefix="/api/v1/operator", tags=["Super Admin"])
Op = operators.Operator


class GatewayFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool
    help: str
    value: str | None = Field(description="Null for a secret: those are never shown")
    is_set: bool


class GatewayOut(BaseModel):
    name: str
    title: str
    pay_label: str
    description: str
    flow: str
    methods: list[str]
    currencies: list[str]
    countries: list[str]
    development_only: bool
    fields: list[GatewayFieldOut]
    enabled: bool
    configured: bool
    default_for: list[str]
    webhook_url: str | None
    webhook_problem: str | None
    updated_at: datetime | None
    updated_by: str | None


class GatewayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    config: dict[str, str] | None = None
    secrets: dict[str, str] | None = Field(default=None, description="Write-only; an empty value keeps the old one")
    clear_secrets: list[str] | None = None
    default_for: list[str] | None = Field(default=None, max_length=30)


class GatewayTestOut(BaseModel):
    ok: bool
    message: str


class OperatorAttempt(BaseModel):
    id: UUID
    reference: str
    invoice_id: UUID
    invoice_number: str | None
    tenant_id: UUID
    tenant_code: str
    tenant_name: str
    provider: str
    provider_label: str
    status: str
    amount: Decimal
    currency: str
    payer_phone_last4: str | None
    provider_transaction_id: str | None
    checkout_request_id: str | None
    payment_reference: str | None
    result_code: str | None
    result_desc: str | None
    created_by: str | None
    completed_by: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    last_checked_at: datetime | None


class TimelineLine(BaseModel):
    occurred_at: datetime
    kind: str
    detail: dict[str, Any] | None


class OperatorAttemptDetail(OperatorAttempt):
    timeline: list[TimelineLine]


class AttemptReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


def _ip(request: Request) -> str | None:
    return client_ip(request)


@router.get("/payment-gateways", response_model=list[GatewayOut])
def list_gateways(_: Op = Depends(require("platform.view"))) -> object:
    """Every installed payment method with its settings. Secrets are only reported as set or not set."""
    return payments.overview()


@router.put("/payment-gateways/{name}", response_model=GatewayOut)
def save_gateway(
    name: str, body: GatewayIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    fields = sorted({*(body.config or {}), *(body.secrets or {}), *(body.clear_secrets or [])})
    return admin.act(
        operator, "payment_gateway.save", name, _ip(request),
        lambda: payments.save_gateway(
            name, enabled=body.enabled, config=body.config, secrets=body.secrets,
            clear_secrets=body.clear_secrets, default_for=body.default_for, by=operator.name,
        ),
        summary=lambda r: {"gateway": name, "fields": fields, "enabled": r["enabled"]},
    )


@router.post("/payment-gateways/{name}/test", response_model=GatewayTestOut)
def test_gateway(name: str, request: Request, operator: Op = Depends(require("platform.billing"))) -> object:
    """The lightest safe call to the provider: does it accept the keys? Moves no money."""
    return admin.act(
        operator, "payment_gateway.test", name, _ip(request), lambda: payments.test_gateway(name),
        summary=lambda r: {"gateway": name, "ok": r["ok"]},
    )


@router.get("/payment-attempts", response_model=list[OperatorAttempt])
def list_attempts(
    status: str | None = Query(default=None, max_length=12),
    tenant: UUID | None = None,
    invoice: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Op = Depends(require("platform.view")),
) -> object:
    return payments.list_attempts(
        tenant_id=tenant, invoice_id=invoice, status=status, since=since, until=until, limit=limit, offset=offset
    )


def _detail(attempt_id: UUID) -> dict[str, Any]:
    return {**payments.get_attempt(attempt_id), "timeline": payments.timeline(attempt_id)}


@router.get("/payment-attempts/{attempt_id}", response_model=OperatorAttemptDetail)
def get_attempt(attempt_id: UUID, _: Op = Depends(require("platform.view"))) -> object:
    return _detail(attempt_id)


@router.post("/payment-attempts/{attempt_id}/recheck", response_model=OperatorAttemptDetail)
def recheck(attempt_id: UUID, request: Request, operator: Op = Depends(require("platform.billing"))) -> object:
    """Ask the provider now what became of this payment (it is credited if confirmed)."""
    admin.act(
        operator, "payment_attempt.recheck", str(attempt_id), _ip(request),
        lambda: payments.recheck(attempt_id, by=f"operator:{operator.name}"),
        summary=lambda r: {"status": r["status"]},
    )
    return _detail(attempt_id)


@router.post("/payment-attempts/{attempt_id}/mark-paid", response_model=OperatorAttemptDetail)
def mark_paid(
    attempt_id: UUID, body: AttemptReasonIn, request: Request, operator: Op = Depends(require("platform.billing"))
) -> object:
    """For a stuck case: confirm by hand that this was paid (with the reason). Credits the invoice."""
    admin.act(
        operator, "payment_attempt.mark_paid", str(attempt_id), _ip(request),
        lambda: payments.mark_paid_manually(attempt_id, body.reason, by=operator.name),
        summary=lambda r: {"status": r["status"]}, reason=body.reason,
    )
    return _detail(attempt_id)


@router.get("/invoices/{invoice_id}/payment-attempts", response_model=list[OperatorAttempt])
def invoice_attempts(invoice_id: UUID, _: Op = Depends(require("platform.view"))) -> object:
    return payments.list_attempts(invoice_id=invoice_id)
