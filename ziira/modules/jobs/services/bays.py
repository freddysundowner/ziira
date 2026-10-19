"""The bay board: bays (a lift, a paint booth, a bench) and jobs scheduled into them. A bay cannot hold two jobs at once
(a database rule, so two people booking the same bay cannot both win)."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ziira.modules.jobs.permissions import JOBS_MANAGE, JOBS_SETTINGS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Bay, BayBooking, Job
from ziira.modules.jobs.services import access
from ziira.modules.jobs.services.common import add_event, clean, load_job
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, check_company, current_context

MAX_BAYS = 60
MAX_SPAN = timedelta(days=30)


def list_bays(session: Session, company_id: UUID, branch_id: UUID | None = None, *,
              only_active: bool = False) -> list[Bay]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    query = select(Bay).where(Bay.company_id == company_id)
    if branch_id is not None:
        query = query.where(Bay.branch_id == branch_id)
    if only_active:
        query = query.where(Bay.is_active)
    return [b for b in session.scalars(query.order_by(Bay.position, Bay.name))
            if access.can_view(b.company_id, b.branch_id)]


def create_bay(session: Session, *, company_id: UUID, branch_id: UUID, name: str, position: int = 0) -> Bay:
    """Add a bay to a branch. Needs 'jobs.settings'."""
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    if not name.strip():
        raise ValidationFailed("Give the bay a name")
    existing = list(session.scalars(select(Bay).where(Bay.branch_id == branch_id)))
    if any(b.name.lower() == name.strip().lower() for b in existing):
        raise Conflict("This branch already has a bay with this name")
    if len(existing) >= MAX_BAYS:
        raise ValidationFailed(f"At most {MAX_BAYS} bays per branch")
    row = Bay(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
              name=name.strip()[:60], position=position)
    repo.add(session, row)
    audit_record(session, "create", "jobs.bay", row.id, {"name": row.name})
    return row


def update_bay(session: Session, bay_id: UUID, **changes: object) -> Bay:
    row = repo.get(session, Bay, bay_id)
    if row is None or not access.can_view(row.company_id, row.branch_id):
        raise NotFound("Bay not found")
    current_context().require(JOBS_SETTINGS, company_id=row.company_id, branch_id=row.branch_id)
    if isinstance(changes.get("name"), str) and str(changes["name"]).strip():
        row.name = str(changes["name"]).strip()[:60]
    if isinstance(changes.get("position"), int):
        row.position = int(str(changes["position"]))
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.updated_by = current_context().user_id
    session.flush()
    return row


def book(session: Session, job_id: UUID, *, bay_id: UUID, starts_at: datetime, ends_at: datetime,
         note: str | None = None) -> BayBooking:
    """Put a job in a bay for a time. Refused when the bay is busy then. Needs 'jobs.manage'."""
    job = load_job(session, job_id)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    bay = repo.get(session, Bay, bay_id)
    if bay is None or bay.branch_id != job.branch_id or not bay.is_active:
        raise ValidationFailed("That bay is not one of this branch's bays")
    if ends_at <= starts_at or ends_at - starts_at > MAX_SPAN:
        raise ValidationFailed("The end must be after the start, and within 30 days")
    row = BayBooking(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, bay_id=bay.id,
                     starts_at=starts_at, ends_at=ends_at, note=clean(note, 300))
    try:
        with session.begin_nested():
            repo.add(session, row)
    except IntegrityError:
        raise Conflict(f"{bay.name} is already booked at that time") from None
    add_event(session, job, "bay", f"In {bay.name} from {starts_at.strftime('%d %b %H:%M')}")
    audit_record(session, "book", "jobs.bay_booking", row.id, {"bay": bay.name, "job": job.number})
    return row


def cancel(session: Session, booking_id: UUID) -> BayBooking:
    row = repo.get(session, BayBooking, booking_id)
    if row is None:
        raise NotFound("Booking not found")
    job = load_job(session, row.job_id)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    if row.cancelled_at is None:
        row.cancelled_at, row.cancelled_by = datetime.now(UTC), ctx.user_id
        session.flush()
        add_event(session, job, "bay", "Bay booking cancelled")
    return row


def board(session: Session, company_id: UUID, branch_id: UUID, day_from: date,
          days: int = 7) -> list[tuple[BayBooking, Job]]:
    """Bookings that touch the days from `day_from` for `days` days, with their jobs (for the bay board)."""
    if not access.can_view(company_id, branch_id):
        raise NotFound("Branch not found")
    start = datetime.combine(day_from, datetime.min.time(), tzinfo=UTC) - timedelta(hours=14)
    end = start + timedelta(days=min(days, 31)) + timedelta(hours=28)
    rows = session.execute(select(BayBooking, Job).join(Job, Job.id == BayBooking.job_id).where(
        Job.company_id == company_id, Job.branch_id == branch_id, BayBooking.cancelled_at.is_(None),
        BayBooking.starts_at < end, BayBooking.ends_at > start).order_by(BayBooking.starts_at))
    return [(b, j) for b, j in rows]
