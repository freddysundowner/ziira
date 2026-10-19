"""Events published and handled by the Jobs and Repairs module.

Publishes: job.received, job.status_changed, job.estimate_approved, job.estimate_declined, job.collected, job.invoiced
Subscribes: goods.received (parts ordered for a job that Purchasing has now received are marked as arrived)
"""

from typing import TYPE_CHECKING
from uuid import UUID

from ziira.modules.jobs.services import jobs, parts
from ziira.modules.jobs.services.common import add_event
from ziira.sdk import Event, Session, subscribe

if TYPE_CHECKING:
    from ziira.modules.jobs.repository.models import Job


@subscribe("goods.received")
def on_goods_received(session: Session, event: Event) -> None:
    """A purchase order was received: the job parts waiting on it have arrived."""
    order_id = event.payload.get("order_id")
    if order_id is not None:
        parts.note_goods_received(session, UUID(str(order_id)))


# --------------------------------------------------------------------------- the job's insurer claim
CLAIM_NOTES = {
    "claim.estimate_submitted": "Estimate sent to the payer",
    "claim.response_recorded": "The payer answered the estimate",
    "claim.authorised": "The payer authorised work",
    "claim.completed": "The work was signed off",
    "claim.closed": "The claim was closed",
}


def _job_of(session: Session, event: Event) -> "Job | None":
    from ziira.modules.jobs.repository import jobs_repo as repo
    from ziira.modules.jobs.repository.models import Job

    if event.payload.get("source_type") != "job" or event.payload.get("source_id") is None:
        return None
    return repo.get(session, Job, UUID(str(event.payload["source_id"])))


@subscribe("claim.created")
def on_claim_created(session: Session, event: Event) -> None:
    """A claim was opened for a job (from here or from Claims): the job remembers it."""
    job = _job_of(session, event)
    if job is not None and job.claim_id is None:
        job.claim_id = event.aggregate_id
        session.flush()
        add_event(session, job, "claim", f"Claim {event.payload.get('number')} opened")


def _note_on_job(session: Session, event: Event) -> None:
    job = _job_of(session, event)
    if job is not None:
        add_event(session, job, "claim", f"{CLAIM_NOTES[event.type]} ({event.payload.get('number')})")


for _name in CLAIM_NOTES:
    subscribe(_name)(_note_on_job)


@subscribe("claim.estimate_submitted")
def on_claim_estimate_submitted(session: Session, event: Event) -> None:
    """The estimate went to the payer: the job waits for the insurer (when the business has that stage)."""
    job = _job_of(session, event)
    if job is not None:
        jobs.move_to_code(session, job, "waiting_for_insurer", "Waiting for the payer's answer")


@subscribe("claim.authorised")
def on_claim_authorised(session: Session, event: Event) -> None:
    """The payer approved work: the job is approved and the workshop may go ahead."""
    job = _job_of(session, event)
    if job is not None and not jobs.move_to_role(session, job, "approved", "The payer authorised work"):
        jobs.move_to_code(session, job, "in_progress", "The payer authorised work")


@subscribe("claim.invoiced")
def on_claim_invoiced(session: Session, event: Event) -> None:
    """Claims billed the claim (from its own screen): the job reads as invoiced and is locked."""
    job = _job_of(session, event)
    if job is None or job.invoiced_at is not None:
        return
    numbers = " / ".join(x for x in (
        str(event.payload.get("payer_invoice_number") or ""), str(event.payload.get("customer_invoice_number") or ""))
        if x)
    from datetime import UTC, datetime

    job.invoice_number, job.invoiced_at = (numbers or "claim")[:60], datetime.now(UTC)
    session.flush()
    add_event(session, job, "invoice", f"Claim invoiced {numbers}".strip())
