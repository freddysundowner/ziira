"""Events published and handled by the Payments and Reconciliation module.

Publishes: payment.received, payment.made, payment.matched, payment.unmatched, payment.settled, payment.banked,
stk.completed, close.completed, close.variance
Subscribes: approval.decided (kernel)
"""

from ziira.modules.payments.services import closing
from ziira.sdk import Event, Session, subscribe


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Reopen the day whose reopening was just approved."""
    if event.aggregate_type == closing.DOC_TYPE:
        closing.apply_decision(session, event.aggregate_id, approved=event.payload["status"] == "approved",
                               decided_by=event.payload.get("decided_by"))
