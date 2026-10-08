"""Append-only audit log with a per-tenant hash chain.

Each entry stores the hash of the previous entry for the same tenant, so any
change or deletion breaks the chain and is detectable by `verify_chain`.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.context import get_context


def _digest(prev_hash: str | None, record: dict[str, Any]) -> str:
    body = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(((prev_hash or "") + body).encode()).hexdigest()


def record(session: Session, action: str, entity_type: str, entity_id: UUID | None,
           changes: dict[str, Any] | None = None) -> None:
    """Write one audit entry in the current transaction."""
    ctx = get_context()
    # Serialise writers per tenant so the chain stays linear.
    session.execute(text("select pg_advisory_xact_lock(hashtext(:t))"), {"t": str(ctx.tenant_id)})
    prev = session.execute(text(
        "select hash from kernel.audit_log where tenant_id = kernel.current_tenant() "
        "order by id desc limit 1")).scalar()
    entry = {"user_id": ctx.user_id, "channel": ctx.channel, "action": action,
             "entity_type": entity_type, "entity_id": entity_id, "changes": changes}
    session.execute(text(
        "insert into kernel.audit_log (tenant_id, user_id, channel, action, entity_type, entity_id, "
        "changes, prev_hash, hash) values (:t, :u, :c, :a, :et, :ei, cast(:ch as jsonb), :p, :h)"),
        {"t": str(ctx.tenant_id), "u": str(ctx.user_id) if ctx.user_id else None,
         "c": ctx.channel, "a": action, "et": entity_type,
         "ei": str(entity_id) if entity_id else None,
         "ch": json.dumps(changes, default=str) if changes is not None else None,
         "p": prev, "h": _digest(prev, entry)})


def verify_chain(session: Session) -> bool:
    """True if every entry for the current tenant links to the one before it."""
    prev = None
    for row in session.execute(text(
            "select prev_hash, hash from kernel.audit_log "
            "where tenant_id = kernel.current_tenant() order by id")):
        if row.prev_hash != prev:
            return False
        prev = row.hash
    return True
