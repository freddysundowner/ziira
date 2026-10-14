"""Recurring work of Intelligence (run by `ziira worker`): the checks, and the baselines they compare against."""

import logging

from sqlalchemy import text

from ziira.modules.intel.services import alerts, baselines, engine
from ziira.sdk import Session, flag_for_review, periodic

log = logging.getLogger("ziira.intel")
SIX_HOURS = 6 * 3600
WEEK = 7 * 24 * 3600


def _companies(session: Session) -> list[object]:
    return list(session.execute(text("select id, name from kernel.company order by id")).all())


@periodic("intel.run_checks", every_seconds=SIX_HOURS)
def run_checks(session: Session) -> None:
    """Run every enabled check for each company, then alert on what is new. One company failing stops no other."""
    for company in _companies(session):
        try:
            with session.begin_nested():
                engine.run_company(session, company.id)  # type: ignore[attr-defined]
                alerts.send_alerts(session, company.id)  # type: ignore[attr-defined]
        except Exception as error:
            log.exception("Intelligence could not run for company %s", company.id)  # type: ignore[attr-defined]
            flag_for_review(session, unit="intel", kind="run_failed", severity="low", company_id=company.id,  # type: ignore[attr-defined]
                            message=f"Daily checks could not run: {error}"[:500],
                            dedupe_key=f"intel-run-failed:{company.id}")  # type: ignore[attr-defined]


@periodic("intel.refresh_baselines", every_seconds=WEEK)
def refresh_baselines(session: Session) -> None:
    """Relearn what is normal for each company from its last 90 days."""
    for company in _companies(session):
        try:
            with session.begin_nested():
                baselines.refresh_company(session, company.id, engine.local_today(session, company.id))  # type: ignore[attr-defined]
        except Exception:
            log.exception("Baselines could not be refreshed for company %s", company.id)  # type: ignore[attr-defined]
