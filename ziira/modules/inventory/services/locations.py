"""Use cases: create and list stock locations."""

from uuid import UUID

from ziira.modules.inventory.domain import locations as rules
from ziira.modules.inventory.permissions import LOCATIONS_MANAGE, STOCK_VIEW
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import Location
from ziira.sdk import Conflict, Session, ValidationFailed, audit_record, check_company, current_context


def create_location(session: Session, *, company_id: UUID, code: str, name: str, kind: str = "store",
                    branch_id: UUID | None = None) -> Location:
    """Create a place stock is held: a shop floor or warehouse of a branch, or a company-level
    in-transit or virtual location. Needs 'locations.manage' for the branch (or the company)."""
    current_context().require(LOCATIONS_MANAGE, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    rules.check_location(kind, branch_id is not None)
    code = rules.normalise_location_code(code)
    if not name.strip():
        raise ValidationFailed("Name is required")
    if inventory_repo.location_code_exists(session, company_id, code):
        raise Conflict(f"Location '{code}' already exists in this company")
    ctx = current_context()
    location = Location(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
                        code=code, name=name.strip(), kind=kind)
    inventory_repo.add(session, location)
    audit_record(session, "create", "inventory.location", location.id,
                 {"code": code, "name": location.name, "kind": kind, "branch_id": branch_id})
    return location


def list_locations(session: Session, company_id: UUID | None = None, branch_id: UUID | None = None,
                   kind: str | None = None) -> list[Location]:
    """Locations in the companies and branches the user may see stock for."""
    scopes = current_context().scopes_with(STOCK_VIEW)
    return inventory_repo.list_locations(session, scopes, company_id, branch_id, kind)
