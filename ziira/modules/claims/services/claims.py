"""Use cases: opening a claim, editing it, notes and visits, the payer's authority, completion sign-off and closing.

A claim is made for one job or appointment where someone other than the customer pays (an insurer, a scheme, a fleet
owner, an employer). Estimates, answers and invoices hang off it (see estimates.py, responses.py, invoicing.py).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.claims.permissions import CLAIMS_MANAGE
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim
from ziira.modules.claims.services import access, status
from ziira.modules.claims.services.common import add_event, clean, load_claim, unit_enabled
from ziira.modules.claims.services.settings import load_payer
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
    publish,
)

SOURCES = ("job", "appointment")
CLOSE_REASONS = ("total_loss", "salvage", "cash_in_lieu", "rejected", "withdrawn", "cancelled", "written_off")
NOTE_KINDS = ("note", "assessor_visit", "reinspection")
EDITABLE = ("customer_id", "insured_name", "insured_phone", "subject", "policy_number", "claim_number", "member_number",
            "preauth_ref", "loss_date", "loss_description", "assessor_name", "assessor_phone", "excess_amount")


@dataclass(frozen=True)
class Source:
    number: str
    company_id: UUID
    branch_id: UUID
    customer_id: UUID | None


def resolve_source(session: Session, source_type: str, source_id: UUID) -> Source:
    """Look the job or appointment up through its unit's public interface."""
    if source_type == "job":
        if not unit_enabled(session, "jobs"):
            raise ValidationFailed("Jobs must be switched on to open a claim for a job")
        from ziira.modules.jobs.public import find_job

        job = find_job(session, source_id)
        if job is None:
            raise NotFound("Job not found")
        return Source(job.number, job.company_id, job.branch_id, job.customer_id)
    if source_type == "appointment":
        if not unit_enabled(session, "bookings"):
            raise ValidationFailed("Bookings must be switched on to open a claim for an appointment")
        from ziira.modules.bookings.public import find_appointment

        appt = find_appointment(session, source_id)
        if appt is None:
            raise NotFound("Appointment not found")
        return Source(appt.number, appt.company_id, appt.branch_id, appt.customer_id)
    raise ValidationFailed("A claim is for a job or an appointment")


def _customer(session: Session, company_id: UUID, customer_id: UUID | None) -> tuple[str | None, str | None]:
    """(name, phone) of the customer record, checking it belongs to the company."""
    if customer_id is None:
        return None, None
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Customers must be switched on to link a customer record")
    from ziira.modules.crm.public import find_customer

    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("The customer was not found in this company")
    return customer.name, customer.phone


def create_claim(session: Session, *, company_id: UUID, branch_id: UUID | None, payer_id: UUID,
                 customer_id: UUID | None = None, insured_name: str | None = None,
                 insured_phone: str | None = None, source_type: str | None = None, source_id: UUID | None = None,
                 subject: str | None = None, policy_number: str | None = None, claim_number: str | None = None,
                 member_number: str | None = None, preauth_ref: str | None = None, loss_date: date | None = None,
                 loss_description: str | None = None, assessor_name: str | None = None,
                 assessor_phone: str | None = None, excess_amount: Decimal = Decimal(0)) -> Claim:
    """Open a claim for a job or appointment (or on its own). Needs 'claims.manage' at the branch."""
    ctx = current_context()
    source: Source | None = None
    if (source_type is None) != (source_id is None):
        raise ValidationFailed("Name both the kind and the id of the job or appointment, or neither")
    if source_type is not None and source_id is not None:
        source = resolve_source(session, source_type, source_id)
        if source.company_id != company_id:
            raise ValidationFailed("That job or appointment belongs to another company")
        branch_id = branch_id or source.branch_id
    if branch_id is None:
        raise ValidationFailed("Say which branch the claim belongs to")
    check_company(session, company_id, branch_id)
    ctx.require(CLAIMS_MANAGE, company_id=company_id, branch_id=branch_id)
    payer = load_payer(session, payer_id)
    if payer.company_id != company_id:
        raise ValidationFailed("The payer belongs to another company")
    if not payer.is_active:
        raise ValidationFailed("That payer is no longer in use")
    customer_id = customer_id or (source.customer_id if source else None)
    name, phone = _customer(session, company_id, customer_id)
    if source_type is not None and source_id is not None \
            and repo.live_claim_for_source(session, company_id, source_type, source_id) is not None:
        raise Conflict("This job or appointment already has a claim")
    claim = Claim(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="claim",
                                    prefix="CLM"),
        payer_id=payer.id, customer_id=customer_id, insured_name=clean(insured_name, 160) or name,
        insured_phone=clean(insured_phone, 40) or phone, source_type=source_type, source_id=source_id,
        source_number=source.number if source else None, subject=clean(subject, 200),
        policy_number=clean(policy_number, 80), claim_number=clean(claim_number, 80),
        member_number=clean(member_number, 80), preauth_ref=clean(preauth_ref, 80), loss_date=loss_date,
        loss_description=clean(loss_description, 2000), assessor_name=clean(assessor_name, 160),
        assessor_phone=clean(assessor_phone, 40), excess_amount=excess_amount)
    repo.add(session, claim)
    add_event(session, claim, "created", f"Claim opened with {payer.name}")
    audit_record(session, "create", "claims.claim", claim.id, {"number": claim.number, "payer": payer.name})
    publish(session, Event("claim.created", "claims.claim", claim.id, {
        "company_id": company_id, "branch_id": branch_id, "number": claim.number, "payer_id": payer.id,
        "source_type": source_type, "source_id": source_id}))
    return claim


def update_claim(session: Session, claim_id: UUID, **changes: Any) -> Claim:
    """Change the claim's details (policy, assessor, excess ...). Needs 'claims.manage'. The excess cannot change once
    the claim has been invoiced (the invoices already use it)."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_MANAGE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    if "excess_amount" in changes and changes["excess_amount"] != claim.excess_amount \
            and repo.runs(session, claim.id):
        raise Conflict("The claim has been invoiced: the excess can no longer change")
    for key, value in changes.items():
        if key not in EDITABLE:
            continue
        if key == "customer_id":
            _customer(session, claim.company_id, value)
        elif isinstance(value, str):
            value = clean(value, 2000 if key == "loss_description" else 200)
        setattr(claim, key, value)
    claim.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "claims.claim", claim.id, {k: str(v) for k, v in changes.items() if k in EDITABLE})
    return claim


def add_note(session: Session, claim_id: UUID, *, kind: str, note: str, occurred_on: date | None = None,
             actor: str | None = None) -> Claim:
    """A dated note on the claim: a plain note, an assessor's visit or a re-inspection. Needs 'claims.manage'."""
    claim = load_claim(session, claim_id)
    current_context().require(CLAIMS_MANAGE, company_id=claim.company_id, branch_id=claim.branch_id)
    if kind not in NOTE_KINDS:
        raise ValidationFailed(f"A note is one of: {', '.join(NOTE_KINDS)}")
    if not note.strip():
        raise ValidationFailed("Write what happened")
    add_event(session, claim, kind, note, occurred_on=occurred_on, actor=actor)
    return claim


def record_authority(session: Session, claim_id: UUID, *, reference: str, amount: Decimal | None,
                     by_name: str | None, at: datetime | None = None) -> Claim:
    """Write down the payer's authority to repair (an approval or LPO number and the amount it covers), as told to us by
    phone, email or letter. Needs 'claims.manage'. Answers given on a response link carry their own reference."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_MANAGE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    ref = clean(reference, 80)
    if ref is None:
        raise ValidationFailed("Type the approval or order number the payer gave")
    claim.authority_ref, claim.authority_amount = ref, amount
    claim.authority_by, claim.authority_at = clean(by_name, 160), at or datetime.now(UTC)
    claim.updated_by = ctx.user_id
    session.flush()
    add_event(session, claim, "authority", f"Authority to repair {ref}" + (f" for {amount}" if amount else ""),
              actor=by_name)
    audit_record(session, "authority", "claims.claim", claim.id, {"reference": ref, "amount": str(amount)})
    status.refresh(session, claim)
    return claim


def complete_claim(session: Session, claim_id: UUID, *, signed_by: str, note: str | None = None,
                   signed_at: datetime | None = None) -> Claim:
    """Record that the work is done and the payer's representative or the customer signed it off (a name and a time).
    Needs 'claims.manage'. Work the payer has not decided on is not blocked here; invoicing bills what is authorised."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_MANAGE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    if claim.completed_at is not None:
        raise Conflict("This claim was already signed off")
    who = clean(signed_by, 160)
    if who is None:
        raise ValidationFailed("Type the name of the person who signed the work off")
    if not any(rules_ok for rules_ok in _has_authorised_work(session, claim)):
        raise ValidationFailed("Nothing has been approved yet: the work cannot be completed")
    stamp = datetime.now(UTC)
    claim.completed_at, claim.completion_signed_by = stamp, who
    claim.completion_signed_at = signed_at or stamp
    claim.completion_note = clean(note, 1000)
    claim.updated_by = ctx.user_id
    session.flush()
    detail = f": {claim.completion_note}" if note else ""
    add_event(session, claim, "completion", f"Work signed off by {who}{detail}", actor=who)
    audit_record(session, "complete", "claims.claim", claim.id, {"signed_by": who})
    status.refresh(session, claim)
    publish(session, Event("claim.completed", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number,
        "source_type": claim.source_type, "source_id": claim.source_id}))
    return claim


def _has_authorised_work(session: Session, claim: Claim) -> list[bool]:
    from ziira.modules.claims.domain import lines as rules

    return [rules.is_authorised_work(status.facts(line)) for _, line in status.in_play(session, claim.id)]


def close_claim(session: Session, claim_id: UUID, *, reason: str, note: str | None = None,
                amount: Decimal | None = None) -> Claim:
    """Close a claim with an outcome: total loss, salvage, cash in lieu (the payer paid the customer instead), rejected,
    withdrawn, cancelled or written off. A claim that has been invoiced can only be closed as written off. Needs
    'claims.manage'."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_MANAGE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is already closed")
    if reason not in CLOSE_REASONS:
        raise ValidationFailed(f"A claim closes as one of: {', '.join(CLOSE_REASONS)}")
    if repo.runs(session, claim.id) and reason != "written_off":
        raise ValidationFailed("This claim has been invoiced: it can only be closed as written off")
    if reason in ("total_loss", "salvage", "cash_in_lieu", "written_off") and not (note or "").strip():
        raise ValidationFailed("Add a note: what was agreed, with whom")
    if amount is not None and amount < 0:
        raise ValidationFailed("The amount cannot be negative")
    for estimate in repo.estimates(session, claim.id):
        if estimate.status in ("draft", "submitted"):
            estimate.status = "withdrawn"
    claim.status, claim.closed_reason, claim.closed_note = "closed", reason, clean(note, 1000)
    claim.closed_amount, claim.closed_at, claim.updated_by = amount, datetime.now(UTC), ctx.user_id
    session.flush()
    add_event(session, claim, "closed", f"Closed: {reason.replace('_', ' ')}" + (f". {note.strip()}" if note else ""))
    audit_record(session, "close", "claims.claim", claim.id, {"reason": reason, "amount": str(amount)})
    publish(session, Event("claim.closed", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number, "reason": reason,
        "source_type": claim.source_type, "source_id": claim.source_id}))
    return claim


def list_claims(session: Session, *, company_id: UUID | None = None, branch_id: UUID | None = None,
                payer_id: UUID | None = None, status_: str | None = None, open_only: bool = False,
                source_type: str | None = None, source_id: UUID | None = None, customer_id: UUID | None = None,
                search: str | None = None, limit: int = 50, offset: int = 0) -> list[Claim]:
    return repo.list_claims(session, access.view_scopes(), company_id=company_id, branch_id=branch_id,
                            payer_id=payer_id, status=status_, open_only=open_only, source_type=source_type,
                            source_id=source_id, customer_id=customer_id, search=search, limit=limit, offset=offset)
