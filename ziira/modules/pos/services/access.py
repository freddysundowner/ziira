"""Who may see which sales and tills (company and branch scope)."""

from uuid import UUID

from ziira.modules.pos.permissions import SALES_SELL, TILL_MANAGE, TILL_REVIEW
from ziira.sdk import current_context


def sale_scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    """(company, branch) pairs whose sales the user may view: where they sell, void, refund or review tills."""
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in (SALES_SELL, TILL_REVIEW, "sales.void", "sales.refund"):
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found.update(scopes)
    return sorted(found, key=str)


def can_review(company_id: UUID, branch_id: UUID) -> bool:
    return current_context().can(TILL_REVIEW, company_id=company_id, branch_id=branch_id)


def can_use_till(company_id: UUID, branch_id: UUID) -> bool:
    ctx = current_context()
    return ctx.can(TILL_MANAGE, company_id=company_id, branch_id=branch_id) or can_review(company_id, branch_id)
