"""Who may see which companies' books."""

from uuid import UUID

from ziira.modules.finance.permissions import (
    ACCOUNTS_MANAGE,
    JOURNAL_APPROVE,
    JOURNAL_POST_MANUAL,
    PERIOD_CLOSE,
    REPORTS_VIEW,
)
from ziira.sdk import NotFound, current_context

READERS = (REPORTS_VIEW, ACCOUNTS_MANAGE, JOURNAL_POST_MANUAL, JOURNAL_APPROVE, PERIOD_CLOSE)


def visible_companies(*permissions: str) -> set[UUID] | None:
    """Companies where the user holds any of the permissions (at any level); None means every company."""
    ctx = current_context()
    found: set[UUID] = set()
    for permission in permissions or READERS:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def require_visible(company_id: UUID) -> None:
    """Raise NotFound unless the user may see this company's books at all."""
    companies = visible_companies()
    if companies is not None and company_id not in companies:
        raise NotFound("Company not found")
