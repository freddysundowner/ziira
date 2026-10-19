"""Public interface of the Time and Billing module.

Other units normally talk to it through events (`timesheet.approved`, `timebilling.invoiced`).
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session


def unbilled_value(session: Session, client_id: UUID) -> Decimal:
    """What approved work for a client is worth at the rates fixed on approval, not yet invoiced (time at its rate,
    expenses with markup, milestones ready to bill). For a customer screen or a credit decision."""
    time_value = session.execute(text(
        "select coalesce(sum(round((e.minutes - e.retainer_minutes) * coalesce(e.bill_rate, 0) / 60, 2)), 0) "
        "from timebilling.entry e join timebilling.project p on p.id = e.project_id "
        "where p.client_id = :c and p.billing_mode <> 'fixed_fee' and e.status = 'approved' and e.billable "
        "and e.invoice_id is null and not e.written_off"), {"c": str(client_id)}).scalar_one()
    expenses = session.execute(text(
        "select coalesce(sum(round(x.amount * (100 + x.markup_percent) / 100, 2)), 0) from timebilling.expense x "
        "join timebilling.project p on p.id = x.project_id where p.client_id = :c and x.status = 'approved' "
        "and x.billable and x.invoice_id is null and not x.written_off"), {"c": str(client_id)}).scalar_one()
    milestones = session.execute(text(
        "select coalesce(sum(m.amount), 0) from timebilling.milestone m join timebilling.project p "
        "on p.id = m.project_id where p.client_id = :c and m.status = 'ready'"), {"c": str(client_id)}).scalar_one()
    return Decimal(time_value) + Decimal(expenses) + Decimal(milestones)
