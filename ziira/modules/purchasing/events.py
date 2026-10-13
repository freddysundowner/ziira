"""Events published and handled by the Purchasing and Suppliers module.

Publishes: po.approved, goods.received, bill.posted, bill.match_exception, supplier.bank_changed,
supplier.price_changed, supplier.paid
Subscribes: approval.decided (kernel): decides purchase requests, orders, bills and supplier bank changes;
payment.reversed: a bill whose payment was reversed is owed again; a refund that was reversed is owed again
"""

from ziira.modules.purchasing.services import bills, orders, refunds, suppliers
from ziira.sdk import Event, Session, subscribe


@subscribe("payment.reversed")
def on_payment_reversed(session: Session, event: Event) -> None:
    """Make a supplier bill owed again when a payment made against it is reversed in Payments."""
    bills.apply_payment_reversal(session, event)
    refunds.apply_payment_reversal(session, event)


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Carry out the decision on whatever was waiting for approval."""
    approved = event.payload["status"] == "approved"
    decided_by = event.payload.get("decided_by")
    if event.aggregate_type == orders.ORDER_DOC:
        orders.apply_order_decision(session, event.aggregate_id, approved=approved, decided_by=decided_by)
    elif event.aggregate_type == orders.REQUEST_DOC:
        orders.apply_request_decision(session, event.aggregate_id, approved=approved, decided_by=decided_by)
    elif event.aggregate_type == bills.DOC_TYPE:
        bills.apply_bill_decision(session, event.aggregate_id, approved=approved, decided_by=decided_by)
    elif event.aggregate_type == suppliers.BANK_DOC_TYPE:
        suppliers.apply_bank_decision(session, event.aggregate_id, approved=approved, decided_by=decided_by)
