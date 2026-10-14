"""Business rules of Intelligence: severity order, the life of a finding, ranking, and what counts as unusual."""

import hashlib
import math
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from ziira.modules.intel.domain.model import SEVERITIES, Baseline

OPEN_STATUSES = ("new", "sent", "acknowledged", "explained")
CLOSED_STATUSES = ("resolved", "dismissed")

# Where a finding may go from each status. A resolved finding that is seen again is reopened by the engine.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("sent", "acknowledged", "explained", "resolved", "dismissed"),
    "sent": ("acknowledged", "explained", "resolved", "dismissed"),
    "acknowledged": ("explained", "resolved", "dismissed"),
    "explained": ("acknowledged", "resolved", "dismissed"),
    "resolved": (),
    "dismissed": (),
}


def severity_rank(severity: str) -> int:
    """0 (info) to 4 (critical)."""
    return SEVERITIES.index(severity)


def at_least(severity: str, minimum: str) -> bool:
    """True if `severity` is as serious as `minimum` or more."""
    return severity_rank(severity) >= severity_rank(minimum)


def can_move(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


def fingerprint(*parts: object) -> str:
    """A stable identity for a problem from what defines it (kind, record, period). Short and safe to store."""
    text = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def rank_score(severity: str, amount: Decimal | None, days_open: int) -> float:
    """Orders findings for a brief: severity first, then the money at stake, then how long it has waited.

    Deterministic and explainable: severity decides the band, money and age move a finding within it.
    """
    money = math.log10(float(amount) + 1) if amount and amount > 0 else 0.0
    return severity_rank(severity) * 100 + min(money, 9.0) * 5 + min(days_open, 30) * 0.5


def mean_std_p95(values: Sequence[Decimal]) -> Baseline | None:
    """Mean, population standard deviation and 95th percentile of the observations (None when there are none)."""
    n = len(values)
    if n == 0:
        return None
    ordered = sorted(values)
    mean = sum(ordered, Decimal(0)) / n
    variance = sum(((v - mean) ** 2 for v in ordered), Decimal(0)) / n
    stddev = variance.sqrt() if variance > 0 else Decimal(0)
    index = min(n - 1, math.ceil(0.95 * n) - 1)
    return Baseline(mean=mean, stddev=stddev, p95=ordered[index], sample_size=n)


def is_unusual(value: Decimal, baseline: Baseline | None, *, min_samples: int = 14,
               deviations: Decimal = Decimal(3)) -> bool:
    """True when the value is well above what is normal for this business: more than `deviations` standard
    deviations over the mean and above the 95th percentile. Needs enough history (`min_samples`) to say anything."""
    if baseline is None or baseline.sample_size < min_samples:
        return False
    return value > baseline.mean + deviations * baseline.stddev and value > baseline.p95


def days_between(earlier: date, later: date) -> int:
    return max((later - earlier).days, 0)
