"""Public interface of the Command Center module.

Units add figures to the Command Center through one extension point, `command.pulse_source`: subclass `PulseSource`,
decorate with `@provides(COMMAND_PULSE_SOURCE)` in the unit's hooks.py, list "command.pulse_source" under
`[extends] implements` and "command" under `optional` in its manifest. Only units enabled for the business take part.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ziira.sdk import Session

COMMAND_PULSE_SOURCE = "command.pulse_source"

FigureKind = Literal["money", "count", "percent"]

__all__ = ["COMMAND_PULSE_SOURCE", "Figure", "FigureKind", "PulseSource"]


@dataclass(frozen=True)
class Figure:
    """One number about the business for a day. `branch_id` None means the whole company.

    `metric` is a stable code (such as "sales.total"); `label` is its English name, the fallback when a screen has no
    translation for the code. `higher_is_better` (None when neither is) lets a screen colour a change.
    """

    metric: str
    label: str
    kind: FigureKind
    value: Decimal
    branch_id: UUID | None = None
    higher_is_better: bool | None = None


class PulseSource(ABC):
    """Supplies a unit's figures for a company and a day, read from its own data (a read model, not raw page loads)."""

    code: str

    @abstractmethod
    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        """The figures for the day (a day that has not ended yet gives the figures so far)."""
