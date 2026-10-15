"""Public interface of the CRM and Customers module.

POS reads customers (and their credit) through these functions; it never reads CRM's tables.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.repository import crm_repo
from ziira.modules.crm.repository.models import Customer
from ziira.sdk import Session


@dataclass(frozen=True)
class CustomerView:
    """What other units need to know about a customer."""

    id: UUID
    company_id: UUID
    code: str
    name: str
    phone: str | None
    email: str | None
    tax_id: str | None
    customer_group: str | None
    credit_limit: Decimal
    payment_terms_days: int
    status: str


def _view(c: Customer) -> CustomerView:
    return CustomerView(c.id, c.company_id, c.code, c.name, c.phone, c.email, c.tax_id, c.customer_group,
                        c.credit_limit, c.payment_terms_days, c.status)


def find_customer(session: Session, customer_id: UUID) -> CustomerView | None:
    """A customer with their current credit limit and terms, or None."""
    customer = crm_repo.get_customer(session, customer_id)
    return _view(customer) if customer is not None else None


def find_customers(session: Session, customer_ids: set[UUID]) -> dict[UUID, CustomerView]:
    """Several customers at once, by id."""
    return {c.id: _view(c) for c in crm_repo.customers_by_ids(session, customer_ids)}


def find_customer_by_code(session: Session, company_id: UUID, code: str) -> CustomerView | None:
    """A company's customer by code (codes are upper case), or None."""
    customer = crm_repo.customer_by_code(session, company_id, code.strip().upper())
    return _view(customer) if customer is not None else None


def change_credit_limit(session: Session, customer_id: UUID, credit_limit: Decimal, reason: str) -> str:
    """Change a customer's credit limit (their payment terms stay) through CRM's own credit-change flow: lowering takes
    effect at once, raising goes to an approver. The caller needs 'customers.manage'. Returns the change's status."""
    from ziira.modules.crm.services import customers
    from ziira.sdk import NotFound

    customer = crm_repo.get_customer(session, customer_id)
    if customer is None:
        raise NotFound("Customer not found")
    version = customers.request_credit_change(session, customer_id, credit_limit=credit_limit,
                                              payment_terms_days=customer.payment_terms_days, reason=reason)
    return str(version.status)
