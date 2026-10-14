"""Kernel HTTP endpoints for messages to people outside the system: which channels a business has set up, the record of
what was sent, and who asked not to be contacted. Needs 'settings.manage' for the company."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from ziira.kernel import credentials, notifications
from ziira.kernel.context import RequestContext
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.sdk import DB_SESSION, Session, check_company, page_limit, page_offset, request_context

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])
Channel = Literal["email", "sms"]
MANAGE = "settings.manage"


def staff(ctx: RequestContext = Depends(request_context)) -> RequestContext:
    if not ctx.has_anywhere(MANAGE):
        from ziira.kernel.errors import Forbidden

        raise Forbidden(f"You need '{MANAGE}'")
    return ctx


class ChannelIn(BaseModel):
    company_id: UUID
    provider: str = Field(min_length=1, max_length=40, examples=["africastalking"])
    secret: dict[str, Any] = Field(description="Keys and passwords for the gateway; stored encrypted, never shown")
    config: dict[str, Any] = Field(default_factory=dict, description="Settings that are not secret (a sender name)")
    label: str = Field(default="Messaging", min_length=1, max_length=60)


class ChannelOut(BaseModel):
    id: UUID
    channel: str
    provider: str | None
    label: str
    status: str


class TestIn(BaseModel):
    company_id: UUID
    channel: Channel
    recipient: str = Field(min_length=1, max_length=200)


class OptOutIn(BaseModel):
    company_id: UUID
    recipient: str = Field(min_length=1, max_length=200)
    channel: Channel | None = None
    reason: str | None = Field(default=None, max_length=300)


class OptOutOut(BaseModel):
    id: UUID
    company_id: UUID
    recipient: str
    channel: str | None
    reason: str | None


class NotificationOut(BaseModel):
    id: UUID
    company_id: UUID
    channel: str
    recipient: str = Field(description="Masked")
    subject: str | None
    status: str
    attempts: int
    provider: str | None
    error: str | None
    ref_type: str | None
    ref_id: UUID | None
    created_at: str
    sent_at: str | None


def _row(r: Any) -> NotificationOut:
    return NotificationOut(
        id=r.id, company_id=r.company_id, channel=r.channel, recipient=notifications.mask(r.recipient),
        subject=r.subject, status=r.status, attempts=r.attempts, provider=r.provider, error=r.error,
        ref_type=r.ref_type, ref_id=r.ref_id, created_at=r.created_at.isoformat(),
        sent_at=r.sent_at.isoformat() if r.sent_at else None)


ACTIVE = ("select id from kernel.integration_credential "
          "where company_id = :c and provider = :ch and status = 'active'")
COLUMNS = ("id, company_id, channel, recipient, subject, status, attempts, provider, error, ref_type, ref_id, "
           "created_at, sent_at")


@router.get("/channels", response_model=list[ChannelOut])
def get_channels(company_id: UUID, ctx: RequestContext = Depends(staff), session: Session = DB_SESSION
                 ) -> object:
    """The channels a business has set up (never their keys)."""
    ctx.require(MANAGE, company_id=company_id)
    check_company(session, company_id)
    rows = session.execute(text(
        "select id, provider as channel, config, label, status from kernel.integration_credential "
        "where company_id = :c and provider in ('email', 'sms') order by provider, created_at desc"),
        {"c": str(company_id)})
    return [ChannelOut(id=r.id, channel=r.channel, provider=(r.config or {}).get("provider"), label=r.label,
                       status=r.status) for r in rows]


@router.put("/channels/{channel}", response_model=ChannelOut)
def put_channel(channel: Channel, body: ChannelIn, ctx: RequestContext = Depends(staff),
                session: Session = DB_SESSION) -> object:
    """Set up (or replace) how a business sends email or SMS. The old keys stop being used."""
    ctx.require(MANAGE, company_id=body.company_id)
    check_company(session, body.company_id)
    for old in session.execute(text(ACTIVE), {"c": str(body.company_id), "ch": channel}):
        credentials.disable(session, old.id)
    config = {**body.config, "provider": body.provider}
    new_id = credentials.store_secret(session, company_id=body.company_id, provider=channel, label=body.label,
                                      secret=body.secret, config=config)
    return ChannelOut(id=new_id, channel=channel, provider=body.provider, label=body.label, status="active")


@router.delete("/channels/{channel}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(channel: Channel, company_id: UUID, ctx: RequestContext = Depends(staff),
                   session: Session = DB_SESSION) -> Response:
    """Stop using a channel (its keys are kept encrypted for the audit trail)."""
    ctx.require(MANAGE, company_id=company_id)
    check_company(session, company_id)
    found = list(session.execute(text(ACTIVE), {"c": str(company_id), "ch": channel}))
    if not found:
        raise NotFound("That channel is not set up")
    for row in found:
        credentials.disable(session, row.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test", response_model=NotificationOut, status_code=status.HTTP_201_CREATED)
def post_test(body: TestIn, ctx: RequestContext = Depends(staff), session: Session = DB_SESSION) -> object:
    """Send a test message to check a channel works."""
    ctx.require(MANAGE, company_id=body.company_id)
    check_company(session, body.company_id)
    notification_id = notifications.queue(
        session, company_id=body.company_id, channel=body.channel, recipient=body.recipient,
        body="This is a test message from Ziira. If you can read it, this channel works.",
        subject="Ziira test message", ref_type="test")
    return _row(session.execute(text(f"select {COLUMNS} from kernel.notification where id = :i"),
                                {"i": str(notification_id)}).one())


@router.get("", response_model=list[NotificationOut])
def get_notifications(company_id: UUID, channel: Channel | None = None,
                      status_: str | None = Query(default=None, alias="status",
                                                  pattern="^(queued|sent|failed|skipped)$"),
                      ref_type: str | None = Query(default=None, max_length=60), ref_id: UUID | None = None,
                      limit: int = page_limit(50), offset: int = page_offset(),
                      ctx: RequestContext = Depends(staff), session: Session = DB_SESSION) -> object:
    """What was sent, and what became of it (recipients masked)."""
    ctx.require(MANAGE, company_id=company_id)
    check_company(session, company_id)
    where, params = ["company_id = :c"], {"c": str(company_id), "n": limit, "o": offset}
    for column, value in (("channel", channel), ("status", status_), ("ref_type", ref_type)):
        if value:
            where.append(f"{column} = :{column}")
            params[column] = value
    if ref_id:
        where.append("ref_id = :ref_id")
        params["ref_id"] = str(ref_id)
    rows = session.execute(text(
        f"select {COLUMNS} from kernel.notification where {' and '.join(where)} order by created_at desc, id "
        "limit :n offset :o"), params)
    return [_row(r) for r in rows]


@router.get("/opt-outs", response_model=list[OptOutOut])
def get_opt_outs(company_id: UUID, limit: int = page_limit(100), offset: int = page_offset(),
                 ctx: RequestContext = Depends(staff), session: Session = DB_SESSION) -> object:
    ctx.require(MANAGE, company_id=company_id)
    check_company(session, company_id)
    rows = session.execute(text(
        "select id, company_id, recipient, channel, reason from kernel.notification_optout where company_id = :c "
        "order by created_at desc limit :n offset :o"), {"c": str(company_id), "n": limit, "o": offset})
    return [OptOutOut(id=r.id, company_id=r.company_id, recipient=notifications.mask(r.recipient), channel=r.channel,
                      reason=r.reason) for r in rows]


@router.post("/opt-outs", response_model=OptOutOut, status_code=status.HTTP_201_CREATED)
def post_opt_out(body: OptOutIn, ctx: RequestContext = Depends(staff), session: Session = DB_SESSION
                 ) -> object:
    """Record that a person asked not to be contacted."""
    ctx.require(MANAGE, company_id=body.company_id)
    check_company(session, body.company_id)
    optout_id = notifications.opt_out(session, company_id=body.company_id, recipient=body.recipient,
                                      channel=body.channel, reason=body.reason)
    to = notifications.check_recipient(body.channel or ("email" if "@" in body.recipient else "sms"), body.recipient,
                                       notifications.calling_code(session, body.company_id))
    return OptOutOut(id=optout_id, company_id=body.company_id, recipient=notifications.mask(to), channel=body.channel,
                     reason=body.reason)


@router.delete("/opt-outs/{optout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_opt_out(optout_id: UUID, company_id: UUID, ctx: RequestContext = Depends(staff),
                   session: Session = DB_SESSION) -> Response:
    ctx.require(MANAGE, company_id=company_id)
    check_company(session, company_id)
    owner = session.execute(text("select company_id from kernel.notification_optout where id = :i"),
                            {"i": str(optout_id)}).scalar_one_or_none()
    if owner != company_id:
        raise ValidationFailed("That record is not this company's") if owner else NotFound("Not found")
    notifications.remove_opt_out(session, optout_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
