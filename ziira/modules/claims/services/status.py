"""Which estimates are in play on a claim, what each line is worth, and the claim's status.

A claim has one *original* chain of estimate versions and any number of *supplementary* chains. In each chain only the
latest version that was sent counts: older ones were superseded by it. The status of the claim follows from that and
from the invoices; it is worked out here, in one place, after every change.
"""

from decimal import Decimal
from uuid import UUID

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain.money import ZERO
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLine
from ziira.sdk import Event, Session, publish


def facts(line: EstimateLine) -> rules.LineFacts:
    return rules.LineFacts(line.asked_total, line.payer_state, line.payer_amount, line.our_decision,
                           line.customer_decision, line.shortfall_to)


def in_play(session: Session, claim_id: UUID) -> list[tuple[Estimate, EstimateLine]]:
    """The lines that count: from the latest sent version of each chain of estimates."""
    latest: dict[UUID, Estimate] = {}
    for estimate in repo.estimates(session, claim_id):
        if estimate.status in ("submitted", "answered"):
            latest[estimate.lineage_id] = estimate          # ordered by seq: the last one wins
    out: list[tuple[Estimate, EstimateLine]] = []
    for estimate in sorted(latest.values(), key=lambda e: e.seq):
        out += [(estimate, line) for line in repo.estimate_lines(session, estimate.id)]
    return out


def refresh(session: Session, claim: Claim) -> str:
    """Work out the claim's status from its estimates, authority, completion and invoices, store it and tell others when
    the payer's approval first arrives. Returns the new status."""
    if claim.status == "closed":
        return claim.status
    old = claim.status
    played = in_play(session, claim.id)
    payable = any(rules.is_authorised_work(facts(line)) for _, line in played)
    unbilled = any(rules.is_authorised_work(facts(line)) and line.invoiced_run_id is None for _, line in played)
    sent = any(e.status in ("submitted", "answered") for e, _ in played) or bool(played)
    has_runs = bool(repo.runs(session, claim.id))
    if has_runs and not unbilled:
        new = "settled" if old == "settled" else "invoiced"
    elif claim.completed_at is not None:
        new = "completed"
    elif payable or claim.authority_ref:
        new = "authorised"
    elif sent:
        new = "open"
    else:
        new = "draft"
    claim.status = new
    session.flush()
    if new != old and new == "authorised":
        publish(session, Event("claim.authorised", "claims.claim", claim.id, {
            "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number,
            "source_type": claim.source_type, "source_id": claim.source_id}))
    return new


def totals(session: Session, claim_id: UUID) -> dict[str, Decimal]:
    """The money picture of the lines in play: asked, what the payer pays, what the customer pays, what is still
    open."""
    asked = payer = customer = open_ = absorbed = ZERO
    for _, line in in_play(session, claim_id):
        f = facts(line)
        asked += line.asked_total
        payer += rules.payer_pays(f)
        customer += rules.customer_owes(f)
        absorbed += rules.business_absorbs(f)
        if rules.is_open(f):
            open_ += line.asked_total
    return {"asked": asked, "payer_pays": payer, "customer_pays": customer, "open": open_, "absorbed": absorbed}


def bulk_in_play(session: Session, claim_ids: set[UUID]) -> dict[UUID, list[tuple[Estimate, EstimateLine]]]:
    """`in_play` for many claims in two queries (for lists)."""
    from sqlalchemy import select

    out: dict[UUID, list[tuple[Estimate, EstimateLine]]] = {c: [] for c in claim_ids}
    if not claim_ids:
        return out
    latest: dict[tuple[UUID, UUID], Estimate] = {}
    found = session.scalars(select(Estimate).where(Estimate.claim_id.in_(claim_ids),
                                                   Estimate.status.in_(("submitted", "answered")))
                            .order_by(Estimate.seq))
    for estimate in found:
        latest[(estimate.claim_id, estimate.lineage_id)] = estimate
    by_id = {e.id: e for e in latest.values()}
    if not by_id:
        return out
    lines = session.scalars(select(EstimateLine).where(EstimateLine.estimate_id.in_(by_id))
                            .order_by(EstimateLine.position))
    for line in lines:
        out[line.claim_id].append((by_id[line.estimate_id], line))
    for pairs in out.values():
        pairs.sort(key=lambda p: (p[0].seq, p[1].position))
    return out


def summarise(pairs: list[tuple[Estimate, EstimateLine]]) -> tuple[dict[str, Decimal], str | None]:
    """(totals, who the claim waits for) from the lines in play."""
    asked = payer = customer = open_ = absorbed = ZERO
    waits: set[str] = set()
    for _, line in pairs:
        f = facts(line)
        asked += line.asked_total
        payer += rules.payer_pays(f)
        customer += rules.customer_owes(f)
        absorbed += rules.business_absorbs(f)
        if rules.is_open(f):
            open_ += line.asked_total
            waits.add(waiting_on(f) or "")
    waiting = next((w for w in ("us", "customer", "payer") if w in waits), None)
    return ({"asked": asked, "payer_pays": payer, "customer_pays": customer, "open": open_, "absorbed": absorbed},
            waiting)


def waiting_on(f: rules.LineFacts) -> str | None:
    if f.payer_state in ("pending", "needs_information"):
        return "payer"
    if f.payer_state == "countered" and f.our_decision is None:
        return "us"
    if f.payer_state == "rejected" and f.customer_decision is None:
        return "customer"
    return None
