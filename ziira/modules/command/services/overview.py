"""What the Command Center shows a person: the figures for their scope and the findings that need them."""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from ziira.modules.command.repository import command_repo as repo
from ziira.modules.command.services import briefs, pulse
from ziira.sdk import RequestContext, Session


@dataclass(frozen=True)
class Overview:
    company_id: UUID
    company_name: str
    currency: str
    day: date
    figures: list[pulse.PulseRow]
    refreshed_at: Any
    open_findings: int
    findings_by_severity: dict[str, int]
    top_findings: list[Any]


def build(session: Session, context: RequestContext, company_id: UUID, day: date) -> Overview:
    """Today's figures so far against yesterday, plus the open findings in the user's scope."""
    if repo.latest_computed(session, company_id, day) is None:
        pulse.refresh_company(session, company_id, day)            # first look of the day: collect once, then hourly
    name, currency = briefs.company_info(session, company_id)
    figures = pulse.summarise(session, context, company_id, day, day)
    by_severity: dict[str, int] = {}
    top: list[Any] = []
    if briefs.intel_enabled(session):
        from ziira.modules.intel.public import findings_summary, top_findings

        by_severity = findings_summary(session, context)
        top = top_findings(session, context, 5)
    return Overview(company_id, name, currency, day, figures, repo.latest_computed(session, company_id, day),
                    sum(by_severity.values()), by_severity, top)
