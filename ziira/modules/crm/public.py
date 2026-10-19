"""Public interface of the CRM and Customers module.

POS reads customers (and their credit) through these functions; it never reads CRM's tables.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.repository import crm_repo
from ziira.modules.crm.repository.models import Customer, Lead
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


def match_or_create_customer(session: Session, company_id: UUID, *, name: str, phone: str | None = None,
                             email: str | None = None) -> tuple[CustomerView, bool]:
    """The company's customer with this phone number or email address, or a new individual customer when there is none.
    Returns (customer, created). Used where a person introduces themselves (an online booking): the phone is read with
    the company's calling code. Needs 'customers.manage' (a public page runs as the system, which holds it)."""
    from sqlalchemy import text

    from ziira.modules.crm.services import customers, phones
    from ziira.sdk import ValidationFailed

    digits = phones.clean(session, company_id, phone)
    address = (email or "").strip().lower() or None
    if digits is None and address is None:
        raise ValidationFailed("A phone number or an email address is needed")
    row = session.execute(text(
        "select id from crm.customer where company_id = :c and status <> 'inactive' "
        "and ((cast(:p as text) is not null and phone = :p) or (cast(:e as text) is not null and lower(email) = :e)) "
        "order by created_at limit 1"), {"c": str(company_id), "p": digits, "e": address}).first()
    if row is not None:
        found = find_customer(session, row.id)
        assert found is not None
        return found, False
    made = customers.create_customer(session, company_id=company_id, name=name, kind="individual", phone=phone,
                                     email=address)
    return _view(made), True


def search_customers(session: Session, company_id: UUID, query: str, limit: int = 20) -> list[CustomerView]:
    """Customers of a company whose name, code or phone matches what was typed (a phone number may be typed the way
    people write it locally: it is read with the company's calling code). No permission is checked: the caller has
    checked its own."""
    from ziira.modules.crm.services import phones

    text_query = query.strip()
    if not text_query:
        return []
    found: dict[UUID, Customer] = {}
    looks_like_phone = (sum(c.isdigit() for c in text_query) >= 6
                        and all(c.isdigit() or c in "+-() ." for c in text_query))
    digits = phones.clean(session, company_id, text_query) if looks_like_phone else None
    if digits:
        for customer in crm_repo.list_customers(session, {company_id}, search=digits, status=None, group=None,
                                                owner_id=None, limit=limit, offset=0):
            found[customer.id] = customer
    for customer in crm_repo.list_customers(session, {company_id}, search=text_query, status=None, group=None,
                                            owner_id=None, limit=limit, offset=0):
        found.setdefault(customer.id, customer)
    return [_view(c) for c in list(found.values())[:limit] if c.status != "inactive"]


@dataclass(frozen=True)
class LeadView:
    """What other units need to know about a lead (an enquiry)."""

    id: UUID
    company_id: UUID
    name: str
    phone: str | None
    email: str | None
    status: str
    converted_customer_id: UUID | None


def _lead_view(lead: Lead) -> LeadView:
    return LeadView(lead.id, lead.company_id, lead.name, lead.phone, lead.email, lead.status,
                    lead.converted_customer_id)


def find_lead(session: Session, lead_id: UUID) -> LeadView | None:
    """A lead, or None."""
    found = crm_repo.get_lead(session, lead_id)
    return _lead_view(found) if found is not None else None


def capture_lead(session: Session, company_id: UUID, *, name: str, phone: str | None = None,
                 email: str | None = None, source_name: str | None = None) -> LeadView:
    """Record an enquiry (a walk-in, a call, a website form) as a lead; the source is created if the name is new. Asking
    again for the same phone number returns the open lead instead of a second one. Needs 'leads.manage'."""
    from sqlalchemy import text

    from ziira.modules.crm.services import leads, phones

    digits = phones.clean(session, company_id, phone)
    if digits:
        row = session.execute(text(
            "select id from crm.lead where company_id = :c and phone = :p and status not in ('lost', 'converted') "
            "order by created_at limit 1"), {"c": str(company_id), "p": digits}).first()
        if row is not None:
            existing = crm_repo.get_lead(session, row.id)
            assert existing is not None
            return _lead_view(existing)
    source_id = None
    if source_name and source_name.strip():
        source = crm_repo.source_by_name(session, source_name.strip()) or leads.create_source(session, source_name)
        source_id = source.id
    return _lead_view(leads.create_lead(session, company_id=company_id, name=name, phone=phone, email=email,
                                        source_id=source_id))


def make_customer_from_lead(session: Session, lead_id: UUID) -> CustomerView:
    """Turn a lead into a customer (moving it along to 'contacted' first when it is new) and return the customer.
    A lead already converted returns its customer. Needs 'leads.manage' and 'customers.manage'."""
    from ziira.modules.crm.services import leads
    from ziira.sdk import NotFound

    lead = crm_repo.get_lead(session, lead_id)
    if lead is None:
        raise NotFound("Lead not found")
    if lead.status == "converted" and lead.converted_customer_id is not None:
        found = find_customer(session, lead.converted_customer_id)
        if found is not None:
            return found
    if lead.status == "new":
        leads.set_lead_status(session, lead_id, "contacted")
    _, customer = leads.convert_lead(session, lead_id)
    return _view(customer)


WALK_IN_CODE = "WALKIN"


def walk_in_customer(session: Session, company_id: UUID) -> CustomerView:
    """The company's catch-all customer for people who gave no phone or email (code WALKIN; made the first time it is
    needed). Used where a document must name a customer record but the person is only passing through (a garage job
    paid at the counter). Needs 'customers.manage' the first time."""
    from ziira.modules.crm.services import customers

    found = find_customer_by_code(session, company_id, WALK_IN_CODE)
    if found is not None:
        return found
    made = customers.create_customer(session, company_id=company_id, name="Walk-in customer", code=WALK_IN_CODE,
                                     kind="individual")
    return _view(made)
