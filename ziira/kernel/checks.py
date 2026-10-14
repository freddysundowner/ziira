"""Integrity checks: units verify their own data, and `ziira verify` runs them for every tenant.

A unit that keeps derived figures (stock balances, ledger totals, till sessions) provides a check
through the "kernel.integrity_check" extension point:

    # hooks.py
    @provides("kernel.integrity_check")
    class StockLedgerCheck(IntegrityCheck):
        name = "stock ledger"
        def run(self, session, *, fix=False) -> list[str]: ...

`run` compares derived figures with what they should be and returns one line per problem found (an empty
list when all is well). With `fix=True` it rebuilds what it can from the source records and returns the
problems it found before fixing. Checks only read and rebuild; they never change source records.
Only units enabled for the tenant are checked.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from ziira.kernel.context import system_context
from ziira.kernel.db import tenant_session
from ziira.kernel.events import unit_of
from ziira.kernel.extensions import define_extension_point, implementations

INTEGRITY_CHECK = "kernel.integrity_check"


class IntegrityCheck(ABC):
    """Contract of the "kernel.integrity_check" extension point."""

    name: str = "check"

    @abstractmethod
    def run(self, session: Session, *, fix: bool = False) -> list[str]:
        """Return the problems found, one line each (empty if none). With `fix`, rebuild derived data."""


define_extension_point(INTEGRITY_CHECK, IntegrityCheck,
                       "Verifies a unit's derived data against its source records; run by `ziira verify`.")


@dataclass(frozen=True)
class CheckResult:
    unit: str
    check: str
    problems: list[str]


def run_integrity_checks_in(session: Session, *, fix: bool = False, unit: str | None = None) -> list[CheckResult]:
    """Run the integrity checks of the units enabled in the database this session is connected to. The caller has set
    the context (`system_context`) and the session's tenant; used for a restored copy of a tenant database as well."""
    results = []
    for check in implementations(session, INTEGRITY_CHECK):
        owner = unit_of(type(check).__module__)
        if unit is None or owner == unit:
            results.append(CheckResult(owner, check.name, check.run(session, fix=fix)))
    return results


def run_integrity_checks(tenant_id: UUID, *, fix: bool = False, unit: str | None = None) -> list[CheckResult]:
    """Run every integrity check of the units enabled for the tenant (or only one unit's)."""
    system_context(tenant_id)
    with tenant_session(tenant_id) as session:
        return run_integrity_checks_in(session, fix=fix, unit=unit)
