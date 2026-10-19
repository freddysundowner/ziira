"""The payer's own page for an estimate: opened from a link, without an account.

The link holds `<business id>.<secret>`; only a hash of the secret is stored. It expires, can be revoked, takes one
sign-off (a name, and each line answered) and shows only the estimate: business, the item, the payer's own claim and
policy numbers, lines and totals. No customer details, no costs, nothing about other claims. Every use is rate limited
and written to the link's access log. A wrong or tampered link is answered like one that never existed (404).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLink, LinkAccess, Payer
from ziira.modules.claims.services import links, photos, responses
from ziira.modules.claims.services.common import business_name, currency_of, now
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    ZiiraError,
    hash_secret,
    rate_limit,
    system_session,
)


def _enabled(session: Session) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'claims' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


def _tenant_of(token: str) -> UUID:
    try:
        return UUID(hex=token.partition(".")[0])
    except ValueError:
        raise NotFound("This link is not valid") from None


def _find(session: Session, token: str) -> tuple[EstimateLink, Estimate, Claim]:
    link = repo.link_by_hash(session, hash_secret(token)) if _enabled(session) else None
    if link is None:
        raise NotFound("This link is not valid")
    estimate = repo.get(session, Estimate, link.estimate_id)
    claim = repo.get(session, Claim, link.claim_id)
    assert estimate is not None and claim is not None
    return link, estimate, claim


def page_state(link: EstimateLink, estimate: Estimate, claim: Claim) -> str:
    """open, answered, expired, revoked, replaced (a newer version was sent), withdrawn or closed."""
    if claim.status == "closed":
        return "closed"
    if estimate.status == "withdrawn":
        return "withdrawn"
    if estimate.status == "superseded":
        return "replaced"
    own = links.state_of(link)
    if own == links.ACTIVE and estimate.status == "submitted":
        return "open"
    if own == links.ANSWERED or estimate.status == "answered":
        return "answered"
    return own if own != links.ACTIVE else "answered"


def _log(session: Session, link: EstimateLink, action: str, outcome: str, ip: str | None, agent: str | None) -> None:
    session.add(LinkAccess(tenant_id=link.tenant_id, company_id=link.company_id, link_id=link.id, action=action,
                           outcome=outcome[:200], ip_address=(ip or "")[:64] or None,
                           user_agent=(agent or "")[:200] or None))
    link.last_accessed_at = now()
    if action == "view":
        link.view_count += 1
    session.flush()


def _page(session: Session, link: EstimateLink, estimate: Estimate, claim: Claim, state: str) -> dict[str, Any]:
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    base: dict[str, Any] = {"state": state, "business": business_name(session, claim.company_id),
                            "currency": currency_of(session, claim.company_id), "payer": payer.name}
    if state in ("expired", "revoked", "replaced", "withdrawn", "closed"):
        return base                                    # nothing about the estimate once the link is no good
    from ziira.modules.claims.services.estimates import label

    rows = repo.estimate_lines(session, estimate.id)
    return {
        **base, "label": label(estimate), "claim_number": claim.claim_number, "policy_number": claim.policy_number,
        "reference": claim.number, "subject": claim.subject, "loss_date": claim.loss_date,
        "notes": estimate.notes, "revision_note": estimate.revision_note, "valid_until": estimate.valid_until,
        "total": estimate.total, "link_expires_at": link.expires_at, "answered_by": link.signer_name,
        "photos": photos.shareable_files(session, claim),
        "lines": [{"id": r.id, "position": r.position, "kind": r.kind, "description": r.description,
                   "quantity": r.quantity, "unit_price": r.unit_price, "total": r.asked_total,
                   "part_class": r.part_class, "locked": r.locked, "state": r.payer_state, "amount": r.payer_amount,
                   "reason": r.payer_reason} for r in rows]}


def view(token: str, ip_address: str | None, user_agent: str | None = None) -> dict[str, Any]:
    """What the payer sees: the estimate with its lines, or only that the link no longer works."""
    rate_limit("claim-response", token, ip_address, per_subject=60, per_ip=240)
    with system_session(_tenant_of(token)) as session:
        link, estimate, claim = _find(session, token)
        state = page_state(link, estimate, claim)
        _log(session, link, "view", state, ip_address, user_agent)
        return _page(session, link, estimate, claim, state)


@dataclass(frozen=True)
class LineAnswer:
    line_id: UUID
    state: str
    amount: Decimal | None = None
    reason: str | None = None


def answer(token: str, ip_address: str | None, user_agent: str | None, *, name: str, role: str | None,
           lines: list[LineAnswer], note: str | None, authority_ref: str | None,
           authority_amount: Decimal | None) -> dict[str, Any]:
    """The payer answers every line and signs off. One sign-off per link; a second attempt changes nothing."""
    rate_limit("claim-response", token, ip_address, per_subject=60, per_ip=240)
    problem: ZiiraError | None = None
    result: dict[str, Any] = {}
    with system_session(_tenant_of(token)) as session:
        link, estimate, claim = _find(session, token)
        state = page_state(link, estimate, claim)
        outcome = "accepted"
        if state != "open":
            problem, outcome = Conflict("This link can no longer be used to answer. Please contact the business"), state
        else:
            who = " ".join((name or "").split())[:160]
            if not who:
                problem, outcome = ValidationFailed("Please type your name to sign off"), "refused: no name"
            else:
                waiting = {r.id for r in repo.estimate_lines(session, estimate.id)
                           if not r.locked and r.payer_state in ("pending", "needs_information")}
                missing = waiting - {a.line_id for a in lines}
                if missing:
                    problem, outcome = ValidationFailed("Please answer every line before you sign off"), \
                        "refused: lines unanswered"
        if problem is None:
            try:
                with session.begin_nested():
                    full = f"{who} ({(role or '').strip()[:80]})" if (role or "").strip() else who
                    record = responses.apply_response(
                        session, estimate, claim,
                        [responses.AnswerIn(a.line_id, a.state, a.amount, a.reason) for a in lines],
                        by_name=full, by_user=None, channel="link", via=None, occurred_at=None, note=note,
                        authority_ref=authority_ref, authority_amount=authority_amount)
                    link.signed_off_at, link.signer_name = now(), full
                    links.revoke_all(session, estimate.id, "signed off")      # one sign-off: other links end too
                result = {"state": "answered", "response": record.response}
            except ZiiraError as failure:
                problem, outcome = failure, "refused: " + str(failure)[:150]
        _log(session, link, "answer", outcome, ip_address, user_agent)
    if problem is not None:
        raise problem
    return result
