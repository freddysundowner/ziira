"""Claims' figures for the Command Center."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.command.public import Figure, FigureKind, PulseSource
from ziira.sdk import Session


class ClaimsPulse(PulseSource):
    """Claims open, claims waiting for a payer, and what payers have been invoiced and not yet paid."""

    code = "claims"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        live = session.execute(text(
            "with live as (select e.* from claims.estimate e where e.company_id = :c and e.status in "
            "('submitted', 'answered') and not exists (select 1 from claims.estimate n where n.lineage_id = "
            "e.lineage_id and n.seq > e.seq and n.status in ('submitted', 'answered'))) "
            "select c.branch_id, count(*) filter (where c.status not in ('settled', 'closed')) as open_claims, "
            "count(distinct c.id) filter (where c.status not in ('settled', 'closed') and exists "
            "  (select 1 from live l join claims.estimate_line x on x.estimate_id = l.id where l.claim_id = c.id "
            "   and x.payer_state in ('pending', 'needs_information'))) as waiting "
            "from claims.claim c where c.company_id = :c group by c.branch_id"), {"c": company_id}).all()

        def build(metric: str, label: str, rows: Sequence[Row[Any]], column: str, better: bool | None) -> list[Figure]:
            kind: FigureKind = "count"
            per_branch = {r.branch_id: Decimal(getattr(r, column)) for r in rows}
            total = sum(per_branch.values(), Decimal(0))
            return [Figure(metric, label, kind, total, None, better),
                    *(Figure(metric, label, kind, v, b, better) for b, v in per_branch.items())]

        return [*build("claims.open", "Claims in progress", live, "open_claims", None),
                *build("claims.waiting_payer", "Claims waiting for a payer", live, "waiting", False)]
