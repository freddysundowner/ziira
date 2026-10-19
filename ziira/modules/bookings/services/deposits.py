"""Deposits for services that ask for one (a long colour, a treatment plan): recorded when the client pays, kept on the
client's account until the checkout uses it, and kept as credit if the visit is cancelled (the business then decides
whether to charge the fee from it). Taking the money is Point of Sale's job (an advance on the customer's account)."""

from decimal import Decimal
from uuid import UUID

from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import access, appointments, delegate, notify
from ziira.modules.bookings.services.common import unit_enabled, user_id
from ziira.sdk import Event, NotFound, Session, ValidationFailed, audit_record, publish

METHODS = ("cash", "mobile_money", "card", "bank", "cheque", "other")


def deposit_due(appt: Appointment) -> Decimal:
    """What is still to be paid as a deposit on an appointment."""
    return max(appt.deposit_amount - appt.deposit_paid, Decimal(0))


def record_deposit(session: Session, appointment_id: UUID, *, amount: Decimal, method: str,
                   reference: str | None = None) -> Appointment:
    """The client paid (part of) the deposit. The money is held on their account; a request waiting for its deposit is
    confirmed when the deposit is complete. Needs 'bookings.checkout' at the branch and a customer on the booking."""
    appt = repo.get_appointment(session, appointment_id, lock=True)
    if appt is None or not access.can_view(appt.company_id, appt.branch_id):
        raise NotFound("Appointment not found")
    if appt.status not in (life.REQUESTED, life.CONFIRMED, life.CHECKED_IN):
        raise ValidationFailed("That appointment is not waiting for a deposit")
    if appt.customer_id is None:
        raise ValidationFailed("Link a client to the appointment first: the deposit is kept on their account")
    if method not in METHODS or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed(f"A deposit is more than zero with two decimals, by one of: {', '.join(METHODS)}")
    if not unit_enabled(session, "pos"):
        raise ValidationFailed("Point of Sale is not switched on: it keeps the money")
    import ziira.modules.pos.public as pos_public

    with delegate.front_desk_rights(appt.company_id, appt.branch_id):
        made = pos_public.take_payment(session, customer_id=appt.customer_id, branch_id=appt.branch_id, amount=amount,
                                       method=method, external_ref=reference)
    appt.deposit_paid = appt.deposit_paid + amount
    appt.updated_by = user_id()
    session.flush()
    audit_record(session, "deposit", "bookings.appointment", appt.id, {"amount": amount, "receipt": made.number})
    publish(session, Event("appointment.deposit_paid", "bookings.appointment", appt.id, {
        "company_id": appt.company_id, "branch_id": appt.branch_id, "appointment_id": appt.id,
        "customer_id": appt.customer_id, "amount": amount, "receipt_number": made.number}))
    if appt.status == life.REQUESTED and deposit_due(appt) <= 0:
        appointments.confirm(session, appt.id)
    return appt


def remind(session: Session, appt: Appointment) -> None:
    """Ask the client for the deposit (a queued message; the wording says how, from the business's deposit note)."""
    settings = repo.ensure_settings(session, appt.company_id)
    phone, email, name = notify.contact_of(session, appt)
    offer = repo.get_offer(session, appt.offer_id)
    notify.to_contact(
        session, company_id=appt.company_id, phone=phone, email=email, template="appointment_deposit",
        variables={"customer": name, "service": offer.name if offer else "", "business": notify.business_name(
            session, appt.company_id), "when": notify.when_text(session, appt.company_id, appt.starts_at),
            "amount": str(deposit_due(appt)), "how": settings.deposit_note or ""},
        ref_type="bookings.appointment", ref_id=appt.id, dedupe_key=f"deposit:{appt.id}:{deposit_due(appt)}")
