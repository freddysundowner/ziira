"""Who may see which time records (company and branch scope), and small shared helpers."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.timebilling.permissions import ALL
from ziira.sdk import Session, ValidationFailed, current_context


def user_id() -> UUID:
    uid = current_context().user_id
    if uid is None:
        raise ValidationFailed("This needs a signed-in person")
    return uid


def unit_enabled(session: Session, unit: str) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def can_see_company(company_id: UUID) -> bool:
    """True when the person holds any time permission anywhere in the company."""
    ctx = current_context()
    for permission in ALL:
        companies = ctx.companies_with(permission)
        if companies is None or company_id in companies:
            return True
    return False


def scopes_for(*permissions: str) -> list[tuple[UUID | None, UUID | None]] | None:
    """(company, branch) pairs where the person holds at least one of the permissions; None means everywhere."""
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in permissions:
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found.update(scopes)
    return sorted(found, key=str)


def can_any(company_id: UUID, branch_id: UUID | None, *permissions: str) -> bool:
    ctx = current_context()
    return any(ctx.can(p, company_id=company_id, branch_id=branch_id) for p in permissions)
