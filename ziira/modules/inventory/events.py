"""Events published and handled by the Inventory and Branches module.

Publishes: stock.moved, stock.adjusted, transfer.dispatched, transfer.received, count.posted, stock.below_reorder
Subscribes: sale.posted, sale.returned, goods.received
"""

from ziira.sdk import Event, Session, subscribe  # noqa: F401

# @subscribe("sale.posted")
# def on_sale_posted(session: Session, event: Event) -> None:
#     ...

# @subscribe("sale.returned")
# def on_sale_returned(session: Session, event: Event) -> None:
#     ...

# @subscribe("goods.received")
# def on_goods_received(session: Session, event: Event) -> None:
#     ...
