"""Billing an appointment: one invoice line for the service, through Point of Sale's invoice service.

Kept behind this small adapter so Bookings works without Point of Sale; without it the answer is a plain "invoicing is
not available" message. Point of Sale makes the invoice (numbering, tax, events and books), and it does so once per
appointment however often this is asked.
"""

from decimal import Decimal
from uuid import UUID

import ziira.modules.pos.public as pos_public
from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository.models import Appointment
from ziira.modules.bookings.services import access, delegate
from ziira.modules.bookings.services.common import unit_enabled
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, flag_for_review

SOURCE = "bookings.appointment"
UNAVAILABLE = "Invoicing is not available: switch on Point of Sale and Customers to bill appointments"


def available(session: Session) -> bool:
    """True when Point of Sale can make invoices from lines and Customers is on."""
    if not (unit_enabled(session, "pos") and unit_enabled(session, "crm")):
        return False
    return hasattr(pos_public, "issue_invoice_from_lines")


def create_invoice(session: Session, appointment_id: UUID) -> Appointment:
    """Invoice a finished appointment to its customer (once). Needs 'bookings.checkout' at the branch (the front desk
    may bill without holding Point of Sale's own invoice right)."""
    appt = repo.get_appointment(session, appointment_id, lock=True)
    if appt is None or not access.can_view(appt.company_id, appt.branch_id):
        raise NotFound("Appointment not found")
    with delegate.front_desk_rights(appt.company_id, appt.branch_id):
        return _create_invoice(session, appt)


def _create_invoice(session: Session, appt: Appointment) -> Appointment:
    if not available(session):
        raise ValidationFailed(UNAVAILABLE)
    if appt.status != life.COMPLETED:
        raise ValidationFailed("Finish the appointment before invoicing it")
    if appt.kind == "class":
        raise ValidationFailed("A class is billed per person at the till, not from here")
    if appt.customer_id is None:
        raise ValidationFailed("Link a customer to the appointment first: an invoice needs one")
    offer = repo.get_offer(session, appt.offer_id)
    if offer is None or offer.product_id is None:
        raise ValidationFailed("Link this service to a service item in Products so it can be invoiced")
    ref = pos_public.issue_invoice_from_lines(
        session, company_id=appt.company_id, branch_id=appt.branch_id, customer_id=appt.customer_id,
        lines=[pos_public.InvoiceLineIn(product_id=offer.product_id, description=f"{offer.name} ({appt.number})",
                             quantity=Decimal(1), unit_price=appt.price)],
        source_type=SOURCE, source_id=appt.id,
        due_days=repo.ensure_settings(session, appt.company_id).invoice_due_days, memo=appt.number)
    appt.invoice_id, appt.invoice_number = ref.id, ref.number
    session.flush()
    audit_record(session, "invoice", "bookings.appointment", appt.id, {"invoice": ref.number})
    from ziira.sdk import Event, publish

    publish(session, Event("appointment.invoiced", "bookings.appointment", appt.id, {
        "company_id": appt.company_id, "branch_id": appt.branch_id, "appointment_id": appt.id,
        "invoice_id": ref.id, "invoice_number": ref.number}))
    return appt


def try_invoice(session: Session, appt: Appointment) -> None:
    """Invoice on completion when the business asked for it. A problem never stops the appointment finishing: it goes
    to the exceptions inbox for the front desk."""
    try:
        with session.begin_nested():
            create_invoice(session, appt.id)
    except (ValidationFailed, NotFound) as exc:
        flag_for_review(session, unit="bookings", kind="invoice_not_made", severity="low",
                        message=f"Appointment {appt.number} was finished but no invoice was made: {exc}",
                        company_id=appt.company_id, branch_id=appt.branch_id, ref_type="bookings.appointment",
                        ref_id=appt.id, dedupe_key=f"bookings:invoice:{appt.id}")
