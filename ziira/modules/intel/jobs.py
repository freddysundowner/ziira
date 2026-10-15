"""Recurring work of Intelligence (run by `ziira worker`): the checks, and the baselines they compare against."""

import logging
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.repository import ai_repo
from ziira.modules.intel.services import alerts, baselines, engine, explain
from ziira.sdk import Session, flag_for_review, periodic, tenant_transaction, unbound_periodic

log = logging.getLogger("ziira.intel")
SIX_HOURS = 6 * 3600
WEEK = 7 * 24 * 3600
CALL_LOG_DAYS = 400              # how long the record of AI calls is kept
CONVERSATION_DAYS = 90           # how long an Ask Ziira conversation is kept after its last message


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


def _company_ids(tenant_id: UUID) -> list[UUID]:
    with tenant_transaction(tenant_id) as session:
        return [c.id for c in _companies(session)]  # type: ignore[attr-defined]


@unbound_periodic("intel.ai_explain", every_seconds=15 * 60)
def ai_explain(tenant_id: UUID) -> None:
    """Explain a few new findings in plain words, for companies that switched that on. Runs with no transaction open
    (it waits on the AI provider); a company where the assistant is off or over budget is skipped."""
    for company_id in _company_ids(tenant_id):
        explain.explain_pending(tenant_id, company_id)


@unbound_periodic("intel.ai_rank", every_seconds=2 * 3600)
def ai_rank(tenant_id: UUID) -> None:
    """Ask the AI layer to order each company's most pressing findings (used while fresh; otherwise rank_score)."""
    for company_id in _company_ids(tenant_id):
        explain.rank_company(tenant_id, company_id)


@periodic("intel.purge_ai_history", every_seconds=24 * 3600)
def purge_ai_history(session: Session) -> None:
    """Forget old AI call-log rows and Ask Ziira conversations."""
    ai_repo.purge_old(session, CALL_LOG_DAYS, CONVERSATION_DAYS)
