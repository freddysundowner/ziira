"""Billing an insurer or scheme for an appointment, through the Claims unit when it is on.

Bookings does not know how an insurer is billed: Claims owns payers, estimates, the payer's answers, invoices to the
payer and the patient's share, and ageing. This file is the one place Bookings talks to it. Without Claims, a visit can
still name the party that pays (the appointment's `payer_customer_id`, member number, pre-authorisation reference and
co-pay) and the checkout splits the bill between the patient and that party's customer account.

With a claim open for an appointment, Claims invoices it, so the checkout leaves that appointment's lines out of the
bill (they show as 'billed through Claims'), finishes the appointment and ties nothing else to it.
"""

from decimal import Decimal
from uuid import UUID

from ziira.modules.bookings.permissions import BOOKINGS_MANAGE
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import unit_enabled
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, current_context

CLAIM_PREFIX = "claim:"


def available(session: Session) -> bool:
    return unit_enabled(session, "claims")


def claim_label(session: Session, appointment_id: UUID) -> str | None:
    """The claim number of an appointment's live claim, or None (also when Claims is off)."""
    if not available(session):
        return None
    import ziira.modules.claims.public as claims

    state = claims.claim_for_source(session, "appointment", appointment_id)
    return state.number if state is not None and state.status != "closed" else None


def open_claim(session: Session, appointment_id: UUID, *, payer_id: UUID, policy_number: str | None = None,
               member_number: str | None = None, preauth_ref: str | None = None) -> Appointment:
    """Open a claim in Claims for this appointment (the co-pay becomes the claim's excess) and remember it. Needs
    'bookings.manage' here and 'claims.manage' there."""
    appt = repo.get_appointment(session, appointment_id, lock=True)
    if appt is None or not access.can_view(appt.company_id, appt.branch_id):
        raise NotFound("Appointment not found")
    current_context().require(BOOKINGS_MANAGE, company_id=appt.company_id, branch_id=appt.branch_id)
    if not available(session):
        raise ValidationFailed("Claims is not switched on: ask the owner to switch it on in Add-ons")
    if appt.customer_id is None:
        raise ValidationFailed("Link a client to the appointment first: the claim is for them")
    if appt.invoice_id is not None:
        raise ValidationFailed("This appointment was already billed")
    if appt.claim_id is not None:
        return appt
    import ziira.modules.claims.public as claims

    offer = repo.get_offer(session, appt.offer_id)
    state = claims.open_claim(
        session, company_id=appt.company_id, branch_id=appt.branch_id, payer_id=payer_id,
        source_type="appointment", source_id=appt.id, customer_id=appt.customer_id,
        subject=offer.name if offer else None, policy_number=policy_number,
        excess_amount=appt.copay_amount if appt.copay_amount is not None else Decimal(0))
    appt.claim_id = state.id
    appt.payer_member_no = (member_number or "").strip() or appt.payer_member_no
    appt.preauth_ref = (preauth_ref or "").strip() or appt.preauth_ref
    session.flush()
    audit_record(session, "claim", "bookings.appointment", appt.id, {"claim": state.number})
    return appt
