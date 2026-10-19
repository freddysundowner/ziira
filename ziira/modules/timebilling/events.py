"""Events published and handled by the Time and Billing module.

Publishes: timesheet.approved, timesheet.rejected, timebilling.invoiced
Subscribes: approval.decided (kernel): the answer for a submitted week when the company has an approval rule for
`timesheet`; invoice.cancelled (POS): the time, expenses and milestones on a cancelled invoice become unbilled again
"""

from ziira.modules.timebilling.services import billing, weeks
from ziira.sdk import Event, Session, subscribe


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Carry out the decision on a week that was waiting in the approvals inbox."""
    if event.aggregate_type == weeks.DOC_TYPE:
        weeks.apply_decision(session, event.aggregate_id, approved=event.payload["status"] == "approved",
                             decided_by=event.payload.get("decided_by"))


@subscribe("invoice.cancelled")
def on_invoice_cancelled(session: Session, event: Event) -> None:
    """An invoice was cancelled: if it was made from a review here, release its work."""
    billing.release_for_cancelled_invoice(session, event.aggregate_id, event.payload.get("reason"))
