"""Use case: give a new business a minimal set of units of measure, so a product can be saved on day one.

The set is data (`data/defaults.toml`). It is added only to a business that has no unit at all, so one that removed or
renamed units on purpose is never given them back. Running it again changes nothing."""

import tomllib
from pathlib import Path

from ziira.modules.products.domain import rules
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Uom
from ziira.sdk import Session, audit_record, current_context

DEFAULTS = Path(__file__).resolve().parent.parent / "data" / "defaults.toml"


def seed_default_uoms(session: Session) -> int:
    """Add the default units when the business has none. Returns how many were added."""
    if products_repo.list_uoms(session):
        return 0
    ctx = current_context()
    added: list[str] = []
    for row in tomllib.loads(DEFAULTS.read_text(encoding="utf-8"))["uom"]:
        code = rules.normalise_uom_code(row["code"])
        products_repo.add(session, Uom(tenant_id=ctx.tenant_id, created_by=ctx.user_id, code=code,
                                       name=rules.check_name(row["name"])))
        added.append(code)
    audit_record(session, "seed_uoms", "products.uom", None, {"codes": added})
    return len(added)
