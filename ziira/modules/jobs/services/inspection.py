"""The vehicle health check (multi-point inspection): a list of things to look at, each marked green (good), amber
(needs attention soon) or red (needs attention now), with a note. It starts from a usual list and the workshop can add
and remove lines on a job. The customer sees the amber and red lines on the estimate page."""

from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import InspectionItem
from ziira.modules.jobs.services.common import add_event, clean, load_job
from ziira.modules.jobs.services.jobs import require_editable
from ziira.sdk import NotFound, Session, ValidationFailed, current_context

RATINGS = ("pending", "green", "amber", "red", "na")
MAX_ITEMS = 120

USUAL: dict[str, list[str]] = {
    "Brakes": ["Front pads and discs", "Rear pads and discs or shoes", "Brake fluid", "Handbrake"],
    "Tyres and wheels": ["Front left tyre", "Front right tyre", "Rear left tyre", "Rear right tyre", "Spare tyre",
                         "Wheel alignment"],
    "Lights and wipers": ["Headlights and indicators", "Brake and tail lights", "Wipers and washer"],
    "Engine and fluids": ["Engine oil level and colour", "Coolant", "Power steering fluid", "Drive belts",
                          "Air filter", "Leaks under the engine"],
    "Battery and electrics": ["Battery condition", "Starter and charging", "Warning lights on the dashboard"],
    "Steering and suspension": ["Shock absorbers", "Ball joints and bushes", "Steering play"],
    "Exhaust and underbody": ["Exhaust and mountings", "Underbody rust or damage"],
    "Body and glass": ["Windscreen", "Mirrors", "Doors, locks and seat belts"],
}


def items(session: Session, job_id: UUID) -> list[InspectionItem]:
    return repo.inspection_items(session, job_id)


def start(session: Session, job_id: UUID) -> list[InspectionItem]:
    """Begin the health check with the usual list (nothing happens when it was already begun). Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    if repo.inspection_items(session, job.id):
        return repo.inspection_items(session, job.id)
    position = 0
    for section, labels in USUAL.items():
        for label in labels:
            repo.add(session, InspectionItem(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id,
                                             section=section, label=label, position=position))
            position += 10
    session.flush()
    add_event(session, job, "note", "Vehicle health check started")
    return repo.inspection_items(session, job.id)


def add_item(session: Session, job_id: UUID, *, section: str, label: str) -> InspectionItem:
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    existing = repo.inspection_items(session, job.id)
    if len(existing) >= MAX_ITEMS:
        raise ValidationFailed(f"At most {MAX_ITEMS} lines in a health check")
    sec, name = clean(section, 80), clean(label, 160)
    if sec is None or name is None:
        raise ValidationFailed("Say which part (for example Brakes) and what to look at")
    row = InspectionItem(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, section=sec, label=name,
                         position=max((x.position for x in existing), default=0) + 10)
    repo.add(session, row)
    return row


def rate(session: Session, job_id: UUID, item_id: UUID, *, rating: str | None = None, note: str | None = None,
         label: str | None = None) -> InspectionItem:
    """Mark a line green, amber, red or not applicable, and/or write a note on it."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    row = repo.get(session, InspectionItem, item_id)
    if row is None or row.job_id != job.id:
        raise NotFound("That line was not found")
    if rating is not None:
        if rating not in RATINGS:
            raise ValidationFailed("A line is green, amber, red, not applicable or still to check")
        row.rating = rating
    if note is not None:
        row.note = clean(note, 500)
    if label is not None:
        row.label = clean(label, 160) or row.label
    row.updated_by = current_context().user_id
    session.flush()
    return row


def remove_item(session: Session, job_id: UUID, item_id: UUID) -> None:
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    row = repo.get(session, InspectionItem, item_id)
    if row is None or row.job_id != job.id:
        raise NotFound("That line was not found")
    session.delete(row)
    session.flush()


def summary(rows: list[InspectionItem]) -> dict[str, int]:
    out = {r: 0 for r in RATINGS}
    for row in rows:
        out[row.rating] += 1
    return out


def for_customer(rows: list[InspectionItem]) -> list[InspectionItem]:
    """What the customer is shown: the lines that need attention, worst first."""
    order = {"red": 0, "amber": 1}
    return sorted((r for r in rows if r.rating in order), key=lambda r: (order[r.rating], r.position))

