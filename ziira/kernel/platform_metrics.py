"""Platform-wide gauges for /metrics: queues, outbox lag, recurring tasks, notifications, Intelligence failures.

One cheap query per active business (through the same tenant iteration the worker uses), summed or maximised across
businesses so the number of metric series does not grow with the number of customers. The result is cached for
`ZIIRA_METRICS_CACHE_SECONDS` (default 15), so a busy scraper never multiplies the load. A business whose database
cannot be queried is counted in `ziira_metrics_tenant_errors` and skipped; it never fails the scrape.
"""

import logging
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session, tenant_session

log = logging.getLogger("ziira.metrics")
OUTBOX_MAX_ATTEMPTS = 10                                   # outbox.MAX_ATTEMPTS: later events are left for a person

_TENANT_SQL = text("""
select
  (select count(*) from kernel.job where status = 'queued') as jobs_queued,
  (select count(*) from kernel.job where status = 'queued' and run_at <= now()) as jobs_due,
  (select count(*) from kernel.job where status = 'failed') as jobs_failed,
  (select coalesce(extract(epoch from now() - min(run_at)), 0) from kernel.job
     where status = 'queued' and run_at <= now()) as jobs_oldest_due_seconds,
  (select count(*) from kernel.event_outbox where published_at is null and attempts < :max) as outbox_pending,
  (select count(*) from kernel.event_outbox where published_at is null and attempts >= :max) as outbox_stuck,
  (select coalesce(extract(epoch from now() - min(created_at)), 0) from kernel.event_outbox
     where published_at is null and attempts < :max) as outbox_lag_seconds,
  (select count(*) from kernel.notification where status = 'queued') as notifications_queued,
  (select count(*) from kernel.notification where status = 'failed') as notifications_failed,
  (select count(*) from kernel.exception_item where unit_name = 'intel' and kind = 'check_failed'
     and status = 'open' and created_at > now() - interval '24 hours') as intel_check_failures
""")
_PERIODIC_SQL = text("select name, extract(epoch from now() - last_run_at) as age, last_error is not null as failed "
                     "from kernel.periodic_run")


@dataclass
class PlatformSnapshot:
    """Totals across businesses at one moment."""

    tenants: dict[str, int] = field(default_factory=dict)            # status -> count
    sums: dict[str, float] = field(default_factory=dict)
    maxes: dict[str, float] = field(default_factory=dict)
    periodic_age: dict[str, float] = field(default_factory=dict)      # task -> oldest "last run" age across businesses
    periodic_failures: dict[str, int] = field(default_factory=dict)  # task -> businesses where its last run failed
    tenant_errors: int = 0
    collected_at: float = 0.0
    collect_seconds: float = 0.0


_SUMMED = ("jobs_queued", "jobs_due", "jobs_failed", "outbox_pending", "outbox_stuck", "notifications_queued",
           "notifications_failed", "intel_check_failures")
_MAXED = ("jobs_oldest_due_seconds", "outbox_lag_seconds")


def collect() -> PlatformSnapshot:
    """Query every active business now (no cache)."""
    started = time.monotonic()
    snap = PlatformSnapshot(sums=dict.fromkeys(_SUMMED, 0.0), maxes=dict.fromkeys(_MAXED, 0.0))
    with master_session() as s:
        snap.tenants = {str(r.status): int(r.n) for r in s.execute(text(
            "select status, count(*) as n from master.tenant group by status"))}
        active = list(s.execute(text("select id from master.tenant where status = 'active' order by id")).scalars())
    for tenant_id in active:
        try:
            with tenant_session(tenant_id) as session:
                row = session.execute(_TENANT_SQL, {"max": OUTBOX_MAX_ATTEMPTS}).one()
                periodic = session.execute(_PERIODIC_SQL).all()
        except Exception:  # noqa: BLE001 - one broken business must not hide the others
            log.warning("Metrics: could not read tenant %s", tenant_id, exc_info=True)
            snap.tenant_errors += 1
            continue
        for key in _SUMMED:
            snap.sums[key] += float(getattr(row, key))
        for key in _MAXED:
            snap.maxes[key] = max(snap.maxes[key], float(getattr(row, key)))
        for p in periodic:
            snap.periodic_age[p.name] = max(snap.periodic_age.get(p.name, 0.0), float(p.age))
            snap.periodic_failures[p.name] = snap.periodic_failures.get(p.name, 0) + (1 if p.failed else 0)
    snap.collected_at = time.time()
    snap.collect_seconds = time.monotonic() - started
    return snap


_cache: PlatformSnapshot | None = None
_cache_lock = threading.Lock()


def snapshot() -> PlatformSnapshot:
    """The cached snapshot, refreshed when older than the configured cache time."""
    global _cache
    ttl = get_settings().metrics_cache_seconds
    with _cache_lock:                    # one scrape refreshes; concurrent scrapes wait and share the result
        if _cache is None or time.time() - _cache.collected_at >= ttl:
            _cache = collect()
        return _cache


def clear_cache() -> None:
    """Forget the cached snapshot (tests)."""
    global _cache
    with _cache_lock:
        _cache = None


def render(snap: PlatformSnapshot) -> list[str]:
    """Prometheus text lines for a snapshot."""
    out: list[str] = []

    def gauge(name: str, help_text: str, samples: list[tuple[str, float]]) -> None:
        out.extend([f"# HELP {name} {help_text}", f"# TYPE {name} gauge"])
        out.extend(f"{name}{labels} {value:g}" for labels, value in samples)

    gauge("ziira_tenants", "Businesses by status.", [(f'{{status="{k}"}}', v) for k, v in sorted(snap.tenants.items())])
    for key, help_text in (
            ("jobs_queued", "Background jobs waiting (including ones scheduled for later)."),
            ("jobs_due", "Background jobs due to run now."),
            ("jobs_failed", "Background jobs that used all their attempts."),
            ("outbox_pending", "Events committed but not yet delivered to their subscribers."),
            ("outbox_stuck", "Events that failed every attempt and wait for a person."),
            ("notifications_queued", "Messages queued to customers and not yet sent."),
            ("notifications_failed", "Messages that failed to send."),
            ("intel_check_failures", "Intelligence checks that could not run in the last 24 hours (open items).")):
        gauge(f"ziira_{key}", help_text, [("", snap.sums[key])])
    gauge("ziira_jobs_oldest_due_seconds", "Age of the longest-waiting due job in any business.",
          [("", snap.maxes["jobs_oldest_due_seconds"])])
    gauge("ziira_outbox_lag_seconds", "Age of the oldest undelivered event in any business.",
          [("", snap.maxes["outbox_lag_seconds"])])
    gauge("ziira_periodic_last_run_age_seconds",
          "Seconds since the least recently run business last ran each recurring task.",
          [(f'{{task="{k}"}}', v) for k, v in sorted(snap.periodic_age.items())])
    gauge("ziira_periodic_failing_tenants", "Businesses where the last run of a recurring task failed.",
          [(f'{{task="{k}"}}', v) for k, v in sorted(snap.periodic_failures.items())])
    gauge("ziira_metrics_tenant_errors", "Businesses that could not be read for these metrics.",
          [("", snap.tenant_errors)])
    gauge("ziira_metrics_collect_seconds", "How long the last platform metrics collection took.",
          [("", snap.collect_seconds)])
    gauge("ziira_metrics_collected_timestamp_seconds", "When the platform metrics were collected.",
          [("", snap.collected_at)])
    return out
