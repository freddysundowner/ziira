"""How much of the job's work the customer has agreed to.

When an estimate has been sent, work beyond the approved amount needs a fresh approval (an *additional work* estimate).
A business chooses what happens meanwhile (job settings): nothing, a warning on the job, or a block. A job nobody
quoted (a walk-in fix priced at the counter) is never checked.
"""

from dataclasses import dataclass
from decimal import Decimal

from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import claims_link, totals
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event
from ziira.sdk import Conflict, Session


@dataclass(frozen=True)
class Approval:
    mode: str                        # off | warn | block
    quoted: bool                     # an estimate was sent, so the customer's agreement is the limit
    approved_total: Decimal
    live_total: Decimal
    extra: Decimal                   # work beyond what is approved (never negative)


def approved_total(session: Session, job: Job) -> Decimal:
    """The total of the approved estimates that are still standing: the approved main estimate and every approved
    additional-work estimate."""
    return sum((e.total for e in repo.estimates(session, job.id) if e.status == "approved"), Decimal(0))


def state(session: Session, job: Job) -> Approval:
    mode = job_settings.get_settings(session, job.company_id).unapproved_work
    live = totals.job_totals(session, job).grand.total
    approved = approved_total(session, job)
    quoted = job.estimate_sent_at is not None
    waiting = any(e.status == "sent" for e in repo.estimates(session, job.id))
    if waiting and approved == 0:
        quoted = False                    # the first estimate is still with the customer: nothing to compare yet
    gate = claims_link.gate(session, job)
    if gate is not None:                  # an insurer job: the payer's answers (and the claim's rule) decide
        claim = claims_link.state(session, job)
        approved = gate.authorised_total
        quoted = claim is not None and claim.status not in ("draft", "closed")
        mode = "off" if (gate.decision_recorded or gate.state == "closed") else gate.policy
    extra = max(live - approved, Decimal(0)) if quoted else Decimal(0)
    return Approval(mode, quoted, approved, live, extra)


def guard(session: Session, job: Job, adding: Decimal, what: str) -> None:
    """Called before a part, labour or charge is added. Blocks, or notes a warning on the timeline, when the new total
    would pass what the customer approved."""
    if adding <= 0:
        return
    current = state(session, job)
    if current.mode == "off" or not current.quoted:
        return
    after = current.live_total + adding
    if after <= current.approved_total:
        return
    over = after - current.approved_total
    if current.mode == "block":
        raise Conflict(f"The customer approved {current.approved_total:,.2f}; {what} would take the job to "
                       f"{after:,.2f}. Send an additional-work estimate and get it approved first")
    add_event(session, job, "note", f"Beyond what the customer approved by {over:,.2f}: {what}")
