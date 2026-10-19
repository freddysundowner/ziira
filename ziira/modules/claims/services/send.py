"""Sending an estimate to the payer as a message. Always queued through the notification layer, never sent in the
request; nobody on the do-not-contact list is messaged (the kernel checks). The channel is any one the business has
(`configured_channels`): this code names none of them."""

import re

from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, Estimate, EstimateLink, Payer
from ziira.modules.claims.services.common import add_event, business_name, clean
from ziira.sdk import (
    Session,
    ValidationFailed,
    company_setting,
    configured_channels,
    mask_contact,
    normalise_phone,
    send_templated,
    settings_public_base_url,
)


def link_url(secret: str) -> str:
    return f"{settings_public_base_url().rstrip('/')}/claim-response/{secret}"


def default_recipient(payer: Payer, channel: str) -> str | None:
    """The address on file for this kind of channel: an email address for email, a phone number for the rest."""
    if channel == "email":
        if payer.estimate_email:
            return payer.estimate_email
        return next((c["email"] for c in payer.contacts if c.get("email")), None)
    return next((c["phone"] for c in payer.contacts if c.get("phone")), None)


def deliver(session: Session, claim: Claim, estimate: Estimate, link: EstimateLink, secret: str, *, channel: str,
            recipient: str | None) -> bool:
    """Queue the link to the payer on `channel`. Raises ValidationFailed when the business has no such channel or there
    is nowhere to send it. True when queued (False: the person asked not to be contacted)."""
    ready = configured_channels(session, claim.company_id)
    if channel not in ready:
        raise ValidationFailed(f"Channel '{channel}' is not set up for this business. "
                               f"Available: {', '.join(sorted(ready)) or 'none'}")
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    to = clean(recipient, 200) or default_recipient(payer, channel)
    if to is None:
        raise ValidationFailed("Type where to send it: the payer has no address on file for this channel")
    if channel == "email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to):
            raise ValidationFailed("That is not an email address")
    else:
        digits = normalise_phone(to, str(company_setting(session, claim.company_id, "phone_country_code")))
        if not digits:
            raise ValidationFailed("That is not a phone number")
        to = digits
    link.sent_to = mask_contact(to)
    queued = send_templated(
        session, company_id=claim.company_id, channel=channel, recipient=to, template="claim_estimate",
        variables={"payer": payer.name, "claim": claim.number,
                   "item": claim.subject or claim.source_number or "the job",
                   "business": business_name(session, claim.company_id), "link": link_url(secret)},
        ref_type="claim", ref_id=claim.id, dedupe_key=f"claim_estimate:{estimate.id}:{link.id}")
    add_event(session, claim, "submitted", f"Estimate queued to {mask_contact(to)} ({channel})"
              if queued is not None else f"Estimate NOT sent to {mask_contact(to)}: contact blocked",
              estimate_id=estimate.id)
    return queued is not None
