"""Secure response links: the payer opens an estimate without an account, answers each line and signs off.

The link holds `<business id>.<secret>`; only a hash of the secret is stored. A link belongs to one estimate version,
expires,
can be revoked, takes one sign-off, and every use is written to `claims.link_access`. The public side (reading and
answering) is in public_response.py.
"""

from datetime import timedelta
from uuid import UUID

from ziira.modules.claims.permissions import CLAIMS_ESTIMATE
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLink, LinkAccess
from ziira.modules.claims.services import photos
from ziira.modules.claims.services.common import add_event, load_estimate, now
from ziira.sdk import Conflict, NotFound, Session, audit_record, current_context, hash_secret, new_secret

ACTIVE, EXPIRED, REVOKED, ANSWERED = "active", "expired", "revoked", "answered"


def state_of(link: EstimateLink) -> str:
    if link.signed_off_at is not None:
        return ANSWERED
    if link.revoked_at is not None:
        return REVOKED
    return EXPIRED if link.expires_at <= now() else ACTIVE


def create_link(session: Session, claim: Claim, estimate: Estimate, *, valid_days: int, sent_via: str | None,
                sent_to: str | None) -> tuple[EstimateLink, str]:
    """Make a link for a sent estimate. Returns the link and its secret, which is shown only now."""
    ctx = current_context()
    secret = f"{ctx.tenant_id.hex}.{new_secret()}"
    link = EstimateLink(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=claim.company_id,
                        claim_id=claim.id, estimate_id=estimate.id, token_hash=hash_secret(secret),
                        expires_at=now() + timedelta(days=max(1, min(valid_days, 90))), sent_via=sent_via,
                        sent_to=sent_to)
    repo.add(session, link)
    audit_record(session, "create", "claims.estimate_link", link.id, {"estimate": str(estimate.id), "via": sent_via})
    return link, secret


def revoke_all(session: Session, estimate_id: UUID, reason: str) -> int:
    """End every live link of an estimate (a newer version was sent, or it was withdrawn)."""
    count = 0
    claim = repo.get(session, Claim, repo.get(session, Estimate, estimate_id).claim_id)  # type: ignore[union-attr]
    for link in repo.links_of_estimate(session, estimate_id):
        if link.revoked_at is None and link.signed_off_at is None:
            link.revoked_at = now()
            count += 1
            session.add(LinkAccess(tenant_id=link.tenant_id, company_id=link.company_id, link_id=link.id,
                                   action="revoke", outcome=reason[:200]))
    session.flush()
    if count and claim is not None:
        photos.end_addresses(session, claim)
    return count


def issue_link(session: Session, estimate_id: UUID, *, valid_days: int | None = None) -> tuple[EstimateLink, str]:
    """Make another link for a sent estimate (the old ones keep working until they expire or are revoked). The secret is
    shown only once. Needs 'claims.estimate'."""
    from ziira.modules.claims.services.settings import get_settings

    estimate, claim = load_estimate(session, estimate_id, lock=True)
    current_context().require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if estimate.status != "submitted":
        raise Conflict("A link can be made only for an estimate that is waiting for the payer's answer")
    days = valid_days or get_settings(session, claim.company_id).link_valid_days
    link, secret = create_link(session, claim, estimate, valid_days=days, sent_via="link", sent_to=None)
    add_event(session, claim, "link", "A response link was made", estimate_id=estimate.id)
    return link, secret


def revoke_link(session: Session, link_id: UUID) -> EstimateLink:
    """Stop a link working now. Needs 'claims.estimate'."""
    link = repo.get(session, EstimateLink, link_id, lock=True)
    if link is None:
        raise NotFound("Link not found")
    estimate, claim = load_estimate(session, link.estimate_id)
    current_context().require(CLAIMS_ESTIMATE, company_id=claim.company_id, branch_id=claim.branch_id)
    if link.revoked_at is None and link.signed_off_at is None:
        link.revoked_at, link.revoked_by = now(), current_context().user_id
        session.add(LinkAccess(tenant_id=link.tenant_id, company_id=link.company_id, link_id=link.id,
                               action="revoke", outcome="revoked by staff"))
        session.flush()
        photos.end_addresses(session, claim)
        add_event(session, claim, "link", "A response link was revoked", estimate_id=estimate.id)
        audit_record(session, "revoke", "claims.estimate_link", link.id, {})
    return link


def links_of(session: Session, estimate_id: UUID) -> list[EstimateLink]:
    load_estimate(session, estimate_id)
    return repo.links_of_estimate(session, estimate_id)


def accesses_of(session: Session, link_id: UUID) -> list[LinkAccess]:
    link = repo.get(session, EstimateLink, link_id)
    if link is None:
        raise NotFound("Link not found")
    load_estimate(session, link.estimate_id)
    return repo.link_accesses(session, link.id)
