"""The printable estimate (HTML to print or save as PDF, or plain text)."""

from uuid import UUID

from ziira.modules.claims.domain import document as doc
from ziira.modules.claims.permissions import CLAIMS_ESTIMATE, CLAIMS_VIEW
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Payer
from ziira.modules.claims.services.common import business_name, currency_of, load_estimate
from ziira.modules.claims.services.estimates import label
from ziira.sdk import Forbidden, Session, current_context


def build(session: Session, estimate_id: UUID, link: str = "") -> doc.DocEstimate:
    """The estimate as a printable document. Needs a claims permission at the claim's branch."""
    estimate, claim = load_estimate(session, estimate_id)
    ctx = current_context()
    if not (ctx.can(CLAIMS_VIEW, company_id=claim.company_id, branch_id=claim.branch_id)
            or ctx.can(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)):
        raise Forbidden("You need to be able to view claims here")
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    rows = repo.estimate_lines(session, estimate.id)
    answers = {"approved": "Approved", "countered": "Counter-offer", "rejected": "Rejected",
               "needs_information": "More information needed", "pending": ""}
    lines = []
    for r in rows:
        answer = answers.get(r.payer_state, "")
        if r.payer_state == "countered" and r.payer_amount is not None:
            answer += f" {r.payer_amount:,.2f}"
        lines.append(doc.DocLine(r.position, r.kind + (f" ({r.part_class})" if r.part_class else ""), r.description,
                                 r.quantity, r.unit_price, r.asked_total, r.payer_state, answer))
    return doc.DocEstimate(
        business=business_name(session, claim.company_id), currency=currency_of(session, claim.company_id),
        label=label(estimate), claim_number=claim.number, payer=payer.name, policy_number=claim.policy_number or "",
        insurer_claim_number=claim.claim_number or "", subject=claim.subject or "",
        loss_date=claim.loss_date.isoformat() if claim.loss_date else "",
        notes=estimate.notes or "", valid_until=estimate.valid_until.isoformat() if estimate.valid_until else "",
        lines=lines, total=estimate.total, link=link)
