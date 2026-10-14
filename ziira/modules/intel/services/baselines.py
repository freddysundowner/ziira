"""Learning what is normal: per-business ranges of a metric, from history, used to tell unusual from usual."""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.intel.domain.model import Baseline
from ziira.modules.intel.domain.rules import mean_std_p95
from ziira.modules.intel.public import INTEL_BASELINE_METRIC, BaselineMetric
from ziira.modules.intel.repository import findings_repo as repo
from ziira.sdk import Session, implementations

HISTORY_DAYS = 90


class Baselines:
    """Lookup of the normal ranges of one company."""

    def __init__(self, rows: dict[tuple[str, str], tuple[Decimal, Decimal, Decimal, int]]) -> None:
        self._rows = rows

    def get(self, metric: str, key: str) -> Baseline | None:
        row = self._rows.get((metric, key))
        return Baseline(*row) if row else None


def load(session: Session, company_id: UUID) -> Baselines:
    return Baselines(repo.load_baselines(session, company_id))


def refresh_company(session: Session, company_id: UUID, today: date,
                    metrics: Iterable[BaselineMetric] | None = None) -> int:
    """Recompute the company's baselines from the last 90 days. Returns how many ranges were stored."""
    stored = 0
    for metric in (metrics if metrics is not None else implementations(session, INTEL_BASELINE_METRIC)):
        samples = metric.samples(session, company_id, today - timedelta(days=HISTORY_DAYS), today)
        by_key: dict[str, list[Decimal]] = {}
        for sample in samples:
            by_key.setdefault(sample.key, []).append(sample.value)
        rows = []
        for key, values in by_key.items():
            stats = mean_std_p95(values)
            if stats is not None:
                rows.append((key, stats.mean, stats.stddev, stats.p95, stats.sample_size))
        repo.replace_baselines(session, company_id, metric.code, rows)
        stored += len(rows)
    return stored
