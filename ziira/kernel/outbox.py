"""Outbox processor: delivers committed events to after-commit subscribers.

Events are written to kernel.event_outbox in the same transaction as the change that caused
them (see events.publish), so an event exists only if its change committed. This processor
reads undelivered events per tenant, oldest first, and runs the @subscribe_after handlers of
the units the tenant has enabled.

- Each event is handled in a savepoint: if a handler fails, its database work is undone, the
  attempt and error are recorded, and the event is retried on a later run.
- After MAX_ATTEMPTS failures an event is left for a person to look at (no more retries).
- Rows are locked with SKIP LOCKED, so several processors can run side by side.

Run it with `ziira outbox-run` (a background worker replaces this loop in a later phase).
"""

import logging
import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.context import system_context
from ziira.kernel.db import app_engine, tenant_session
from ziira.kernel.events import Event, after_commit_handlers

log = logging.getLogger("ziira.outbox")
MAX_ATTEMPTS = 10


def _active_tenants() -> list[UUID]:
    """Active tenants (kernel.tenant is not tenant-scoped, so the app role can list them)."""
    with app_engine().connect() as conn:
        return list(conn.execute(text("select id from kernel.tenant where status = 'active' order by id")).scalars())


def _enabled_units(s: Session) -> set[str]:
    return {"kernel", *s.execute(text(
        "select unit_name from kernel.tenant_unit "
        "where status = 'enabled' and tenant_id = kernel.current_tenant()")).scalars()}


def process_tenant(tenant_id: UUID, batch_size: int = 100) -> int:
    """Deliver up to `batch_size` pending events of one tenant. Returns how many were delivered."""
    system_context(tenant_id)
    delivered = 0
    with tenant_session(tenant_id) as s:
        rows = s.execute(text(
            "select id, event_type, aggregate_type, aggregate_id, payload from kernel.event_outbox "
            "where published_at is null and attempts < :max order by id limit :n for update skip locked"),
            {"max": MAX_ATTEMPTS, "n": batch_size}).all()
        if not rows:
            return 0
        enabled = _enabled_units(s)
        for row in rows:
            event = Event(type=row.event_type, aggregate_type=row.aggregate_type, aggregate_id=row.aggregate_id,
                          payload=row.payload)
            savepoint = s.begin_nested()
            try:
                for unit, handler in after_commit_handlers(event.type):
                    if unit in enabled:
                        handler(s, event)
                savepoint.commit()
            except Exception as exc:  # noqa: BLE001 - any handler failure is recorded and retried
                savepoint.rollback()
                log.warning("Event %s (%s) failed: %s", row.id, row.event_type, exc)
                s.execute(text("update kernel.event_outbox set attempts = attempts + 1, last_error = :e "
                               "where id = :i"), {"e": f"{type(exc).__name__}: {exc}"[:2000], "i": row.id})
                continue
            s.execute(text("update kernel.event_outbox set published_at = now(), attempts = attempts + 1, "
                           "last_error = null where id = :i"), {"i": row.id})
            delivered += 1
    return delivered


def process_all(batch_size: int = 100) -> int:
    """One pass over every tenant. Returns how many events were delivered."""
    return sum(process_tenant(t, batch_size) for t in _active_tenants())


def run_forever(interval_seconds: float = 2.0) -> None:
    """Keep delivering events; sleep when there is nothing to do."""
    while True:
        if process_all() == 0:
            time.sleep(interval_seconds)
