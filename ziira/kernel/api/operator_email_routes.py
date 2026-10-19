"""Super Admin: the platform's email (providers, write-only credentials, sender, test) and the platform behaviour
settings (registration mode, default edition, trial length, public addresses and links).

Superadmin only (`platform.settings`), a fresh confirmation for every change, a line in the operator trail that names
the fields changed and never a value of a secret."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import editions, operators
from ziira.kernel.api.operator_routes import require
from ziira.kernel.auth import client_ip
from ziira.kernel.platform import admin, behaviour, mail

router = APIRouter(prefix="/api/v1/operator", tags=["Super Admin"])
Op = operators.Operator
PERM = "platform.settings"


class MailFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    required: bool
    help: str
    kind: str
    options: list[str]
    value: str | None = Field(description="Null for a secret: those are never shown")
    is_set: bool


class MailProviderOut(BaseModel):
    name: str
    label: str
    description: str
    dns_hint: str
    fields: list[MailFieldOut]
    configured: bool
    missing: list[str]
    selected: bool
    tested_ok: bool
    updated_at: datetime | None
    updated_by: str | None


class SenderOut(BaseModel):
    from_address: str
    from_name: str
    reply_to: str


class EnvMailOut(BaseModel):
    provider: str
    from_address: str
    from_name: str
    host: str
    port: str
    username: str
    has_secret: bool


class MailStatusOut(BaseModel):
    source: str = Field(description="platform | environment | development | none")
    provider: str | None
    configured: bool
    working: bool
    last_success_at: datetime | None
    failures_24h: int


class LastTestOut(BaseModel):
    provider: str
    at: str
    ok: bool
    message: str
    to: str


class EmailOut(BaseModel):
    source: str
    providers: list[MailProviderOut]
    sender: SenderOut
    environment: EnvMailOut | None
    status: MailStatusOut
    last_test: LastTestOut | None


class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, str] | None = None
    secrets: dict[str, str] | None = Field(default=None, description="Write-only; an empty value keeps the old one")
    clear_secrets: list[str] | None = None


class SenderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_address: str = Field(max_length=200)
    from_name: str = Field(default="", max_length=100)
    reply_to: str = Field(default="", max_length=200)


class ActiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=40, description="Empty: go back to the environment's settings")


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str | None = Field(default=None, max_length=40)
    to: str | None = Field(default=None, max_length=200, description="Default: the signed-in operator's address")


class CheckLine(BaseModel):
    level: str
    message: str


class LogLine(BaseModel):
    id: int
    sent_at: datetime
    kind: str
    recipient_masked: str
    status: str
    provider: str | None
    detail: str | None


class BehaviourValue(BaseModel):
    value: Any
    effective: str
    source: str


class BehaviourOut(BaseModel):
    values: dict[str, BehaviourValue]
    editions: list[str]
    email_working: bool
    email_reason: str | None


class BehaviourIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any = None


def _ip(request: Request) -> str | None:
    return client_ip(request)


@router.get("/email", response_model=EmailOut)
def get_email(_: Op = Depends(require(PERM))) -> object:
    """The providers with their settings (secrets only as set / not set), the sender and the status."""
    return mail.overview()


@router.put("/email/providers/{name}", response_model=MailProviderOut)
def save_provider(name: str, body: ProviderIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    fields = sorted({*(body.config or {}), *(body.secrets or {}), *(body.clear_secrets or [])})
    return admin.act(
        operator, "email.provider_save", name, _ip(request),
        lambda: mail.save_provider(name, config=body.config, secrets=body.secrets,
                                   clear_secrets=body.clear_secrets, by=operator.name),
        summary=lambda r: {"provider": name, "fields": fields})


@router.put("/email/sender", response_model=SenderOut)
def save_sender(body: SenderIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    return admin.act(
        operator, "email.sender_save", "sender", _ip(request),
        lambda: mail.save_sender(from_address=body.from_address, from_name=body.from_name, reply_to=body.reply_to,
                                 by=operator.name),
        summary=lambda r: {"from_address": r["from_address"]})


@router.put("/email/active", response_model=EmailOut)
def set_active(body: ActiveIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    """Make a tested provider live, or go back to the environment's settings (empty name)."""
    return admin.act(
        operator, "email.activate", body.provider or "environment", _ip(request),
        lambda: mail.set_active(body.provider.strip(), by=operator.name),
        summary=lambda r: {"provider": body.provider or "environment"})


@router.post("/email/test", response_model=LastTestOut)
def send_test(body: TestIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    """A test message (to the operator's own address by default). The answer is the provider's reason."""
    return admin.act(
        operator, "email.test", body.provider or "live", _ip(request),
        lambda: mail.send_test(body.provider, body.to or operator.email, by=operator.name),
        summary=lambda r: {"ok": r["ok"], "provider": r["provider"]})


@router.post("/email/check", response_model=list[CheckLine])
def check(provider: str | None = Query(default=None, max_length=40), _: Op = Depends(require(PERM))) -> object:
    """Plain checks of the saved settings, with advice about SPF and DKIM. Looks nothing up."""
    return mail.check_configuration(provider)


@router.post("/email/move-from-environment", response_model=EmailOut)
def move_from_environment(request: Request, operator: Op = Depends(require(PERM))) -> object:
    """Copy the environment's plain mail settings here; the secret is typed in afterwards."""
    return admin.act(
        operator, "email.move_from_environment", "environment", _ip(request),
        lambda: mail.move_from_environment(by=operator.name), summary=lambda r: {"source": r["source"]})


@router.get("/email/log", response_model=list[LogLine])
def mail_log(limit: int = Query(default=50, ge=1, le=200), _: Op = Depends(require(PERM))) -> object:
    return mail.log_lines(limit)


@router.get("/platform/behaviour", response_model=BehaviourOut)
def get_behaviour(_: Op = Depends(require(PERM))) -> object:
    status = mail.status()
    return {"values": behaviour.overview(), "editions": list(editions.load_editions()),
            "email_working": bool(status["working"]),
            "email_reason": None if status["working"] else mail.working_reason()}


def _change_behaviour(key: str, value: Any, by: str) -> Any:
    return behaviour.set_value(key, value, by)


@router.put("/platform/behaviour/{key}")
def put_behaviour(key: str, body: BehaviourIn, request: Request, operator: Op = Depends(require(PERM))) -> object:
    stored = admin.act(operator, "platform.behaviour", key, _ip(request),
                       lambda: _change_behaviour(key, body.value, operator.name),
                       summary=lambda r: {"key": key})
    return {"key": key, "value": stored}
