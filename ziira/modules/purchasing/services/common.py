"""Small helpers shared by the purchasing services."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.purchasing.repository.models import Supplier
from ziira.modules.purchasing.services import access
from ziira.sdk import NotFound, Session, ValidationFailed, current_context


def unit_enabled(session: Session, unit: str) -> bool:
    """True when the unit is enabled for this business (optional units may be missing)."""
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def active_supplier(supplier: Supplier | None, company_id: UUID | None = None) -> Supplier:
    """A supplier that can be ordered from or billed (not on hold or inactive)."""
    if supplier is None or (company_id is not None and supplier.company_id != company_id) \
            or not access.can_see_company(supplier.company_id):
        raise ValidationFailed("Supplier not found in this company")
    if supplier.status != "active":
        raise ValidationFailed(f"{supplier.name} is {supplier.status.replace('_', ' ')}")
    return supplier


def require_view(company_id: UUID, branch_id: UUID | None) -> None:
    if not access.can_view(company_id, branch_id):
        raise NotFound("Not found")


def user_id() -> UUID:
    uid = current_context().user_id
    if uid is None:
        raise ValidationFailed("This needs a signed-in person")
    return uid

