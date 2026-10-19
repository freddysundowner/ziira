"""Small helpers shared by the jobs services."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobEvent
from ziira.modules.jobs.services import access
from ziira.sdk import NotFound, Session, ValidationFailed, current_context


def unit_enabled(session: Session, unit: str) -> bool:
    """True when the unit is enabled for this business (optional units may be missing)."""
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def user_id() -> UUID | None:
    return current_context().user_id


def check_person(session: Session, person_id: UUID | None) -> None:
    """A staff member of this business, or ValidationFailed."""
    if person_id is not None and session.execute(text("select 1 from kernel.app_user where id = :u"),
                                                 {"u": str(person_id)}).first() is None:
        raise ValidationFailed("That person was not found")


def names_of(session: Session, ids: set[UUID | None]) -> dict[UUID, str]:
    """Display names of staff members, for screens."""
    wanted = [str(i) for i in ids if i is not None]
    if not wanted:
        return {}
    rows = session.execute(text("select id, full_name from kernel.app_user where id = any(cast(:ids as uuid[]))"),
                           {"ids": wanted})
    return {r.id: r.full_name for r in rows}


def load_job(session: Session, job_id: UUID, *, lock: bool = False) -> Job:
    """A job the user may see, or NotFound."""
    job = repo.get(session, Job, job_id, lock=lock)
    if job is None or not access.can_view(job.company_id, job.branch_id):
        raise NotFound("Job not found")
    return job


def add_event(session: Session, job: Job, kind: str, note: str | None = None, *, from_status: UUID | None = None,
              to_status: UUID | None = None) -> JobEvent:
    ctx = current_context()
    event = JobEvent(tenant_id=ctx.tenant_id, job_id=job.id, kind=kind, note=(note or "").strip()[:1000] or None,
                     from_status_id=from_status, to_status_id=to_status, created_by=ctx.user_id)
    repo.add(session, event)
    return event


def clean(value: str | None, limit: int) -> str | None:
    text_ = (value or "").strip()
    return text_[:limit] or None
