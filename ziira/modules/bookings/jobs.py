"""Recurring work of Bookings: reminders, waitlist offers that ran out, recall messages, chair rent."""

from ziira.modules.bookings.services import notify, recalls, rentals, sessions
from ziira.sdk import Session, periodic


@periodic("bookings.send_reminders", every_seconds=15 * 60)
def send_reminders(session: Session) -> None:
    """Queue the appointment reminders that are due (once each, outside quiet hours)."""
    notify.send_due_reminders(session)


@periodic("bookings.expire_waitlist_offers", every_seconds=5 * 60)
def expire_waitlist_offers(session: Session) -> None:
    """A place offered to a waiting person that nobody took in time goes to the next person."""
    sessions.expire_offers(session)


@periodic("bookings.send_recalls", every_seconds=3 * 3600)
def send_recalls(session: Session) -> None:
    """Queue 'due again' reminders and rebooking prompts (outside quiet hours; each client once per visit)."""
    recalls.run_automatic(session)


@periodic("bookings.run_rentals", every_seconds=3600)
def run_rentals(session: Session) -> None:
    """Invoice the chair and room rent that has fallen due (each period once)."""
    rentals.run_due(session)
