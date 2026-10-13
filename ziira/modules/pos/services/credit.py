"""Use cases: selling on credit - may this customer take this much on account?

A customer's credit is a limit and payment terms (CRM). What they owe is the unpaid part of their invoices. A sale on
credit is refused for a customer who is on hold or would go over the limit; a sale that already happened offline is
recorded anyway and the problem is raised for a manager.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.public import CustomerView, find_customer
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.services.common import unit_enabled
from ziira.sdk import Session, ValidationFailed


def load_customer(session: Session, customer_id: UUID, company_id: UUID, *, for_credit: bool) -> CustomerView | None:
    """The customer from CRM. `None` when CRM is off and credit is not being asked for."""
    if not unit_enabled(session, "crm"):
        if for_credit:
            raise ValidationFailed("Enable CRM to sell on credit: credit is given to customers")
        return None
    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("Customer not found in this company")
    return customer


def owed(session: Session, customer_id: UUID) -> Decimal:
    """What the customer owes on unpaid invoices, less money they hold on account in advance (negative: they are in
    credit)."""
    return pos_repo.customer_exposure(session, customer_id) - pos_repo.customer_advances(session, customer_id)


def due_date(day: date, customer: CustomerView) -> date:
    return day + timedelta(days=customer.payment_terms_days)


def check_credit(session: Session, customer: CustomerView, amount: Decimal, *, offline: bool) -> list[str]:
    """Can the customer take `amount` more on account? Online it raises when not; offline it returns what is wrong, as
    warnings, because the goods have already gone."""
    # one customer's credit decisions happen one at a time, so two sales cannot both fit under the same limit
    pos_repo.lock_key(session, f"pos.credit:{customer.id}")
    problems: list[tuple[str, str]] = []
    if customer.status != "active":
        problems.append((f"customer_on_hold:{customer.code}",
                         f"{customer.name} is {customer.status.replace('_', ' ')}"))
    already = owed(session, customer.id)
    if already + amount > customer.credit_limit:
        problems.append((f"over_credit_limit:{customer.code}:{already + amount}:{customer.credit_limit}",
                         f"{customer.name} owes {already} and this sale adds {amount}, over their credit limit of "
                         f"{customer.credit_limit}"))
    if problems and not offline:
        raise ValidationFailed(f"Credit refused: {'; '.join(text for _, text in problems)}")
    return [code for code, _ in problems]
