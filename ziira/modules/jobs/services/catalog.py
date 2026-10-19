"""The workshop's catalogue, all of it data a business edits: work types (mechanical, body, paint, electrical) with
their hourly rates, the flat-rate task library (standard times), part categories with their markup, and job types.

An industry pack seeds the same rows (marked `is_example` for tasks, because standard times differ by make and
workshop). Reading needs any jobs permission; changing needs 'jobs.settings'.
"""

import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_SETTINGS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import ChecklistTemplate, JobType, LabourTask, PartCategory, WorkType
from ziira.modules.jobs.services import access
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, check_company, current_context

CODE = re.compile(r"[^a-z0-9_-]+")
MAX_ROWS = 500
CLASSES = ("genuine", "aftermarket", "used")


def make_code(value: str) -> str:
    """A short lowercase code from a name or a typed code."""
    code = CODE.sub("-", value.strip().lower()).strip("-")[:40]
    if not code:
        raise ValidationFailed("Give it a name or a code")
    return code


def _visible(company_id: UUID) -> None:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")


def _setup(company_id: UUID) -> None:
    current_context().require(JOBS_SETTINGS, company_id=company_id)


def _money(value: object, what: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or value < 0:
        raise ValidationFailed(f"{what} cannot be negative")
    return value


# --------------------------------------------------------------------------- work types
def list_work_types(session: Session, company_id: UUID, *, only_active: bool = False) -> list[WorkType]:
    _visible(company_id)
    return repo.work_types(session, company_id, only_active=only_active)


def create_work_type(session: Session, *, company_id: UUID, name: str, code: str | None = None,
                     hourly_rate: Decimal | None = None, position: int = 0) -> WorkType:
    """Add a kind of labour. A blank rate means the company's labour rate. Needs 'jobs.settings'."""
    _setup(company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("Give the work type a name")
    key = make_code(code or name)
    if repo.work_type_by_code(session, company_id, key) is not None:
        raise Conflict("There is already a work type with this code")
    if len(repo.work_types(session, company_id)) >= 40:
        raise ValidationFailed("At most 40 work types")
    ctx = current_context()
    row = WorkType(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=key,
                   name=name.strip()[:60], hourly_rate=_money(hourly_rate, "The rate"), position=position)
    repo.add(session, row)
    audit_record(session, "create", "jobs.work_type", row.id, {"code": key})
    return row


def update_work_type(session: Session, row_id: UUID, **changes: Any) -> WorkType:
    row = repo.get(session, WorkType, row_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Work type not found")
    _setup(row.company_id)
    if changes.get("name"):
        row.name = str(changes["name"]).strip()[:60]
    if "hourly_rate" in changes:
        row.hourly_rate = _money(changes["hourly_rate"], "The rate")
    if isinstance(changes.get("position"), int):
        row.position = int(changes["position"])
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "jobs.work_type", row.id, {})
    return row


def rate_for_work_type(session: Session, company_id: UUID, code: str | None, default: Decimal) -> Decimal:
    """The hourly rate of a work type, or `default` when it has none (or there is no such type)."""
    if not code:
        return default
    found = repo.work_type_by_code(session, company_id, code)
    return found.hourly_rate if found is not None and found.hourly_rate is not None else default


# --------------------------------------------------------------------------- the flat-rate task library
def list_tasks(session: Session, company_id: UUID, *, only_active: bool = False,
               search: str | None = None) -> list[LabourTask]:
    _visible(company_id)
    return repo.labour_tasks(session, company_id, only_active=only_active, search=search)


def _check_work_type(session: Session, company_id: UUID, code: str | None) -> str | None:
    if not code:
        return None
    if repo.work_type_by_code(session, company_id, code) is None:
        raise ValidationFailed("That work type does not exist. Add it first")
    return code


def create_task(session: Session, *, company_id: UUID, name: str, standard_hours: Decimal, code: str | None = None,
                work_type_code: str | None = None, flat_price: Decimal | None = None,
                asset_kind: str | None = None, is_example: bool = False) -> LabourTask:
    """Add a standard job with a standard time (and optionally a fixed price). Needs 'jobs.settings'."""
    _setup(company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("Give the task a name")
    if standard_hours <= 0 or standard_hours > 500:
        raise ValidationFailed("The standard time is more than zero and at most 500 hours")
    key = make_code(code or name)
    if repo.labour_task_by_code(session, company_id, key) is not None:
        raise Conflict("There is already a task with this code")
    if len(repo.labour_tasks(session, company_id)) >= MAX_ROWS:
        raise ValidationFailed(f"At most {MAX_ROWS} tasks in the library")
    ctx = current_context()
    row = LabourTask(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=key,
                     name=name.strip()[:160], work_type_code=_check_work_type(session, company_id, work_type_code),
                     standard_hours=standard_hours, flat_price=_money(flat_price, "The price"),
                     asset_kind=(asset_kind or "").strip()[:40] or None, is_example=is_example)
    repo.add(session, row)
    audit_record(session, "create", "jobs.labour_task", row.id, {"code": key})
    return row


def update_task(session: Session, row_id: UUID, **changes: Any) -> LabourTask:
    row = repo.get(session, LabourTask, row_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Task not found")
    _setup(row.company_id)
    if changes.get("name"):
        row.name = str(changes["name"]).strip()[:160]
    if "standard_hours" in changes and changes["standard_hours"] is not None:
        hours = changes["standard_hours"]
        if not isinstance(hours, Decimal) or hours <= 0 or hours > 500:
            raise ValidationFailed("The standard time is more than zero and at most 500 hours")
        row.standard_hours = hours
    if "work_type_code" in changes:
        row.work_type_code = _check_work_type(session, row.company_id, changes["work_type_code"])
    if "flat_price" in changes:
        row.flat_price = _money(changes["flat_price"], "The price")
    if "asset_kind" in changes:
        row.asset_kind = str(changes["asset_kind"] or "").strip()[:40] or None
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.is_example = False                        # once a business has looked at a time and kept it, it is theirs
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "jobs.labour_task", row.id, {})
    return row


# --------------------------------------------------------------------------- part categories
def list_part_categories(session: Session, company_id: UUID, *, only_active: bool = False) -> list[PartCategory]:
    _visible(company_id)
    return repo.part_categories(session, company_id, only_active=only_active)


def _check_class(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if value not in CLASSES:
        raise ValidationFailed("A part is genuine, aftermarket or used")
    return value


def create_part_category(session: Session, *, company_id: UUID, name: str, code: str | None = None,
                         markup_percent: Decimal = Decimal(0), default_class: str | None = None,
                         position: int = 0) -> PartCategory:
    """Add a kind of part with the markup on cost. Needs 'jobs.settings'."""
    _setup(company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("Give the category a name")
    if markup_percent < 0 or markup_percent > 1000:
        raise ValidationFailed("The markup is between 0 and 1000 percent")
    key = make_code(code or name)
    if repo.part_category_by_code(session, company_id, key) is not None:
        raise Conflict("There is already a category with this code")
    if len(repo.part_categories(session, company_id)) >= 100:
        raise ValidationFailed("At most 100 part categories")
    ctx = current_context()
    row = PartCategory(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=key,
                       name=name.strip()[:60], markup_percent=markup_percent,
                       default_class=_check_class(default_class), position=position)
    repo.add(session, row)
    audit_record(session, "create", "jobs.part_category", row.id, {"code": key})
    return row


def update_part_category(session: Session, row_id: UUID, **changes: Any) -> PartCategory:
    row = repo.get(session, PartCategory, row_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Category not found")
    _setup(row.company_id)
    if changes.get("name"):
        row.name = str(changes["name"]).strip()[:60]
    if "markup_percent" in changes and changes["markup_percent"] is not None:
        value = changes["markup_percent"]
        if not isinstance(value, Decimal) or value < 0 or value > 1000:
            raise ValidationFailed("The markup is between 0 and 1000 percent")
        row.markup_percent = value
    if "default_class" in changes:
        row.default_class = _check_class(changes["default_class"])
    if isinstance(changes.get("position"), int):
        row.position = int(changes["position"])
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "jobs.part_category", row.id, {})
    return row


# --------------------------------------------------------------------------- job types
def list_job_types(session: Session, company_id: UUID, *, only_active: bool = False) -> list[JobType]:
    _visible(company_id)
    return repo.job_types(session, company_id, only_active=only_active)


def _check_template(session: Session, company_id: UUID, template_id: UUID | None) -> UUID | None:
    if template_id is None:
        return None
    found = repo.get(session, ChecklistTemplate, template_id)
    if found is None or found.company_id != company_id:
        raise ValidationFailed("Checklist not found in this company")
    return template_id


def create_job_type(session: Session, *, company_id: UUID, name: str, code: str | None = None,
                    checklist_template_id: UUID | None = None, default_warranty_days: int | None = None,
                    position: int = 0, required_photos: list[dict[str, Any]] | None = None) -> JobType:
    """Add a kind of job (a service, a body repair, an alteration). Needs 'jobs.settings'."""
    _setup(company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("Give the job type a name")
    key = make_code(code or name)
    if repo.job_type_by_code(session, company_id, key) is not None:
        raise Conflict("There is already a job type with this code")
    if len(repo.job_types(session, company_id)) >= 50:
        raise ValidationFailed("At most 50 job types")
    if default_warranty_days is not None and not 0 <= default_warranty_days <= 3650:
        raise ValidationFailed("The warranty is between 0 and 3650 days")
    ctx = current_context()
    row = JobType(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=key,
                  name=name.strip()[:60], checklist_template_id=_check_template(session, company_id,
                                                                                 checklist_template_id),
                  default_warranty_days=default_warranty_days, position=position,
                  required_photos=_photo_rules(session, company_id, required_photos))
    repo.add(session, row)
    audit_record(session, "create", "jobs.job_type", row.id, {"code": key})
    return row


def _photo_rules(session: Session, company_id: UUID, given: Any) -> list[dict[str, Any]]:
    from ziira.modules.jobs.services import photos

    return photos.clean_rules(session, company_id, [dict(x) for x in given] if given else [])


def update_job_type(session: Session, row_id: UUID, **changes: Any) -> JobType:
    row = repo.get(session, JobType, row_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Job type not found")
    _setup(row.company_id)
    if changes.get("name"):
        row.name = str(changes["name"]).strip()[:60]
    if "checklist_template_id" in changes:
        value = changes["checklist_template_id"]
        row.checklist_template_id = _check_template(session, row.company_id, value if isinstance(value, UUID)
                                                    else None)
    if "default_warranty_days" in changes:
        days = changes["default_warranty_days"]
        if days is not None and (not isinstance(days, int) or not 0 <= days <= 3650):
            raise ValidationFailed("The warranty is between 0 and 3650 days")
        row.default_warranty_days = days
    if "required_photos" in changes:
        row.required_photos = _photo_rules(session, row.company_id, changes["required_photos"])
    if isinstance(changes.get("position"), int):
        row.position = int(changes["position"])
    if isinstance(changes.get("is_active"), bool):
        row.is_active = bool(changes["is_active"])
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "jobs.job_type", row.id, {})
    return row
