"""The Ziira SDK: the only kernel interface modules and plugins may import.

Modules and plugins must import from `ziira.sdk`, never from `ziira.kernel`
(enforced by import-linter). This keeps units independent of kernel internals.
"""

from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext, get_context, set_context
from ziira.kernel.db import tenant_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed, ZiiraError
from ziira.kernel.events import Event, publish, subscribe

__all__ = [
    "Conflict", "Event", "NotFound", "Session", "ValidationFailed", "ZiiraError",
    "audit_record", "current_context", "db_session", "request_context", "money", "publish", "subscribe",
]

SDK_VERSION = "1.0"


def money(value: Decimal | int | str) -> Decimal:
    """Round a money amount to 2 decimal places, half up. Never use float for money."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def current_context() -> RequestContext:
    """Tenant, user and channel of the current request."""
    return get_context()


def audit_record(session: Session, action: str, entity_type: str, entity_id: UUID | None,
                 changes: dict[str, object] | None = None) -> None:
    """Add an entry to the audit log in the current transaction."""
    audit.record(session, action, entity_type, entity_id, changes)


async def request_context(
    x_tenant_id: UUID | None = Header(default=None, description="Tenant ID (development; replaced by authentication)"),
    x_user_id: UUID | None = Header(default=None),
) -> RequestContext:
    """FastAPI dependency: set who is acting for which tenant.

    Async on purpose: it runs in the request's own task, so the context it sets is
    copied into the threads that run synchronous dependencies and endpoints.
    """
    if not get_settings().dev_tenant_header:
        raise ZiiraError("Tenant header is disabled; authentication is required")
    tenant_id = x_tenant_id or get_settings().dev_default_tenant
    if tenant_id is None:
        raise ValidationFailed("Send the X-Tenant-ID header")
    ctx = RequestContext(tenant_id=tenant_id, user_id=x_user_id, channel="api")
    set_context(ctx)
    return ctx


def db_session(ctx: RequestContext = Depends(request_context)) -> Iterator[Session]:
    """FastAPI dependency: one transaction scoped to the request's tenant."""
    with tenant_session(ctx.tenant_id) as session:
        yield session
