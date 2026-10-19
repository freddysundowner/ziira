"""Files and photos attached to records (docs/files.md).

Everything signed-in goes through the permissions of the record the file belongs to. Bytes are never served from a path:
a signed-in person opens a file with their token (`/{id}/content`) or, for a browser `<img>`, with a short-lived signed
address (`/dl/<token>`) made by `/{id}/link`; pages for people without an account (an insurer's response page) get the
same kind of address from `ziira.sdk` `files.public_links`, which only ever covers files marked shareable.
"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote, unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ziira.kernel.auth import client_ip
from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext, system_context
from ziira.kernel.db import tenant_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.files import service, tokens
from ziira.kernel.files.service import FileContent, FileInfo
from ziira.kernel.public_slugs import rate_limit
from ziira.sdk import DB_SESSION, request_context, require_permission

router = APIRouter(prefix="/api/v1/files", tags=["Files and photos"])
Variant = Literal["original", "web", "thumb"]
LINK_SECONDS = 600
NAME_MAX = 200


class AttachedFileCategoryOut(BaseModel):
    key: str
    label: str


class AttachedFileConfigOut(BaseModel):
    entity_type: str
    entity_label: str
    categories: list[AttachedFileCategoryOut]
    can_add: bool = Field(description="The actor may add, change and remove files on this record")
    photo_consent: bool = Field(description="Show the note for the customer's consent to be photographed")
    count: int
    max_per_record: int
    max_file_bytes: int
    accepted: list[str] = Field(description="The content types the server accepts")


class AttachedFileOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    company_id: UUID | None
    category: str
    caption: str
    visibility: Literal["staff", "shareable"]
    consent_note: str
    kind: Literal["image", "pdf"]
    content_type: str
    name: str
    size_bytes: int
    width: int | None
    height: int | None
    page_count: int | None
    location_stripped: bool
    created_at: datetime
    created_by_name: str | None
    thumb_url: str | None = Field(description="Short-lived address of the thumbnail (pictures only); ask again later")
    web_url: str | None = Field(description="Short-lived address of the web-size copy (pictures only)")


class AttachedFilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caption: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    visibility: Literal["staff", "shareable"] | None = None
    consent_note: str | None = Field(default=None, max_length=300)


class AttachedFileDeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=300, description="Why the file is removed")


class AttachedFileLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant: Variant = "original"
    seconds: int = Field(default=300, ge=30, le=900)


class AttachedFileLinkOut(BaseModel):
    path: str = Field(description="Address on this server; works without signing in until it ends")
    expires_at: datetime


class AttachedFileAccessOut(BaseModel):
    at: datetime
    variant: str
    via: str = Field(description="'staff' (a signed-in person), 'link' (someone holding a link), 'api'")
    purpose: str
    label: str
    ip: str
    user_id: str | None
    user_name: str | None


class AttachedFileUsageOut(BaseModel):
    files: int
    bytes: int
    company_limit_bytes: int = Field(description="The company's own cap; 0 means none")
    plan_limit_bytes: int | None = Field(description="The plan's cap for the business; null means none")


def _out(info: FileInfo, session: Session) -> AttachedFileOut:
    thumb = service.signed_link(session, info.id, "thumb", seconds=LINK_SECONDS).path if info.has_thumb else None
    web = service.signed_link(session, info.id, "web", seconds=LINK_SECONDS).path if info.has_web else None
    return AttachedFileOut(
        id=info.id, entity_type=info.entity_type, entity_id=info.entity_id, company_id=info.company_id,
        category=info.category, caption=info.caption, visibility=info.visibility,  # type: ignore[arg-type]
        consent_note=info.consent_note, kind=info.kind, content_type=info.content_type,  # type: ignore[arg-type]
        name=info.name, size_bytes=info.size_bytes, width=info.width, height=info.height, page_count=info.page_count,
        location_stripped=info.location_stripped, created_at=info.created_at, created_by_name=info.created_by_name,
        thumb_url=thumb, web_url=web)


def _response(content: FileContent, *, download: bool, cacheable: bool) -> Response:
    inline = content.content_type.startswith("image/") or content.content_type == "application/pdf"
    disposition = "inline" if inline and not download else "attachment"
    name = content.name.replace('"', "")
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
               "Cache-Control": "private, max-age=300" if cacheable else "no-store",
               "X-Content-Type-Options": "nosniff"}
    return Response(content.data, media_type=content.content_type, headers=headers)


async def upload_body(request: Request, _: RequestContext = Depends(request_context)) -> bytes:
    """The raw bytes of the upload (the request body), refused as soon as they pass the size limit. Signing in is
    checked first, so a stranger cannot make the server read megabytes."""
    limit = get_settings().files_max_upload_bytes
    too_big = f"The file is larger than {limit // (1024 * 1024)} MB"
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise ValidationFailed(too_big)
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > limit:
            raise ValidationFailed(too_big)
    return bytes(received)


def _header_text(value: str | None, limit: int) -> str:
    try:
        return unquote(value or "", errors="strict")[:limit]
    except UnicodeDecodeError:
        raise ValidationFailed("A header could not be read as text; send it percent-encoded as UTF-8") from None


# --------------------------------------------------------------------------- not tied to a file
@router.get("/config", response_model=AttachedFileConfigOut)
def get_config(entity_type: str = Query(max_length=60), entity_id: UUID = Query(),
               ctx: RequestContext = Depends(request_context), s: Session = DB_SESSION) -> object:
    """What the Attachments component needs for a record: its photo kinds, who may edit, the limits."""
    kind = service.entity(s, entity_type)
    company_id, branch_id = service._record_scope(s, kind, entity_id)
    service._require(s, kind, company_id, branch_id, edit=False)
    limits = service.limits_for(s, company_id)
    return AttachedFileConfigOut(
        entity_type=entity_type, entity_label=kind.label, categories=[AttachedFileCategoryOut(key=c.key, label=c.label)
                                                                      for c in kind.categories(s)],
        can_add=service._allowed(ctx, kind.edit_permission, company_id, branch_id, edit=True),
        photo_consent=kind.photo_consent, count=service.counts(s, entity_type, [entity_id]).get(entity_id, 0),
        max_per_record=limits.max_per_record, max_file_bytes=limits.max_file_bytes,
        accepted=["image/jpeg", "image/png", "image/webp", "application/pdf"])


@router.get("/usage", response_model=AttachedFileUsageOut,
            dependencies=[Depends(require_permission("settings.manage"))])
def get_usage(company_id: UUID | None = None, ctx: RequestContext = Depends(request_context),
              s: Session = DB_SESSION) -> object:
    """Space used by photos and files, with the limits that apply (Settings > Photos and files)."""
    if company_id is not None:
        ctx.require("settings.manage", company_id=company_id)
    limits = service.limits_for(s, company_id)
    used = service.usage(s, company_id)
    return AttachedFileUsageOut(files=used["files"], bytes=used["bytes"],
                                company_limit_bytes=limits.storage_limit_bytes,
                                plan_limit_bytes=limits.plan_limit_bytes)


@router.get("", response_model=list[AttachedFileOut])
def list_files(entity_type: str = Query(max_length=60), entity_id: UUID = Query(),
               category: str | None = Query(default=None, max_length=40), s: Session = DB_SESSION) -> object:
    """The files of a record. Needs the permission that opens the record."""
    return [_out(i, s) for i in service.list_files(s, entity_type, entity_id, category=category)]


@router.post("", response_model=AttachedFileOut, status_code=201)
def upload(body: bytes = Depends(upload_body), entity_type: str = Query(max_length=60), entity_id: UUID = Query(),
           category: str = Query(default="general", max_length=40),
           visibility: Literal["staff", "shareable"] = "staff",
           x_file_name: str | None = Header(default=None, description="The file's name, percent-encoded"),
           x_file_caption: str | None = Header(default=None, description="Caption, percent-encoded"),
           x_file_consent: str | None = Header(default=None, description="Consent note, percent-encoded"),
           idempotency_key: str | None = Header(default=None, alias="Idempotency-Key",
                                                description="Makes a retry safe: the same key stores the file once"),
           s: Session = DB_SESSION) -> object:
    """Attach a photo or PDF: the request body is the file itself. Its real type is read from the bytes; a name or
    content type that says otherwise is ignored. Needs the permission that edits the record."""
    info = service.attach(
        s, entity_type=entity_type, entity_id=entity_id, data=body, name=_header_text(x_file_name, NAME_MAX),
        category=category, caption=_header_text(x_file_caption, 400), visibility=visibility,
        consent_note=_header_text(x_file_consent, 400), local_id=service.local_id_from(idempotency_key))
    return _out(info, s)


# --------------------------------------------------------------------------- public: a signed address
@router.get("/dl/{token}", include_in_schema=True)
def download_by_link(token: str, request: Request, download: bool = False) -> Response:
    """Open a file with a signed address made by `/{id}/link` or by a unit's public page. No sign-in: the address is
    the proof, it ends by itself, and every opening of a full-size picture or document is logged."""
    claims = tokens.read(token)
    ip = client_ip(request)
    rate_limit("file_link", str(claims.file_id), ip, per_subject=600, per_ip=6000)
    system_context(claims.tenant_id)
    with tenant_session(claims.tenant_id) as s:
        content = service.open_link(s, claims, ip)
    return _response(content, download=download, cacheable=claims.variant != "original")


# --------------------------------------------------------------------------- one file
@router.get("/{file_id}", response_model=AttachedFileOut)
def get_file(file_id: UUID, s: Session = DB_SESSION) -> object:
    """One file's details."""
    return _out(service.get_file(s, file_id), s)


@router.patch("/{file_id}", response_model=AttachedFileOut)
def patch_file(file_id: UUID, body: AttachedFilePatch, s: Session = DB_SESSION) -> object:
    """Change the caption, kind, visibility or consent note. Making a file staff-only ends the links made for it."""
    return _out(service.update_file(s, file_id, **body.model_dump(exclude_unset=True)), s)


@router.post("/{file_id}/delete", status_code=204)
def delete_file(file_id: UUID, body: AttachedFileDeleteIn, s: Session = DB_SESSION) -> Response:
    """Remove a file, with the reason. Its bytes are removed and its links stop working."""
    service.delete_file(s, file_id, body.reason)
    return Response(status_code=204)


@router.get("/{file_id}/content")
def get_content(file_id: UUID, variant: Variant = "web", download: bool = False, s: Session = DB_SESSION) -> Response:
    """The bytes of a file for a signed-in caller (an API client; a browser uses `/{id}/link`)."""
    return _response(service.read(s, file_id, variant), download=download, cacheable=False)


@router.post("/{file_id}/link", response_model=AttachedFileLinkOut)
def make_link(file_id: UUID, body: AttachedFileLinkIn, s: Session = DB_SESSION) -> object:
    """A short-lived address (up to 15 minutes) a browser can open without a token: for an image or a download."""
    link = service.signed_link(s, file_id, body.variant, seconds=body.seconds)
    return AttachedFileLinkOut(path=link.path, expires_at=link.expires_at)


@router.post("/{file_id}/revoke-links", status_code=204)
def revoke(file_id: UUID, s: Session = DB_SESSION) -> Response:
    """End every address made for this file so far."""
    service.revoke_links(s, file_id)
    return Response(status_code=204)


@router.get("/{file_id}/access", response_model=list[AttachedFileAccessOut])
def get_access(file_id: UUID, limit: Annotated[int, Query(ge=1, le=500)] = 100, s: Session = DB_SESSION) -> object:
    """Who opened this file and how (permission files.audit)."""
    return [AttachedFileAccessOut(**{**row, "user_id": str(row["user_id"]) if row["user_id"] else None})
            for row in service.access_log(s, file_id, limit)]

