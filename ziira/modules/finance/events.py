"""Events published and handled by the Finance and Accounting module.

Publishes: journal.posted, period.closed, expense.approved
Subscribes: stock.moved, sale.posted, sale.returned, payment.settled, payment.banked, till.closed, bill.posted,
bill.reversed, supplier.paid, supplier.payment_reversed, supplier.refunded, supplier.refund_reversed,
credit_note.posted, payroll.approved, payroll.paid, customer.paid, customer.payment_reversed,
customer.advance_refunded, customer.refund_reversed, customer.opening_balance, customer.opening_balance_reversed,
supplier.opening_balance, supplier.opening_balance_reversed, approval.decided (kernel)
"""

from ziira.modules.finance.services import event_postings, expenses, manual_journals
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


@subscribe("payment.settled")
def on_payment_settled(session: Session, event: Event) -> None:
    """Post an M-Pesa settlement to the bank."""
    event_postings.post_settlement(session, event)


@subscribe("payment.banked")
def on_cash_banked(session: Session, event: Event) -> None:
    """Post cash deposited in the bank."""
    event_postings.post_cash_deposit(session, event)


@subscribe("till.closed")
def on_till_closed(session: Session, event: Event) -> None:
    """Post a till shortage or overage."""
    event_postings.post_till_variance(session, event)


@subscribe("approval.decided")
def on_approval_decided(session: Session, event: Event) -> None:
    """Post or reject the manual journal or expense whose approval was just decided."""
    approved = event.payload["status"] == "approved"
    if event.aggregate_type == manual_journals.DOC_TYPE:
        manual_journals.apply_decision(session, event.aggregate_id, approved=approved,
                                       decided_by=event.payload.get("decided_by"))
    elif event.aggregate_type == expenses.DOC_TYPE:
        expenses.apply_decision(session, event.aggregate_id, approved=approved,
                                decided_by=event.payload.get("decided_by"))


@subscribe("bill.posted")
def on_bill_posted(session: Session, event: Event) -> None:
    """Clear goods received not invoiced and record what is owed to the supplier."""
    event_postings.post_supplier_bill(session, event)


@subscribe("supplier.paid")
def on_supplier_paid(session: Session, event: Event) -> None:
    """Reduce what is owed to the supplier by the money paid."""
    event_postings.post_supplier_payment(session, event)


@subscribe("bill.reversed")
def on_bill_reversed(session: Session, event: Event) -> None:
    """Undo the entry of a supplier bill that was posted by mistake."""
    event_postings.post_supplier_bill(session, event, reverse=True)


@subscribe("supplier.payment_reversed")
def on_supplier_payment_reversed(session: Session, event: Event) -> None:
    """Put back what was owed to the supplier when its payment is reversed."""
    event_postings.post_supplier_payment(session, event, kind="payment_reversal")


@subscribe("credit_note.posted")
def on_credit_note_posted(session: Session, event: Event) -> None:
    """Reduce what is owed to the supplier by its credit note."""
    event_postings.post_supplier_credit_note(session, event)


@subscribe("customer.paid")
def on_customer_paid(session: Session, event: Event) -> None:
    """Reduce what the customer owes by the money received."""
    event_postings.post_customer_payment(session, event)


@subscribe("customer.payment_reversed")
def on_customer_payment_reversed(session: Session, event: Event) -> None:
    """The customer owes the amount again when its payment is cancelled."""
    event_postings.post_customer_payment(session, event, kind="payment_reversal")


@subscribe("customer.advance_refunded")
def on_customer_advance_refunded(session: Session, event: Event) -> None:
    """Money held for a customer was given back: their account is no longer in credit by that much."""
    event_postings.post_customer_payment(session, event, kind="refund")


@subscribe("customer.refund_reversed")
def on_customer_refund_reversed(session: Session, event: Event) -> None:
    """A refund was cancelled: the customer is in credit again."""
    event_postings.post_customer_payment(session, event, kind="refund_reversal")


@subscribe("supplier.refunded")
def on_supplier_refunded(session: Session, event: Event) -> None:
    """A supplier paid back an overpaid bill: the amount the supplier owed the business is cleared."""
    event_postings.post_supplier_payment(session, event, kind="refund")


@subscribe("supplier.refund_reversed")
def on_supplier_refund_reversed(session: Session, event: Event) -> None:
    """A refund from a supplier was cancelled: the supplier owes the business again."""
    event_postings.post_supplier_payment(session, event, kind="refund_reversal")


@subscribe("payroll.approved")
def on_payroll_approved(session: Session, event: Event) -> None:
    """Post an approved payroll run."""
    event_postings.post_payroll(session, event)


@subscribe("payroll.paid")
def on_payroll_paid(session: Session, event: Event) -> None:
    """Post the payment of a payroll run's net pay."""
    event_postings.post_payroll_payment(session, event)


@subscribe("customer.opening_balance")
def on_customer_opening_balance(session: Session, event: Event) -> None:
    """Post a customer's opening balance against opening balance equity."""
    event_postings.post_customer_opening_balance(session, event)


@subscribe("customer.opening_balance_reversed")
def on_customer_opening_balance_reversed(session: Session, event: Event) -> None:
    """Take a customer's opening balance out again."""
    event_postings.post_customer_opening_balance(session, event, reverse=True)


@subscribe("supplier.opening_balance")
def on_supplier_opening_balance(session: Session, event: Event) -> None:
    """Post a supplier's opening balance against opening balance equity."""
    event_postings.post_supplier_opening_balance(session, event)


@subscribe("supplier.opening_balance_reversed")
def on_supplier_opening_balance_reversed(session: Session, event: Event) -> None:
    """Take a supplier's opening balance out again."""
    event_postings.post_supplier_opening_balance(session, event, reverse=True)
