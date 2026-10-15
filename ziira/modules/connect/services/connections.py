"""Connecting, changing, pausing and disconnecting systems. Secrets go to the encrypted credential store and are never
returned or logged; the connection row keeps only non-secret settings and the credential's id."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.connect.permissions import CONNECT_MANAGE, CONNECT_VIEW
from ziira.modules.connect.public import ConfigField, ConnectionCheck, Connector
from ziira.modules.connect.repository import connect_repo as repo
from ziira.modules.connect.services import connectors
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    read_credential,
    store_credential,
)

RESERVED = ("_secrets", "file")          # config keys the business cannot set directly
LIVE_MINUTES, DAILY_MINUTES = 15, 1440
NAME_MAX = 80


def default_minutes(connector: Connector) -> int:
    return LIVE_MINUTES if connector.freshness == "live" else DAILY_MINUTES


def split_fields(connector: Connector, supplied: dict[str, Any], *, creating: bool) -> tuple[dict[str, Any], dict[str,
    Any]]:
    """(settings, secrets) from what the business typed. Unknown names are refused; on creation every required field
    must be there; on a change a blank secret means 'keep the one I have'."""
    known: dict[str, ConfigField] = {f.name: f for f in connector.config_fields}
    unknown = sorted(set(supplied) - set(known))
    if unknown:
        raise ValidationFailed(f"Unknown setting(s) for {connector.title}: {', '.join(unknown)}")
    config: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    for name, field_ in known.items():
        value = supplied.get(name)
        blank = value is None or (isinstance(value, str) and not value.strip())
        if blank:
            if creating and field_.required:
                raise ValidationFailed(f"{field_.label} is required")
            continue
        (secrets if field_.secret else config)[name] = value.strip() if isinstance(value, str) else value
    return config, secrets


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not 2 <= len(cleaned) <= NAME_MAX:
        raise ValidationFailed(f"A name is 2 to {NAME_MAX} characters")
    return cleaned


def public_config(row: Row[Any]) -> dict[str, Any]:
    """The settings that may be shown: the business's own non-secret entries, without internal keys."""
    return {k: v for k, v in dict(row.config).items() if k not in RESERVED}


def secrets_set(row: Row[Any]) -> list[str]:
    """Names of the secret fields that have a value (never the values)."""
    return sorted(dict(row.config).get("_secrets", []))


def get(session: Session, connection_id: UUID, *, manage: bool = False) -> Row[Any]:
    """A connection the caller may see (or change, with `manage`)."""
    row = repo.get_connection(session, connection_id)
    if row is None:
        raise NotFound("Connection not found")
    current_context().require(CONNECT_MANAGE if manage else CONNECT_VIEW, company_id=row.company_id)
    return row


def create(session: Session, *, company_id: UUID, kind: str, name: str, fields: dict[str, Any],
           auto_create_branches: bool, sync_every_minutes: int | None) -> UUID:
    ctx = current_context()
    ctx.require(CONNECT_MANAGE, company_id=company_id)
    check_company(session, company_id)
    connector = connectors.connector_for(session, kind)
    clean = _clean_name(name)
    if any(r.company_id == company_id and r.name.lower() == clean.lower() for r in repo.list_connections(session,
        {company_id})):
        raise Conflict(f"This company already has a connection called '{clean}'")
    config, secrets = split_fields(connector, fields, creating=not connector.needs_oauth)
    minutes = sync_every_minutes or default_minutes(connector)
    if minutes < LIVE_MINUTES:
        raise ValidationFailed(f"A system is read at most every {LIVE_MINUTES} minutes")
    credential_id: UUID | None = None
    if secrets:
        credential_id = store_credential(session, company_id=company_id, provider=f"connect_{connector.kind}"[:40],
                                         label=f"{connector.title}: {clean}"[:120], secret=secrets)
        config["_secrets"] = sorted(secrets)
    connection_id = repo.add_connection(session, company_id=company_id, kind=kind, name=clean, config=config,
                                        credential_id=credential_id, auto_create_branches=auto_create_branches,
                                        sync_every_minutes=minutes, created_by=ctx.user_id)
    if connectors.is_file_kind(connector):
        repo.update_connection(session, connection_id, {"next_sync_at": None})
    audit_record(session, "create", "connect.connection", connection_id,
                 {"kind": kind, "name": clean, "company_id": str(company_id)})
    return connection_id


def update(session: Session, connection_id: UUID, *, name: str | None, fields: dict[str, Any] | None,
           auto_create_branches: bool | None, sync_every_minutes: int | None) -> None:
    row = get(session, connection_id, manage=True)
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected: connect again to change it")
    connector = connectors.connector_for(session, row.kind)
    changes: dict[str, Any] = {}
    audited: dict[str, Any] = {}
    if name is not None:
        changes["name"] = _clean_name(name)
        audited["name"] = changes["name"]
    if auto_create_branches is not None:
        changes["auto_create_branches"] = auto_create_branches
        audited["auto_create_branches"] = auto_create_branches
    if sync_every_minutes is not None:
        if sync_every_minutes < LIVE_MINUTES:
            raise ValidationFailed(f"A system is read at most every {LIVE_MINUTES} minutes")
        changes["sync_every_minutes"] = sync_every_minutes
        audited["sync_every_minutes"] = sync_every_minutes
    if fields:
        config, secrets = split_fields(connector, fields, creating=False)
        new_config = {**dict(row.config), **config}
        if secrets:
            new_config["_secrets"] = sorted({*dict(row.config).get("_secrets", []), *secrets})
            changes["credential_id"] = store_secrets(session, row, connector, secrets)
        changes["config"] = new_config
        audited["settings_changed"] = sorted([*config, *secrets])      # names only, never values
    if row.status == "error" and fields:
        changes["status"] = "active"
        changes["next_sync_at"] = None if connectors.is_file_kind(connector) else datetime.now(UTC)
    repo.update_connection(session, connection_id, changes)
    if audited:
        audit_record(session, "update", "connect.connection", connection_id, audited)


def store_secrets(session: Session, row: Row[Any], connector: Connector, secrets: dict[str, Any]) -> UUID:
    """Save secrets for a connection (merged with the ones it has). Also used by the OAuth endpoints to keep tokens."""
    if row.credential_id is not None:
        merged = {**read_credential(session, row.credential_id), **secrets}
        return store_credential(session, company_id=row.company_id, provider=f"connect_{connector.kind}"[:40],
                                label=f"{connector.title}: {row.name}"[:120], secret=merged, replace=row.credential_id)
    return store_credential(session, company_id=row.company_id, provider=f"connect_{connector.kind}"[:40],
                            label=f"{connector.title}: {row.name}"[:120], secret=secrets)


def load_secrets(session: Session, row: Row[Any]) -> dict[str, Any]:
    if row.credential_id is None:
        return {}
    try:
        return read_credential(session, row.credential_id)
    except NotFound:
        return {}


def test(session: Session, connection_id: UUID) -> ConnectionCheck:
    """Try the credentials with the lightest read the system offers. Never changes anything in the other system."""
    row = get(session, connection_id, manage=True)
    connector = connectors.connector_for(session, row.kind)
    secrets = load_secrets(session, row)
    try:
        result = connector.check(dict(public_config(row)), secrets)
        if connector.updated_secrets is not None:           # the vendor rotated a secret while we checked: keep it
            store_secrets(session, row, connector, connector.updated_secrets)
    except Exception as error:  # noqa: BLE001 - a connector's check must not raise, but if it does the owner gets words
        return ConnectionCheck(ok=False, message=f"The check could not be completed ({type(error).__name__}).")
    return ConnectionCheck(ok=result.ok, message=result.message[:500], details=dict(result.details))


def pause(session: Session, connection_id: UUID) -> None:
    row = get(session, connection_id, manage=True)
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected")
    repo.update_connection(session, connection_id, {"status": "paused", "next_sync_at": None})
    audit_record(session, "pause", "connect.connection", connection_id, {"name": row.name})


def resume(session: Session, connection_id: UUID) -> None:
    row = get(session, connection_id, manage=True)
    if row.status == "disconnected":
        raise ValidationFailed("This connection is disconnected: connect again")
    connector = connectors.connector_for(session, row.kind)
    repo.update_connection(session, connection_id, {
        "status": "active", "failures": 0,
        "next_sync_at": None if connectors.is_file_kind(connector) else datetime.now(UTC)})
    audit_record(session, "resume", "connect.connection", connection_id, {"name": row.name})


def disconnect(session: Session, connection_id: UUID, *, delete_data: bool) -> dict[str, int]:
    """Stop reading the system and forget its key. With `delete_data` everything read from it is deleted too;
    otherwise it stays for history but takes no further part in the checks."""
    row = get(session, connection_id, manage=True)
    if row.status == "disconnected" and not delete_data:
        return {}
    if row.credential_id is not None:                     # overwrite the key: the secret is gone, not just unused
        connector = connectors.connector_for(session, row.kind)
        store_credential(session, company_id=row.company_id, provider=f"connect_{connector.kind}"[:40],
                         label=f"{connector.title}: {row.name} (disconnected)"[:120], secret={"revoked": True},
                         replace=row.credential_id)
    removed = repo.delete_source_data(session, connection_id) if delete_data else {}
    config = {k: v for k, v in dict(row.config).items() if k != "_secrets"}
    repo.update_connection(session, connection_id, {
        "status": "disconnected", "disconnected_at": datetime.now(UTC), "next_sync_at": None, "config": config})
    audit_record(session, "disconnect", "connect.connection", connection_id,
                 {"name": row.name, "deleted_data": delete_data, "removed": removed})
    return removed
