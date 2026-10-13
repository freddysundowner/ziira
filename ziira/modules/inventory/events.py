"""Events published and handled by the Inventory and Branches module.

Publishes: stock.moved, stock.negative, stock.adjusted, transfer.dispatched, transfer.received,
count.posted, stock.below_reorder
Subscribes: approval.decided (kernel), sale.posted, sale.returned, goods.received, goods.returned
"""

from ziira.modules.inventory.services import adjustments, counts, stock_events, transfers
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



@subscribe("sale.posted")
def on_sale_posted(session: Session, event: Event) -> None:
    """Take sold stock out of the location. See services/stock_events.py for the payload."""
    stock_events.post_sale(session, event)


@subscribe("sale.returned")
def on_sale_returned(session: Session, event: Event) -> None:
    """Put returned stock back at the cost it left with."""
    stock_events.post_sale_return(session, event)


@subscribe("goods.received")
def on_goods_received(session: Session, event: Event) -> None:
    """Receive purchased stock at its cost (with landed cost spread over the lines)."""
    stock_events.post_goods_receipt(session, event)


@subscribe("goods.returned")
def on_goods_returned(session: Session, event: Event) -> None:
    """Take stock sent back to a supplier out of the location."""
    stock_events.post_goods_return(session, event)
