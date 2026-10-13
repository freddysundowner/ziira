"""Events published and handled by the Finance and Accounting module.

Publishes: journal.posted, period.closed
Subscribes: stock.moved, sale.posted, sale.returned, approval.decided (kernel)
"""

from ziira.modules.finance.services import event_postings, manual_journals
from ziira.sdk import Event, Session, subscribe


@subscribe("stock.moved")
def on_stock_moved(session: Session, event: Event) -> None:
    """Post the inventory, cost of sales, shrinkage and transfer entries for a stock movement."""
    event_postings.post_stock_movement(session, event)


@subscribe("sale.posted")
def on_sale_posted(session: Session, event: Event) -> None:
    """Post a sale: money received or owed against sales and VAT output."""
    event_postings.post_sale(session, event)


@subscribe("sale.returned")
def on_sale_returned(session: Session, event: Event) -> None:
    """Post a customer return."""
    event_postings.post_sale_return(session, event)


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Post or reject the manual journal whose approval was just decided."""
    if event.aggregate_type == manual_journals.DOC_TYPE:
        manual_journals.apply_decision(session, event.aggregate_id, approved=event.payload["status"] == "approved",
                                       decided_by=event.payload.get("decided_by"))
