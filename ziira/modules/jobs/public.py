"""Public interface of the Jobs and Repairs module.

Other units (industry packs, Time and Billing) use these. Jobs publishes events (`job.received`, `job.status_changed`,
`job.estimate_approved`, `job.estimate_declined`, `job.collected`, `job.invoiced`); packs seed through the
`kernel.industry_seeder` extension point (see hooks.py) or call `seed_statuses` directly.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.jobs.domain.workflow import DEFAULT as DEFAULT_WORKFLOW
from ziira.modules.jobs.domain.workflow import Definition, StatusDef
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import parts, statuses
from ziira.modules.jobs.services import settings as job_settings
from ziira.sdk import Session, ValidationFailed

__all__ = ["DEFAULT_WORKFLOW", "Definition", "JobView", "StatusDef", "add_labour_line", "find_job",
           "parse_definition", "seed_checklist", "seed_statuses"]


def parse_definition(data: dict[str, Any]) -> Definition:
    """A workflow from plain data, for packs that ship it as a file: `{"statuses": [{"code", "name", "kind",
    "role"?}], "moves": [["from_code", "to_code"], ...]}`."""
    try:
        stages = [StatusDef(str(s["code"]), str(s["name"]), str(s["kind"]), s.get("role")) for s in data["statuses"]]
        moves = [(str(a), str(b)) for a, b in data.get("moves", [])]
    except (KeyError, TypeError, ValueError):
        raise ValidationFailed("A workflow lists statuses (code, name, kind) and moves (from, to)") from None
    return Definition(stages, moves)


def seed_statuses(session: Session, company_id: UUID, definition: Definition) -> tuple[int, int]:
    """Add the stages and moves of `definition` that the company does not have (existing ones are never changed or
    removed; running it again changes nothing). Returns (stages added, moves added)."""
    done = statuses.seed_statuses(session, company_id, definition)
    return done.statuses_added, done.moves_added


def seed_checklist(session: Session, company_id: UUID, name: str, items: list[str],
                   asset_kind: str | None = None) -> bool:
    """Add an intake checklist unless the company has one with this name. True when added."""
    return job_settings.seed_template(session, company_id, name, items, asset_kind)


@dataclass(frozen=True)
class JobView:
    """What other units need to know about a job."""

    id: UUID
    company_id: UUID
    branch_id: UUID
    number: str
    customer_id: UUID | None
    asset_id: UUID | None
    status_role: str | None
    invoice_id: UUID | None


def find_job(session: Session, job_id: UUID) -> JobView | None:
    job = repo.get(session, Job, job_id)
    if job is None:
        return None
    stage = repo.statuses_by_ids(session, {job.status_id})[job.status_id]
    return JobView(job.id, job.company_id, job.branch_id, job.number, job.customer_id, job.asset_id, stage.role,
                   job.invoice_id)


def add_labour_line(session: Session, job_id: UUID, *, hours: Decimal, description: str, source: str,
                    source_id: UUID, rate: Decimal | None = None, assignee_id: UUID | None = None,
                    work_date: date | None = None) -> UUID:
    """Put time worked on a job as a labour line (Time and Billing's timers use this). Idempotent by (`source`,
    `source_id`): asking again returns the same line. The caller needs 'jobs.manage'; a locked job refuses."""
    line = parts.add_labour(session, job_id, hours=hours, description=description, rate=rate,
                            assignee_id=assignee_id, work_date=work_date, source=source, source_id=source_id)
    return line.id
