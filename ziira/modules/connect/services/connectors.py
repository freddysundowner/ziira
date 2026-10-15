"""Finding the connector for a connection, and describing the catalogue of kinds a business can connect."""

from dataclasses import dataclass
from typing import Any

from ziira.modules.connect.public import CONNECTOR, ENTITIES, ConfigField, Connector
from ziira.sdk import NotFound, Session, implementations

GROUPS = {"api": "Your ERP", "file": "Statements and exports"}


def is_file_kind(connector: Connector) -> bool:
    return connector.freshness == "on_upload"


@dataclass(frozen=True)
class Kind:
    kind: str
    title: str
    description: str
    group: str
    entities: tuple[str, ...]
    config_fields: tuple[ConfigField, ...]
    needs_oauth: bool
    freshness: str
    how_to: str
    file_fields: tuple[dict[str, Any], ...] = ()


def all_connectors(session: Session) -> list[Connector]:
    """The connectors of this business: every enabled unit's, in a stable order (title)."""
    return sorted(implementations(session, CONNECTOR), key=lambda c: (is_file_kind(c), c.title))


def connector_for(session: Session, kind: str) -> Connector:
    for connector in implementations(session, CONNECTOR):
        if connector.kind == kind:
            found: Connector = connector
            return found
    raise NotFound(f"There is no connector of kind '{kind}'")


def describe(connector: Connector) -> Kind:
    file_fields = tuple(getattr(connector, "describe_fields", lambda: ())())
    return Kind(kind=connector.kind, title=connector.title, description=connector.description,
                group=GROUPS["file" if is_file_kind(connector) else "api"],
                entities=tuple(e for e in connector.entities if e in ENTITIES), config_fields=connector.config_fields,
                needs_oauth=connector.needs_oauth, freshness=connector.freshness,
                how_to=str(getattr(connector, "how_to", "") or ""), file_fields=file_fields)


def catalogue(session: Session) -> list[Kind]:
    return [describe(c) for c in all_connectors(session)]
