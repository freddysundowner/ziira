"""Queued messages to customers for Memberships: where to reach them and the one call that queues a templated message.

Nothing here sends in a request. The notification layer holds the message, respects the do-not-contact list and the
customer's channel, and the worker delivers it."""

from uuid import UUID

from ziira.modules.crm.public import CustomerView
from ziira.sdk import Session, company_setting, configured_channels, send_templated


def route(session: Session, company_id: UUID, customer: CustomerView) -> list[tuple[str, str]]:
    """Where to reach the customer, best first: the company's reminder channel, then SMS, then email."""
    configured = configured_channels(session, company_id)
    preferred = str(company_setting(session, company_id, "reminder_channel"))
    order = [c for c in (preferred, "sms", "email") if c != "off"]
    found: list[tuple[str, str]] = []
    for channel in dict.fromkeys(order):
        recipient = customer.email if channel == "email" else customer.phone
        if channel in configured and recipient:
            found.append((channel, recipient))
    return found


def send(session: Session, company_id: UUID, customer: CustomerView, template: str, variables: dict[str, str],
         language: str, ref_type: str, ref_id: UUID, key: str) -> str | None:
    """Queue a message to the customer. Returns the channel used, or None when there is no way to reach them."""
    options = route(session, company_id, customer)
    if not options:
        return None
    (channel, recipient), rest = options[0], options[1:]
    send_templated(session, company_id=company_id, channel=channel, recipient=recipient, template=template,
                   variables=variables, language=language,
                   fallbacks=[{"channel": c, "recipient": r} for c, r in rest], ref_type=ref_type, ref_id=ref_id,
                   dedupe_key=key)
    return channel
