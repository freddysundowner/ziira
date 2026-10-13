"""Recurring tasks of the POS module (run by `ziira worker`)."""

from sqlalchemy import text

from ziira.modules.pos.services import documents, receivables
from ziira.sdk import Session, company_setting, periodic

DAY = 24 * 3600


@periodic("pos.expire_quotations", every_seconds=6 * 3600)
def expire_quotations(session: Session) -> None:
    """Quotations past their date are expired, whether or not anyone looked at them."""
    documents.expire_all(session)


@periodic("pos.send_reminders", every_seconds=DAY)
def send_reminders(session: Session) -> None:
    """For each business that has turned on automatic reminders, chase customers with overdue invoices."""
    for row in session.execute(text("select id from kernel.company order by id")).all():
        channel = str(company_setting(session, row.id, "reminder_channel"))
        if channel == "off":
            continue
        receivables.send_due_reminders(
            session, channel=channel, company_id=row.id,
            min_days_overdue=int(company_setting(session, row.id, "reminder_min_days_overdue")),
            repeat_days=int(company_setting(session, row.id, "reminder_repeat_days")))
