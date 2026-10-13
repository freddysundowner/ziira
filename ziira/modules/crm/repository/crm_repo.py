"""Database access for the crm schema. Row-level security scopes every query to the tenant."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ziira.modules.crm.repository.models import (
    Activity,
    CreditVersion,
    Customer,
    CustomerContact,
    Lead,
    LeadSource,
)


def add(session: Session, record: Any) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def _locked(query: Any) -> Any:
    return query.with_for_update().execution_options(populate_existing=True)


def _like(text_: str) -> str:
    escaped = text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --------------------------------------------------------------------------- customers
def get_customer(session: Session, customer_id: UUID, *, lock: bool = False) -> Customer | None:
    if lock:
        return session.scalars(_locked(select(Customer).where(Customer.id == customer_id))).first()
    return session.get(Customer, customer_id)


def customers_by_ids(session: Session, ids: set[UUID]) -> list[Customer]:
    if not ids:
        return []
    return list(session.scalars(select(Customer).where(Customer.id.in_(ids))))


def customer_by_code(session: Session, company_id: UUID, code: str) -> Customer | None:
    return session.scalar(select(Customer).where(Customer.company_id == company_id, Customer.code == code))


def list_customers(session: Session, company_ids: set[UUID] | None, *, search: str | None, status: str | None,
                   group: str | None, owner_id: UUID | None, limit: int, offset: int) -> list[Customer]:
    query = select(Customer).order_by(Customer.name, Customer.id).limit(limit).offset(offset)
    if company_ids is not None:
        query = query.where(Customer.company_id.in_(company_ids))
    if status:
        query = query.where(Customer.status == status)
    if group:
        query = query.where(Customer.customer_group == group)
    if owner_id:
        query = query.where(Customer.owner_user_id == owner_id)
    if search:
        pattern = _like(search.strip())
        query = query.where(Customer.name.ilike(pattern, escape="\\") | Customer.code.ilike(pattern, escape="\\")
                            | Customer.phone.ilike(pattern, escape="\\"))
    return list(session.scalars(query))


def contacts_of(session: Session, customer_id: UUID) -> list[CustomerContact]:
    return list(session.scalars(select(CustomerContact).where(CustomerContact.customer_id == customer_id)
                                .order_by(CustomerContact.created_at, CustomerContact.id)))


def get_contact(session: Session, contact_id: UUID) -> CustomerContact | None:
    return session.get(CustomerContact, contact_id)


# --------------------------------------------------------------------------- credit
def credit_versions(session: Session, customer_id: UUID) -> list[CreditVersion]:
    return list(session.scalars(select(CreditVersion).where(CreditVersion.customer_id == customer_id)
                                .order_by(CreditVersion.valid_from.desc(), CreditVersion.created_at.desc())))


def get_credit_version(session: Session, version_id: UUID, *, lock: bool = False) -> CreditVersion | None:
    if lock:
        return session.scalars(_locked(select(CreditVersion).where(CreditVersion.id == version_id))).first()
    return session.get(CreditVersion, version_id)


def active_credit(session: Session, customer_id: UUID) -> CreditVersion | None:
    return session.scalar(select(CreditVersion).where(CreditVersion.customer_id == customer_id,
                                                      CreditVersion.status == "active"))


def pending_credit(session: Session, customer_id: UUID) -> CreditVersion | None:
    return session.scalar(select(CreditVersion).where(CreditVersion.customer_id == customer_id,
                                                      CreditVersion.status == "pending_approval"))


# --------------------------------------------------------------------------- leads
def get_source(session: Session, source_id: UUID) -> LeadSource | None:
    return session.get(LeadSource, source_id)


def source_by_name(session: Session, name: str) -> LeadSource | None:
    return session.scalar(select(LeadSource).where(func.lower(LeadSource.name) == name.lower()))


def list_sources(session: Session) -> list[LeadSource]:
    return list(session.scalars(select(LeadSource).order_by(LeadSource.name)))


def get_lead(session: Session, lead_id: UUID, *, lock: bool = False) -> Lead | None:
    if lock:
        return session.scalars(_locked(select(Lead).where(Lead.id == lead_id))).first()
    return session.get(Lead, lead_id)


def list_leads(session: Session, company_ids: set[UUID] | None, *, status: str | None, owner_id: UUID | None,
               source_id: UUID | None, search: str | None, limit: int, offset: int) -> list[Lead]:
    query = select(Lead).order_by(Lead.created_at.desc(), Lead.id).limit(limit).offset(offset)
    if company_ids is not None:
        query = query.where(Lead.company_id.in_(company_ids))
    if status:
        query = query.where(Lead.status == status)
    if owner_id:
        query = query.where(Lead.owner_user_id == owner_id)
    if source_id:
        query = query.where(Lead.source_id == source_id)
    if search:
        pattern = _like(search.strip())
        query = query.where(Lead.name.ilike(pattern, escape="\\") | Lead.business_name.ilike(pattern, escape="\\")
                            | Lead.phone.ilike(pattern, escape="\\"))
    return list(session.scalars(query))


# --------------------------------------------------------------------------- activities
def get_activity(session: Session, activity_id: UUID, *, lock: bool = False) -> Activity | None:
    if lock:
        return session.scalars(_locked(select(Activity).where(Activity.id == activity_id))).first()
    return session.get(Activity, activity_id)


def list_activities(session: Session, *, related_type: str | None, related_id: UUID | None, owner_id: UUID | None,
                    open_only: bool, due_before: datetime | None, limit: int, offset: int) -> list[Activity]:
    query = select(Activity).order_by(Activity.due_at.asc().nulls_last(), Activity.created_at.desc()).limit(
        limit).offset(offset)
    if related_type:
        query = query.where(Activity.related_type == related_type)
    if related_id:
        query = query.where(Activity.related_id == related_id)
    if owner_id:
        query = query.where(Activity.owner_user_id == owner_id)
    if open_only:
        query = query.where(Activity.done_at.is_(None))
    if due_before:
        query = query.where(Activity.due_at <= due_before)
    return list(session.scalars(query))
