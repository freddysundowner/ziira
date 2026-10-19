"""What the workshop or clinic may do for a claim: which lines are authorised, and whether starting work is allowed.

Used by `public.py` (Jobs and Bookings ask these questions) and by the claim screens."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain.money import ZERO
from ziira.modules.claims.domain.split import BillableLine, Split, compute_split
from ziira.modules.claims.permissions import CLAIMS_MANAGE
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLine, WorkDecision
from ziira.modules.claims.services import settings as claim_settings
from ziira.modules.claims.services import status
from ziira.modules.claims.services.common import add_event, clean, load_claim
from ziira.sdk import Conflict, Session, ValidationFailed, audit_record, current_context


@dataclass(frozen=True)
class WorkGateResult:
    has_claim: bool
    state: str                       # no_claim | waiting_for_payer | partly_authorised | authorised | closed
    allowed: bool
    policy: str                      # warn | block
    authorised_total: Decimal
    unapproved_total: Decimal
    decision_recorded: bool
    message: str
    claim_id: UUID | None = None


def claim_of(session: Session, source_type: str, source_id: UUID) -> Claim | None:
    """The live claim for a job or appointment, else the latest closed one, else none."""
    from sqlalchemy import select

    found = session.scalars(select(Claim).where(Claim.source_type == source_type, Claim.source_id == source_id)
                            .order_by(Claim.created_at.desc())).all()
    live = [c for c in found if c.status != "closed"]
    return live[0] if live else (found[0] if found else None)


def _latest_sent(session: Session, claim_id: UUID) -> Estimate | None:
    sent = [e for e in repo.estimates(session, claim_id) if e.submitted_at is not None]
    return max(sent, key=lambda e: e.submitted_at, default=None)  # type: ignore[arg-type, return-value]


def gate(session: Session, claim: Claim | None) -> WorkGateResult:
    if claim is None:
        return WorkGateResult(False, "no_claim", True, "warn", ZERO, ZERO, False, "", None)
    policy = claim_settings.get_settings(session, claim.company_id).unapproved_work
    if claim.status == "closed":
        return WorkGateResult(True, "closed", True, policy, ZERO, ZERO, False,
                              f"The claim is closed ({(claim.closed_reason or '').replace('_', ' ')}): any work is "
                              "for the customer's account", claim.id)
    authorised = unapproved = ZERO
    for _, line in status.in_play(session, claim.id):
        f = status.facts(line)
        if rules.is_authorised_work(f):
            authorised += rules.payer_pays(f) + rules.customer_owes(f)
        elif rules.is_open(f) or (line.payer_state == "countered" and line.our_decision == "declined"):
            unapproved += line.asked_total
    latest = _latest_sent(session, claim.id)
    decisions = repo.work_decisions(session, claim.id)
    decided = bool(decisions and latest is not None and latest.submitted_at is not None
                   and decisions[-1].created_at >= latest.submitted_at)
    if authorised > 0 and unapproved == 0:
        return WorkGateResult(True, "authorised", True, policy, authorised, unapproved, decided, "", claim.id)
    state = "partly_authorised" if authorised > 0 else "waiting_for_payer"
    if unapproved == 0 and authorised == 0:
        unapproved, state = ZERO, "waiting_for_payer"
    message = ("Some work is not approved by the payer yet" if authorised > 0
               else "The payer has not approved any work yet")
    allowed = decided or policy == "warn"
    if decided:
        message += ". A decision to go ahead is recorded"
    elif policy == "block":
        message += ". Record a decision to go ahead, or wait for the payer"
    return WorkGateResult(True, state, allowed, policy, authorised, unapproved, decided, message, claim.id)


def record_work_decision(session: Session, claim_id: UUID, note: str) -> WorkDecision:
    """Write down that the business decided to go ahead with work the payer has not approved (who decided, and why).
    Needs 'claims.manage'."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_MANAGE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    reason = clean(note, 1000)
    if reason is None:
        raise ValidationFailed("Say why the work goes ahead without the payer's approval")
    latest = _latest_sent(session, claim.id)
    row = WorkDecision(tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id,
                       estimate_id=latest.id if latest else None, decided_by=ctx.user_id, note=reason)
    repo.add(session, row)
    add_event(session, claim, "work", f"Decision to go ahead before the payer's approval: {reason}")
    audit_record(session, "decide_work", "claims.claim", claim.id, {"note": reason})
    return row


def split_of(session: Session, claim: Claim) -> Split:
    """The payer / customer split of everything authorised so far, billed or not (a figure for screens)."""
    billable = [BillableLine(line.id, line.description, line.quantity, line.unit_price, status.facts(line))
                for _, line in status.in_play(session, claim.id)
                if rules.is_authorised_work(status.facts(line))]
    return compute_split(billable, excess=claim.excess_amount)


def lines_of(session: Session, claim: Claim) -> list[tuple[Estimate, EstimateLine]]:
    return status.in_play(session, claim.id)
