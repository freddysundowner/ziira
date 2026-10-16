"""HTTP endpoints of the channel layer: a person's own notification settings (channel per kind of message, quiet hours,
verified number) and a business's message templates and their approval."""

from datetime import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from ziira.kernel import channels as registry
from ziira.kernel import messaging, notifications, templates
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import Forbidden
from ziira.sdk import DB_SESSION, Session, check_company, request_context

router = APIRouter(prefix="/api/v1/notifications", tags=["Notification settings"])
MANAGE = "settings.manage"
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


def _me(ctx: RequestContext) -> UUID:
    if ctx.user_id is None:
        raise Forbidden("Sign in as a person to change your own settings")
    return ctx.user_id


def _staff(ctx: RequestContext = Depends(request_context)) -> RequestContext:
    if not ctx.has_anywhere(MANAGE):
        raise Forbidden(f"You need '{MANAGE}'")
    return ctx


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


class PreferencesOut(BaseModel):
    channels: dict[str, str] = Field(description="Kind of message -> channel, 'app' or 'default'")
    unavailable: list[str] = Field(
        description="Kinds whose chosen channel the business does not have now (its plugin is off): messages for "
                    "them go by the next channel until it is back")
    quiet_enabled: bool
    quiet_start: str
    quiet_end: str
    quiet_critical_ok: bool
    language: str
    can_verify: bool = Field(description="A channel that receives replies is available, so a number can be verified")
    verified_number: str | None = Field(description="Masked")
    number_verified: bool
    number_pending: bool


class PreferencesIn(BaseModel):
    channels: dict[str, str] | None = None
    quiet_enabled: bool | None = None
    quiet_start: str | None = Field(default=None, pattern=HHMM)
    quiet_end: str | None = Field(default=None, pattern=HHMM)
    quiet_critical_ok: bool | None = None
    language: str | None = Field(default=None, min_length=2, max_length=5)


class NumberIn(BaseModel):
    company_id: UUID
    phone: str = Field(min_length=6, max_length=30)


class PhoneCodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=10, pattern=r"^\d+$")


class TemplateRunIn(BaseModel):
    company_id: UUID


class TemplateOut(BaseModel):
    id: UUID
    channel: str
    code: str
    language: str
    category: str
    body: str
    variables: list[str]
    buttons: list[list[str]]
    status: str
    provider_template_id: str | None
    rejection_reason: str | None
    submitted_at: str | None
    decided_at: str | None


class TemplateRunOut(BaseModel):
    counts: dict[str, int]
    templates: list[TemplateOut]


def _prefs_out(session: Session, user_id: UUID) -> PreferencesOut:
    prefs = messaging.get_prefs(session, user_id)
    phone = messaging.phone_state(session, user_id)
    have = set(registry.names(session))
    return PreferencesOut(
        channels={k: prefs.channels.get(k, "default") for k in messaging.KINDS},
        unavailable=[k for k, v in prefs.channels.items() if v not in have and v != messaging.APP_ONLY],
        quiet_enabled=prefs.quiet_enabled, quiet_start=_hhmm(prefs.quiet_start), quiet_end=_hhmm(prefs.quiet_end),
        quiet_critical_ok=prefs.quiet_critical_ok, language=prefs.language,
        can_verify=any(i.supports_inbound for i in registry.available(session)),
        verified_number=notifications.mask(phone["phone"]) if phone["phone"] else None,
        number_verified=phone["verified"], number_pending=phone["pending"])


@router.get("/me/preferences", response_model=PreferencesOut)
def get_my_preferences(ctx: RequestContext = Depends(request_context), session: Session = DB_SESSION) -> object:
    """How I want to be messaged: a channel for each kind of message, quiet hours, language, my verified number."""
    return _prefs_out(session, _me(ctx))


@router.put("/me/preferences", response_model=PreferencesOut)
def put_my_preferences(body: PreferencesIn, ctx: RequestContext = Depends(request_context),
                       session: Session = DB_SESSION) -> object:
    """Change my channel choices and quiet hours (the times are read in the company's time zone)."""
    user_id = _me(ctx)
    messaging.set_prefs(
        session, user_id, channels=body.channels,
        quiet_enabled=body.quiet_enabled, quiet_start=_parse(body.quiet_start), quiet_end=_parse(body.quiet_end),
        quiet_critical_ok=body.quiet_critical_ok, language=body.language)
    return _prefs_out(session, user_id)


def _parse(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


@router.post("/me/verified-number", response_model=PreferencesOut, status_code=status.HTTP_202_ACCEPTED)
def post_my_number(body: NumberIn, ctx: RequestContext = Depends(request_context),
                     session: Session = DB_SESSION) -> object:
    """Add the number I reply from: a code is sent to prove it is mine, by the first channel the business has set up
    that reaches it (then the next; email last)."""
    user_id = _me(ctx)
    check_company(session, body.company_id)
    messaging.start_phone_verification(session, user_id, body.company_id, body.phone)
    return _prefs_out(session, user_id)


@router.post("/me/verified-number/verify", response_model=PreferencesOut)
def post_my_number_verify(body: PhoneCodeIn, ctx: RequestContext = Depends(request_context),
                            session: Session = DB_SESSION) -> object:
    """Type the code I received: the number becomes mine, and replies from it count as me."""
    user_id = _me(ctx)
    messaging.confirm_phone(session, user_id, body.code)
    return _prefs_out(session, user_id)


@router.delete("/me/verified-number", response_model=PreferencesOut)
def delete_my_number(ctx: RequestContext = Depends(request_context), session: Session = DB_SESSION) -> object:
    """Remove my verified number."""
    user_id = _me(ctx)
    messaging.remove_phone(session, user_id)
    return _prefs_out(session, user_id)


# --------------------------------------------------------------------------- templates
def _template(r: Any) -> TemplateOut:
    return TemplateOut(
        id=r.id, channel=r.channel, code=r.code, language=r.language, category=r.category, body=r.body,
        variables=list(r.variables),
        buttons=[list(b) for b in r.buttons or []], status=r.status, provider_template_id=r.provider_template_id,
        rejection_reason=r.rejection_reason, submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
        decided_at=r.decided_at.isoformat() if r.decided_at else None)


@router.get("/templates", response_model=list[TemplateOut])
def get_templates(company_id: UUID, ctx: RequestContext = Depends(_staff), session: Session = DB_SESSION) -> object:
    """The message templates of a business, per channel that needs them, and where each stands with its provider."""
    ctx.require(MANAGE, company_id=company_id)
    check_company(session, company_id)
    return [_template(r) for r in templates.list_templates(session, company_id)]


@router.post("/templates/submit", response_model=TemplateRunOut)
def post_templates_submit(body: TemplateRunIn, ctx: RequestContext = Depends(_staff),
                          session: Session = DB_SESSION) -> object:
    """Send every draft or rejected template to the provider for approval."""
    ctx.require(MANAGE, company_id=body.company_id)
    check_company(session, body.company_id)
    counts = templates.submit_all(session, body.company_id)
    return TemplateRunOut(counts=counts, templates=[_template(r) for r in templates.list_templates(
        session, body.company_id)])


@router.post("/templates/sync", response_model=TemplateRunOut)
def post_templates_sync(body: TemplateRunIn, ctx: RequestContext = Depends(_staff),
                        session: Session = DB_SESSION) -> object:
    """Ask the provider for its decisions on the templates that were submitted."""
    ctx.require(MANAGE, company_id=body.company_id)
    check_company(session, body.company_id)
    counts = templates.sync_all(session, body.company_id)
    return TemplateRunOut(counts=counts, templates=[_template(r) for r in templates.list_templates(
        session, body.company_id)])
