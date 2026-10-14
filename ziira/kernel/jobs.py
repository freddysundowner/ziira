"""The job queue: work to do later, or again after a failure (checking an M-Pesa payment, retrying a submission).

`enqueue` adds a job in the caller's transaction (so it exists only if the caller's change committed). `run_due` runs
the jobs that are due: each in its own savepoint, with the failed ones retried with growing delays (30 s, 1 min, 2 min,
... up to an hour) and, after the last attempt, left for a person in the exceptions inbox.

A unit registers a handler in its `jobs.py`:

    @job("payments.check_stk")
    def check_stk(session: Session, payload: dict) -> None: ...

Handlers must be safe to run twice. Run the queue with `ziira worker`.

Recurring work is registered with `@periodic`; the worker runs it for each business at most once per interval:

    @periodic("pos.expire_quotations", every_seconds=3600)
    def expire(session: Session) -> None: ...
"""

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import exceptions_inbox
from ziira.kernel.context import get_context, system_context
from ziira.kernel.db import tenant_session
from ziira.kernel.events import unit_of

log = logging.getLogger("ziira.jobs")
Handler = Callable[[Session, dict[str, Any]], None]
PeriodicHandler = Callable[[Session], None]
_handlers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)
_periodic: dict[str, tuple[str, int, PeriodicHandler]] = {}
MAX_BACKOFF_SECONDS = 3600


def job(job_type: str) -> Callable[[Handler], Handler]:
    """Decorator: run this function for jobs of this type."""

    def register(handler: Handler) -> Handler:
        _handlers[job_type].append((unit_of(handler.__module__), handler))
        return handler

    return register


def periodic(name: str, *, every_seconds: int) -> Callable[[PeriodicHandler], PeriodicHandler]:
    """Decorator: run this function for each business at most once every `every_seconds`, while its unit is enabled."""
    if every_seconds < 60:
        raise ValueError("A recurring task runs at most once a minute")

    def register(handler: PeriodicHandler) -> PeriodicHandler:
        _periodic[name] = (unit_of(handler.__module__), every_seconds, handler)
        return handler

    return register


def periodic_names() -> list[str]:
    """The recurring tasks units have registered."""
    return sorted(_periodic)


def enqueue(session: Session, job_type: str, payload: dict[str, Any] | None = None, *, delay_seconds: int = 0,
            dedupe_key: str | None = None, max_attempts: int = 8) -> None:
    """Add a job to run `delay_seconds` from now. With a `dedupe_key`, a job with the same key is not added twice."""
    session.execute(text(
        "insert into kernel.job (tenant_id, job_type, payload, run_at, max_attempts, dedupe_key) "
        "values (kernel.current_tenant(), :t, cast(:p as jsonb), now() + make_interval(secs => :d), :m, :k) "
        "on conflict (tenant_id, dedupe_key) do nothing"),
        {"t": job_type, "p": json.dumps(payload or {}, default=str), "d": delay_seconds, "m": max_attempts,
         "k": dedupe_key})


def backoff_seconds(attempts: int) -> int:
    """How long to wait before the next try: 30 s, 60 s, 120 s, ... at most an hour."""
    return int(min(30 * 2 ** max(attempts - 1, 0), MAX_BACKOFF_SECONDS))


def _enabled(s: Session) -> set[str]:
    return {"kernel", *s.execute(text(
        "select unit_name from kernel.tenant_unit where status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).scalars()}


def run_due(tenant_id: UUID, batch_size: int = 50) -> int:
    """Run the jobs of one tenant that are due. Returns how many finished."""
    system_context(tenant_id)
    finished = 0
    with tenant_session(tenant_id) as s:
        rows = s.execute(text(
            "select id, job_type, payload, attempts, max_attempts from kernel.job where status = 'queued' "
            "and run_at <= now() order by run_at, id limit :n for update skip locked"), {"n": batch_size}).all()
        if not rows:
            return 0
        enabled = _enabled(s)
        for row in rows:
            handlers = [(unit, h) for unit, h in _handlers.get(row.job_type, []) if unit in enabled]
            if not handlers and row.job_type in _handlers:
                continue                                    # its unit is off for this tenant: leave it queued
            savepoint = s.begin_nested()
            try:
                if row.job_type not in _handlers:
                    raise LookupError(f"No handler for job type '{row.job_type}'")
                for _, handler in handlers:
                    handler(s, dict(row.payload))
                savepoint.commit()
            except Exception as exc:  # noqa: BLE001 - any failure is recorded and retried
                savepoint.rollback()
                attempts = row.attempts + 1
                log.warning("Job %s (%s) failed, attempt %s: %s", row.id, row.job_type, attempts, exc)
                last = attempts >= row.max_attempts
                s.execute(text(
                    "update kernel.job set attempts = :a, last_error = :e, status = :st, "
                    "run_at = now() + make_interval(secs => :d) where id = :i"),
                    {"a": attempts, "e": f"{type(exc).__name__}: {exc}"[:2000], "st": "failed" if last else "queued",
                     "d": backoff_seconds(attempts), "i": row.id})
                if last:
                    exceptions_inbox.flag(s, unit="kernel", kind="job_failed", severity="high",
                                          message=f"A background job ({row.job_type}) kept failing: {exc}"[:500],
                                          ref_type="job", dedupe_key=f"job:{row.id}")
                continue
            s.execute(text("update kernel.job set status = 'done', attempts = attempts + 1, last_error = null, "
                           "finished_at = now() where id = :i"), {"i": row.id})
            finished += 1
    return finished


def run_periodic(tenant_id: UUID, *, only: str | None = None, force: bool = False) -> int:
    """Run the recurring tasks of one tenant that are due. Returns how many ran. A task is claimed before it runs, so
    two workers never run it at once; one that fails is recorded, put in the exceptions inbox, and tried again at its
    next interval. `only` runs just that task and `force` runs it even if it ran recently (`ziira run-task`)."""
    system_context(tenant_id)
    ran = 0
    with tenant_session(tenant_id) as s:
        enabled = _enabled(s)
        for name, (unit, every, handler) in sorted(_periodic.items()):
            if unit not in enabled or (only is not None and name != only):
                continue
            claimed = True if force else s.execute(text(
                "insert into kernel.periodic_run (tenant_id, name, last_run_at) "
                "values (kernel.current_tenant(), :n, now()) "
                "on conflict (tenant_id, name) do update set last_run_at = now() "
                "where kernel.periodic_run.last_run_at < now() - make_interval(secs => :e) returning name"),
                {"n": name, "e": every}).first()
            if claimed is None:
                continue
            savepoint = s.begin_nested()
            try:
                handler(s)
                savepoint.commit()
                s.execute(text("update kernel.periodic_run set last_error = null where name = :n"), {"n": name})
            except Exception as exc:  # noqa: BLE001 - recorded, flagged and tried again next interval
                savepoint.rollback()
                log.warning("Recurring task %s failed: %s", name, exc)
                s.execute(text("update kernel.periodic_run set last_error = :e where name = :n"),
                          {"n": name, "e": f"{type(exc).__name__}: {exc}"[:2000]})
                exceptions_inbox.flag(s, unit=unit, kind="periodic_failed", severity="medium",
                                      message=f"A recurring task ({name}) failed: {exc}"[:500],
                                      dedupe_key=f"periodic:{name}:{type(exc).__name__}")
            ran += 1
    return ran


def run_all(batch_size: int = 50) -> int:
    """One pass over every active tenant: the jobs that are due, then the recurring tasks."""
    from ziira.kernel.outbox import _active_tenants

    return sum(run_due(t, batch_size) + run_periodic(t) for t in _active_tenants())


def current_tenant_id() -> UUID:
    return get_context().tenant_id


def purge_finished(s: Session, days: int = 7) -> int:
    """Forget jobs that finished (or gave up) more than `days` ago."""
    return len(s.execute(text(
        "delete from kernel.job where status in ('done', 'failed') and coalesce(finished_at, run_at) < "
        "now() - make_interval(days => :d) returning id"), {"d": days}).all())
