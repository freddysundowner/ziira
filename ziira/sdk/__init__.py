"""The Ziira SDK: the only kernel interface modules and plugins may import.

Modules and plugins must import from `ziira.sdk`, never from `ziira.kernel`
(enforced by import-linter). This keeps units independent of kernel internals.
"""

from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import approvals, audit, company_settings, numbering, reasons
from ziira.kernel.auth import client_ip, context_from_access_token, context_from_api_key
from ziira.kernel.checks import IntegrityCheck
from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext, get_context, set_context
from ziira.kernel.db import tenant_session
from ziira.kernel.errors import (
    Conflict,
    Forbidden,
    NotFound,
    Unauthorized,
    ValidationFailed,
    ZiiraError,
)
from ziira.kernel.events import Event, publish, subscribe, subscribe_after
from ziira.kernel.extensions import (
    define_extension_point,
    define_validation_hook,
    implementations,
    provides,
    run_validators,
    validate,
)
from ziira.kernel.manifest import SDK_VERSION
from ziira.kernel.numbers import Amount, Quantity, Rate, UnitCost, page_limit, page_offset

__all__ = [
    "SDK_VERSION", "Amount", "Conflict", "Event", "Forbidden", "IntegrityCheck", "NotFound", "Quantity", "Rate",
    "RequestContext", "Session", "Unauthorized", "UnitCost", "ValidationFailed", "ZiiraError", "audit_record",
    "check_company", "check_reason", "company_setting", "current_context", "db_session", "define_extension_point",
    "define_validation_hook", "implementations", "money", "next_document_number", "page_limit", "page_offset",
    "provides", "publish", "request_context", "require_permission", "run_validators", "submit_for_approval",
    "subscribe", "subscribe_after", "validate",
]


def money(value: Decimal | int | str) -> Decimal:
    """Round a money amount to 2 decimal places, half up. Never use float for money."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def current_context() -> RequestContext:
    """Tenant, user, channel and permissions of the current request.

    Check scope inside services with `current_context().require("stock.adjust", company_id=..., branch_id=...)`.
    """
    return get_context()


def audit_record(session: Session, action: str, entity_type: str, entity_id: UUID | None,
                 changes: dict[str, object] | None = None) -> None:
    """Add an entry to the audit log in the current transaction."""
    audit.record(session, action, entity_type, entity_id, changes)


# --------------------------------------------------------------------------- kernel services
def company_setting(session: Session, company_id: UUID, key: str) -> Any:
    """A company policy such as 'negative_stock_allowed' (default if never changed). See kernel/company_settings.py."""
    return company_settings.get_setting(session, company_id, key)


def check_company(session: Session, company_id: UUID, branch_id: UUID | None = None) -> None:
    """Raise ValidationFailed unless the company (and branch, if given) belong to the current tenant.

    Call it before saving any record that names a company or branch: foreign keys are checked
    by PostgreSQL without row-level security, so they would accept another tenant's id.
    """
    if session.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None:
        raise ValidationFailed("Company not found")
    if branch_id is not None and session.execute(
            text("select 1 from kernel.branch where id = :b and company_id = :c"),
            {"b": str(branch_id), "c": str(company_id)}).first() is None:
        raise ValidationFailed("Branch not found in that company")


def next_document_number(session: Session, *, company_id: UUID, branch_id: UUID | None, doc_type: str,
                         prefix: str) -> str:
    """Take the next human document number, e.g. ADJ-THK-000001. See kernel/numbering.py."""
    return numbering.next_document_number(session, company_id=company_id, branch_id=branch_id,
                                          doc_type=doc_type, prefix=prefix)


def check_reason(session: Session, category: str, reason_code_id: UUID | None, note: str | None = None) -> None:
    """Raise ValidationFailed unless a valid, active reason of `category` was given (with a note if needed)."""
    reasons.check_reason(session, category, reason_code_id, note)


def submit_for_approval(session: Session, *, company_id: UUID, doc_type: str, doc_id: UUID,
                        amount: Decimal = Decimal("0")) -> str:
    """Start approval of a document. Returns 'approved' (no approval needed) or 'pending'.

    When pending, subscribe to 'approval.decided' (aggregate_type == doc_type) to post or reject
    the document; event.payload["status"] is 'approved' or 'rejected'.
    """
    return approvals.submit_for_approval(session, company_id=company_id, doc_type=doc_type, doc_id=doc_id,
                                         amount=amount).status


# --------------------------------------------------------------------------- FastAPI dependencies
async def request_context(
    request: Request,
    authorization: str | None = Header(default=None, description="Bearer <access token>"),
    x_api_key: str | None = Header(default=None, description="API key for server-to-server integrations"),
    x_tenant_id: UUID | None = Header(default=None, description="Development only: act as this tenant"),
) -> RequestContext:
    """FastAPI dependency: authenticate the request and set who is acting.

    Order: bearer token, then API key, then (development only) the X-Tenant-ID header,
    which acts with every permission. Async on purpose: it runs in the request's own task,
    so the context it sets is copied into the threads that run sync dependencies and endpoints.
    """
    settings = get_settings()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("Use 'Authorization: Bearer <token>'")
        ctx = await run_in_threadpool(context_from_access_token, token.strip())
    elif x_api_key:
        ctx = await run_in_threadpool(context_from_api_key, x_api_key.strip())
    elif settings.dev_tenant_header and (x_tenant_id or settings.dev_default_tenant):
        tenant_id = x_tenant_id or settings.dev_default_tenant
        assert tenant_id is not None
        ctx = RequestContext(tenant_id=tenant_id, channel="api", all_permissions=True)
    else:
        raise Unauthorized("Sign in first")
    ctx = replace(ctx, ip_address=client_ip(request))
    set_context(ctx)
    return ctx


def db_session(ctx: RequestContext = Depends(request_context)) -> Iterator[Session]:
    """FastAPI dependency: one transaction scoped to the request's tenant."""
    with tenant_session(ctx.tenant_id) as session:
        yield session


def require_permission(permission: str) -> Callable[[RequestContext], RequestContext]:
    """FastAPI dependency: reject the request unless the actor holds `permission` somewhere.

    Endpoints that act on a company or branch must also check the scope in the service:
    `current_context().require(permission, company_id=..., branch_id=...)`.
    """

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not ctx.has_anywhere(permission):
            raise Forbidden(f"You do not have permission '{permission}'")
        return ctx

    return check
