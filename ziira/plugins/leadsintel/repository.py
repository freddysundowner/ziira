"""This plugin's tables (schema plg_leadsintel) and the credential rows it manages."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.sdk import Session


def credential(session: Session, company_id: UUID, channel: str) -> Row[Any] | None:
    """The business's active Lead Intel credential for a channel, or None. Holds no secret."""
    return session.execute(text(
        "select id, config from kernel.integration_credential where company_id = :c and provider = :ch "
        "and status = 'active' and config->>'provider' = 'leadsintel' order by created_at desc limit 1"),
        {"c": str(company_id), "ch": channel}).first()


def insert_connection(session: Session, *, company_id: UUID, kind: str, external_id: str, token_hash: str,
                      status: str, request_id: str | None = None, claim_id: str | None = None) -> UUID:
    row = session.execute(text(
        "insert into plg_leadsintel.connection (tenant_id, company_id, kind, external_connection_id, token_hash, "
        "status, request_id, claim_id) values (kernel.current_tenant(), :c, :k, :e, :t, :s, :r, :cl) returning id"),
        {"c": str(company_id), "k": kind, "e": external_id, "t": token_hash, "s": status, "r": request_id,
         "cl": claim_id}).one()
    connection_id: UUID = row.id
    return connection_id


def latest_connection(session: Session, company_id: UUID, kind: str = "whatsapp") -> Row[Any] | None:
    return session.execute(text(
        "select * from plg_leadsintel.connection where company_id = :c and kind = :k order by created_at desc, id "
        "limit 1"), {"c": str(company_id), "k": kind}).first()


def connection_by_token(session: Session, token_hash: str) -> Row[Any] | None:
    return session.execute(text("select * from plg_leadsintel.connection where token_hash = :t"),
                           {"t": token_hash}).first()


def update_connection(session: Session, connection_id: UUID, **fields: Any) -> None:
    allowed = {"status", "request_id", "claim_id", "display_phone", "phone_number_id", "error_code", "error_message"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown connection fields {sorted(unknown)}")
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    session.execute(text(f"update plg_leadsintel.connection set {sets}, updated_at = now(), "
                         "last_checked_at = now() where id = :id"), {**fields, "id": str(connection_id)})


def mark_event_seen(session: Session, event_id: str) -> bool:
    """True the first time an event id is seen, False for a repeat delivery."""
    return session.execute(text(
        "insert into plg_leadsintel.inbound_event (tenant_id, event_id) values (kernel.current_tenant(), :e) "
        "on conflict do nothing returning event_id"), {"e": event_id}).first() is not None


def store_inbound(session: Session, *, company_id: UUID, connection_id: UUID, provider_message_id: str, sender: str,
                  kind: str, body: str | None, button_id: str | None, media: str | None,
                  received_at: Any) -> UUID | None:
    """Keep a message people sent. None when it was already stored (a repeat)."""
    row = session.execute(text(
        "insert into plg_leadsintel.inbound_message (tenant_id, company_id, connection_id, provider_message_id, "
        "sender, kind, body, button_id, media, received_at, outcome) values (kernel.current_tenant(), :c, :cn, :m, "
        ":s, :k, :b, :bt, cast(:me as jsonb), :r, 'received') on conflict do nothing returning id"),
        {"c": str(company_id), "cn": str(connection_id), "m": provider_message_id, "s": sender, "k": kind,
         "b": body, "bt": button_id, "me": media, "r": received_at}).first()
    if row is None:
        return None
    stored: UUID = row.id
    return stored


def set_outcome(session: Session, message_id: UUID, outcome: str) -> None:
    session.execute(text("update plg_leadsintel.inbound_message set outcome = :o where id = :i"),
                    {"o": outcome, "i": str(message_id)})


def list_inbound(session: Session, company_id: UUID, limit: int, offset: int) -> list[Row[Any]]:
    return list(session.execute(text(
        "select id, created_at, sender, kind, body, button_id, outcome, read_at from plg_leadsintel.inbound_message "
        "where company_id = :c order by created_at desc, id limit :n offset :o"),
        {"c": str(company_id), "n": limit, "o": offset}))
