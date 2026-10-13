"""Use case: create a unit of measure."""

from ziira.modules.products.domain import rules
from ziira.modules.products.permissions import PRODUCTS_MANAGE
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Uom
from ziira.sdk import Conflict, Session, audit_record, current_context


def create_uom(session: Session, code: str, name: str) -> Uom:
    """Create a unit such as PCS or CTN. Codes are unique per tenant (so this needs a tenant-wide grant)."""
    current_context().require(PRODUCTS_MANAGE)
    code = rules.normalise_uom_code(code)
    if products_repo.uom_code_exists(session, code):
        raise Conflict(f"Unit '{code}' already exists")
    ctx = current_context()
    uom = Uom(tenant_id=ctx.tenant_id, created_by=ctx.user_id, code=code, name=name.strip())
    products_repo.add(session, uom)
    audit_record(session, "create", "products.uom", uom.id, {"code": code, "name": uom.name})
    return uom
