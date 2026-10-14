"""Support access, the business's side: give platform staff time-limited access, see what they did, take it back.
Everything needs 'support.grant' (the Owner by default) and a signed-in person. See docs/security.md."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import support
from ziira.kernel.api.routes import signed_in_user
from ziira.sdk import DB_SESSION, Session, page_limit, page_offset, require_permission

router = APIRouter(prefix="/api/v1/support", tags=["Support access"],
                   dependencies=[Depends(require_permission(support.PERMISSION)), Depends(signed_in_user)])


class SupportGrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500, description="Why Ziira support needs to look at the business")
    level: Literal["read", "full"] = Field(
        default="read", description="read: look only, nothing can be changed. full: staff can also make changes "
                                    "(never passwords, two-step verification, roles, API keys or support access)")
    hours: int = Field(default=support.DEFAULT_GRANT_HOURS, ge=1, le=support.MAX_GRANT_HOURS,
                       description="How long the access lasts (1 hour to 7 days)")
    note: str | None = Field(default=None, max_length=1000)


class SupportGrantSessionOut(BaseModel):
    id: UUID
    operator_name: str
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None
    requests: int


class SupportGrantOut(BaseModel):
    id: UUID
    created_at: datetime
    created_by: UUID | None
    created_by_name: str | None
    reason: str
    level: str
    note: str | None
    expires_at: datetime
    revoked_at: datetime | None
    status: Literal["active", "expired", "revoked"]
    sessions: list[SupportGrantSessionOut]


class AccessLogOut(BaseModel):
    id: int
    occurred_at: datetime
    action: str
    entity_type: str
    entity_id: UUID | None
    operator: str | None
    operator_id: str | None
    detail: dict[str, Any]


@router.post("/grants", response_model=SupportGrantOut, status_code=201)
def create_grant(body: SupportGrantIn, s: Session = DB_SESSION) -> object:
    """Let Ziira support in, for a reason, read-only or full, for a limited time."""
    return support.create_grant(s, reason=body.reason, level=body.level, hours=body.hours, note=body.note)


@router.get("/grants", response_model=list[SupportGrantOut])
def list_grants(limit: int = page_limit(50), offset: int = page_offset(),
                s: Session = DB_SESSION) -> object:
    """Support access given so far, newest first, with who opened the business under each."""
    return support.list_grants(s, limit=limit, offset=offset)


@router.post("/grants/{grant_id}/revoke", response_model=SupportGrantOut)
def revoke_grant(grant_id: UUID, s: Session = DB_SESSION) -> object:
    """Take the access back now: every open support session ends with its next request."""
    return support.revoke_grant(s, grant_id)


@router.get("/access-log", response_model=list[AccessLogOut])
def access_log(limit: int = page_limit(100), offset: int = page_offset(),
               s: Session = DB_SESSION) -> object:
    """What Ziira staff did in this business, newest first (from the business's own audit log)."""
    return support.access_log(s, limit=limit, offset=offset)
