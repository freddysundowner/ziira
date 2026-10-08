"""Events published and handled by the Finance and Accounting module.

Publishes: journal.posted, period.closed, expense.approved
Subscribes: sale.posted, sale.returned, payment.received, goods.received, bill.posted, stock.adjusted, payroll.approved
"""

from ziira.sdk import Event, Session, subscribe  # noqa: F401

# @subscribe("sale.posted")
# def on_sale_posted(session: Session, event: Event) -> None:
#     ...

# @subscribe("sale.returned")
# def on_sale_returned(session: Session, event: Event) -> None:
#     ...

# @subscribe("payment.received")
# def on_payment_received(session: Session, event: Event) -> None:
#     ...

# @subscribe("goods.received")
# def on_goods_received(session: Session, event: Event) -> None:
#     ...

# @subscribe("bill.posted")
# def on_bill_posted(session: Session, event: Event) -> None:
#     ...

# @subscribe("stock.adjusted")
# def on_stock_adjusted(session: Session, event: Event) -> None:
#     ...

# @subscribe("payroll.approved")
# def on_payroll_approved(session: Session, event: Event) -> None:
#     ...
