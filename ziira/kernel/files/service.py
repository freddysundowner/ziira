"""Files and photos attached to records: the use cases (docs/files.md).

Every function here checks the actor's permission for the record the file belongs to (the permissions the record's unit
declared in its `kernel.attachable_entity`), so a unit or an endpoint cannot forget to. Work done for nobody in
particular (a public approval page showing the shareable photos of a job) runs as the system and says so by name
(`public_links`, `open_link`).

Bytes go to the store first, then the row is inserted in the caller's transaction; if the transaction rolls back the
bytes are removed again, and a deleted file's bytes are removed once the delete has committed. Whatever still slips
through (a crash between the two) is found and fixed by `ziira verify` (checks.py).
"""

import hashlib
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from ziira.kernel import audit, company_settings
from ziira.kernel.context import RequestContext, get_context
from ziira.kernel.errors import Forbidden, NotFound, PlanLimitReached, ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations
from ziira.kernel.files import media, tokens
from ziira.kernel.files.store import get_store
from ziira.kernel.jobs import periodic

log = logging.getLogger("ziira.files")

ATTACHABLE_ENTITY = "kernel.attachable_entity"
VISIBILITIES = ("staff", "shareable")
VARIANTS = tokens.VARIANTS
MB = 1024 * 1024
REASON_MIN, REASON_MAX = 3, 300
PRIVACY_PERMISSION = "privacy.manage"
AUDIT_PERMISSION = "files.audit"
DEFAULT_CATEGORY = "general"
_COLUMNS = ("f.id, f.created_at, f.created_by, u.full_name as created_by_name, f.company_id, f.branch_id, "
            "f.entity_type, f.entity_id, f.category, f.caption, f.visibility, f.consent_note, f.kind, f.content_type, "
            "f.original_name, f.size_bytes, f.checksum, f.width, f.height, f.page_count, f.storage_key, f.web_key, "
            "f.thumb_key, f.web_bytes, f.thumb_bytes, f.location_stripped, f.link_epoch, f.status, f.deleted_at, "
            "f.delete_reason, f.blobs_removed")
_FROM = "kernel.attachment f left join kernel.app_user u on u.id = f.created_by"


@dataclass(frozen=True)
class Category:
    """A kind of photo a record can have ("intake", "damage", "before", "receipt"): a key and the words shown."""

    key: str
    label: str


class AttachableEntity(ABC):
    """Contract of the "kernel.attachable_entity" extension point: one kind of record that can have files attached."""

    entity_type: str = ""            # stable id, "<unit>.<record>", e.g. "jobs.job"
    label: str = ""                  # plain words: "Job"
    view_permission: str = ""        # who may see and open its files (the permission that opens the record)
    edit_permission: str = ""        # who may add, change and remove them (the permission that edits the record)
    photo_consent: bool = False      # the screen shows a note for the customer's consent to be photographed

    @abstractmethod
    def scope(self, session: Session, entity_id: UUID) -> tuple[UUID | None, UUID | None] | None:
        """The record's (company_id, branch_id), or None when there is no such record in this business."""

    def categories(self, session: Session) -> list[Category]:
        """The kinds of photo this record can have, as data the unit or a pack keeps. Default: one general kind."""
        return [Category(DEFAULT_CATEGORY, "General")]


define_extension_point(ATTACHABLE_ENTITY, AttachableEntity,
                       "A kind of record that can have photos and files attached: names the type, its permissions, "
                       "its scope and the categories of photo it uses")


@dataclass(frozen=True)
class FileInfo:
    """One attached file, as units and screens see it. Never includes the bytes."""

    id: UUID
    entity_type: str
    entity_id: UUID
    company_id: UUID | None
    branch_id: UUID | None
    category: str
    caption: str
    visibility: str
    consent_note: str
    kind: str
    content_type: str
    name: str
    size_bytes: int
    checksum: str
    width: int | None
    height: int | None
    page_count: int | None
    has_web: bool
    has_thumb: bool
    location_stripped: bool
    created_at: datetime
    created_by: UUID | None
    created_by_name: str | None
    status: str = "active"
    deleted_at: datetime | None = None
    delete_reason: str | None = None


@dataclass(frozen=True)
class FileContent:
    """The bytes of one form of a file, with what a response needs."""

    data: bytes
    content_type: str
    name: str
    variant: str


@dataclass(frozen=True)
class SignedLink:
    """A download address that works without signing in until `expires_at`."""

    path: str                       # "/api/v1/files/dl/<token>"
    expires_at: datetime
    variant: str


@dataclass(frozen=True)
class PublicFile:
    """A shareable file as a public page (an approval or insurer response page) shows it."""

    id: UUID
    category: str
    caption: str
    kind: str
    content_type: str
    name: str
    size_bytes: int
    width: int | None
    height: int | None
    thumb: SignedLink | None
    web: SignedLink | None
    original: SignedLink


@dataclass
class Limits:
    max_file_bytes: int
    max_per_record: int
    storage_limit_bytes: int            # the company's own cap; 0 = none
    plan_limit_bytes: int | None        # the plan's cap for the business; None = none
    strip_location: bool
    extras: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- record types, permissions
def entities(session: Session) -> dict[str, AttachableEntity]:
    """The kinds of record that can have files attached in this business (units that are on), by entity type."""
    return {impl.entity_type: impl for impl in implementations(session, ATTACHABLE_ENTITY) if impl.entity_type}


def entity(session: Session, entity_type: str) -> AttachableEntity:
    found = entities(session).get(entity_type)
    if found is None:
        raise NotFound(f"Files cannot be attached to '{entity_type}' here")
    return found


def _allowed(ctx: RequestContext, permission: str, company_id: UUID | None, branch_id: UUID | None, *,
             edit: bool) -> bool:
    if edit or branch_id is not None:
        return ctx.can(permission, company_id=company_id, branch_id=branch_id)
    allowed = ctx.companies_with(permission)             # a company-wide record: a grant at any level in it is enough
    return allowed is None or company_id in allowed


def _require(session: Session, kind: AttachableEntity, company_id: UUID | None, branch_id: UUID | None, *,
             edit: bool) -> None:
    ctx = get_context()
    permission = (kind.edit_permission if edit else (kind.view_permission or kind.edit_permission))
    if not _allowed(ctx, permission, company_id, branch_id, edit=edit):
        raise Forbidden(f"You do not have permission '{permission}' here")


def _record_scope(session: Session, kind: AttachableEntity, entity_id: UUID) -> tuple[UUID | None, UUID | None]:
    scope = kind.scope(session, entity_id)
    if scope is None:
        raise NotFound("Record not found")
    return scope


# --------------------------------------------------------------------------- limits and settings
def limits_for(session: Session, company_id: UUID | None) -> Limits:
    """What a company may attach: from its settings, and the plan's storage cap for the business."""
    values = company_settings.get_settings(session, company_id) if company_id else {
        name: s.default for name, s in company_settings.SETTINGS.items()}
    plan_mb = _plan_storage_mb()
    return Limits(max_file_bytes=int(values["files_max_file_mb"]) * MB,
                  max_per_record=int(values["files_max_per_record"]),
                  storage_limit_bytes=int(values["files_storage_limit_mb"]) * MB,
                  plan_limit_bytes=plan_mb * MB if plan_mb is not None else None,
                  strip_location=bool(values["files_strip_location"]))


def _plan_storage_mb() -> int | None:
    """The plan's (or licence's) storage cap in megabytes, from its limits data (`storage_mb`), or None."""
    from ziira.kernel.platform import entitlements

    extra = entitlements.for_tenant(get_context().tenant_id).extra or {}
    value = extra.get("limit_storage_mb")
    return int(value) if isinstance(value, int | str) and str(value).isdigit() else None


def usage(session: Session, company_id: UUID | None = None) -> dict[str, int]:
    """Files and bytes in use (every stored form of every active file), for the business or one company."""
    row = session.execute(text(
        "select count(*) as files, coalesce(sum(size_bytes + web_bytes + thumb_bytes), 0) as bytes "
        "from kernel.attachment where status = 'active' and (cast(:c as uuid) is null or company_id = :c)"),
        {"c": str(company_id) if company_id else None}).one()
    return {"files": int(row.files), "bytes": int(row.bytes)}


def _check_room(session: Session, company_id: UUID | None, limits: Limits, adding: int) -> None:
    if limits.storage_limit_bytes and usage(session, company_id)["bytes"] + adding > limits.storage_limit_bytes:
        raise ValidationFailed(
            f"This company's photos and files are using their {limits.storage_limit_bytes // MB} MB limit "
            "(Settings > Photos and files). Remove some or raise the limit")
    if limits.plan_limit_bytes is not None:
        have = usage(session)["bytes"]
        if have + adding > limits.plan_limit_bytes:
            raise PlanLimitReached(
                f"Your plan allows {limits.plan_limit_bytes // MB} MB of photos and files and you are using "
                f"{have // MB} MB. Upgrade your plan to add more.",
                {"limit": limits.plan_limit_bytes // MB, "kind": "storage_mb", "used": have // MB})


# --------------------------------------------------------------------------- bytes follow the transaction
class _Pending:
    """Bytes written and bytes to remove, tied to one transaction (session)."""

    def __init__(self) -> None:
        self.written: list[str] = []
        self.to_remove: list[str] = []


_KEY = "files_pending"


def _pending(session: Session) -> _Pending:
    found: _Pending | None = session.info.get(_KEY)
    if found is None:
        found = session.info[_KEY] = _Pending()

        def rolled_back(_: Session) -> None:
            for key in found.written:
                _quietly(lambda key=key: get_store().delete(key))           # type: ignore[misc]
            found.written.clear()
            found.to_remove.clear()

        def committed(_: Session) -> None:
            for key in found.to_remove:
                _quietly(lambda key=key: get_store().delete(key))           # type: ignore[misc]
            found.written.clear()
            found.to_remove.clear()

        event.listen(session, "after_rollback", rolled_back)
        event.listen(session, "after_commit", committed)
    return found


def _quietly(action: Callable[[], object]) -> None:
    try:
        action()
    except Exception:                       # the file is found again by `ziira verify`; never fail a request for it
        log.exception("Could not remove a stored file; `ziira verify --fix` will clean it up")


def _key(tenant_id: UUID, file_id: UUID, variant: str) -> str:
    return f"{tenant_id}/{str(file_id)[:2]}/{file_id}.{variant}"


# --------------------------------------------------------------------------- reading rows
def _info(row: Any) -> FileInfo:
    return FileInfo(
        id=row.id, entity_type=row.entity_type, entity_id=row.entity_id, company_id=row.company_id,
        branch_id=row.branch_id, category=row.category, caption=row.caption, visibility=row.visibility,
        consent_note=row.consent_note, kind=row.kind, content_type=row.content_type, name=row.original_name,
        size_bytes=row.size_bytes, checksum=row.checksum, width=row.width, height=row.height,
        page_count=row.page_count, has_web=row.web_key is not None, has_thumb=row.thumb_key is not None,
        location_stripped=row.location_stripped, created_at=row.created_at, created_by=row.created_by,
        created_by_name=row.created_by_name, status=row.status, deleted_at=row.deleted_at,
        delete_reason=row.delete_reason)


def _row(session: Session, file_id: UUID, *, lock: bool = False, active_only: bool = True) -> Any:
    row = session.execute(text(
        f"select {_COLUMNS} from {_FROM} where f.id = :i" + (" and f.status = 'active'" if active_only else "")
        + (" for update of f" if lock else "")), {"i": str(file_id)}).first()
    if row is None:
        raise NotFound("File not found")
    return row


def _row_permission(session: Session, row: Any, *, edit: bool) -> AttachableEntity:
    kind = entity(session, row.entity_type)
    ctx = get_context()
    permission = kind.edit_permission if edit else (kind.view_permission or kind.edit_permission)
    if _allowed(ctx, permission, row.company_id, row.branch_id, edit=edit):
        return kind
    if not edit and ctx.can(PRIVACY_PERMISSION, company_id=row.company_id):
        return kind                           # whoever handles a data subject request may open the files it finds
    raise Forbidden(f"You do not have permission '{permission}' here")


def get_file(session: Session, file_id: UUID) -> FileInfo:
    """One file's details. Needs the permission that opens its record."""
    row = _row(session, file_id)
    _row_permission(session, row, edit=False)
    return _info(row)


def list_files(session: Session, entity_type: str, entity_id: UUID, *, category: str | None = None,
               shareable_only: bool = False) -> list[FileInfo]:
    """The files of a record, oldest first. Needs the permission that opens the record."""
    kind = entity(session, entity_type)
    company_id, branch_id = _record_scope(session, kind, entity_id)
    _require(session, kind, company_id, branch_id, edit=False)
    return _listing(session, entity_type, [entity_id], category=category, shareable_only=shareable_only)


def _listing(session: Session, entity_type: str, entity_ids: list[UUID], *, category: str | None = None,
             shareable_only: bool = False) -> list[FileInfo]:
    rows = session.execute(text(
        f"select {_COLUMNS} from {_FROM} where f.status = 'active' and f.entity_type = :t "
        "and f.entity_id = any(cast(:ids as uuid[])) and (cast(:cat as text) is null or f.category = :cat) "
        "and (not :share or f.visibility = 'shareable') order by f.created_at, f.id"),
        {"t": entity_type, "ids": [str(i) for i in entity_ids], "cat": category, "share": shareable_only})
    return [_info(r) for r in rows]


def counts(session: Session, entity_type: str, entity_ids: list[UUID]) -> dict[UUID, int]:
    """How many files each record has (for a badge in a list). No permission check: it reveals only a number for ids
    the caller already lists; the unit has checked it may show those records."""
    if not entity_ids:
        return {}
    rows = session.execute(text(
        "select entity_id, count(*) as n from kernel.attachment where status = 'active' and entity_type = :t "
        "and entity_id = any(cast(:ids as uuid[])) group by entity_id"),
        {"t": entity_type, "ids": [str(i) for i in entity_ids]})
    return {r.entity_id: int(r.n) for r in rows}


# --------------------------------------------------------------------------- attaching
def _clean_text(value: str | None, limit: int, label: str) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) > limit:
        raise ValidationFailed(f"{label} can be at most {limit} characters")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationFailed(f"{label} contains characters that cannot be saved")
    return cleaned


def _check_category(value: str) -> str:
    key = (value or DEFAULT_CATEGORY).strip().lower()
    if not (key[:1].isalpha() and key.replace("_", "").isalnum() and len(key) <= 40):
        raise ValidationFailed("The photo kind is lowercase letters, digits and '_', starting with a letter")
    return key


def local_id_from(key: str | None) -> UUID | None:
    """A retry-safe id from a client's Idempotency-Key (a UUID is used as it is, other text is hashed into one)."""
    if not key:
        return None
    try:
        return UUID(key)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"ziira-file:{key}")


def attach(session: Session, *, entity_type: str, entity_id: UUID, data: bytes, name: str = "",
           category: str = DEFAULT_CATEGORY, caption: str = "", visibility: str = "staff", consent_note: str = "",
           local_id: UUID | None = None) -> FileInfo:
    """Attach a photo or PDF to a record. The real type is read from the bytes; a picture is cleaned (location removed
    when the company keeps that setting on) and gets a web-size copy and a thumbnail. With a `local_id` a retry returns
    the first result and stores nothing more. Needs the permission that edits the record."""
    kind = entity(session, entity_type)
    company_id, branch_id = _record_scope(session, kind, entity_id)
    _require(session, kind, company_id, branch_id, edit=True)
    if visibility not in VISIBILITIES:
        raise ValidationFailed("Visibility is 'staff' (staff only) or 'shareable'")
    category = _check_category(category)
    caption = _clean_text(caption, 300, "The caption")
    consent_note = _clean_text(consent_note, 300, "The consent note")
    if consent_note and not kind.photo_consent:
        consent_note = ""
    limits = limits_for(session, company_id)
    if len(data) > limits.max_file_bytes:
        raise ValidationFailed(f"This file is {len(data) / MB:.1f} MB; the most allowed is "
                               f"{limits.max_file_bytes // MB} MB. Take the photo at a lower resolution or split it")
    session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"file:{entity_id}"})
    if local_id is not None:
        again = session.execute(text(
            f"select {_COLUMNS} from {_FROM} where f.local_id = :l and f.status = 'active'"),
            {"l": str(local_id)}).first()
        if again is not None:
            return _info(again)
    held = session.execute(text(
        "select count(*) from kernel.attachment where status = 'active' and entity_type = :t and entity_id = :e"),
        {"t": entity_type, "e": str(entity_id)}).scalar_one()
    if held >= limits.max_per_record:
        raise ValidationFailed(f"This record already has {held} files; the most allowed is {limits.max_per_record}. "
                               "Remove some first")
    prepared = media.prepare(data, strip_location=limits.strip_location)
    sizes = len(prepared.original) + len(prepared.web or b"") + len(prepared.thumb or b"")
    _check_room(session, company_id, limits, sizes)
    ctx = get_context()
    file_id = uuid4()
    store, pending = get_store(), _pending(session)
    keys: dict[str, str | None] = {"original": _key(ctx.tenant_id, file_id, "original"),
                                   "web": _key(ctx.tenant_id, file_id, "web") if prepared.web else None,
                                   "thumb": _key(ctx.tenant_id, file_id, "thumb") if prepared.thumb else None}
    for variant, blob in (("original", prepared.original), ("web", prepared.web), ("thumb", prepared.thumb)):
        key = keys[variant]
        if key is not None and blob is not None:
            pending.written.append(key)
            store.put(key, blob)
    info = prepared.info
    row = session.execute(text(
        "insert into kernel.attachment (id, tenant_id, created_by, company_id, branch_id, entity_type, entity_id, "
        "category, caption, visibility, consent_note, kind, content_type, original_name, size_bytes, checksum, width, "
        "height, page_count, storage_key, web_key, thumb_key, web_bytes, thumb_bytes, location_stripped, local_id) "
        "values (:id, kernel.current_tenant(), :by, :c, :b, :t, :e, :cat, :cap, :vis, :cons, :kind, :ct, :nm, :sz, "
        ":sum, :w, :h, :pg, :ko, :kw, :kt, :wb, :tb, :ls, :lid) on conflict (tenant_id, local_id) "
        "where local_id is not null do nothing returning id"),
        {"id": str(file_id), "by": str(ctx.user_id) if ctx.user_id else None,
         "c": str(company_id) if company_id else None, "b": str(branch_id) if branch_id else None,
         "t": entity_type, "e": str(entity_id), "cat": category, "cap": caption, "vis": visibility,
         "cons": consent_note, "kind": info.kind, "ct": info.content_type,
         "nm": media.clean_name(name, info.extension, "photo" if info.kind == "image" else "document"),
         "sz": len(prepared.original), "sum": hashlib.sha256(prepared.original).hexdigest(), "w": info.width,
         "h": info.height, "pg": info.pages, "ko": keys["original"], "kw": keys["web"], "kt": keys["thumb"],
         "wb": len(prepared.web or b""), "tb": len(prepared.thumb or b""), "ls": prepared.location_stripped,
         "lid": str(local_id) if local_id else None}).first()
    if row is None:                                  # a parallel retry won: return its file, drop our bytes
        for key in [k for k in keys.values() if k]:
            _quietly(lambda key=key: store.delete(key))      # type: ignore[misc]
        pending.written.clear()
        won = session.execute(text(f"select {_COLUMNS} from {_FROM} where f.local_id = :l"),
                              {"l": str(local_id)}).one()
        return _info(won)
    audit.record(session, "attach", "kernel.attachment", file_id,
                 {"entity_type": entity_type, "entity_id": str(entity_id), "category": category, "kind": info.kind,
                  "bytes": len(prepared.original), "visibility": visibility})
    return _info(_row(session, file_id))


# --------------------------------------------------------------------------- changing and removing
def update_file(session: Session, file_id: UUID, *, caption: str | None = None, category: str | None = None,
                visibility: str | None = None, consent_note: str | None = None) -> FileInfo:
    """Change a file's caption, kind, visibility or consent note. Making a file staff-only ends every link made for it.
    Needs the permission that edits the record."""
    row = _row(session, file_id, lock=True)
    kind = _row_permission(session, row, edit=True)
    changes: dict[str, Any] = {}
    if caption is not None:
        changes["caption"] = _clean_text(caption, 300, "The caption")
    if category is not None:
        changes["category"] = _check_category(category)
    if consent_note is not None:
        changes["consent_note"] = _clean_text(consent_note, 300, "The consent note") if kind.photo_consent else ""
    if visibility is not None:
        if visibility not in VISIBILITIES:
            raise ValidationFailed("Visibility is 'staff' (staff only) or 'shareable'")
        changes["visibility"] = visibility
    if not changes:
        return _info(row)
    bump = changes.get("visibility") == "staff" and row.visibility != "staff"
    session.execute(text(
        "update kernel.attachment set caption = :caption, category = :category, visibility = :visibility, "
        "consent_note = :consent_note, link_epoch = link_epoch + :bump, updated_at = now(), updated_by = :u "
        "where id = :i"),
        {"caption": changes.get("caption", row.caption), "category": changes.get("category", row.category),
         "visibility": changes.get("visibility", row.visibility),
         "consent_note": changes.get("consent_note", row.consent_note), "bump": 1 if bump else 0,
         "u": str(get_context().user_id) if get_context().user_id else None, "i": str(file_id)})
    audit.record(session, "update", "kernel.attachment", file_id,       # what changed, never the words (names)
                 {k: (v if k in ("category", "visibility") else "changed") for k, v in changes.items()})
    return _info(_row(session, file_id))


def _check_reason(reason: str) -> str:
    cleaned = " ".join((reason or "").split())
    if not REASON_MIN <= len(cleaned) <= REASON_MAX:
        raise ValidationFailed(f"Say why the file is removed ({REASON_MIN} to {REASON_MAX} characters)")
    return cleaned


def _remove(session: Session, row: Any, reason: str) -> None:
    session.execute(text(
        "update kernel.attachment set status = 'deleted', deleted_at = now(), deleted_by = :u, delete_reason = :r, "
        "caption = '', original_name = '', consent_note = '', link_epoch = link_epoch + 1, updated_at = now() "
        "where id = :i"),
        {"u": str(get_context().user_id) if get_context().user_id else None, "r": reason, "i": str(row.id)})
    pending = _pending(session)
    pending.to_remove.extend(k for k in (row.storage_key, row.web_key, row.thumb_key) if k)
    audit.record(session, "delete", "kernel.attachment", row.id,
                 {"entity_type": row.entity_type, "entity_id": str(row.entity_id), "reason": reason,
                  "kind": row.kind, "bytes": row.size_bytes})


def delete_file(session: Session, file_id: UUID, reason: str) -> None:
    """Remove a file, with the reason. The row stays (who, when, why) without the caption or name; the bytes are removed
    once this commits and every link made for the file stops working. Needs the permission that edits the record."""
    row = _row(session, file_id, lock=True)
    _row_permission(session, row, edit=True)
    _remove(session, row, _check_reason(reason))


def remove_for_entity(session: Session, entity_type: str, entity_id: UUID, reason: str) -> int:
    """Remove every file of a record (a unit calls this when it removes the record, so no file is left behind). Needs
    the permission that edits the record; returns how many files were removed."""
    kind = entity(session, entity_type)
    scope = kind.scope(session, entity_id)
    if scope is not None:
        _require(session, kind, scope[0], scope[1], edit=True)
    reason = _check_reason(reason)
    rows = session.execute(text(
        f"select {_COLUMNS} from {_FROM} where f.status = 'active' and f.entity_type = :t and f.entity_id = :e "
        "for update of f"), {"t": entity_type, "e": str(entity_id)}).all()
    for row in rows:
        _remove(session, row, reason)
    return len(rows)


# --------------------------------------------------------------------------- opening
def _log_access(session: Session, row: Any, variant: str, via: str, purpose: str = "", label: str = "",
                user_id: UUID | None = None, ip: str | None = None) -> None:
    if variant == "thumb":
        return                                # thumbnails fill grids; only the real pictures and documents are logged
    session.execute(text(
        "insert into kernel.attachment_access (tenant_id, file_id, company_id, variant, via, purpose, label, user_id, "
        "ip) "
        "values (kernel.current_tenant(), :f, :c, :v, :via, :p, :l, :u, :ip)"),
        {"f": str(row.id), "c": str(row.company_id) if row.company_id else None, "v": variant, "via": via,
         "p": purpose, "l": label[:60], "u": str(user_id) if user_id else None, "ip": (ip or "")[:64]})


def _bytes(row: Any, variant: str) -> FileContent:
    if variant not in VARIANTS:
        raise ValidationFailed("The form is 'original', 'web' or 'thumb'")
    key, content_type = row.storage_key, row.content_type
    if variant == "web" and row.web_key:
        key, content_type = row.web_key, "image/jpeg"
    elif variant == "thumb":
        if not row.thumb_key:
            raise NotFound("This file has no preview")
        key, content_type = row.thumb_key, "image/jpeg"
    try:
        data = get_store().get(key)
    except FileNotFoundError:
        log.error("File %s is missing from the store (%s); run `ziira verify`", row.id, variant)
        raise NotFound("The stored file is missing. Tell your administrator") from None
    name = row.original_name or f"file.{row.content_type.split('/')[-1]}"
    if content_type == "image/jpeg" and variant != "original":
        name = name.rsplit(".", 1)[0] + ".jpg"
    return FileContent(data, content_type, name, variant)


def read(session: Session, file_id: UUID, variant: str = "web") -> FileContent:
    """The bytes of a file (`variant`: 'original', 'web' copy or 'thumb'nail), after checking the actor may open the
    record. Opening a full-size picture or document is logged (who, when)."""
    row = _row(session, file_id)
    _row_permission(session, row, edit=False)
    content = _bytes(row, variant)
    ctx = get_context()
    _log_access(session, row, variant, "api" if ctx.api_key_id else "staff", user_id=ctx.user_id, ip=ctx.ip_address)
    return content


# --------------------------------------------------------------------------- links
def _expires(seconds: int, maximum: int) -> tuple[int, datetime]:
    seconds = max(30, min(int(seconds), maximum))
    ends = int(time.time()) + seconds
    return ends, datetime.fromtimestamp(ends, UTC)


def _link(row: Any, variant: str, *, purpose: str, label: str, seconds: int, user_id: UUID | None) -> SignedLink:
    ends, when = _expires(seconds, tokens.MAX_STAFF_SECONDS if purpose == "staff" else tokens.MAX_PUBLIC_SECONDS)
    token = tokens.make(tokens.LinkClaims(get_context().tenant_id, row.id, variant, ends, row.link_epoch, purpose,
                                          label, user_id))
    return SignedLink(f"/api/v1/files/dl/{token}", when, variant)


def signed_link(session: Session, file_id: UUID, variant: str = "web", *, seconds: int = 300) -> SignedLink:
    """A short-lived address a signed-in person's browser can use directly (an <img src>), valid up to 15 minutes. Needs
    the permission that opens the record; opening through it is logged against that person."""
    if variant not in VARIANTS:
        raise ValidationFailed("The form is 'original', 'web' or 'thumb'")
    row = _row(session, file_id)
    _row_permission(session, row, edit=False)
    return _link(row, variant, purpose="staff", label="", seconds=seconds, user_id=get_context().user_id)


def public_links(session: Session, entity_type: str, entity_id: UUID, *, label: str, seconds: int = 1800,
                 category: str | None = None) -> list[PublicFile]:
    """The SHAREABLE files of a record with addresses that work without signing in (up to 24 hours), for a public
    approval or insurer response page. No sign-in check: the caller has already authenticated the visitor by its own
    link and must call this only for the record that link is for. `label` says why in the access list ("insurer
    response CLM-00012"). Every opening is logged with it and the visitor's address. Staff-only files never appear."""
    kind = entity(session, entity_type)
    if kind.scope(session, entity_id) is None:
        raise NotFound("Record not found")
    label = _clean_text(label, 60, "The link label") or "public link"
    rows = session.execute(text(
        f"select {_COLUMNS} from {_FROM} where f.status = 'active' and f.visibility = 'shareable' "
        "and f.entity_type = :t and f.entity_id = :e and (cast(:cat as text) is null or f.category = :cat) "
        "order by f.created_at, f.id"), {"t": entity_type, "e": str(entity_id), "cat": category}).all()
    out = []
    for row in rows:
        def mint(variant: str, row: Any = row) -> SignedLink:
            return _link(row, variant, purpose="public", label=label, seconds=seconds, user_id=None)

        out.append(PublicFile(row.id, row.category, row.caption, row.kind, row.content_type, row.original_name,
                              row.size_bytes, row.width, row.height, mint("thumb") if row.thumb_key else None,
                              mint("web") if row.web_key else None, mint("original")))
    return out


def revoke_links(session: Session, file_id: UUID) -> None:
    """End every address made for a file so far (staff and public). Needs the permission that edits the record."""
    row = _row(session, file_id, lock=True)
    _row_permission(session, row, edit=True)
    session.execute(text("update kernel.attachment set link_epoch = link_epoch + 1 where id = :i"), {"i": str(file_id)})
    audit.record(session, "revoke_links", "kernel.attachment", file_id, None)


def revoke_links_for_entity(session: Session, entity_type: str, entity_id: UUID) -> int:
    """End every address made for the files of a record (a unit calls it when it closes an approval or insurer link)."""
    kind = entity(session, entity_type)
    scope = _record_scope(session, kind, entity_id)
    _require(session, kind, scope[0], scope[1], edit=True)
    done = session.execute(text(
        "update kernel.attachment set link_epoch = link_epoch + 1 where status = 'active' and entity_type = :t "
        "and entity_id = :e"), {"t": entity_type, "e": str(entity_id)}).rowcount  # type: ignore[attr-defined]
    audit.record(session, "revoke_links", "kernel.attachment", entity_id, {"entity_type": entity_type, "files": done})
    return int(done or 0)


def open_link(session: Session, claims: tokens.LinkClaims, ip: str | None) -> FileContent:
    """Open a file through a link already read from its token. Runs as the system in the link's business. The file must
    still exist, the link must belong to its current generation, and a public link needs the file to be shareable."""
    row = session.execute(text(f"select {_COLUMNS} from {_FROM} where f.id = :i and f.status = 'active'"),
                          {"i": str(claims.file_id)}).first()
    if row is None or row.link_epoch != claims.epoch or (claims.purpose == "public" and row.visibility != "shareable"):
        raise NotFound("This link is not valid")
    content = _bytes(row, claims.variant)
    _log_access(session, row, claims.variant, "link", claims.purpose, claims.label, claims.user_id, ip)
    return content


def access_log(session: Session, file_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
    """Who opened a file, newest first (permission files.audit for its company)."""
    row = _row(session, file_id, active_only=False)
    get_context().require(AUDIT_PERMISSION, company_id=row.company_id)
    found = session.execute(text(
        "select a.at, a.variant, a.via, a.purpose, a.label, a.ip, a.user_id, u.full_name "
        "from kernel.attachment_access a "
        "left join kernel.app_user u on u.id = a.user_id where a.file_id = :f order by a.at desc limit :n"),
        {"f": str(file_id), "n": min(max(limit, 1), 500)})
    return [{"at": r.at, "variant": r.variant, "via": r.via, "purpose": r.purpose, "label": r.label, "ip": r.ip,
             "user_id": r.user_id, "user_name": r.full_name} for r in found]


# --------------------------------------------------------------------------- housekeeping
def purge_deleted(session: Session) -> int:
    """Remove the bytes of deleted files whose removal did not finish (a crash, a full disk) and mark them done."""
    rows = session.execute(text(
        "select id, storage_key, web_key, thumb_key from kernel.attachment "
        "where status = 'deleted' and not blobs_removed "
        "and deleted_at < now() - interval '2 minutes' limit 200")).all()
    store = get_store()
    for row in rows:
        for key in (row.storage_key, row.web_key, row.thumb_key):
            if key:
                store.delete(key)
        session.execute(text("update kernel.attachment set blobs_removed = true where id = :i"), {"i": str(row.id)})
    return len(rows)


def purge_access_log(session: Session) -> int:
    """Remove access-log lines older than each company's `retention_file_access_days` (0 keeps them)."""
    removed = 0
    for company_id in session.execute(text("select id from kernel.company")).scalars().all():
        days = int(company_settings.get_setting(session, company_id, "retention_file_access_days"))
        if days > 0:
            removed += session.execute(text(
                "delete from kernel.attachment_access where company_id = :c and at < :cut"),
                {"c": str(company_id), "cut": datetime.now(UTC) - timedelta(days=days)}
            ).rowcount or 0  # type: ignore[attr-defined]
    return removed


@periodic("files.housekeeping", every_seconds=600)
def housekeeping(session: Session) -> None:
    """Finish removing deleted files' bytes; drop access-log lines past their retention."""
    purged = purge_deleted(session)
    removed = purge_access_log(session)
    if purged or removed:
        log.info("Files housekeeping: %s deleted file(s) cleaned, %s access line(s) removed", purged, removed)
