"""Shared helpers of the Memberships services: access, customers, units."""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.public import CustomerView, find_customer, find_customers
from ziira.modules.memberships import permissions as perm
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.sdk import Forbidden, NotFound, Session, ValidationFailed, company_today, current_context


def unit_enabled(session: Session, unit: str) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def today(session: Session, company_id: UUID) -> date:
    return company_today(session, company_id)


def require(permission: str, company_id: UUID, branch_id: UUID | None = None) -> None:
    current_context().require(permission, company_id=company_id, branch_id=branch_id)


def require_in_company(permission: str, company_id: UUID) -> None:
    """For records of a person (a profile, their terms, measurements): the actor holds the permission at some level
    in the
    company, at one branch or all (such a record does not belong to one branch)."""
    ctx = current_context()
    companies = ctx.companies_with(permission)
    if companies is not None and company_id not in companies:
        raise Forbidden(f"You do not have permission '{permission}' here")


def view_scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    """Where the person may see memberships records (None: everywhere)."""
    ctx = current_context()
    found: list[tuple[UUID | None, UUID | None]] = []
    for permission in perm.ALL:
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found += scopes
    return found


def check_visible(company_id: UUID, branch_id: UUID | None = None, what: str = "Record") -> None:
    scopes = view_scopes()
    if scopes is None:
        return
    if not any((c is None or c == company_id) and (b is None or branch_id is None or b == branch_id)
               for c, b in scopes):
        raise NotFound(f"{what} not found")


def visible_company_ids() -> set[UUID] | None:
    ctx = current_context()
    found: set[UUID] = set()
    for permission in perm.ALL:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def customer_of(session: Session, company_id: UUID, customer_id: UUID) -> CustomerView:
    """The customer, who must belong to the company and be allowed new business."""
    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("The customer was not found in this company")
    if customer.status == "inactive":
        raise ValidationFailed("This customer is inactive")
    return customer


def customer_of_any(session: Session, customer_id: UUID) -> CustomerView:
    """The customer, whatever their status (an inactive customer can still spend what they paid for)."""
    customer = find_customer(session, customer_id)
    if customer is None:
        raise ValidationFailed("Customer not found")
    return customer


def customer_names(session: Session, customer_ids: set[UUID]) -> dict[UUID, CustomerView]:
    return find_customers(session, customer_ids) if customer_ids else {}


def check_product(session: Session, company_id: UUID, product_id: UUID | None, *, service_only: bool = True) -> None:
    """A product named by a plan, package or invoice line must be the company's (a service item when asked)."""
    if product_id is None:
        return
    if not unit_enabled(session, "products"):
        raise ValidationFailed("Products must be switched on to name a service item")
    from ziira.modules.products.public import find_product

    product = find_product(session, product_id)
    if product is None or product.company_id != company_id:
        raise ValidationFailed("That product was not found in this company")
    if service_only and product.product_type != "service":
        raise ValidationFailed(f"{product.name} is not a service item")


def get_row(session: Session, table: str, row_id: UUID, what: str, *, lock: bool = False) -> repo.Row:
    row = repo.get(session, table, row_id, lock=lock)
    if row is None:
        raise NotFound(f"{what} not found")
    check_visible(row["company_id"], row.get("branch_id"), what)
    return row


def forbid_if(condition: bool, message: str) -> None:
    if condition:
        raise Forbidden(message)


def one_company(session: Session, company_id: UUID) -> repo.Row:
    """The company's name and currency (for message wording)."""
    found = repo.one(session, "select name, base_currency from kernel.company where id = :c", c=company_id)
    if found is None:
        raise NotFound("Company not found")
    return found
