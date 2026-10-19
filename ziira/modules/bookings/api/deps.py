"""Access dependencies shared by the Bookings routers."""

from fastapi import Depends

from ziira.modules.bookings.permissions import (
    ALL,
    BOOKINGS_CHECKOUT,
    BOOKINGS_MANAGE,
    BOOKINGS_REPORTS,
    BOOKINGS_SETUP,
)
from ziira.sdk import Forbidden, RequestContext, request_context


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(*ALL))]
MANAGE = [Depends(any_of(BOOKINGS_MANAGE))]
SETUP = [Depends(any_of(BOOKINGS_SETUP))]
CHECKOUT = [Depends(any_of(BOOKINGS_CHECKOUT))]
REPORTS = [Depends(any_of(BOOKINGS_REPORTS))]
