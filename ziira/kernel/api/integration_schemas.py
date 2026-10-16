"""Request and response shapes for API keys, the public API description and outgoing webhooks."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel.api.schemas import Out


# --------------------------------------------------------------------------- API keys
class ApiKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=120)]
    scopes: list[Annotated[str, Field(max_length=100)]] = Field(
        max_length=200, description="Permission codes the key may use"
    )
    read_only: bool = Field(default=False, description="A read-only key can make GET requests only")
    company_id: UUID | None = Field(default=None, description="Limit the key to one company")
    branch_id: UUID | None = Field(default=None, description="Limit the key to one branch (needs the company)")
    rate_limit_per_minute: int | None = Field(
        default=None, ge=1, le=100_000, description="Requests a minute; empty uses the platform's default"
    )
    expires_at: datetime | None = None


class ApiKeyRotateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grace_hours: int = Field(default=24, ge=0, le=720, description="How long the old key keeps working (0: stops now)")


class ApiKeyCreatedOut(BaseModel):
    id: UUID
    key: str = Field(description="Shown only once; store it safely")


class ApiKeyOut(Out):
    id: UUID
    name: str
    scopes: list[str]
    read_only: bool
    company_id: UUID | None
    branch_id: UUID | None
    rate_limit_per_minute: int | None
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    last_ip: str | None
    use_count: int
    rotated_from: UUID | None


# --------------------------------------------------------------------------- webhooks
class WebhookEventOut(BaseModel):
    type: str
    unit: str
    description: str
    fields: list[str] = Field(description="The only payload fields sent for this event")


class WebhookIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=120)]
    url: Annotated[str, Field(min_length=8, max_length=2000, description="https:// address that receives the events")]
    event_types: list[Annotated[str, Field(max_length=100)]] = Field(min_length=1, max_length=50)


class WebhookPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    url: Annotated[str, Field(min_length=8, max_length=2000)] | None = None
    event_types: list[Annotated[str, Field(max_length=100)]] | None = Field(default=None, min_length=1, max_length=50)
    status: Literal["active", "paused"] | None = Field(
        default=None, description="'paused' stops sending; 'active' resumes (and re-enables a disabled endpoint)"
    )


class WebhookOut(Out):
    id: UUID
    name: str
    url: str
    event_types: list[str]
    secret_hint: str = Field(description="Last four characters of the signing secret")
    status: str
    disabled_reason: str | None
    consecutive_failures: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    created_at: datetime


class WebhookCreatedOut(BaseModel):
    endpoint: WebhookOut
    secret: str = Field(description="The signing secret; shown only once")


class WebhookSecretOut(BaseModel):
    secret: str = Field(description="The new signing secret; shown only once")


class DeliveryOut(Out):
    id: UUID
    created_at: datetime
    endpoint_id: UUID
    event_id: UUID
    event_type: str
    status: str
    attempts: int
    max_attempts: int
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    last_status_code: int | None
    last_duration_ms: int | None
    last_error: str | None
    is_test: bool
    body_bytes: int
    has_body: bool = Field(description="False once the content is no longer kept (it cannot be sent again)")


class AttemptOut(Out):
    attempted_at: datetime
    ok: bool
    status_code: int | None
    duration_ms: int | None
    error: str | None


class DeliveryDetailOut(DeliveryOut):
    aggregate_type: str | None
    aggregate_id: UUID | None
    body_sha256: str
    body_preview: str = Field(description="The first bytes of what was sent")
    attempt_log: list[AttemptOut]


class QueuedOut(BaseModel):
    delivery_id: UUID
