"""Who may see which bookings records (company and branch scope)."""

from uuid import UUID

from ziira.modules.bookings.permissions import ALL
from ziira.sdk import current_context


def view_scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    """(company, branch) pairs the user may see: wherever they hold any bookings permission. None means everywhere."""
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in ALL:
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found.update(scopes)
    return sorted(found, key=str)


def can_view(company_id: UUID, branch_id: UUID | None) -> bool:
    ctx = current_context()
    return any(ctx.can(p, company_id=company_id, branch_id=branch_id) for p in ALL)


def view_companies() -> set[UUID] | None:
    ctx = current_context()
    found: set[UUID] = set()
    for permission in ALL:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def can_see_company(company_id: UUID) -> bool:
    companies = view_companies()
    return companies is None or company_id in companies
