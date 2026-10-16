"""The Super Admin's shell and landing page: search, alerts, setup checklist, trends, feeds and the audit trail.

All reads. Same rules as the rest of the console: an operator token and a permission per route (checked by
`tests/test_platform_roles.py`). Search is rate limited; the audit trail needs `platform.operators` and its export is
written to the operator trail."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ziira.kernel import operator_console as console
from ziira.kernel import operators, throttle
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import overview

router = APIRouter(prefix="/api/v1/operator", tags=["Super Admin"])
Op = operators.Operator


class SearchHit(BaseModel):
    kind: Literal["subscriber", "invoice", "plan", "licence", "operator"]
    id: str
    title: str
    subtitle: str
    to: str = Field(description="A path inside the console")


class AlertOut(BaseModel):
    key: str
    severity: Literal["bad", "warn", "info"]
    count: int
    to: str
    needs: str = Field(description="The permission that can act on it")


class AlertsOut(BaseModel):
    total: int
    worst: Literal["bad", "warn", "info"] | None
    items: list[AlertOut]


class SystemOut(BaseModel):
    ready: bool
    problems: int
    queues_known: bool
    failed_jobs: int
    jobs_due: int
    jobs_oldest_due_seconds: int
    outbox_pending: int
    outbox_stuck: int
    backup_reported: bool
    backup_age_hours: float | None
    businesses_behind: int
    businesses_unreadable: int
    mail_configured: bool
    mail_working: bool
    ai_has_provider: bool
    ai_cap_usd: str | None
    ai_spend_usd: str
    ai_cap_reached: bool


class SetupItem(BaseModel):
    key: str
    done: bool
    to: str
    needs: str
    optional: bool
    detail: str | None
    feature: str | None


class RiskOut(BaseModel):
    key: str
    severity: Literal["bad", "warn", "info"]
    to: str
    needs: str


class SetupOut(BaseModel):
    environment: str
    mode: str
    items: list[SetupItem]
    risks: list[RiskOut]


class SeriesLine(BaseModel):
    currency: str | None = Field(description="Null for a count; money is one line per currency")
    points: list[str] = Field(description="One decimal string per bucket")


class OperatorSeriesOut(BaseModel):
    metric: str
    range: str
    buckets: list[date] = Field(description="The first day of each month or week")
    series: list[SeriesLine]


class FeedPayment(BaseModel):
    id: UUID
    paid_on: date
    amount: str
    currency: str
    method: str
    reversed: bool
    invoice_number: str | None
    tenant_code: str | None
    tenant_name: str | None


class FeedSignup(BaseModel):
    code: str
    name: str
    created_at: datetime
    status: str | None
    plan_name: str | None


class FeedOut(BaseModel):
    payments: list[FeedPayment]
    signups: list[FeedSignup]


class AuditLine(BaseModel):
    id: int
    occurred_at: datetime
    operator_name: str
    action: str
    target: str | None
    outcome: str
    reason: str | None
    detail: dict[str, Any] | None


class AuditOut(BaseModel):
    total: int
    items: list[AuditLine]


def _filters(operator: str | None, action: str | None, target: str | None, outcome: str | None,
             date_from: date | None, date_to: date | None) -> dict[str, Any]:
    return {"operator": operator, "action": action, "target": target, "outcome": outcome, "date_from": date_from,
            "date_to": date_to}


@router.get("/search", response_model=list[SearchHit])
def search(request: Request, q: str = Query(max_length=100),
           operator: Op = Depends(require("platform.view"))) -> object:
    """Find subscribers, invoices, plans, licences (and operators, where allowed) by what they are called."""
    counters = throttle.action_counters("operator-search", str(operator.id), client_ip(request), per_subject=300,
                                        per_ip=600)
    throttle.guard(counters)
    throttle.failed(counters)                       # every search counts; the limit is far above a person typing
    return overview.search(q, operator.permissions)


@router.get("/alerts", response_model=AlertsOut)
def alerts(operator: Op = Depends(require("platform.view"))) -> object:
    """What needs an operator now, limited to the areas their role can act in."""
    return overview.alerts(operator.permissions)


@router.get("/dashboard/system", response_model=SystemOut)
def dashboard_system(_: Op = Depends(require("platform.view"))) -> object:
    """The dashboard's health tiles: readiness, queues, backup age, upgrades, mail, AI spend (never secrets)."""
    return overview.system()


@router.get("/dashboard/series", response_model=OperatorSeriesOut)
def dashboard_series(
    metric: Literal["revenue", "signups", "churn"] = Query(default="revenue"),
    range: Literal["12m", "12w"] = Query(default="12m"),  # noqa: A002 - the name the screen sends
    _: Op = Depends(require("platform.view")),
) -> object:
    """Money collected (a line per currency), new businesses or businesses lost, per month or week."""
    return overview.series(metric, range)


@router.get("/dashboard/feed", response_model=FeedOut)
def dashboard_feed(_: Op = Depends(require("platform.view"))) -> object:
    """The newest payments and sign-ups."""
    return overview.feed()


@router.get("/setup", response_model=SetupOut)
def setup(operator: Op = Depends(require("platform.view"))) -> object:
    """First-time set-up from real state (email, registration, AI, payments, plans, website) and risky settings."""
    return overview.setup(operator.permissions)


@router.get("/audit", response_model=AuditOut)
def audit(
    operator_name: str | None = Query(default=None, alias="operator", max_length=100),
    action: str | None = Query(default=None, max_length=100),
    target: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, max_length=10),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Op = Depends(require("platform.operators")),
) -> object:
    """The operator action trail with filters: who, what, which subscriber, outcome, dates."""
    return overview.audit_trail(**_filters(operator_name, action, target, outcome, date_from, date_to), limit=limit,
                                offset=offset)


@router.get("/audit/export")
def audit_export(
    request: Request,
    operator_name: str | None = Query(default=None, alias="operator", max_length=100),
    action: str | None = Query(default=None, max_length=100),
    target: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, max_length=10),
    date_from: date | None = None,
    date_to: date | None = None,
    operator: Op = Depends(require("platform.operators")),
) -> Response:
    """The filtered trail as a CSV file (at most 5000 lines); the download is itself written to the trail."""
    body, count = overview.audit_csv(**_filters(operator_name, action, target, outcome, date_from, date_to))
    console.log_action(operator, "audit.export", target="operator_action_log", detail={"lines": count},
                       ip_address=client_ip(request))
    disposition = 'attachment; filename="audit-trail.csv"'
    return Response(body, media_type="text/csv", headers={"Content-Disposition": disposition})
