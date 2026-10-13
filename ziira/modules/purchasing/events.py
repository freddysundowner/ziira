"""Events published and handled by the Purchasing and Suppliers module.

Publishes: po.approved, goods.received, bill.posted, bill.match_exception, supplier.bank_changed,
supplier.price_changed, supplier.paid
Subscribes: approval.decided (kernel): decides purchase requests, orders, bills and supplier bank changes
"""

from ziira.modules.purchasing.services import bills, orders, suppliers
from ziira.sdk import Event, Session, subscribe


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
