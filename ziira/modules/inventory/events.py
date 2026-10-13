"""Events published and handled by the Inventory and Branches module.

Publishes: stock.moved, stock.negative, stock.adjusted, transfer.dispatched, transfer.received,
count.posted, stock.below_reorder
Subscribes: approval.decided (kernel), sale.posted, sale.returned, goods.received
"""

from ziira.modules.inventory.services import adjustments, counts, transfers
from ziira.sdk import Event, Session, subscribe


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Post or reject the stock document whose approval was just decided."""
    approved = event.payload["status"] == "approved"
    if event.aggregate_type == adjustments.DOC_TYPE:
        adjustments.apply_decision(session, event.aggregate_id, approved=approved,
                                   decided_by=event.payload.get("decided_by"))
    elif event.aggregate_type == counts.DOC_TYPE:
        counts.apply_decision(session, event.aggregate_id, approved=approved,
                              decided_by=event.payload.get("decided_by"))
    elif event.aggregate_type == transfers.DOC_TYPE:
        transfers.apply_decision(session, event.aggregate_id, approved=approved,
                                 decided_by=event.payload.get("decided_by"))

# @subscribe("sale.posted")
# def on_sale_posted(session: Session, event: Event) -> None:
#     ...

# @subscribe("sale.returned")
# def on_sale_returned(session: Session, event: Event) -> None:
#     ...

# @subscribe("goods.received")
# def on_goods_received(session: Session, event: Event) -> None:
#     ...
