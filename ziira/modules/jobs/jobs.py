"""Recurring work of Jobs: next-service reminders and reminders to collect a finished item."""

from ziira.modules.jobs.services import notify, service_due
from ziira.sdk import Session, periodic


@periodic("jobs.service_reminders", every_seconds=6 * 3600)
def service_reminders(session: Session) -> None:
    """Queue the next-service reminders that are due (once per item and date)."""
    service_due.send_due_reminders(session)


@periodic("jobs.ready_reminders", every_seconds=6 * 3600)
def ready_reminders(session: Session) -> None:
    """Remind customers whose finished item has waited too long (once per job)."""
    notify.send_ready_reminders(session)
