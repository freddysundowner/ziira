"""Append-only audit log with a per-tenant hash chain.

Each entry stores the hash of the previous entry for the same tenant, so any
change or deletion breaks the chain and is detectable by `verify_chain`.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from ziira.kernel.context import get_context


def _digest(prev_hash: str | None, record: dict[str, Any]) -> str:
    body = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(((prev_hash or "") + body).encode()).hexdigest()


def record(session: Session, action: str, entity_type: str, entity_id: UUID | None,
           changes: dict[str, Any] | None = None) -> None:
    """Record one audit entry as part of the current transaction.

    The entry is written (and chained to the one before it) just before the transaction commits, not at this call.
    The chain needs a lock per tenant, held until the transaction ends; taking it at the first audit call of a long
    operation (a sale posts stock and books after its first audit entry) would make every audited operation of the
    tenant wait for it. Taken just before commit, the lock is held only for the few statements that write the entries.
    Entries of one transaction keep their order, and a rolled-back transaction writes none.
    """
    ctx = get_context()
    if not session.info.get(_LISTENING):
        session.info[_LISTENING] = True
        event.listen(session, "before_commit", _write_pending)
        event.listen(session, "after_rollback", _forget_pending)
    session.info.setdefault(_PENDING, []).append({
        "user_id": ctx.user_id, "channel": ctx.channel, "device_id": ctx.device_id, "ip": ctx.ip_address,
        "tenant_id": ctx.tenant_id, "action": action, "entity_type": entity_type, "entity_id": entity_id,
        "changes": changes})


_PENDING = "audit_pending"
_LISTENING = "audit_listening"


def _forget_pending(session: Session) -> None:
    session.info.pop(_PENDING, None)


def _write_pending(session: Session) -> None:
    pending: list[dict[str, Any]] = session.info.pop(_PENDING, None) or []
    for item in pending:
        _write(session, item)


def flush_pending(session: Session) -> None:
    """Write the audit entries queued in this transaction now (for code that reads the log before committing)."""
    pending: list[dict[str, Any]] = session.info.get(_PENDING) or []
    session.info[_PENDING] = []
    for item in pending:
        _write(session, item)


def _write(session: Session, item: dict[str, Any]) -> None:
    # Serialise writers per tenant so the chain stays linear.
    session.execute(text("select pg_advisory_xact_lock(hashtext(:t))"), {"t": str(item["tenant_id"])})
    prev = session.execute(text(
        "select hash from kernel.audit_log where tenant_id = kernel.current_tenant() "
        "order by id desc limit 1")).scalar()
    entry = {"user_id": item["user_id"], "channel": item["channel"], "action": item["action"],
             "entity_type": item["entity_type"], "entity_id": item["entity_id"], "changes": item["changes"]}
    changes = item["changes"]
    session.execute(text(
        "insert into kernel.audit_log (tenant_id, user_id, channel, device_id, ip_address, action, entity_type, "
        "entity_id, changes, prev_hash, hash) values (:t, :u, :c, :d, cast(:ip as inet), :a, :et, :ei, "
        "cast(:ch as jsonb), :p, :h)"),
        {"t": str(item["tenant_id"]), "u": str(item["user_id"]) if item["user_id"] else None,
         "c": item["channel"], "d": item["device_id"], "ip": item["ip"], "a": item["action"],
         "et": item["entity_type"], "ei": str(item["entity_id"]) if item["entity_id"] else None,
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
