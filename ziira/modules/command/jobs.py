"""Recurring work of the Command Center (run by `ziira worker`): collect the figures, send the briefs that are due."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ziira.modules.command.services import briefs, pulse
from ziira.sdk import Session, company_setting, flag_for_review, periodic

log = logging.getLogger("ziira.command")


@periodic("command.refresh_pulse", every_seconds=3600)
def refresh_pulse(session: Session) -> None:
    """Collect today's and yesterday's figures for each company (yesterday's may have been finished late)."""
    from datetime import timedelta

    for company in session.execute(text("select id from kernel.company order by id")).all():
        zone = ZoneInfo(str(company_setting(session, company.id, "timezone")))
        today = datetime.now(zone).date()
        for day in (today, today - timedelta(days=1)):
            try:
                with session.begin_nested():
                    pulse.refresh_company(session, company.id, day)
            except Exception as error:
                log.exception("Figures could not be collected for company %s", company.id)
                flag_for_review(session, unit="command", kind="pulse_failed", severity="low", company_id=company.id,
                                message=f"Figures could not be collected: {error}"[:500],
                                dedupe_key=f"pulse-run-failed:{company.id}:{day}")


@periodic("command.send_briefs", every_seconds=600)
def send_briefs(session: Session) -> None:
    """Send the briefs whose time has come (a brief missed while the worker was down goes out later the same day)."""
    briefs.send_due(session)
