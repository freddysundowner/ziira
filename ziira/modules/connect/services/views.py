"""Turning stored connections into what the API shows. Never includes a secret."""

from typing import Any

from sqlalchemy.engine import Row

from ziira.modules.connect.api.schemas import ConnectionDetailOut, ConnectionOut, EntityStatusOut
from ziira.modules.connect.public import ENTITIES
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.services import connections, connectors
from ziira.sdk import Session


def _connector_facts(session: Session, kind: str) -> dict[str, Any]:
    try:
        described = connectors.describe(connectors.connector_for(session, kind))
    except Exception:  # noqa: BLE001 - the connector's unit may be off: still show the connection
        return {"title": kind, "group": "", "entities": (), "freshness": "daily", "needs_oauth": False}
    return {"title": described.title, "group": described.group, "entities": described.entities,
            "freshness": described.freshness, "needs_oauth": described.needs_oauth}


def connection_out(session: Session, row: Row[Any]) -> ConnectionOut:
    facts = _connector_facts(session, row.kind)
    cursors = repo.cursors(session, row.id)
    entities = [EntityStatusOut(entity=e, complete_at=cursors[e].updated_at if e in cursors else None,
                                data_through=cursors[e].data_through if e in cursors else None)
                for e in ENTITIES if e in facts["entities"]]
    return ConnectionOut(
        id=row.id, company_id=row.company_id, kind=row.kind, kind_title=facts["title"], group=facts["group"],
        name=row.name, status=row.status, config=connections.public_config(row),
        secrets_set=connections.secrets_set(row), freshness=facts["freshness"], entities=entities,
        auto_create_branches=row.auto_create_branches, sync_every_minutes=row.sync_every_minutes,
        last_sync_at=row.last_sync_at, last_success_at=row.last_success_at, next_sync_at=row.next_sync_at,
        failures=row.failures, last_error=row.last_error, needs_oauth=facts["needs_oauth"], created_at=row.created_at)


def connection_detail(session: Session, row: Row[Any]) -> ConnectionDetailOut:
    base = connection_out(session, row)
    unmapped = sum(1 for m in repo.list_branch_map(session, row.id) if m.branch_id is None and not m.ignored)
    return ConnectionDetailOut(**base.model_dump(), counts=repo.entity_counts(session, row.id),
        unmapped_branches=unmapped)
