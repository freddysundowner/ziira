"""Super Admin: the platform's chat bot (connect a number, what the bot says, try it, switch it on, people waiting).

Superadmin only (`platform.settings`), a fresh confirmation for every change, a line in the operator trail that names
what
changed and never a secret. The development routes exist only with `ZIIRA_CHAT_FAKE=1` (never in production)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import operators
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import admin, chat_bot, chat_brain

router = APIRouter(prefix="/api/v1/operator/chat", tags=["Super Admin"])
Op = operators.Operator
PERM = "platform.settings"


class ChatFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool
    help: str
    value: str | None = Field(description="Null for a secret: those are never shown")
    is_set: bool


class ChatProviderOut(BaseModel):
    name: str
    title: str
    description: str
    fields: list[ChatFieldOut]


class ChatKeyOut(BaseModel):
    is_set: bool
    tested_ok: bool | None
    tested_at: datetime | None = None


class ChatConnectionOut(BaseModel):
    state: str = Field(description="none | pending | awaiting_code | connected | failed | cancelled")
    mode: str | None
    message: str
    code: str
    number: str | None
    display_phone: str | None
    has_request: bool
    active: bool


class ChatWebhookOut(BaseModel):
    url: str | None = Field(description="The address the provider calls, with its token hidden")
    problem: str | None
    secret_set: bool


class ChatProfileOut(BaseModel):
    about: str
    description: str
    website: str


class ChatTextsOut(BaseModel):
    welcome: str
    handoff: str
    off_hours: str
    language: str
    hours_start: str
    hours_end: str
    hours_timezone: str
    profile: ChatProfileOut


class ChatBotOut(BaseModel):
    enabled: bool
    can_enable: bool
    not_ready_because: str | None = Field(description="key | test | connect | null")
    texts: ChatTextsOut


class ChatStatsOut(BaseModel):
    last: int
    answered: int
    unknown: int
    opted_out: int
    failed: int
    other: int
    open_handoffs: int


class ChatOverviewOut(BaseModel):
    provider: ChatProviderOut | None
    fake: bool
    key: ChatKeyOut
    connection: ChatConnectionOut
    webhook: ChatWebhookOut
    bot: ChatBotOut
    stats: ChatStatsOut
    updated_at: datetime | None
    updated_by: str | None


class ChatKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(max_length=400, description="Write-only")


class ChatKeyTestOut(BaseModel):
    ok: bool
    message: str


class ChatConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = Field(default="new", max_length=12, description="new | existing")
    country_code: str = Field(max_length=8)
    phone_number: str = Field(max_length=24)
    business_name: str = Field(default="", max_length=120)
    display_name: str = Field(default="", max_length=120)


class ChatCodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=12)


class ChatLookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country_code: str = Field(max_length=8)
    phone_number: str = Field(max_length=24)


class ChatLookupOut(BaseModel):
    found: bool
    active: bool
    status: str | None
    display_phone: str | None


class ChatRotateOut(BaseModel):
    rotated: bool


class ChatProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    about: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=700)
    website: str = Field(default="", max_length=300)


class ChatTextsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    welcome: str | None = Field(default=None, max_length=1000)
    handoff: str | None = Field(default=None, max_length=1000)
    off_hours: str | None = Field(default=None, max_length=1000)
    language: str | None = Field(default=None, max_length=8)
    hours_start: str | None = Field(default=None, max_length=8)
    hours_end: str | None = Field(default=None, max_length=8)
    hours_timezone: str | None = Field(default=None, max_length=60)
    profile: ChatProfileIn | None = None


class ChatTextsSavedOut(ChatTextsOut):
    profile_warning: str | None


class ChatEnabledIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class ChatEnabledOut(BaseModel):
    enabled: bool


class ChatTryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=1000)
    lang: str | None = Field(default=None, max_length=4)


class ChatButtonOut(BaseModel):
    id: str
    title: str


class ChatTryOut(BaseModel):
    text: str
    buttons: list[ChatButtonOut]
    outcome: str
    lang: str


class ChatTestMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(max_length=30)


class ChatTestMessageOut(BaseModel):
    sent: bool
    to: str


class ChatDisconnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(max_length=40, description="The connected number, typed")


class ChatDisconnectOut(BaseModel):
    disconnected: bool


class ChatHandoffOut(BaseModel):
    id: UUID
    sender_masked: str
    snippet: str | None
    status: str
    created_at: datetime
    done_at: datetime | None
    done_by: str | None


class ChatDevSimulateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str = Field(max_length=30)
    message: str = Field(max_length=1000)
    button_id: str | None = Field(default=None, max_length=60)


class ChatDevSentOut(BaseModel):
    sent: list[dict[str, str]]


class ChatDevSimulateOut(BaseModel):
    status: int
    reply: dict[str, Any] | None
    sent: list[dict[str, str]]


def _ip(request: Request) -> str | None:
    return client_ip(request)


@router.get("", response_model=ChatOverviewOut)
def get_chat(_: Op = Depends(require(PERM))) -> object:
    """Everything the page shows. Secrets only as set / not set; the inbound address with its token hidden."""
    return chat_bot.overview()


@router.put("/key", response_model=ChatKeyOut)
def save_key(body: ChatKeyIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.key_save",
        "key",
        _ip(request),
        lambda: chat_bot.save_key(body.api_key, operator.name),
        summary=lambda r: {"is_set": r["is_set"]},
    )


@router.post("/key/test", response_model=ChatKeyTestOut)
def test_key(request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.key_test",
        "key",
        _ip(request),
        lambda: chat_bot.test_key(operator.name),
        summary=lambda r: {"ok": r["ok"]},
    )


@router.post("/connect", response_model=ChatConnectionOut)
def connect(body: ChatConnectIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.connect",
        body.mode,
        _ip(request),
        lambda: chat_bot.start_connect(body.model_dump(), operator.name),
        summary=lambda r: {"mode": body.mode, "state": r["state"]},
    )


@router.get("/connect/status", response_model=ChatConnectionOut)
def connect_status(operator: Op = Depends(require(PERM))) -> object:
    """Ask the provider where connecting stands (also finishes the job once the number is active)."""
    return chat_bot.poll_connect(operator.name)


@router.post("/connect/code", response_model=ChatConnectionOut)
def connect_code(body: ChatCodeIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.connect_code",
        "code",
        _ip(request),
        lambda: chat_bot.submit_code(body.code, operator.name),
        summary=lambda r: {"state": r["state"]},
    )


@router.post("/connect/cancel", response_model=ChatConnectionOut)
def connect_cancel(request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.connect_cancel",
        "request",
        _ip(request),
        lambda: chat_bot.cancel_connect(operator.name),
        summary=lambda r: {"state": r["state"]},
    )


@router.post("/lookup", response_model=ChatLookupOut)
def lookup(body: ChatLookupIn, _: Op = Depends(require(PERM))) -> object:
    """Is this number already connected at the provider? Changes nothing."""
    return chat_bot.find_existing(body.country_code, body.phone_number)


@router.post("/adopt", response_model=ChatConnectionOut)
def adopt(body: ChatLookupIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    """Take over a connection found at the provider (it is pointed at this platform with a new secret)."""
    return admin.act(
        operator,
        "chat.adopt",
        "connection",
        _ip(request),
        lambda: chat_bot.adopt_existing(body.country_code, body.phone_number, operator.name),
        summary=lambda r: {"state": r["state"]},
    )


@router.post("/rotate-secret", response_model=ChatRotateOut)
def rotate(request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.rotate_secret",
        "webhook",
        _ip(request),
        lambda: chat_bot.rotate_secret(operator.name),
        summary=lambda r: {"rotated": r["rotated"]},
    )


@router.put("/texts", response_model=ChatTextsSavedOut)
def save_texts(body: ChatTextsIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    data = body.model_dump(exclude_none=True)
    return admin.act(
        operator,
        "chat.texts_save",
        "texts",
        _ip(request),
        lambda: chat_bot.save_texts(data, operator.name),
        summary=lambda r: {"fields": sorted(data)},
    )


@router.put("/enabled", response_model=ChatEnabledOut)
def set_enabled(body: ChatEnabledIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.enabled",
        "on" if body.enabled else "off",
        _ip(request),
        lambda: chat_bot.set_enabled(body.enabled, operator.name),
        summary=lambda r: {"enabled": r["enabled"]},
    )


@router.post("/try", response_model=ChatTryOut)
def try_it(body: ChatTryIn, _: Op = Depends(require(PERM))) -> object:
    """What the bot would say, exactly as it would be sent. Sends and stores nothing."""
    return chat_bot.try_it(body.message, body.lang)


@router.post("/test-message", response_model=ChatTestMessageOut)
def test_message(body: ChatTestMessageIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    """A real message to a number the owner types (only works inside the provider's 24-hour window)."""
    return admin.act(
        operator,
        "chat.test_message",
        chat_brain.mask_number("".join(c for c in body.to if c.isdigit())),
        _ip(request),
        lambda: chat_bot.send_test_message(body.to, operator.name),
        summary=lambda r: {"to": r["to"]},
    )


@router.post("/disconnect", response_model=ChatDisconnectOut)
def disconnect(body: ChatDisconnectIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.disconnect",
        "connection",
        _ip(request),
        lambda: chat_bot.disconnect(body.confirm, operator.name),
        summary=lambda r: {"disconnected": True},
    )


@router.get("/handoffs", response_model=list[ChatHandoffOut])
def handoffs(status: str | None = Query(default=None, max_length=8), _: Op = Depends(require(PERM))) -> object:
    return chat_bot.handoffs(status)


@router.post("/handoffs/{handoff_id}/done", response_model=ChatHandoffOut)
def handoff_done(handoff_id: UUID, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator,
        "chat.handoff_done",
        str(handoff_id),
        _ip(request),
        lambda: chat_bot.mark_handoff_done(handoff_id, operator.name),
        summary=lambda r: {"id": str(r["id"])},
    )


@router.get("/dev/state", response_model=ChatDevSentOut)
def dev_state(_: Op = Depends(require(PERM))) -> object:
    """Development only (`ZIIRA_CHAT_FAKE=1`): what the practice provider was asked to send."""
    return chat_bot.dev_state()


@router.post("/dev/simulate", response_model=ChatDevSimulateOut)
def dev_simulate(body: ChatDevSimulateIn, _: Op = Depends(require(PERM))) -> object:
    """Development only: a signed delivery from a made-up sender through the real inbound path."""
    return chat_bot.dev_simulate(body.sender, body.message, body.button_id)
