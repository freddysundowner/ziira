"""Events published and handled by the Point of Sale and Sales module.

Publishes: sale.posted, sale.voided, sale.returned, discount.override, till.opened, till.closed, pos.synced,
invoice.issued, invoice.cancelled, customer.paid, customer.payment_reversed, customer.over_limit_attempt
Subscribes: approval.decided (kernel): posts or rejects a return, and confirms an order, that waited for approval;
payment.reversed (Payments): the invoices a reversed customer payment paid are owed again
"""

from ziira.modules.pos.services import customer_receipts, documents, returns
from ziira.sdk import Event, Session, subscribe


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Post or reject the return whose approval was just decided."""
    approved = event.payload["status"] == "approved"
    if event.aggregate_type == returns.DOC_TYPE:
        returns.apply_decision(session, event.aggregate_id, approved=approved,
                               decided_by=event.payload.get("decided_by"))
    elif event.aggregate_type == documents.ORDER_DOC:
        documents.apply_order_decision(session, event.aggregate_id, approved=approved,
                                       decided_by=event.payload.get("decided_by"))


@subscribe("payment.reversed")
def on_payment_reversed(session: Session, event: Event) -> None:
    """Make invoices owed again when the customer payment that settled them is reversed in Payments."""
    customer_receipts.apply_payment_reversal(session, event)
