"""A mechanic's clock on a job. Start it when the work starts, stop it when it ends: the time worked goes on the job
as a labour line (source 'timer', so it counts as booked hours). One clock per person at a time."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select

from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobTimer
from ziira.modules.jobs.services import parts
from ziira.modules.jobs.services.common import add_event, clean, load_job
from ziira.modules.jobs.services.jobs import require_editable
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, current_context

MIN_HOURS = Decimal("0.01")


def running_for(session: Session, user_id: UUID) -> JobTimer | None:
    return session.scalar(select(JobTimer).where(JobTimer.user_id == user_id, JobTimer.stopped_at.is_(None)))


def on_job(session: Session, job_id: UUID, *, only_running: bool = False) -> list[JobTimer]:
    query = select(JobTimer).where(JobTimer.job_id == job_id)
    if only_running:
        query = query.where(JobTimer.stopped_at.is_(None))
    return list(session.scalars(query.order_by(JobTimer.started_at)))


def hours_between(start: datetime, end: datetime) -> Decimal:
    """Elapsed time in hours to two places, never less than one hundredth (a stopped clock is never free)."""
    seconds = Decimal(max((end - start).total_seconds(), 0))
    return max((seconds / Decimal(3600)).quantize(MIN_HOURS, rounding=ROUND_HALF_UP), MIN_HOURS)


def start(session: Session, job_id: UUID, *, note: str | None = None) -> JobTimer:
    """Start the signed-in person's clock on the job. Needs 'jobs.manage'. One clock at a time per person."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    assert ctx.user_id is not None
    mine = running_for(session, ctx.user_id)
    if mine is not None:
        if mine.job_id == job.id:
            return mine
        other = repo.get(session, Job, mine.job_id)
        raise Conflict(f"Your clock is already running on {other.number if other else 'another job'}. Stop it first")
    row = JobTimer(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, user_id=ctx.user_id,
                   note=clean(note, 300))
    repo.add(session, row)
    add_event(session, job, "labour", "Clock started")
    return row


def stop(session: Session, job_id: UUID, *, description: str | None = None, discard: bool = False) -> JobTimer:
    """Stop the signed-in person's clock on the job and put the time worked on it as labour (or, with `discard`,
    throw the time away). Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    assert ctx.user_id is not None
    timer = running_for(session, ctx.user_id)
    if timer is None or timer.job_id != job.id:
        raise NotFound("You have no clock running on this job")
    now = datetime.now(UTC)
    timer.stopped_at = now
    if discard:
        session.flush()
        add_event(session, job, "labour", "Clock stopped and the time thrown away")
        return timer
    require_editable(session, job)
    hours = hours_between(timer.started_at, now)
    if hours > 24:
        raise ValidationFailed(f"This clock has run for {hours:,.0f} hours. Stop it with 'discard', then add the real "
                               "hours by hand")
    what = clean(description, 300) or timer.note or f"Work on {job.title}"
    line = parts.add_labour(session, job.id, hours=hours, assignee_id=timer.user_id, source="timer",
                            source_id=timer.id, description=what)
    timer.labour_id = line.id
    session.flush()
    return timer
