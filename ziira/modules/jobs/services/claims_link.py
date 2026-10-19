"""The seam between a job and the claims unit (insurers, fleet owners and other payers who pay for the work).

Jobs never reads the claims unit's tables: everything comes through `claims.public`, and only while that unit is on
for the business. A job that has a claim keeps its id (`job.claim_id`) so lists can filter on it without asking Claims
about every job. The money side belongs to Claims: the payer and the customer are invoiced from the claim's estimate
lines, so a job with a claim is invoiced there (`bill`), not by the job's own invoice.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services.common import add_event, unit_enabled
from ziira.sdk import Session, ValidationFailed, current_context

if TYPE_CHECKING:
    from ziira.modules.claims.public import ApprovedLine, ClaimState, PayerTerms

SOURCE = "job"


@dataclass(frozen=True)
class Gate:
    """May the workshop go ahead with work the payer has not approved? (`policy` is the claims business setting.)"""

    state: str
    allowed: bool
    policy: str
    message: str
    decision_recorded: bool
    authorised_total: Decimal
    unapproved_total: Decimal


def available(session: Session) -> bool:
    return unit_enabled(session, "claims")


def state(session: Session, job: Job) -> "ClaimState | None":
    """The job's claim (live, else the latest closed one), or None."""
    if job.claim_id is None or not available(session):
        return None
    from ziira.modules.claims.public import claim_for_source

    return claim_for_source(session, SOURCE, job.id)


def lines(session: Session, job: Job) -> "list[ApprovedLine]":
    if job.claim_id is None or not available(session):
        return []
    from ziira.modules.claims.public import approved_lines

    return approved_lines(session, SOURCE, job.id)


def gate(session: Session, job: Job) -> Gate | None:
    if job.claim_id is None or not available(session):
        return None
    from ziira.modules.claims.public import work_gate

    found = work_gate(session, SOURCE, job.id)
    if not found.has_claim:
        return None
    return Gate(found.state, found.allowed, found.policy, found.message, found.decision_recorded,
                found.authorised_total, found.unapproved_total)


def terms(session: Session, job: Job) -> "PayerTerms | None":
    """The payer's rates and parts rules, to suggest prices on the job's labour and parts."""
    if job.claim_id is None or not available(session):
        return None
    from ziira.modules.claims.public import payer_terms

    return payer_terms(session, SOURCE, job.id)


def waiting_on_payer(session: Session, jobs: list[Job]) -> set[UUID]:
    """Ids of those jobs whose claim is waiting for the payer's answer."""
    wanted = {j.id for j in jobs if j.claim_id is not None}
    if not wanted or not available(session):
        return set()
    from ziira.modules.claims.public import claims_for_sources

    return {job_id for job_id, claim in claims_for_sources(session, SOURCE, wanted).items()
            if claim.waiting_on == "payer" and claim.status != "closed"}


def open_claim(session: Session, job: Job, *, payer_id: UUID, policy_number: str | None = None,
               claim_number: str | None = None, excess_amount: Decimal = Decimal(0), loss_date: object = None,
               customer_id: UUID | None = None) -> "ClaimState":
    """Open a claim for the job (the insurer, fleet owner or other payer pays all or part). The job needs a customer
    record: the customer's own share (the excess) is invoiced to them. Needs 'jobs.manage' and 'claims.manage'."""
    from datetime import date

    from ziira.modules.claims.public import open_claim as open_

    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    if not available(session):
        raise ValidationFailed("Insurer and fleet claims need the Claims unit to be switched on")
    if job.claim_id is not None:
        raise ValidationFailed("This job already has a claim")
    if customer_id is None and job.customer_id is None:
        from ziira.modules.jobs.services import invoicing

        customer_id = invoicing.invoice_customer(session, job)
    created = open_(session, company_id=job.company_id, branch_id=job.branch_id, payer_id=payer_id,
                    source_type=SOURCE, source_id=job.id, customer_id=customer_id or job.customer_id,
                    subject=job.title, policy_number=policy_number, claim_number=claim_number,
                    excess_amount=excess_amount, loss_date=loss_date if isinstance(loss_date, date) else None)
    link(session, job, created.id, created.number, created.payer_name)
    return created


def link(session: Session, job: Job, claim_id: UUID, number: str, payer_name: str) -> None:
    """Remember the claim on the job and say so on the timeline (once)."""
    if job.claim_id == claim_id:
        return
    job.claim_id = claim_id
    session.flush()
    add_event(session, job, "claim", f"Claim {number} opened with {payer_name}")


def draft_estimate(session: Session, job: Job, *, kind: str = "original") -> UUID:
    """Start a draft claim estimate from the job's parts and labour so far (the payer's labour rate for the work type is
    used for labour with no price; customer-supplied parts are left out). Returns the claim estimate's id."""
    from ziira.modules.claims.public import EstimateLineSpec
    from ziira.modules.claims.public import draft_estimate as draft

    if job.claim_id is None:
        raise ValidationFailed("Open a claim for this job first")
    specs: list[EstimateLineSpec] = []
    for part in repo.parts(session, job.id, include_voided=False):
        if part.source == "customer_supplied":
            continue
        specs.append(EstimateLineSpec("parts", part.description, part.quantity, part.unit_price, None,
                                      part.part_class, part.product_id))
    for work in repo.labour(session, job.id, include_voided=False):
        kind_ = "paint" if work.work_type_code == "paint" else "labour"
        if work.flat_price is not None:
            specs.append(EstimateLineSpec(kind_, f"{work.description} (fixed price)", Decimal(1), work.flat_price,
                                          work.work_type_code))
        else:
            specs.append(EstimateLineSpec(kind_, work.description, work.hours, work.rate, work.work_type_code))
    for charge in repo.charges(session, job.id, include_voided=False):
        specs.append(EstimateLineSpec("other", charge.description, charge.quantity, charge.unit_price))
    if not specs:
        raise ValidationFailed("Put parts or labour on the job first: the estimate for the payer is made from them")
    estimate_id = draft(session, SOURCE, job.id, specs, kind=kind)
    add_event(session, job, "claim", "Estimate for the payer drafted from the job")
    return estimate_id


def complete(session: Session, job: Job, *, signed_by: str, note: str | None = None) -> None:
    """Record the completion sign-off on the job's claim (needs 'jobs.manage' here and 'claims.manage' there)."""
    from ziira.modules.claims.public import complete_claim_work

    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    if job.claim_id is None:
        raise ValidationFailed("This job has no claim")
    complete_claim_work(session, SOURCE, job.id, signed_by=signed_by, note=note)
    add_event(session, job, "claim", f"Work signed off by {signed_by.strip()}")


def bill(session: Session, job: Job) -> tuple[str, Decimal]:
    """Invoice the claim: the payer's invoice (less the excess) and the customer's invoice. Returns the numbers for the
    timeline and the total. The job is then invoiced (and locked); its invoice number reads as both."""
    from ziira.modules.claims.public import bill_claim

    made = bill_claim(session, SOURCE, job.id)
    parts = []
    if made.payer_invoice_number:
        parts.append(f"{made.payer_invoice_number} (payer)")
    if made.customer_invoice_number:
        parts.append(f"{made.customer_invoice_number} (customer)")
    return " / ".join(parts) or "none", made.payer_amount + made.customer_amount
