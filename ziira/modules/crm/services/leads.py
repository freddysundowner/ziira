"""Use cases: leads, where they come from, follow-up activities, and turning a lead into a customer."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.domain import rules
from ziira.modules.crm.permissions import CUSTOMERS_MANAGE, LEADS_MANAGE
from ziira.modules.crm.repository import crm_repo as repo
from ziira.modules.crm.repository.models import Activity, Customer, Lead, LeadSource
from ziira.modules.crm.services import access, customers, phones
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
    publish,
)


def _user_exists(session: Session, user_id: UUID) -> bool:
    return session.execute(text("select 1 from kernel.app_user where id = :u"), {"u": str(user_id)}).first() is not None


# --------------------------------------------------------------------------- sources
def list_sources(session: Session) -> list[LeadSource]:
    return repo.list_sources(session)


def create_source(session: Session, name: str) -> LeadSource:
    """Add a place leads come from (a referral, a flyer, Facebook). Needs 'leads.manage'."""
    ctx = current_context()
    if not ctx.has_anywhere(LEADS_MANAGE):
        raise Forbidden(f"You do not have permission '{LEADS_MANAGE}' here")
    clean = rules.clean_name(name, "Source name")
    if repo.source_by_name(session, clean) is not None:
        raise Conflict(f"There is already a source called {clean}")
    source = LeadSource(tenant_id=ctx.tenant_id, created_by=ctx.user_id, name=clean)
    repo.add(session, source)
    return source


# --------------------------------------------------------------------------- leads
def get_lead(session: Session, lead_id: UUID) -> Lead:
    lead = repo.get_lead(session, lead_id)
    if lead is None:
        raise NotFound("Lead not found")
    access.check_visible(lead.company_id, "Lead")
    return lead


def list_leads(session: Session, *, status: str | None = None, owner_id: UUID | None = None,
               source_id: UUID | None = None, search: str | None = None, limit: int = 50,
               offset: int = 0) -> list[Lead]:
    return repo.list_leads(session, access.visible_companies(), status=status, owner_id=owner_id,
                           source_id=source_id, search=search, limit=min(limit, 200), offset=offset)


def create_lead(session: Session, *, company_id: UUID, name: str, business_name: str | None = None,
                phone: str | None = None, email: str | None = None, source_id: UUID | None = None,
                owner_user_id: UUID | None = None, customer_kind: str | None = None) -> Lead:
    """Capture a prospective customer. Needs 'leads.manage'."""
    ctx = current_context()
    access.require(LEADS_MANAGE, company_id)
    check_company(session, company_id)
    if source_id is not None and repo.get_source(session, source_id) is None:
        raise ValidationFailed("Lead source not found")
    if owner_user_id is not None and not _user_exists(session, owner_user_id):
        raise ValidationFailed("The owner was not found")
    if customer_kind not in (None, "individual", "business"):
        raise ValidationFailed("Kind must be 'individual' or 'business'")
    clean_phone, clean_mail = phones.clean(session, company_id, phone), rules.clean_email(email)
    if clean_phone is None and clean_mail is None:
        raise ValidationFailed("Give a phone number or an email address to reach the lead")
    lead = Lead(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, name=rules.clean_name(name),
                business_name=(business_name or "").strip()[:200] or None, phone=clean_phone, email=clean_mail,
                source_id=source_id, owner_user_id=owner_user_id or ctx.user_id, customer_kind=customer_kind)
    repo.add(session, lead)
    audit_record(session, "create", "crm.lead", lead.id, {"name": lead.name})
    publish(session, Event("lead.created", "crm.lead", lead.id, {
        "company_id": company_id, "name": lead.name, "owner_user_id": lead.owner_user_id, "source_id": source_id}))
    return lead


def update_lead(session: Session, lead_id: UUID, *, name: str | None = None, business_name: str | None = None,
                phone: str | None = None, email: str | None = None, owner_user_id: UUID | None = None,
                source_id: UUID | None = None) -> Lead:
    lead = repo.get_lead(session, lead_id, lock=True)
    if lead is None:
        raise NotFound("Lead not found")
    access.check_visible(lead.company_id, "Lead")
    access.require(LEADS_MANAGE, lead.company_id)
    if lead.status == "converted":
        raise Conflict("A converted lead is now a customer: change the customer instead")
    if name is not None:
        lead.name = rules.clean_name(name)
    if business_name is not None:
        lead.business_name = business_name.strip()[:200] or None
    if phone is not None:
        lead.phone = phones.clean(session, lead.company_id, phone)
    if email is not None:
        lead.email = rules.clean_email(email)
    if owner_user_id is not None:
        if not _user_exists(session, owner_user_id):
            raise ValidationFailed("The owner was not found")
        lead.owner_user_id = owner_user_id
    if source_id is not None:
        if repo.get_source(session, source_id) is None:
            raise ValidationFailed("Lead source not found")
        lead.source_id = source_id
    lead.updated_by, lead.updated_at = current_context().user_id, datetime.now(UTC)
    session.flush()
    audit_record(session, "update", "crm.lead", lead.id, None)
    return lead


def set_lead_status(session: Session, lead_id: UUID, status: str, *, lost_reason: str | None = None) -> Lead:
    """Move a lead along (new, contacted, qualified, or lost with a reason). Converting is done by `convert_lead`."""
    lead = repo.get_lead(session, lead_id, lock=True)
    if lead is None:
        raise NotFound("Lead not found")
    access.check_visible(lead.company_id, "Lead")
    access.require(LEADS_MANAGE, lead.company_id)
    if status == "converted":
        raise ValidationFailed("Convert the lead to make it a customer")
    rules.check_lead_move(lead.status, status)
    if status == "lost":
        if not (lost_reason and lost_reason.strip()):
            raise ValidationFailed("Say why the lead was lost")
        lead.lost_reason = lost_reason.strip()[:300]
    else:
        lead.lost_reason = None
    lead.status = status
    session.flush()
    audit_record(session, "status", "crm.lead", lead.id, {"status": status, "reason": lead.lost_reason})
    return lead


def convert_lead(session: Session, lead_id: UUID, *, code: str | None = None,
                 customer_group: str | None = None) -> tuple[Lead, Customer]:
    """Turn a qualified or contacted lead into a customer. Needs 'leads.manage' and 'customers.manage'."""
    lead = repo.get_lead(session, lead_id, lock=True)
    if lead is None:
        raise NotFound("Lead not found")
    access.check_visible(lead.company_id, "Lead")
    access.require(LEADS_MANAGE, lead.company_id)
    access.require(CUSTOMERS_MANAGE, lead.company_id)
    if lead.status == "converted":
        raise Conflict("This lead has already been converted")
    if lead.status in ("lost", "new"):
        raise ValidationFailed(f"A lead that is {lead.status} cannot be converted: contact or qualify it first")
    kind = lead.customer_kind or ("business" if lead.business_name else "individual")
    customer = customers.create_customer(
        session, company_id=lead.company_id, name=lead.business_name or lead.name, code=code, kind=kind,
        phone=lead.phone, email=lead.email, customer_group=customer_group, owner_user_id=lead.owner_user_id)
    if kind == "business" and lead.business_name:
        customers.add_contact(session, customer.id, name=lead.name, phone=lead.phone, email=lead.email, role="Contact")
    lead.status, lead.converted_customer_id = "converted", customer.id
    session.flush()
    audit_record(session, "convert", "crm.lead", lead.id, {"customer": customer.code})
    publish(session, Event("lead.converted", "crm.lead", lead.id, {
        "company_id": lead.company_id, "customer_id": customer.id, "customer_code": customer.code}))
    return lead, customer


# --------------------------------------------------------------------------- activities
def _related_company(session: Session, related_type: str, related_id: UUID) -> UUID:
    if related_type == "lead":
        lead = repo.get_lead(session, related_id)
        if lead is None:
            raise NotFound("Lead not found")
        return lead.company_id
    if related_type == "customer":
        customer = repo.get_customer(session, related_id)
        if customer is None:
            raise NotFound("Customer not found")
        return customer.company_id
    raise ValidationFailed("An activity is about a lead or a customer")


def create_activity(session: Session, *, related_type: str, related_id: UUID, kind: str,
                    due_at: datetime | None = None, owner_user_id: UUID | None = None,
                    note: str | None = None) -> Activity:
    """Plan or log a call, visit, message, meeting or task about a lead or customer. Needs 'leads.manage' or
    'customers.manage'."""
    ctx = current_context()
    company_id = _related_company(session, related_type, related_id)
    access.check_visible(company_id, "Record")
    if not (access.holds(LEADS_MANAGE, company_id) or access.holds(CUSTOMERS_MANAGE, company_id)):
        raise Forbidden("You do not have permission to add activities here")
    if kind not in rules.ACTIVITY_KINDS:
        raise ValidationFailed(f"Kind must be one of: {', '.join(rules.ACTIVITY_KINDS)}")
    if owner_user_id is not None and not _user_exists(session, owner_user_id):
        raise ValidationFailed("The owner was not found")
    activity = Activity(tenant_id=ctx.tenant_id, created_by=ctx.user_id, related_type=related_type,
                        related_id=related_id, kind=kind, due_at=due_at, owner_user_id=owner_user_id or ctx.user_id,
                        note=(note or "").strip()[:1000] or None)
    repo.add(session, activity)
    return activity


def complete_activity(session: Session, activity_id: UUID, *, note: str | None = None) -> Activity:
    """Mark a follow-up done. The owner or anyone who can manage the lead or customer may."""
    activity = repo.get_activity(session, activity_id, lock=True)
    if activity is None:
        raise NotFound("Activity not found")
    company_id = _related_company(session, activity.related_type, activity.related_id)
    access.check_visible(company_id, "Activity")
    ctx = current_context()
    if activity.owner_user_id != ctx.user_id and not (
            access.holds(LEADS_MANAGE, company_id) or access.holds(CUSTOMERS_MANAGE, company_id)):
        raise Forbidden("This follow-up belongs to someone else")
    if activity.done_at is not None:
        raise Conflict("This follow-up is already done")
    activity.done_at = datetime.now(UTC)
    if note and note.strip():
        activity.note = f"{activity.note or ''}\n{note.strip()}".strip()[:1000]
    session.flush()
    return activity


def list_activities(session: Session, *, related_type: str | None = None, related_id: UUID | None = None,
                    mine: bool = False, open_only: bool = False, due_before: datetime | None = None,
                    limit: int = 50, offset: int = 0) -> list[Activity]:
    """Follow-ups about a record the person may see, or (with `mine`) their own."""
    if related_id is not None:
        company_id = _related_company(session, related_type or "customer", related_id)
        access.check_visible(company_id, "Record")
    elif not mine:
        raise ValidationFailed("Name the lead or customer, or ask for your own follow-ups")
    return repo.list_activities(
        session, related_type=related_type, related_id=related_id,
        owner_id=current_context().user_id if mine else None, open_only=open_only, due_before=due_before,
        limit=min(limit, 200), offset=offset)
