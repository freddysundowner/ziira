"""Public interface of the People, HR and Payroll module.

Other units may import only from this file.

* Extension point STATUTORY_TABLE_SEED: a country pack implements `StatutoryTables` to supply statutory rules (payroll
  taxes, contributions, levies) as effective-dated DATA. They are copied into a business that switches the pack on,
  *unverified*: a different person must check each against the official notice before a payroll run that used it can be
  approved. People has no rules of its own and no rates in code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

STATUTORY_TABLE_SEED = "people.statutory_table_seed"


@dataclass(frozen=True)
class StatutoryTableSeed:
    """One rule table a pack supplies: the `definition` has the shape `people/domain/rules.py` reads (name, kind, base,
    order, employee/employer methods ...); `source_reference` says where the figures come from."""

    code: str
    effective_from: date
    definition: dict[str, Any]
    source_reference: str


def check_statutory_tables(tables: "list[StatutoryTableSeed]") -> None:
    """For a pack's own tests: raises ValidationFailed saying what is wrong with the first table the engine cannot read,
    or ValueError when two tables share a code and a start date."""
    from ziira.modules.people.domain import rules

    seen: set[tuple[str, date]] = set()
    for table in tables:
        rules.parse_rule(table.code.strip().upper(), table.definition)
        key = (table.code.strip().upper(), table.effective_from)
        if key in seen:
            raise ValueError(f"{table.code} appears twice from {table.effective_from}")
        seen.add(key)


class StatutoryTables(ABC):
    """Contract for the STATUTORY_TABLE_SEED extension point. `countries` are ISO codes (empty: worldwide)."""

    countries: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def tables(self) -> list[StatutoryTableSeed]:
        """The rule tables to add (a code the business already has any table for is left alone)."""
