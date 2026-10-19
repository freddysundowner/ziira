"""Use cases: work orders, from taking an item in to collection.

    received -> diagnosing -> quoted -> approved -> in progress -> ready -> collected -> closed     (the default stages)

The stages and the moves between them are the business's data (services/statuses.py); this file only checks that a move
is allowed and does what a stage with a special role means: 'ready' tells the customer, 'collected' starts the
warranty, a closed stage finishes the job. Once a job is invoiced (or closed) it is locked: only notes, the warranty
period, a return visit and collection can still happen.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.domain import pricing
from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import (
    Asset,
    ChecklistTemplate,
    Job,
    JobChecklistItem,
    JobStatus,
    JobTask,
)
from ziira.modules.jobs.services import access, assets, claims_link, notify, photos, release, statuses
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, check_person, clean, load_job, unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_today,
    current_context,
    next_document_number,
    publish,
)

LOCKED = "This job has been invoiced or closed. Only notes, the warranty, a return visit and collection can change"
MAX_CHECKLIST = 60
MAX_TASKS = 100


@dataclass(frozen=True)
class NewAsset:
    """An item to record while taking a job in."""

    label: str
    kind: str = "item"
    identifiers: dict[str, str] | None = None
    notes: str | None = None


def status_of(session: Session, job: Job) -> JobStatus:
    found = repo.get(session, JobStatus, job.status_id)
    assert found is not None
    return found


def is_locked(session: Session, job: Job) -> bool:
    return job.invoiced_at is not None or status_of(session, job).kind == "closed"


def require_editable(session: Session, job: Job) -> None:
    """Raise Conflict when the job is invoiced or closed."""
    if is_locked(session, job):
        raise Conflict(LOCKED)


def _customer_snapshot(session: Session, company_id: UUID, customer_id: UUID | None, name: str | None,
                       phone: str | None) -> tuple[str | None, str | None]:
    """The customer's name and phone to keep on the job: what was typed, else the customer record's."""
    if customer_id is not None:
        assets.check_customer(session, company_id, customer_id)
        if unit_enabled(session, "crm"):
            from ziira.modules.crm.public import find_customer

            record = find_customer(session, customer_id)
            if record is not None:
                name, phone = name or record.name, phone or record.phone
    return clean(name, 160), clean(phone, 40)


def receive_job(session: Session, *, company_id: UUID, branch_id: UUID, title: str, customer_id: UUID | None = None,
                customer_name: str | None = None, customer_phone: str | None = None, asset_id: UUID | None = None,
                new_asset: NewAsset | None = None, description: str | None = None,
                condition_notes: str | None = None, assignee_id: UUID | None = None, promised_at: date | None = None,
                checklist_template_id: UUID | None = None, checklist_items: list[str] | None = None,
                job_type_code: str | None = None, odometer_in: Decimal | None = None, fuel_level: str | None = None,
                key_tag: str | None = None, belongings: str | None = None,
                acknowledged_by_name: str | None = None) -> Job:
    """Take an item in: make the work order in its first stage. Needs 'jobs.manage' at the branch. The intake details
    (odometer, fuel, key tag, belongings, who signed for the drop-off) are kept on the job; the odometer also updates
    the item's last reading."""
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    if not title.strip():
        raise ValidationFailed("Say what the job is, for example 'Brake pads worn'")
    asset: Asset | None = None
    if asset_id is not None:
        asset = assets.load_asset(session, asset_id)
        if asset.company_id != company_id:
            raise ValidationFailed("The item was not found in this company")
    elif new_asset is not None:
        asset = assets.create_asset(session, company_id=company_id, label=new_asset.label, kind=new_asset.kind,
                                    customer_id=customer_id, identifiers=new_asset.identifiers, notes=new_asset.notes)
    if customer_id is None and asset is not None:
        customer_id = asset.customer_id
    name, phone = _customer_snapshot(session, company_id, customer_id, customer_name, customer_phone)
    if customer_id is None and name is None:
        raise ValidationFailed("Say who the customer is: pick a customer or type a name")
    check_person(session, assignee_id)
    statuses.ensure_seeded(session, company_id)
    first = repo.status_by_role(session, company_id, "initial")
    if first is None:
        raise ValidationFailed("No stage is marked as the first one. Choose one in the job settings")
    settings = job_settings.get_settings(session, company_id)
    job_type = None
    if job_type_code:
        job_type = repo.job_type_by_code(session, company_id, job_type_code.strip().lower())
        if job_type is None or not job_type.is_active:
            raise ValidationFailed("That job type does not exist. Choose one from the list")
        if checklist_template_id is None and checklist_items is None and job_type.checklist_template_id:
            checklist_template_id = job_type.checklist_template_id
    items = _checklist_items(session, company_id, checklist_template_id, checklist_items)
    reading = _reading(odometer_in, "The odometer")
    job = Job(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="job",
                                    prefix="JOB"),
        customer_id=customer_id, customer_name=name, customer_phone=phone, asset_id=asset.id if asset else None,
        status_id=first.id, title=title.strip()[:200], description=clean(description, 4000),
        condition_notes=clean(condition_notes, 4000), assignee_id=assignee_id, promised_at=promised_at,
        warranty_days=(job_type.default_warranty_days if job_type and job_type.default_warranty_days is not None
                       else settings.default_warranty_days),
        job_type_code=job_type.code if job_type else None, odometer_in=reading, fuel_level=clean(fuel_level, 40),
        key_tag=clean(key_tag, 40), belongings=clean(belongings, 1000),
        acknowledged_by_name=clean(acknowledged_by_name, 160),
        acknowledged_at=datetime.now(UTC) if clean(acknowledged_by_name, 160) else None)
    repo.add(session, job)
    for position, label in enumerate(items, start=1):
        session.add(JobChecklistItem(tenant_id=ctx.tenant_id, job_id=job.id, position=position, label=label))
    session.flush()
    add_event(session, job, "received", None, to_status=first.id)
    if reading is not None and asset is not None:
        warning = assets.record_odometer(session, asset, reading)
        if warning:
            add_event(session, job, "intake", warning)
    audit_record(session, "create", "jobs.job", job.id, {"number": job.number})
    publish(session, Event("job.received", "jobs.job", job.id, {
        "company_id": company_id, "branch_id": branch_id, "number": job.number, "customer_id": customer_id,
        "asset_id": job.asset_id}))
    return job


def _reading(value: Decimal | None, what: str) -> Decimal | None:
    if value is None:
        return None
    if value < 0 or value > Decimal("99999999"):
        raise ValidationFailed(f"{what} reading is not valid")
    return value


def _checklist_items(session: Session, company_id: UUID, template_id: UUID | None,
                     given: list[str] | None) -> list[str]:
    if given is not None:
        items = job_settings.clean_items(given)
    elif template_id is not None:
        template = repo.get(session, ChecklistTemplate, template_id)
        if template is None or template.company_id != company_id:
            raise ValidationFailed("Checklist not found in this company")
        items = list(template.items)
    else:
        items = []
    return items[:MAX_CHECKLIST]


def get_job(session: Session, job_id: UUID) -> Job:
    return load_job(session, job_id)


def list_jobs(session: Session, *, company_id: UUID | None = None, branch_id: UUID | None = None,
              status_id: UUID | None = None, open_only: bool = False, assignee_id: UUID | None = None,
              asset_id: UUID | None = None, customer_id: UUID | None = None, search: str | None = None,
              overdue: bool = False, limit: int = 50, offset: int = 0, waiting_on: str | None = None,
              job_type_code: str | None = None) -> list[Job]:
    day = company_today(session, company_id) if (overdue and company_id) else date.today()
    found = repo.list_jobs(
        session, access.view_scopes(), company_id=company_id, branch_id=branch_id, status_id=status_id,
        kinds=("open", "waiting", "done") if open_only else None, assignee_id=assignee_id, asset_id=asset_id,
        customer_id=customer_id, search=search, overdue_on=day if overdue else None,
        limit=min(limit, 200) if waiting_on != "insurer" else 500, offset=0 if waiting_on == "insurer" else offset,
        waiting_on=waiting_on, job_type_code=job_type_code)
    if waiting_on == "insurer":                      # only the jobs whose claim waits for the payer's answer
        waiting = claims_link.waiting_on_payer(session, found)
        found = [j for j in found if j.id in waiting][offset:offset + min(limit, 200)]
    return found


@dataclass
class Board:
    statuses: list[JobStatus]
    jobs: list[Job]
    truncated: bool


def board(session: Session, *, company_id: UUID, branch_id: UUID | None = None, assignee_id: UUID | None = None,
          asset_id: UUID | None = None, overdue: bool = False, include_closed: bool = False,
          search: str | None = None) -> Board:
    """Every live job of a company grouped by stage on the screen: the stages (in order) and the jobs. Closed jobs only
    when asked for."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    stages = statuses.list_statuses(session, company_id, only_active=True)
    kinds = ("open", "waiting", "done", "closed") if include_closed else ("open", "waiting", "done")
    day = company_today(session, company_id)
    limit = 600
    found = repo.list_jobs(session, access.view_scopes(), company_id=company_id, branch_id=branch_id, kinds=kinds,
                           assignee_id=assignee_id, asset_id=asset_id, search=search,
                           overdue_on=day if overdue else None, limit=limit + 1)
    return Board(stages, found[:limit], len(found) > limit)


def update_job(session: Session, job_id: UUID, **changes: object) -> Job:
    """Change a job's description, customer, item, person in charge or promised date. Needs 'jobs.manage'. A locked job
    accepts only a new warranty period."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    if "warranty_days" in changes:
        _set_warranty(session, job, int(str(changes.pop("warranty_days"))))
    if {"next_service_date", "next_service_odometer", "next_service_note"} & set(changes) and job.asset_id:
        assets.set_next_service(session, assets.load_asset(session, job.asset_id),
                                date_=changes.pop("next_service_date", None),            # type: ignore[arg-type]
                                odometer=changes.pop("next_service_odometer", None),     # type: ignore[arg-type]
                                note=changes.pop("next_service_note", None),             # type: ignore[arg-type]
                                job=job)
    else:
        for key in ("next_service_date", "next_service_odometer", "next_service_note"):
            changes.pop(key, None)
    if not changes:
        return job
    require_editable(session, job)
    for key, limit in (("title", 200), ("description", 4000), ("condition_notes", 4000)):
        if key in changes:
            value = clean(str(changes[key] or ""), limit)
            if key == "title" and value is None:
                raise ValidationFailed("A job needs a title")
            setattr(job, key, value)
    if "customer_id" in changes or "customer_name" in changes or "customer_phone" in changes:
        customer_id = changes.get("customer_id", job.customer_id)
        customer_id = customer_id if isinstance(customer_id, UUID) else None
        name, phone = _customer_snapshot(
            session, job.company_id, customer_id, _text(changes.get("customer_name")) if "customer_name" in changes
            else (None if "customer_id" in changes else job.customer_name),
            _text(changes.get("customer_phone")) if "customer_phone" in changes
            else (None if "customer_id" in changes else job.customer_phone))
        if customer_id is None and name is None:
            raise ValidationFailed("Say who the customer is")
        job.customer_id, job.customer_name, job.customer_phone = customer_id, name, phone
    if "asset_id" in changes:
        asset_id = changes["asset_id"] if isinstance(changes["asset_id"], UUID) else None
        if asset_id is not None and assets.load_asset(session, asset_id).company_id != job.company_id:
            raise ValidationFailed("The item was not found in this company")
        job.asset_id = asset_id
    if "assignee_id" in changes:
        person = changes["assignee_id"] if isinstance(changes["assignee_id"], UUID) else None
        check_person(session, person)
        if person != job.assignee_id:
            job.assignee_id = person
            add_event(session, job, "assigned", None)
    if "promised_at" in changes:
        job.promised_at = changes["promised_at"] if isinstance(changes["promised_at"], date) else None
    for key, limit in (("fuel_level", 40), ("key_tag", 40), ("belongings", 1000)):
        if key in changes:
            setattr(job, key, clean(str(changes[key] or ""), limit))
    for key in ("odometer_in", "odometer_out"):
        if key in changes:
            given = changes[key]
            setattr(job, key, _reading(given if isinstance(given, Decimal) else None, "The odometer"))
    if "acknowledged_by_name" in changes:
        who = clean(str(changes["acknowledged_by_name"] or ""), 160)
        job.acknowledged_by_name, job.acknowledged_at = who, (datetime.now(UTC) if who else None)
    if "job_type_code" in changes:
        code = str(changes["job_type_code"] or "").strip().lower()
        if code and repo.job_type_by_code(session, job.company_id, code) is None:
            raise ValidationFailed("That job type does not exist. Choose one from the list")
        job.job_type_code = code or None
    job.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "jobs.job", job.id, {k: str(v) for k, v in changes.items()})
    return job


def _text(value: object) -> str | None:
    return str(value) if value is not None else None


def _set_warranty(session: Session, job: Job, days: int) -> None:
    if days < 0 or days > 3650:
        raise ValidationFailed("The warranty is between 0 and 3650 days")
    job.warranty_days = days
    if job.collected_at is not None:
        job.warranty_ends = pricing.warranty_end(job.collected_at.date(), days)
    add_event(session, job, "warranty", f"Warranty set to {days} days")
    session.flush()


def add_note(session: Session, job_id: UUID, text_: str) -> Job:
    """Write a note on the timeline. Allowed on any job, even a locked one. Needs 'jobs.manage'."""
    job = load_job(session, job_id)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    note = clean(text_, 1000)
    if note is None:
        raise ValidationFailed("Write something first")
    add_event(session, job, "note", note)
    return job


def change_status(session: Session, job_id: UUID, to_status_id: UUID, note: str | None = None, *,
                  collected_by_name: str | None = None, acknowledge_unpaid: bool = False,
                  odometer_out: Decimal | None = None) -> Job:
    """Move a job to another stage the workflow allows from where it is. Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    target = repo.get(session, JobStatus, to_status_id)
    if target is None or target.company_id != job.company_id or not target.is_active:
        raise ValidationFailed("Stage not found in this company")
    current = status_of(session, job)
    if target.id == current.id:
        raise ValidationFailed(f"The job is already {current.name}")
    if repo.move_pair(session, current.id, target.id) is None:
        raise ValidationFailed(f"A job cannot go from {current.name} to {target.name}")
    photos.guard(session, job, target.role)
    if target.role == "collected":
        release.guard(session, job, acknowledged=acknowledge_unpaid)
        job.odometer_out = _reading(odometer_out, "The odometer") if odometer_out is not None else job.odometer_out
    _apply_status(session, job, current, target, note, collected_by_name)
    return job


def _apply_status(session: Session, job: Job, current: JobStatus, target: JobStatus, note: str | None,
                  collected_by_name: str | None) -> None:
    now = datetime.now(UTC)
    job.status_id, job.status_changed_at, job.updated_by = target.id, now, current_context().user_id
    if target.role == "ready":
        job.ready_at = now
    elif target.role != "collected":
        job.ready_at = None
    if target.role == "collected":
        if job.odometer_out is not None and job.asset_id is not None:
            found = repo.get(session, Asset, job.asset_id)
            if found is not None:
                assets.record_odometer(session, found, job.odometer_out)
        job.collected_at = now
        job.collected_by_name = clean(collected_by_name, 160)
        job.warranty_ends = pricing.warranty_end(company_today(session, job.company_id), job.warranty_days)
    job.closed_at = now if target.kind == "closed" else None
    session.flush()
    add_event(session, job, "status", note, from_status=current.id, to_status=target.id)
    if target.role == "collected":
        add_event(session, job, "collected", collected_by_name)
        publish(session, Event("job.collected", "jobs.job", job.id, {
            "company_id": job.company_id, "branch_id": job.branch_id, "number": job.number,
            "warranty_ends": job.warranty_ends}))
    publish(session, Event("job.status_changed", "jobs.job", job.id, {
        "company_id": job.company_id, "branch_id": job.branch_id, "number": job.number,
        "from_status": current.code, "to_status": target.code, "to_role": target.role}))
    audit_record(session, "status", "jobs.job", job.id, {"from": current.code, "to": target.code})
    if target.role == "ready":
        notify.tell_customer_ready(session, job)


def move_to_role(session: Session, job: Job, role: str, note: str | None = None) -> bool:
    """Move a job to the stage that holds a role, when the workflow allows it from the current stage (an approved
    estimate moves it to 'approved'). Returns False, changing nothing, when there is no such stage or no such move."""
    target = repo.status_by_role(session, job.company_id, role)
    current = status_of(session, job)
    if target is None or target.id == current.id or repo.move_pair(session, current.id, target.id) is None:
        return False
    photos.guard(session, job, target.role, may_block=False)
    _apply_status(session, job, current, target, note, None)
    return True


def move_to_code(session: Session, job: Job, code: str, note: str | None = None) -> bool:
    """Move a job to the stage with this code when the company has it and the workflow allows the move from where
    the job is (the system moving a job along after a claim event). False, changing nothing, otherwise."""
    target = repo.status_by_code(session, job.company_id, code)
    current = status_of(session, job)
    if target is None or not target.is_active or target.id == current.id \
            or repo.move_pair(session, current.id, target.id) is None:
        return False
    _apply_status(session, job, current, target, note, None)
    return True


def collect_job(session: Session, job_id: UUID, *, collected_by_name: str | None = None,
                note: str | None = None, acknowledge_unpaid: bool = False,
                odometer_out: Decimal | None = None) -> Job:
    """The customer collects the item: move to the 'collected' stage and start the warranty. Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    target = repo.status_by_role(session, job.company_id, "collected")
    if target is None:
        raise ValidationFailed("No stage is marked as 'collected'. Choose one in the job settings")
    current = status_of(session, job)
    if current.id == target.id:
        raise Conflict("The item was already collected")
    if repo.move_pair(session, current.id, target.id) is None:
        raise ValidationFailed(f"A job cannot be collected from {current.name}")
    photos.guard(session, job, "collected")
    release.guard(session, job, acknowledged=acknowledge_unpaid)
    if odometer_out is not None:
        job.odometer_out = _reading(odometer_out, "The odometer")
    _apply_status(session, job, current, target, note, collected_by_name)
    return job


def create_return_visit(session: Session, job_id: UUID, *, title: str | None = None,
                        description: str | None = None) -> Job:
    """A new job for the same customer and item as a collected one, flagged as a return visit (warranty rework) and
    pointing at the original. Allowed on an invoiced job. Needs 'jobs.manage'."""
    original = load_job(session, job_id)
    current_context().require(JOBS_MANAGE, company_id=original.company_id, branch_id=original.branch_id)
    if original.collected_at is None:
        raise ValidationFailed("A return visit starts from a job the customer has already collected")
    day = company_today(session, original.company_id)
    visit = receive_job(
        session, company_id=original.company_id, branch_id=original.branch_id,
        title=clean(title, 200) or f"Return visit: {original.title}"[:200], customer_id=original.customer_id,
        customer_name=original.customer_name, customer_phone=original.customer_phone, asset_id=original.asset_id,
        description=description)
    visit.is_rework, visit.rework_of_id = True, original.id
    visit.rework_in_warranty = pricing.in_warranty(original.warranty_ends, day)
    session.flush()
    add_event(session, visit, "rework", f"Return visit for {original.number}"
              + (" (inside the warranty)" if visit.rework_in_warranty else " (warranty over)"))
    add_event(session, original, "rework", f"Return visit {visit.number}")
    return visit


# --------------------------------------------------------------------------- checklist and tasks
def set_checklist_item(session: Session, job_id: UUID, item_id: UUID, *, state: str | None = None,
                       note: str | None = None, label: str | None = None) -> JobChecklistItem:
    """Tick off a checklist line (ok, issue, not applicable, pending) with a note. Needs 'jobs.manage'."""
    job = load_job(session, job_id)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    item = repo.get(session, JobChecklistItem, item_id)
    if item is None or item.job_id != job.id:
        raise NotFound("Checklist line not found")
    if state is not None:
        if state not in ("pending", "ok", "issue", "na"):
            raise ValidationFailed("A checklist line is pending, ok, an issue or not applicable")
        item.state = state
    if note is not None:
        item.note = clean(note, 500)
    if label is not None and label.strip():
        item.label = label.strip()[:120]
    session.flush()
    return item


def add_checklist_item(session: Session, job_id: UUID, label: str) -> JobChecklistItem:
    job = load_job(session, job_id)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    existing = repo.checklist(session, job.id)
    if not label.strip():
        raise ValidationFailed("Write the checklist line")
    if len(existing) >= MAX_CHECKLIST:
        raise ValidationFailed(f"At most {MAX_CHECKLIST} checklist lines")
    item = JobChecklistItem(tenant_id=current_context().tenant_id, job_id=job.id, position=len(existing) + 1,
                            label=label.strip()[:120])
    repo.add(session, item)
    return item


def add_task(session: Session, job_id: UUID, *, title: str, assignee_id: UUID | None = None,
             due_date: date | None = None) -> JobTask:
    """A piece of work on the job with a person and a date. Needs 'jobs.manage'."""
    job = load_job(session, job_id)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    if not title.strip():
        raise ValidationFailed("A task needs a title")
    check_person(session, assignee_id)
    existing = repo.tasks(session, job.id)
    if len(existing) >= MAX_TASKS:
        raise ValidationFailed(f"At most {MAX_TASKS} tasks on a job")
    task = JobTask(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, title=title.strip()[:200],
                   assignee_id=assignee_id, due_date=due_date, position=len(existing) + 1)
    repo.add(session, task)
    return task


def update_task(session: Session, job_id: UUID, task_id: UUID, **changes: object) -> JobTask:
    """Change a task or mark it done (`done` true or false). Needs 'jobs.manage'."""
    job = load_job(session, job_id)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    task = repo.get(session, JobTask, task_id)
    if task is None or task.job_id != job.id:
        raise NotFound("Task not found")
    if "title" in changes and str(changes["title"] or "").strip():
        task.title = str(changes["title"]).strip()[:200]
    if "assignee_id" in changes:
        person = changes["assignee_id"] if isinstance(changes["assignee_id"], UUID) else None
        check_person(session, person)
        task.assignee_id = person
    if "due_date" in changes:
        task.due_date = changes["due_date"] if isinstance(changes["due_date"], date) else None
    if "done" in changes:
        if changes["done"] and task.done_at is None:
            task.done_at, task.done_by = datetime.now(UTC), ctx.user_id
        elif not changes["done"]:
            task.done_at, task.done_by = None, None
    task.updated_by = ctx.user_id
    session.flush()
    return task


def delete_task(session: Session, job_id: UUID, task_id: UUID) -> None:
    job = load_job(session, job_id)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    task = repo.get(session, JobTask, task_id)
    if task is None or task.job_id != job.id:
        raise NotFound("Task not found")
    session.delete(task)
    session.flush()
