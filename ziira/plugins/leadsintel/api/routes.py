"""Lead Intel plugin endpoints: connecting WhatsApp (permission `settings.manage`), the list of what people
wrote
to the business, and the public address Lead Intel posts incoming messages to."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from ziira.plugins.leadsintel import repository as repo
from ziira.plugins.leadsintel.api import schemas as sc
from ziira.plugins.leadsintel.services import setup, webhook
from ziira.sdk import (
    DB_SESSION,
    NotFound,
    Session,
    Unauthorized,
    check_company,
    current_context,
    mask_contact,
    page_limit,
    page_offset,
    require_permission,
)

log = logging.getLogger("ziira.leadsintel")
router = APIRouter()
MANAGE = [Depends(require_permission("settings.manage"))]


def _state(session: Session, company_id: UUID) -> sc.LeadIntelStateOut:
    return sc.state_out(setup.state(session, company_id))


@router.get("/state", response_model=sc.LeadIntelStateOut, dependencies=MANAGE)
def get_state(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Where the connection stands. Never holds a key."""
    return _state(session, company_id)


@router.put("/key", response_model=sc.LeadIntelStateOut, dependencies=MANAGE)
def put_key(body: sc.LeadIntelKeyIn, session: Session = DB_SESSION) -> object:
    """Check the Lead Intel platform key with Lead Intel and store it encrypted."""
    setup.save_platform_key(session, body.company_id, body.platform_key)
    return _state(session, body.company_id)


@router.post("/check", response_model=sc.LeadIntelCheckOut, dependencies=MANAGE)
def post_check(body: sc.LeadIntelCompanyIn, session: Session = DB_SESSION) -> object:
    """Is the stored platform key still accepted by Lead Intel?"""
    return sc.LeadIntelCheckOut(**setup.check_credentials(session, body.company_id))


@router.post("/whatsapp/connect", response_model=sc.LeadIntelStateOut, status_code=status.HTTP_202_ACCEPTED,
             dependencies=MANAGE)
def post_connect(body: sc.LeadIntelConnectIn, session: Session = DB_SESSION) -> object:
    """Ask Lead Intel to connect a new WhatsApp number. Setup takes a while: poll `/whatsapp/refresh`."""
    profile = {k: v for k, v in {
        "about": body.about, "description": body.description, "address": body.address, "email": body.email,
        "websites": body.websites or None, "profileImageUrl": body.profile_image_url}.items() if v}
    setup.request_number(session, body.company_id, country_code=body.country_code, phone_number=body.phone_number,
                         business_name=body.business_name, display_name=body.display_name, profile=profile or None)
    return _state(session, body.company_id)


@router.post("/whatsapp/refresh", response_model=sc.LeadIntelStateOut, dependencies=MANAGE)
def post_refresh(body: sc.LeadIntelCompanyIn, session: Session = DB_SESSION) -> object:
    """Ask Lead Intel how the connection is going."""
    return sc.state_out(setup.refresh(session, body.company_id))


@router.post("/whatsapp/cancel", response_model=sc.LeadIntelStateOut, dependencies=MANAGE)
def post_cancel(body: sc.LeadIntelCompanyIn, session: Session = DB_SESSION) -> object:
    """Stop a connection that has not finished."""
    return sc.state_out(setup.cancel(session, body.company_id))


@router.post("/whatsapp/disconnect", response_model=sc.LeadIntelStateOut, dependencies=MANAGE)
def post_disconnect(body: sc.LeadIntelCompanyIn, session: Session = DB_SESSION) -> object:
    """Remove the connected number from Lead Intel and stop using WhatsApp."""
    return sc.state_out(setup.disconnect(session, body.company_id))


@router.post("/whatsapp/existing", response_model=sc.LeadIntelExistingOut, dependencies=MANAGE)
def post_existing(body: sc.LeadIntelNumberIn, session: Session = DB_SESSION) -> object:
    """Is this number already on Lead Intel, and can it be claimed by an SMS code?"""
    found = setup.check_existing(session, body.company_id, body.country_code, body.phone_number)
    return sc.LeadIntelExistingOut(**found)


@router.post("/whatsapp/claim", response_model=sc.LeadIntelStateOut, status_code=status.HTTP_202_ACCEPTED,
             dependencies=MANAGE)
def post_claim(body: sc.LeadIntelNumberIn, session: Session = DB_SESSION) -> object:
    """Start claiming a number already on Lead Intel: it sends a code by SMS to the number."""
    return sc.state_out(setup.start_claim(session, body.company_id, body.country_code, body.phone_number))


@router.post("/whatsapp/claim/verify", response_model=sc.LeadIntelStateOut, dependencies=MANAGE)
def post_claim_verify(body: sc.LeadIntelCodeIn, session: Session = DB_SESSION) -> object:
    """Type the code the number received."""
    return sc.state_out(setup.verify_claim(session, body.company_id, body.code))


@router.get("/inbox", response_model=list[sc.LeadIntelInboundOut], dependencies=MANAGE)
def get_inbox(company_id: UUID, limit: int = page_limit(50), offset: int = page_offset(),
              session: Session = DB_SESSION) -> object:
    """What people wrote to the business by WhatsApp (replies to reminders, commands from staff)."""
    current_context().require("settings.manage", company_id=company_id)
    check_company(session, company_id)
    return [sc.LeadIntelInboundOut(
        id=r.id, created_at=r.created_at.isoformat(), sender=mask_contact(r.sender), kind=r.kind, body=r.body,
        button_id=r.button_id, outcome=r.outcome, read=r.read_at is not None)
        for r in repo.list_inbound(session, company_id, limit, offset)]


# =========================================================================== public: Lead Intel posts here
public_router = APIRouter()


@public_router.post("/webhook/{token}", include_in_schema=False)
async def receive_webhook(token: str, request: Request) -> Response:
    """Incoming messages and delivery reports. The raw bytes are verified before anything is read from them."""
    from fastapi.concurrency import run_in_threadpool

    raw = await request.body()
    try:
        await run_in_threadpool(webhook.receive, token, raw, {k.lower(): v for k, v in request.headers.items()})
    except (webhook.Rejected, Unauthorized, NotFound):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    except Exception:
        # Whatever went wrong, answer 500 (Lead Intel delivers again): the general handlers would turn a database
        # conflict into a 409, which Lead Intel treats as permanent and never retries.
        log.exception("A Lead Intel delivery could not be handled")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(status_code=status.HTTP_202_ACCEPTED)
