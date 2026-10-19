"""Photos on jobs: the kinds of photo (data), and the photos a kind of job must have before it reaches a stage.

The pictures are kept by the kernel files service (`ziira.sdk.files`, attached to `jobs.job`); this file only knows
the categories a workshop uses and the rule: "a body-repair job needs 3 damage photos before it is quoted". A business
chooses (job settings) whether a job that moves on without them is allowed, allowed with a note, or refused.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ziira.modules.jobs.permissions import JOBS_SETTINGS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobType, PhotoCategory
from ziira.modules.jobs.services import access, catalog
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, unit_enabled
from ziira.sdk import (
    Category,
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    files,
)

ENTITY = "jobs.job"
STAGE_ROLES = ("quoted", "approved", "ready", "collected", "closed")
DEFAULT_CATEGORIES = (("intake", "Intake"), ("damage", "Damage"), ("odometer", "Odometer"), ("fuel", "Fuel gauge"),
                      ("progress", "Progress"), ("before_after", "Before and after"), ("old_part", "Old part"),
                      ("other", "Other"))


@dataclass(frozen=True)
class PhotoStatus:
    category: str
    name: str
    minimum: int
    before: str
    have: int

    @property
    def ok(self) -> bool:
        return self.have >= self.minimum


# --------------------------------------------------------------------------- the kinds of photo
def all_categories(session: Session) -> list[Category]:
    """The kinds of photo this business uses (the same code in two companies is one kind), else the usual ones."""
    rows = session.scalars(select(PhotoCategory).where(PhotoCategory.is_active).order_by(
        PhotoCategory.position, PhotoCategory.name))
    seen: dict[str, str] = {}
    for row in rows:
        seen.setdefault(row.code, row.name)
    if not seen:
        return [Category(code, name) for code, name in DEFAULT_CATEGORIES]
    return [Category(code, name) for code, name in seen.items()]


def list_categories(session: Session, company_id: UUID, *, only_active: bool = False) -> list[PhotoCategory]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    query = select(PhotoCategory).where(PhotoCategory.company_id == company_id)
    if only_active:
        query = query.where(PhotoCategory.is_active)
    return list(session.scalars(query.order_by(PhotoCategory.position, PhotoCategory.name)))


def create_category(session: Session, *, company_id: UUID, name: str, code: str | None = None,
                    position: int = 0) -> PhotoCategory:
    """Add a kind of photo. Needs 'jobs.settings'."""
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("Give the kind of photo a name")
    key = catalog.make_code(code or name)
    if any(c.code == key for c in list_categories(session, company_id)):
        raise Conflict("There is already a kind of photo with this code")
    if len(list_categories(session, company_id)) >= 40:
        raise ValidationFailed("At most 40 kinds of photo")
    row = PhotoCategory(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=key,
                        name=name.strip()[:60], position=position)
    repo.add(session, row)
    audit_record(session, "create", "jobs.photo_category", row.id, {"code": key})
    return row


def update_category(session: Session, row_id: UUID, **changes: Any) -> PhotoCategory:
    row = repo.get(session, PhotoCategory, row_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Kind of photo not found")
    current_context().require(JOBS_SETTINGS, company_id=row.company_id)
    if changes.get("name"):
        row.name = str(changes["name"]).strip()[:60]
    if isinstance(changes.get("position"), int):
        row.position = int(changes["position"])
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.updated_by = current_context().user_id
    session.flush()
    return row


# --------------------------------------------------------------------------- the rule
def clean_rules(session: Session, company_id: UUID, given: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Check a job type's photo rules: each names a kind of photo, how many, and the stage it is needed before."""
    known = {c.code for c in list_categories(session, company_id)} or {code for code, _ in DEFAULT_CATEGORIES}
    out: list[dict[str, Any]] = []
    for item in given or []:
        category, before = str(item.get("category", "")).strip().lower(), str(item.get("before", "")).strip()
        minimum = int(item.get("min", 1))
        if category not in known:
            raise ValidationFailed(f"'{category}' is not one of your kinds of photo. Add it first")
        if before not in STAGE_ROLES:
            raise ValidationFailed(f"Photos are needed before one of: {', '.join(STAGE_ROLES)}")
        if not 1 <= minimum <= 20:
            raise ValidationFailed("Ask for between 1 and 20 photos of a kind")
        out.append({"category": category, "min": minimum, "before": before})
    if len(out) > 20:
        raise ValidationFailed("At most 20 photo rules per job type")
    return out


def _job_type(session: Session, job: Job) -> JobType | None:
    return repo.job_type_by_code(session, job.company_id, job.job_type_code) if job.job_type_code else None


def status(session: Session, job: Job) -> list[PhotoStatus]:
    """For each photo the job's type asks for: how many it has now."""
    kind = _job_type(session, job)
    if kind is None or not kind.required_photos:
        return []
    names = {c.key: c.label for c in all_categories(session)}
    have: dict[str, int] = {}
    for info in files.list_files(session, ENTITY, job.id):
        have[info.category] = have.get(info.category, 0) + 1
    return [PhotoStatus(r["category"], names.get(r["category"], r["category"]), int(r.get("min", 1)), r["before"],
                        have.get(r["category"], 0)) for r in kind.required_photos]


def guard(session: Session, job: Job, target_role: str | None, *, may_block: bool = True) -> None:
    """Before a job enters a stage with a role: are the photos that stage needs there? Depending on the business
    setting the move is refused (block), allowed with a note on the timeline (warn) or not checked (off). A move the
    system makes (an approval moving the job on) only ever warns."""
    if target_role is None or not unit_enabled(session, "jobs"):
        return
    mode = job_settings.get_settings(session, job.company_id).required_photos
    if mode == "off":
        return
    missing = [p for p in status(session, job) if p.before == target_role and not p.ok]
    if not missing:
        return
    text = ", ".join(f"{p.name} ({p.have} of {p.minimum})" for p in missing)
    if mode == "block" and may_block:
        raise ValidationFailed(f"Photos are needed first: {text}")
    add_event(session, job, "photo", f"Moved on without the photos asked for: {text}")
