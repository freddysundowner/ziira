"""Pulse figures: units supply them, they are stored per day, and the dashboard and briefs read the stored copy."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.command.permissions import COMMAND_VIEW
from ziira.modules.command.public import COMMAND_PULSE_SOURCE
from ziira.modules.command.repository import command_repo as repo
from ziira.sdk import RequestContext, Session, flag_for_review, implementations

log = logging.getLogger("ziira.command")
KINDS = ("money", "count", "percent")


@dataclass(frozen=True)
class PulseRow:
    metric: str
    label: str
    kind: str
    value: Decimal
    previous: Decimal | None
    branch_id: UUID | None
    branch_name: str | None
    higher_is_better: bool | None


def refresh_company(session: Session, company_id: UUID, day: date) -> int:
    """Ask every enabled unit for its figures for the day and store them. A unit failing does not stop the others."""
    stored = 0
    for source in implementations(session, COMMAND_PULSE_SOURCE):
        try:
            with session.begin_nested():
                figures = source.figures(session, company_id, day)
                rows = [{"metric": f.metric, "label": f.label, "kind": f.kind, "value": Decimal(f.value),
                         "branch_id": f.branch_id, "higher_is_better": f.higher_is_better}
                        for f in figures if f.kind in KINDS]
                repo.replace_figures(session, company_id, day, {r["metric"] for r in rows}, rows)
                stored += len(rows)
        except Exception as error:
            log.exception("Pulse source %s failed for company %s", source.code, company_id)
            flag_for_review(session, unit="command", kind="pulse_failed", severity="low", company_id=company_id,
                            message=f"The figures from '{source.code}' could not be collected: {error}"[:500],
                            dedupe_key=f"pulse-failed:{source.code}:{company_id}:{day}")
    return stored


def _combine(values: list[tuple[date, Decimal]], kind: str) -> Decimal | None:
    if not values:
        return None
    total = sum((v for _, v in values), Decimal(0))
    return total / len(values) if kind == "percent" else total


def summarise(session: Session, context: RequestContext, company_id: UUID, date_from: date,
              date_to: date) -> list[PulseRow]:
    """The figures the user may see for a period, set against the period of the same length just before it.

    Money and counts are added up over the days; percentages are averaged. Branch figures are visible to people whose
    role covers that branch; company-wide figures to people whose role covers the company.
    """
    span = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)
    rows = repo.figures_between(session, company_id, prev_from, date_to)
    grouped: dict[tuple[str, UUID | None], dict[str, Any]] = {}
    for r in rows:
        if not context.can(COMMAND_VIEW, company_id=company_id, branch_id=r.branch_id):
            continue
        g = grouped.setdefault((r.metric, r.branch_id), {"label": r.label, "kind": r.kind, "name": r.branch_name,
                                                          "better": r.higher_is_better, "now": [], "before": []})
        (g["now"] if r.day >= date_from else g["before"]).append((r.day, Decimal(r.value)))
    out = []
    for (metric, branch_id), g in grouped.items():
        value = _combine(g["now"], g["kind"])
        if value is None:
            continue
        out.append(PulseRow(metric, g["label"], g["kind"], value, _combine(g["before"], g["kind"]), branch_id,
                            g["name"], g["better"]))
    out.sort(key=lambda p: (p.branch_id is not None, p.branch_name or "", p.metric))
    return out
