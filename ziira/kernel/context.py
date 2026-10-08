"""Request context: which tenant and user the current work is for."""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RequestContext:
    """Who is acting, for which tenant, through which channel."""

    tenant_id: UUID
    user_id: UUID | None = None
    channel: str = "api"


_current: ContextVar[RequestContext | None] = ContextVar("ziira_request_context", default=None)


def set_context(ctx: RequestContext) -> None:
    """Set the context for the current task or request."""
    _current.set(ctx)


def get_context() -> RequestContext:
    """Return the current context, or raise if none is set."""
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("No tenant context is set for this operation")
    return ctx
