"""Dependencies and helpers shared by the Memberships route files."""

from collections.abc import Callable
from typing import Any

from fastapi import Depends

from ziira.modules.memberships.permissions import ALL, CHECKIN, CREDITS, MANAGE, PLANS, RECURRING, REPORTS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common
from ziira.sdk import Forbidden, RequestContext, Session, request_context


def any_of(*permissions: str) -> Callable[..., RequestContext]:
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


SEE = [Depends(any_of(*ALL))]
CATALOGUE = [Depends(any_of(PLANS))]
SERVE = [Depends(any_of(MANAGE))]
ADJUST = [Depends(any_of(CREDITS))]
RECUR = [Depends(any_of(RECURRING))]
REVIEW = [Depends(any_of(RECURRING, MANAGE))]
DESK = [Depends(any_of(CHECKIN))]
REPORT = [Depends(any_of(REPORTS, MANAGE, PLANS))]


def named(session: Session, rows: list[repo.Row]) -> list[repo.Row]:
    """Rows with their customer's name and code added (read through the customers unit)."""
    found = common.customer_names(session, {r["customer_id"] for r in rows})
    return [{**r, "customer_name": found[r["customer_id"]].name if r["customer_id"] in found else None,
             "customer_code": found[r["customer_id"]].code if r["customer_id"] in found else None} for r in rows]


def one_named(session: Session, row: repo.Row) -> repo.Row:
    return named(session, [row])[0]


def plain(value: Any) -> Any:
    return value
