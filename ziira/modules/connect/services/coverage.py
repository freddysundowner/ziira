"""What Intelligence can see: which entities are supplied by the connected systems, and so which checks can run.

An entity counts as supplied by a connection once it has been read to the end at least once (a cursor row exists) and
the connection is not disconnected. A standalone check that needs an entity nobody supplies stays silent, and the
Coverage panel says what to connect to switch it on.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import ENTITIES
from ziira.modules.connect.services import connectors
from ziira.sdk import Session

AREAS = ("cash_sales", "customers", "suppliers", "stock", "books", "people", "controls")


@dataclass
class Supply:
    """The connections that supply each entity for one company, and how far their data is complete."""

    connections: dict[str, list[UUID]] = field(default_factory=dict)
    through: dict[str, datetime | None] = field(default_factory=dict)      # earliest 'complete up to' among them

    def has(self, *entities: str) -> bool:
        return all(e in self.connections for e in entities)

    def ids(self, entity: str) -> list[str]:
        return [str(c) for c in self.connections.get(entity, [])]

    def complete_until(self, entity: str) -> datetime | None:
        """Data of this entity is complete up to this moment (None: no limit is known)."""
        return self.through.get(entity)


def supplied(session: Session, company_id: UUID) -> Supply:
    supply = Supply()
    rows = session.execute(text(
        "select c.connection_id, c.entity, c.data_through from connect.cursor c "
        "join connect.connection k on k.id = c.connection_id where k.company_id = :c and k.status <> 'disconnected' "
        "order by c.entity, c.connection_id"), {"c": str(company_id)})
    moments: dict[str, list[datetime | None]] = {}
    for r in rows:
        supply.connections.setdefault(r.entity, []).append(r.connection_id)
        moments.setdefault(r.entity, []).append(r.data_through)
    for entity, values in moments.items():
        known = [v for v in values if v is not None]
        supply.through[entity] = None if len(known) < len(values) else min(known)
    return supply


def coverage(session: Session, company_id: UUID) -> dict[str, object]:
    """The matrix for the Coverage panel: per area, each standalone check and whether it can run today."""
    from ziira.modules.connect.standalone_checks import CHECKS

    supply = supplied(session, company_id)
    kinds = connectors.catalogue(session)
    suppliers_of: dict[str, list[str]] = {}
    for kind in kinds:
        for entity in kind.entities:
            suppliers_of.setdefault(entity, []).append(kind.kind)
    areas: dict[str, list[dict[str, object]]] = {a: [] for a in AREAS}
    for check in CHECKS:
        missing = [e for e in check.requires if not supply.has(e)]
        areas.setdefault(check.area, []).append({
            "code": check.code, "title": check.title, "active": not missing, "needs": missing,
            "connect": sorted({k for e in missing for k in suppliers_of.get(e, [])})})
    return {
        "connected": {e: len(supply.connections[e]) for e in ENTITIES if e in supply.connections},
        "areas": [{"area": a, "active": sum(1 for i in items if i["active"]), "total": len(items), "checks": items}
                  for a, items in areas.items() if items],
        "as_of": datetime.now(UTC)}
