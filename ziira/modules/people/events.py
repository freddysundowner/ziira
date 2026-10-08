"""Events published and handled by the People, HR and Payroll module.

Publishes: employee.pay_changed, employee.bank_changed, payroll.approved, payroll.paid
Subscribes: till.opened, till.closed
"""

from ziira.sdk import Event, Session, subscribe  # noqa: F401

# @subscribe("till.opened")
# def on_till_opened(session: Session, event: Event) -> None:
#     ...

# @subscribe("till.closed")
# def on_till_closed(session: Session, event: Event) -> None:
#     ...
