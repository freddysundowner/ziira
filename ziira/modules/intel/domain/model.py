"""What a check produces and what the engine works with. Plain data, no database."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

SEVERITIES = ("info", "low", "medium", "high", "critical")
AREAS = ("cash_sales", "customers", "suppliers", "stock", "cash_planning", "books", "people", "controls", "general")


@dataclass(frozen=True)
class Record:
    """One record behind a finding, so a person can open it: its kind (such as "pos.sale"), id and a readable label."""

    type: str
    id: UUID | None
    label: str


@dataclass(frozen=True)
class Candidate:
    """A problem a check found. The engine turns it into a finding (or recognises it as one already open).

    `fingerprint` says which problem this is (which cashier, which day, which supplier): the same problem seen again is
    the same finding. `summary` and `recommended_action` are plain sentences built from the figures, never guesses.
    """

    fingerprint: str
    severity: str
    summary: str
    recommended_action: str
    company_id: UUID
    branch_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    value: Decimal | None = None
    expected_value: Decimal | None = None
    amount: Decimal | None = None
    records: tuple[Record, ...] = ()
    figures: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Baseline:
    """The normal range of a metric for one dimension, learned from history."""

    mean: Decimal
    stddev: Decimal
    p95: Decimal
    sample_size: int


@dataclass(frozen=True)
class Sample:
    """One observation of a metric (a day's void rate for a cashier), to learn a baseline from."""

    key: str
    value: Decimal
