"""Jobs' figures for the Command Center."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.command.public import Figure, FigureKind, PulseSource
from ziira.sdk import Session, company_setting


class JobsPulse(PulseSource):
    """Work in the shop: jobs open, late, ready to be collected, waiting for an answer, and taken in today."""

    code = "jobs"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        tz = str(company_setting(session, company_id, "timezone"))
        live = session.execute(text(
            "select j.branch_id, "
            "count(*) filter (where s.kind in ('open', 'waiting')) as open_jobs, "
            "count(*) filter (where s.kind in ('open', 'waiting') and j.promised_at < :day) as late, "
            "count(*) filter (where s.role = 'ready') as ready, "
            "count(*) filter (where e.id is not null) as awaiting "
            "from jobs.job j join jobs.job_status s on s.id = j.status_id "
            "left join lateral (select id from jobs.estimate where job_id = j.id and status = 'sent' limit 1) e "
            "on true where j.company_id = :c and s.kind <> 'closed' group by j.branch_id"),
            {"c": company_id, "day": day}).all()
        today = session.execute(text(
            "select branch_id, count(*) as n from jobs.job where company_id = :c "
            "and (received_at at time zone :tz)::date = :day group by branch_id"),
            {"c": company_id, "tz": tz, "day": day}).all()

        def build(metric: str, label: str, rows: Sequence[Row[Any]], column: str, better: bool | None) -> list[Figure]:
            kind: FigureKind = "count"
            per_branch = {r.branch_id: Decimal(getattr(r, column)) for r in rows}
            total = sum(per_branch.values(), Decimal(0))
            return [Figure(metric, label, kind, total, None, better),
                    *(Figure(metric, label, kind, v, b, better) for b, v in per_branch.items())]

        return [
            *build("jobs.open", "Jobs in progress", live, "open_jobs", None),
            *build("jobs.late", "Jobs past their promised date", live, "late", False),
            *build("jobs.ready_for_collection", "Ready to be collected", live, "ready", None),
            *build("jobs.awaiting_approval", "Estimates waiting for an answer", live, "awaiting", None),
            *build("jobs.received_today", "Items taken in today", today, "n", None),
        ]
