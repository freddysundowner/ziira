"""Events published and handled by the CRM and Customers module.

Publishes: customer.created, lead.created, lead.converted, customer.credit_limit_changed
Subscribes: approval.decided (kernel): applies or drops a credit limit increase
"""

from ziira.modules.crm.services import customers
from ziira.sdk import Event, Session, subscribe


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Apply the decision on a credit limit increase."""
    if event.aggregate_type == customers.CREDIT_DOC:
        customers.apply_credit_decision(session, event.aggregate_id, approved=event.payload["status"] == "approved",
                                        decided_by=event.payload.get("decided_by"))
