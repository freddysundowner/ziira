"""Courtesy and hire cars: a car (an item of kind 'courtesy-car') lent to a customer while theirs is in the workshop.
Only out and in dates, the readings and the fuel level are kept: this is not a rental business."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, Loan
from ziira.modules.jobs.services import access, assets
from ziira.modules.jobs.services.common import add_event, clean, load_job
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, current_context

COURTESY_KIND = "courtesy-car"


def lend(session: Session, job_id: UUID, *, asset_id: UUID, borrower_name: str | None = None,
         due_at: date | None = None, odometer_out: Decimal | None = None, fuel_out: str | None = None,
         note: str | None = None) -> Loan:
    """Lend a courtesy car to the customer of a job. The car is an item with kind 'courtesy-car'; it can be out on one
    loan at a time. Needs 'jobs.manage'."""
    job = load_job(session, job_id)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    car = assets.load_asset(session, asset_id)
    if car.company_id != job.company_id or car.kind != COURTESY_KIND:
        raise ValidationFailed("Pick one of the courtesy cars (items of kind 'courtesy-car')")
    if car.id == job.asset_id:
        raise ValidationFailed("That is the customer's own vehicle")
    if odometer_out is not None and odometer_out < 0:
        raise ValidationFailed("The odometer reading is not valid")
    row = Loan(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, asset_id=car.id,
               borrower_name=clean(borrower_name, 160) or job.customer_name, due_at=due_at,
               odometer_out=odometer_out, fuel_out=clean(fuel_out, 40), note=clean(note, 300))
    try:
        with session.begin_nested():
            repo.add(session, row)
    except IntegrityError:
        raise Conflict(f"{car.label} is already out on loan") from None
    if odometer_out is not None:
        assets.record_odometer(session, car, odometer_out)
    add_event(session, job, "loan", f"Courtesy car {car.label} lent out")
    audit_record(session, "lend", "jobs.loan", row.id, {"asset": car.label, "job": job.number})
    return row


def take_back(session: Session, loan_id: UUID, *, odometer_in: Decimal | None = None,
              fuel_in: str | None = None, note: str | None = None) -> Loan:
    """The courtesy car came back. Allowed on an invoiced job. Needs 'jobs.manage'."""
    row = repo.get(session, Loan, loan_id, lock=True)
    if row is None:
        raise NotFound("Loan not found")
    job = load_job(session, row.job_id)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    if row.in_at is not None:
        raise Conflict("The car is already back")
    low = row.odometer_out is not None and odometer_in is not None and odometer_in < row.odometer_out
    if odometer_in is not None and (odometer_in < 0 or low):
        raise ValidationFailed("The reading on return cannot be lower than on the way out")
    row.in_at, row.odometer_in, row.fuel_in = datetime.now(UTC), odometer_in, clean(fuel_in, 40)
    if note:
        row.note = clean(f"{row.note or ''} {note}", 300)
    session.flush()
    car = assets.load_asset(session, row.asset_id)
    if odometer_in is not None:
        assets.record_odometer(session, car, odometer_in)
    add_event(session, job, "loan", f"Courtesy car {car.label} returned")
    return row


def out_now(session: Session, company_id: UUID) -> list[Loan]:
    """Cars out on loan right now (for jobs the user may see)."""
    rows = session.execute(select(Loan, Job).join(Job, Job.id == Loan.job_id).where(
        Loan.in_at.is_(None), Job.company_id == company_id).order_by(Loan.out_at))
    return [loan for loan, job in rows if access.can_view(job.company_id, job.branch_id)]
