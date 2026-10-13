"""Who may see and change customers and leads. CRM records belong to a company (not a branch), so a grant at any
branch of the company is enough to work with them; the permission says what the person may do."""

from uuid import UUID

from ziira.modules.crm.permissions import CREDIT_APPROVE, CUSTOMERS_MANAGE, CUSTOMERS_VIEW, LEADS_MANAGE
from ziira.sdk import Forbidden, NotFound, current_context

ALL = (CUSTOMERS_VIEW, CUSTOMERS_MANAGE, CREDIT_APPROVE, LEADS_MANAGE)


def holds(permission: str, company_id: UUID) -> bool:
    """True when the person has the permission somewhere in the company (at any level)."""
    companies = current_context().companies_with(permission)
    return companies is None or company_id in companies


def require(permission: str, company_id: UUID) -> None:
    if not holds(permission, company_id):
        raise Forbidden(f"You do not have permission '{permission}' here")


def visible_companies() -> set[UUID] | None:
    """Companies whose CRM records the person may see (None: all)."""
    ctx = current_context()
    found: set[UUID] = set()
    for permission in ALL:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def check_visible(company_id: UUID, what: str = "Record") -> None:
    companies = visible_companies()
    if companies is not None and company_id not in companies:
        raise NotFound(f"{what} not found")
