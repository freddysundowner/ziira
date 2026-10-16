"""Use case: give every branch that has no stock location one store, so stock can be received and sold from day one.

Name and code suffix are data (`data/defaults.toml`); the business edits or renames the store like any location.
A branch that already has a location (active or not) is left alone, so a store removed on purpose never returns."""

import tomllib
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from ziira.modules.inventory.domain import locations as rules
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import Location
from ziira.sdk import Session, audit_record, current_context

DEFAULTS = Path(__file__).resolve().parent.parent / "data" / "defaults.toml"


def seed_default_stores(session: Session, company_id: UUID) -> int:
    """Add the default store to each active branch of the company that has no location. Returns how many."""
    spec = tomllib.loads(DEFAULTS.read_text(encoding="utf-8"))["store"]
    ctx = current_context()
    branches = session.execute(text(
        "select b.id, b.code from kernel.branch b where b.company_id = :c and b.is_active and not exists "
        "(select 1 from inventory.location l where l.branch_id = b.id) order by b.code"), {"c": str(company_id)}).all()
    added = 0
    for branch in branches:
        code = rules.normalise_location_code(f"{branch.code}-{spec['code_suffix']}"[:20])
        if inventory_repo.location_code_exists(session, company_id, code):
            continue
        location = Location(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                            branch_id=branch.id, code=code, name=spec["name"], kind="store")
        inventory_repo.add(session, location)
        audit_record(session, "seed_store", "inventory.location", location.id, {"code": code, "branch_id": branch.id})
        added += 1
    return added
