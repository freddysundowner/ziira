"""Kernel HTTP endpoints for data protection: data subject requests (access, correction, erasure) and retention.
Everything needs 'privacy.manage' for the company. See docs/privacy.md."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ziira.kernel import privacy
from ziira.sdk import DB_SESSION, Session, page_limit, page_offset, require_permission

router = APIRouter(prefix="/api/v1/privacy", tags=["Privacy"],
                   dependencies=[Depends(require_permission("privacy.manage"))])


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    request_type: Literal["access", "correction", "erasure"]
    subject: str = Field(min_length=1, max_length=200,
                         description="What the person gave to be found by: an email, a phone number, an id or a name")
    notes: str | None = Field(default=None, max_length=2000,
                              description="How the person was identified, what they asked")
    received_on: date | None = Field(default=None, description="When the request arrived (default: today)")


class FoundOut(BaseModel):
    source: str
    kind: str
    record_id: UUID
    label: str
    match: Literal["exact", "possible"]
    company_id: UUID | None


class RequestOut(BaseModel):
    id: UUID
    number: str
    company_id: UUID
    request_type: str
    subject: str
    subject_masked: str
    status: str
    received_on: date
    due_date: date
    overdue: bool
    handled_by: UUID | None
    notes: str | None
    found: list[FoundOut]
    awaiting_approval: bool
    outcome: dict[str, Any] | None
    completed_at: datetime | None
    created_at: datetime


class SelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_ids: list[UUID] | None = Field(
        default=None, max_length=1000,
        description="Records to include. Leave empty for every exact match; list a possible match (found by name) "
                    "only after checking it is the same person")


class EraseIn(SelectionIn):
    confirm_subject: str = Field(min_length=1, max_length=200, description="The subject of the request, typed again")
    reason: str = Field(min_length=1, max_length=500)


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["completed", "refused"]
    note: str = Field(min_length=1, max_length=2000, description="What was done, or why the request is refused")


@router.post("/requests", response_model=RequestOut, status_code=201)
def create_request(body: RequestIn, s: Session = DB_SESSION) -> object:
    """Record a request. The due date is `privacy_response_days` after it was received."""
    return privacy.create_request(s, company_id=body.company_id, request_type=body.request_type,
                                  subject=body.subject, notes=body.notes, received_on=body.received_on)


@router.get("/requests", response_model=list[RequestOut])
def list_requests(status: Literal["open", "in_progress", "completed", "refused"] | None = None,
                  company_id: UUID | None = None, limit: int = page_limit(), offset: int = page_offset(),
                  s: Session = DB_SESSION) -> object:
    return privacy.list_requests(s, status=status, company_id=company_id, limit=limit, offset=offset)


@router.get("/requests/{request_id}", response_model=RequestOut)
def get_request(request_id: UUID, s: Session = DB_SESSION) -> object:
    return privacy.get_request(s, request_id)


@router.post("/requests/{request_id}/search", response_model=RequestOut)
def search(request_id: UUID, s: Session = DB_SESSION) -> object:
    """Ask every unit what it holds about the subject. Matches by name are flagged 'possible'."""
    return privacy.search(s, request_id)


@router.post("/requests/{request_id}/export")
def export(request_id: UUID, body: SelectionIn | None = None, s: Session = DB_SESSION) -> object:
    """The data held about the subject as a JSON bundle. Written to the audit log as a data export."""
    return privacy.export(s, request_id, body.record_ids if body else None)


@router.post("/requests/{request_id}/erase", response_model=RequestOut)
def erase(request_id: UUID, body: EraseIn, s: Session = DB_SESSION) -> object:
    """Anonymise the subject's records. Irreversible. Waits for a second person's approval when the company setting
    `privacy_erasure_needs_approval` is on (the default)."""
    return privacy.erase(s, request_id, confirm_subject=body.confirm_subject, reason=body.reason,
                         record_ids=body.record_ids)


@router.post("/requests/{request_id}/close", response_model=RequestOut)
def close(request_id: UUID, body: CloseIn, s: Session = DB_SESSION) -> object:
    """Finish a request by hand: an access answer was sent, a correction was made, or the request is refused."""
    return privacy.close_request(s, request_id, outcome=body.outcome, note=body.note)


@router.get("/retention")
def retention(company_id: UUID = Query(...), s: Session = DB_SESSION) -> object:
    """What each unit keeps about people, for how long, and the company's retention settings."""
    return privacy.retention_overview(s, company_id)

