"""HTTP endpoints of the CRM module. Routes only convert HTTP to service calls."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ziira.modules.crm.api import schemas as sc
from ziira.modules.crm.permissions import CREDIT_APPROVE, CUSTOMERS_MANAGE, CUSTOMERS_VIEW, LEADS_MANAGE
from ziira.modules.crm.services import customers, leads
from ziira.sdk import Forbidden, RequestContext, Session, db_session, page_limit, page_offset, request_context

router = APIRouter()
CREATED = status.HTTP_201_CREATED
NO_CONTENT = status.HTTP_204_NO_CONTENT


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the company)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(CUSTOMERS_VIEW, CUSTOMERS_MANAGE, CREDIT_APPROVE, LEADS_MANAGE))]
MANAGE = [Depends(any_of(CUSTOMERS_MANAGE))]
LEADS = [Depends(any_of(LEADS_MANAGE))]
FOLLOW_UP = [Depends(any_of(LEADS_MANAGE, CUSTOMERS_MANAGE))]


# --------------------------------------------------------------------------- customers
@router.post("/customers", response_model=sc.CustomerOut, status_code=CREATED, dependencies=MANAGE)
def post_customer(body: sc.CustomerIn, session: Session = Depends(db_session)) -> object:
    return customers.create_customer(session, **body.model_dump())


@router.get("/customers", response_model=list[sc.CustomerOut], dependencies=VIEW)
def get_customers(search: str | None = Query(default=None, max_length=100),
                  status_: str | None = Query(default=None, alias="status"),
                  group: str | None = Query(default=None, max_length=60), owner_id: UUID | None = None,
                  limit: int = page_limit(50), offset: int = page_offset(),
                  session: Session = Depends(db_session)) -> object:
    return customers.list_customers(session, search=search, status=status_, group=group, owner_id=owner_id,
                                    limit=limit, offset=offset)


@router.get("/customers/{customer_id}", response_model=sc.CustomerOut, dependencies=VIEW)
def get_customer(customer_id: UUID, session: Session = Depends(db_session)) -> object:
    return customers.get_customer(session, customer_id)


@router.patch("/customers/{customer_id}", response_model=sc.CustomerOut, dependencies=MANAGE)
def patch_customer(customer_id: UUID, body: sc.CustomerUpdate, session: Session = Depends(db_session)) -> object:
    return customers.update_customer(session, customer_id, **body.model_dump(exclude_unset=True))


@router.get("/customers/{customer_id}/contacts", response_model=list[sc.ContactOut], dependencies=VIEW)
def get_contacts(customer_id: UUID, session: Session = Depends(db_session)) -> object:
    return customers.list_contacts(session, customer_id)


@router.post("/customers/{customer_id}/contacts", response_model=sc.ContactOut, status_code=CREATED,
             dependencies=MANAGE)
def post_contact(customer_id: UUID, body: sc.ContactIn, session: Session = Depends(db_session)) -> object:
    return customers.add_contact(session, customer_id, **body.model_dump())


@router.delete("/customers/{customer_id}/contacts/{contact_id}", status_code=NO_CONTENT, dependencies=MANAGE)
def delete_contact(customer_id: UUID, contact_id: UUID, session: Session = Depends(db_session)) -> Response:
    customers.remove_contact(session, customer_id, contact_id)
    return Response(status_code=NO_CONTENT)


@router.post("/customers/{customer_id}/do-not-contact", response_model=sc.DoNotContactOut, dependencies=MANAGE)
def post_do_not_contact(customer_id: UUID, body: sc.DoNotContactIn, session: Session = Depends(db_session)) -> object:
    """The customer asked not to be messaged: reminders and statements will skip them."""
    return sc.DoNotContactOut(recorded=customers.do_not_contact(session, customer_id, channel=body.channel,
                                                               reason=body.reason))


@router.get("/customers/{customer_id}/credit", response_model=list[sc.CreditVersionOut], dependencies=VIEW)
def get_credit_history(customer_id: UUID, session: Session = Depends(db_session)) -> object:
    """Every credit limit and terms the customer has had, newest first."""
    return customers.credit_history(session, customer_id)


@router.post("/customers/{customer_id}/credit", response_model=sc.CreditVersionOut, status_code=CREATED,
             dependencies=MANAGE)
def post_credit_change(customer_id: UUID, body: sc.CreditChangeIn, session: Session = Depends(db_session)) -> object:
    """Change the credit limit and terms. Raising the limit is approved by someone else."""
    return customers.request_credit_change(session, customer_id, **body.model_dump())


# --------------------------------------------------------------------------- leads
@router.get("/lead-sources", response_model=list[sc.SourceOut], dependencies=VIEW)
def get_sources(session: Session = Depends(db_session)) -> object:
    return leads.list_sources(session)


@router.post("/lead-sources", response_model=sc.SourceOut, status_code=CREATED, dependencies=LEADS)
def post_source(body: sc.SourceIn, session: Session = Depends(db_session)) -> object:
    return leads.create_source(session, body.name)


@router.post("/leads", response_model=sc.LeadOut, status_code=CREATED, dependencies=LEADS)
def post_lead(body: sc.LeadIn, session: Session = Depends(db_session)) -> object:
    return leads.create_lead(session, **body.model_dump())


@router.get("/leads", response_model=list[sc.LeadOut], dependencies=VIEW)
def get_leads(status_: str | None = Query(default=None, alias="status"), owner_id: UUID | None = None,
              source_id: UUID | None = None, search: str | None = Query(default=None, max_length=100),
              limit: int = page_limit(50), offset: int = page_offset(),
              session: Session = Depends(db_session)) -> object:
    return leads.list_leads(session, status=status_, owner_id=owner_id, source_id=source_id, search=search,
                            limit=limit, offset=offset)


@router.get("/leads/{lead_id}", response_model=sc.LeadOut, dependencies=VIEW)
def get_lead(lead_id: UUID, session: Session = Depends(db_session)) -> object:
    return leads.get_lead(session, lead_id)


@router.patch("/leads/{lead_id}", response_model=sc.LeadOut, dependencies=LEADS)
def patch_lead(lead_id: UUID, body: sc.LeadUpdate, session: Session = Depends(db_session)) -> object:
    return leads.update_lead(session, lead_id, **body.model_dump(exclude_unset=True))


@router.post("/leads/{lead_id}/status", response_model=sc.LeadOut, dependencies=LEADS)
def post_lead_status(lead_id: UUID, body: sc.LeadStatusIn, session: Session = Depends(db_session)) -> object:
    return leads.set_lead_status(session, lead_id, body.status, lost_reason=body.lost_reason)


@router.post("/leads/{lead_id}/convert", response_model=sc.ConvertedOut, dependencies=LEADS)
def post_convert_lead(lead_id: UUID, body: sc.LeadConvertIn, session: Session = Depends(db_session)) -> object:
    """Turn the lead into a customer."""
    lead, customer = leads.convert_lead(session, lead_id, code=body.code, customer_group=body.customer_group)
    return sc.ConvertedOut(lead=sc.LeadOut.model_validate(lead), customer=sc.CustomerOut.model_validate(customer))


# --------------------------------------------------------------------------- follow-ups
@router.post("/activities", response_model=sc.ActivityOut, status_code=CREATED, dependencies=FOLLOW_UP)
def post_activity(body: sc.ActivityIn, session: Session = Depends(db_session)) -> object:
    return leads.create_activity(session, **body.model_dump())


@router.get("/activities", response_model=list[sc.ActivityOut], dependencies=VIEW)
def get_activities(related_type: str | None = Query(default=None, pattern="^(lead|customer)$"),
                   related_id: UUID | None = None, mine: bool = False, open_only: bool = False,
                   due_before: datetime | None = None, limit: int = page_limit(50), offset: int = page_offset(),
                   session: Session = Depends(db_session)) -> object:
    """Follow-ups about one lead or customer, or (with mine=true) your own."""
    return leads.list_activities(session, related_type=related_type, related_id=related_id, mine=mine,
                                 open_only=open_only, due_before=due_before, limit=limit, offset=offset)


@router.post("/activities/{activity_id}/done", response_model=sc.ActivityOut, dependencies=VIEW)
def post_activity_done(activity_id: UUID, body: sc.ActivityDoneIn, session: Session = Depends(db_session)) -> object:
    return leads.complete_activity(session, activity_id, note=body.note)
