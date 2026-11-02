"""Turn a booked appointment (Bookings) into a job: the customer arrives for the slot they booked and the workshop
takes the vehicle in with the customer already filled in. Bookings is read only through its public functions."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text

from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import jobs as jobs_service
from ziira.modules.jobs.services.common import add_event, unit_enabled
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, company_today, company_zone


@dataclass(frozen=True)
class AppointmentIntake:
    title: str | None = None
    asset_id: UUID | None = None
    new_asset: jobs_service.NewAsset | None = None
    description: str | None = None
    condition_notes: str | None = None
    odometer_in: Decimal | None = None
    fuel_level: str | None = None
    key_tag: str | None = None
    belongings: str | None = None
    acknowledged_by_name: str | None = None
    job_type_code: str | None = None
    assignee_id: UUID | None = None
    promised_at: date | None = None
    checklist_items: list[str] | None = None


def job_for(session: Session, appointment_id: UUID) -> Job | None:
    return session.scalar(select(Job).where(Job.appointment_id == appointment_id))


def waiting(session: Session, branch_id: UUID, day: date | None = None) -> list[dict[str, object]]:
    """The day's appointments at a branch (default today) that are still expected and have no job yet, earliest first.
    Empty when Bookings is not switched on or the person may not see it."""
    if not unit_enabled(session, "bookings"):
        return []
    from ziira.modules.bookings.public import appointments_between
    from ziira.modules.crm.public import find_customer
    from ziira.sdk import Forbidden

    company_id = session.execute(text("select company_id from kernel.branch where id = :b"),
                                 {"b": str(branch_id)}).scalar_one_or_none()
    if company_id is None:
        raise NotFound("Branch not found")
    zone = company_zone(session, company_id)
    start = datetime.combine(day or company_today(session, company_id), time.min, tzinfo=zone)
    try:
        rows = appointments_between(session, branch_id, start, start + timedelta(days=1),
                                    statuses=["requested", "confirmed", "checked_in"])
    except Forbidden:
        return []
    taken = {a for (a,) in session.execute(select(Job.appointment_id).where(
        Job.appointment_id.in_([r.id for r in rows]))).all()} if rows else set()
    out: list[dict[str, object]] = []
    for r in rows:
        if r.id in taken:
            continue
        name = r.client_name
        if r.customer_id is not None and unit_enabled(session, "crm"):
            found = find_customer(session, r.customer_id)
            name = found.name if found is not None else name
        out.append({"id": r.id, "number": r.number, "starts_at": r.starts_at, "status": r.status,
                    "customer_id": r.customer_id, "customer_name": name})
    return out


def receive_from_appointment(session: Session, appointment_id: UUID, intake: AppointmentIntake) -> Job:
    """Take the vehicle in for a booked appointment. Needs 'jobs.manage' at the branch. One job per appointment."""
    if not unit_enabled(session, "bookings"):
        raise ValidationFailed("Bookings is not switched on for this business")
    from ziira.modules.bookings.public import find_appointment

    appt = find_appointment(session, appointment_id)
    if appt is None:
        raise NotFound("Appointment not found")
    if appt.status in ("cancelled", "no_show"):
        raise ValidationFailed("That appointment was cancelled or the customer did not come")
    if job_for(session, appointment_id) is not None:
        raise Conflict("A job was already made for this appointment")
    job = jobs_service.receive_job(
        session, company_id=appt.company_id, branch_id=appt.branch_id, customer_id=appt.customer_id,
        title=(intake.title or f"Booked visit {appt.number}").strip(), asset_id=intake.asset_id,
        new_asset=intake.new_asset, description=intake.description, condition_notes=intake.condition_notes,
        job_type_code=intake.job_type_code, odometer_in=intake.odometer_in, fuel_level=intake.fuel_level,
        key_tag=intake.key_tag, belongings=intake.belongings, acknowledged_by_name=intake.acknowledged_by_name,
        assignee_id=intake.assignee_id, promised_at=intake.promised_at, checklist_items=intake.checklist_items)
    job.appointment_id = appt.id
    session.flush()
    add_event(session, job, "intake", f"Made from appointment {appt.number}")
    return job
