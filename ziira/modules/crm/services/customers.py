"""Use cases: customers, their contacts, and their credit.

A customer's credit limit and payment terms are versioned. Lowering the limit or changing the terms takes effect at
once; *raising* the limit is approved by someone else (document type `credit_limit_change`; with no rule configured
only a person who holds `credit.approve` can raise it, so a salesperson cannot grant their own customer credit). Every
position is kept as history. POS reads the current limit through `public.find_customer`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.domain import rules
from ziira.modules.crm.permissions import CREDIT_APPROVE, CUSTOMERS_MANAGE
from ziira.modules.crm.repository import crm_repo as repo
from ziira.modules.crm.repository.models import CreditVersion, Customer, CustomerContact
from ziira.modules.crm.services import access, phones
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
    opt_out_contact,
    publish,
    submit_for_approval,
)

CREDIT_DOC = "credit_limit_change"


def _user_exists(session: Session, user_id: UUID) -> bool:
    return session.execute(text("select 1 from kernel.app_user where id = :u"), {"u": str(user_id)}).first() is not None


def get_customer(session: Session, customer_id: UUID) -> Customer:
    customer = repo.get_customer(session, customer_id)
    if customer is None:
        raise NotFound("Customer not found")
    access.check_visible(customer.company_id, "Customer")
    return customer


def list_customers(session: Session, *, search: str | None = None, status: str | None = None,
                   group: str | None = None, owner_id: UUID | None = None, limit: int = 50,
                   offset: int = 0) -> list[Customer]:
    return repo.list_customers(session, access.visible_companies(), search=search, status=status, group=group,
                               owner_id=owner_id, limit=min(limit, 200), offset=offset)


def create_customer(session: Session, *, company_id: UUID, name: str, code: str | None = None,
                    kind: str = "business", phone: str | None = None, email: str | None = None,
                    tax_id: str | None = None, customer_group: str | None = None, payment_terms_days: int = 0,
                    owner_user_id: UUID | None = None) -> Customer:
    """Add a customer with no credit (give credit with `request_credit_change`). The code is made for you when left
    out. Needs 'customers.manage'."""
    ctx = current_context()
    access.require(CUSTOMERS_MANAGE, company_id)
    check_company(session, company_id)
    if kind not in ("individual", "business"):
        raise ValidationFailed("Kind must be 'individual' or 'business'")
    rules.check_credit(Decimal(0), payment_terms_days)
    if owner_user_id is not None and not _user_exists(session, owner_user_id):
        raise ValidationFailed("The owner was not found")
    customer_code = rules.normalise_code(code) if code else next_document_number(
        session, company_id=company_id, branch_id=None, doc_type="customer", prefix="CUS")
    if repo.customer_by_code(session, company_id, customer_code) is not None:
        raise Conflict(f"There is already a customer with code {customer_code}")
    customer = Customer(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=customer_code,
        name=rules.clean_name(name), kind=kind, phone=phones.clean(session, company_id, phone),
        email=rules.clean_email(email),
        tax_id=rules.clean_tax_id(tax_id), customer_group=rules.clean_group(customer_group),
        payment_terms_days=payment_terms_days, owner_user_id=owner_user_id or ctx.user_id)
    repo.add(session, customer)
    repo.add(session, CreditVersion(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, customer_id=customer.id, credit_limit=Decimal(0),
        payment_terms_days=payment_terms_days, valid_from=datetime.now(UTC), reason="New customer",
        approved_by=ctx.user_id, status="active"))
    audit_record(session, "create", "crm.customer", customer.id, {"code": customer.code, "name": customer.name})
    publish(session, Event("customer.created", "crm.customer", customer.id, {
        "company_id": company_id, "code": customer.code, "name": customer.name}))
    return customer


def update_customer(session: Session, customer_id: UUID, *, name: str | None = None, phone: str | None = None,
                    email: str | None = None, tax_id: str | None = None, customer_group: str | None = None,
                    owner_user_id: UUID | None = None, status: str | None = None,
                    kind: str | None = None) -> Customer:
    """Change a customer's details or put it on hold. Credit is changed with `request_credit_change`. Needs
    'customers.manage'."""
    customer = repo.get_customer(session, customer_id, lock=True)
    if customer is None:
        raise NotFound("Customer not found")
    access.check_visible(customer.company_id, "Customer")
    access.require(CUSTOMERS_MANAGE, customer.company_id)
    changes: dict[str, object] = {}
    if name is not None:
        customer.name = rules.clean_name(name)
        changes["name"] = customer.name
    if phone is not None:
        customer.phone = phones.clean(session, customer.company_id, phone)
        changes["phone"] = customer.phone
    if email is not None:
        customer.email = rules.clean_email(email)
    if tax_id is not None:
        customer.tax_id = rules.clean_tax_id(tax_id)
        changes["tax_id"] = customer.tax_id
    if customer_group is not None:
        customer.customer_group = rules.clean_group(customer_group)
        changes["customer_group"] = customer.customer_group
    if owner_user_id is not None:
        if not _user_exists(session, owner_user_id):
            raise ValidationFailed("The owner was not found")
        customer.owner_user_id = owner_user_id
    if kind is not None:
        if kind not in ("individual", "business"):
            raise ValidationFailed("Kind must be 'individual' or 'business'")
        customer.kind = kind
    if status is not None:
        if status not in rules.CUSTOMER_STATUSES:
            raise ValidationFailed(f"Status must be one of: {', '.join(rules.CUSTOMER_STATUSES)}")
        customer.status = status
        changes["status"] = status
    customer.updated_by, customer.updated_at = current_context().user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "update", "crm.customer", customer.id, changes)
    return customer


# --------------------------------------------------------------------------- contacts
def list_contacts(session: Session, customer_id: UUID) -> list[CustomerContact]:
    get_customer(session, customer_id)
    return repo.contacts_of(session, customer_id)


def add_contact(session: Session, customer_id: UUID, *, name: str, phone: str | None = None,
                email: str | None = None, role: str | None = None) -> CustomerContact:
    """Add a person at a business customer. Needs 'customers.manage'."""
    customer = get_customer(session, customer_id)
    access.require(CUSTOMERS_MANAGE, customer.company_id)
    contact = CustomerContact(tenant_id=current_context().tenant_id, customer_id=customer.id,
                              name=rules.clean_name(name), phone=phones.clean(session, customer.company_id, phone),
                              email=rules.clean_email(email), role=(role or "").strip()[:60] or None)
    repo.add(session, contact)
    audit_record(session, "add_contact", "crm.customer", customer.id, {"contact": contact.name})
    return contact


def remove_contact(session: Session, customer_id: UUID, contact_id: UUID) -> None:
    customer = get_customer(session, customer_id)
    access.require(CUSTOMERS_MANAGE, customer.company_id)
    contact = repo.get_contact(session, contact_id)
    if contact is None or contact.customer_id != customer.id:
        raise NotFound("Contact not found")
    session.delete(contact)
    session.flush()
    audit_record(session, "remove_contact", "crm.customer", customer.id, {"contact": contact.name})


# --------------------------------------------------------------------------- credit
def credit_history(session: Session, customer_id: UUID) -> list[CreditVersion]:
    get_customer(session, customer_id)
    return repo.credit_versions(session, customer_id)


def request_credit_change(session: Session, customer_id: UUID, *, credit_limit: Decimal, payment_terms_days: int,
                          reason: str) -> CreditVersion:
    """Change a customer's credit limit and payment terms. Lowering the limit (or changing only the terms) applies at
    once; raising it goes to an approver. Needs 'customers.manage', and 'credit.approve' to raise the limit when no
    approval rule is configured. A reason is required."""
    customer = repo.get_customer(session, customer_id, lock=True)
    if customer is None:
        raise NotFound("Customer not found")
    access.check_visible(customer.company_id, "Customer")
    access.require(CUSTOMERS_MANAGE, customer.company_id)
    ctx = current_context()
    rules.check_credit(credit_limit, payment_terms_days)
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if credit_limit == customer.credit_limit and payment_terms_days == customer.payment_terms_days:
        raise ValidationFailed("That is what the customer has already")
    if repo.pending_credit(session, customer.id) is not None:
        raise Conflict("A credit change for this customer is already waiting for approval")
    version = CreditVersion(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, customer_id=customer.id, credit_limit=credit_limit,
        payment_terms_days=payment_terms_days, valid_from=datetime.now(UTC), reason=reason.strip(),
        status="pending_approval", previous_limit=customer.credit_limit)
    repo.add(session, version)
    increase = credit_limit - customer.credit_limit
    if not rules.credit_change_needs_approval(customer.credit_limit, credit_limit):
        _apply(session, customer, version, approved_by=ctx.user_id)
        return version
    decision = submit_for_approval(session, company_id=customer.company_id, doc_type=CREDIT_DOC, doc_id=version.id,
                                   amount=increase)
    if decision == "approved":
        if not access.holds(CREDIT_APPROVE, customer.company_id):
            raise Forbidden("Raising a credit limit needs a finance manager: ask for the increase to be approved")
        _apply(session, customer, version, approved_by=ctx.user_id)
    return version


def apply_credit_decision(session: Session, version_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Apply or drop a credit increase once its approval has been decided (from `approval.decided`)."""
    version = repo.get_credit_version(session, version_id, lock=True)
    customer = repo.get_customer(session, version.customer_id, lock=True) if version else None
    if version is None or customer is None or version.status != "pending_approval":
        return
    access.require(CREDIT_APPROVE, customer.company_id)
    if approved:
        _apply(session, customer, version, approved_by=decided_by)
    else:
        version.status = "rejected"
        session.flush()
        audit_record(session, "reject_credit", "crm.customer", customer.id, {"limit": version.credit_limit})


def _apply(session: Session, customer: Customer, version: CreditVersion, *, approved_by: UUID | None) -> None:
    previous = repo.active_credit(session, customer.id)
    if previous is not None:
        previous.status = "superseded"
        session.flush()
    version.status, version.approved_by, version.valid_from = "active", approved_by, datetime.now(UTC)
    before = customer.credit_limit
    customer.credit_limit, customer.payment_terms_days = version.credit_limit, version.payment_terms_days
    session.flush()
    audit_record(session, "set_credit", "crm.customer", customer.id,
                 {"limit": version.credit_limit, "terms": version.payment_terms_days, "reason": version.reason})
    publish(session, Event("customer.credit_limit_changed", "crm.customer", customer.id, {
        "company_id": customer.company_id, "code": customer.code, "previous": before, "new": version.credit_limit,
        "terms_days": version.payment_terms_days, "approved_by": approved_by, "reason": version.reason}))


def do_not_contact(session: Session, customer_id: UUID, *, channel: str | None = None,
                   reason: str | None = None) -> list[str]:
    """The customer asked not to be messaged (on one channel, or all of them): their phone and email are added to
    the business's do-not-contact list, which every message respects. Returns what was recorded. Needs
    'customers.manage'."""
    customer = repo.get_customer(session, customer_id)
    if customer is None:
        raise NotFound("Customer not found")
    access.check_visible(customer.company_id, "Customer")
    access.require(CUSTOMERS_MANAGE, customer.company_id)
    if channel not in (None, "email", "sms"):
        raise ValidationFailed("Channel must be email or sms")
    wanted = []
    if customer.phone and channel != "email":
        wanted.append(customer.phone)
    if customer.email and channel in (None, "email"):
        wanted.append(customer.email)
    if not wanted:
        raise ValidationFailed("The customer has no phone number or email address on record for that")
    for recipient in wanted:
        opt_out_contact(session, company_id=customer.company_id, recipient=recipient, channel=channel, reason=reason)
    audit_record(session, "do_not_contact", "crm.customer", customer.id, {"channel": channel})
    return ["email" if "@" in r else "phone" for r in wanted]
