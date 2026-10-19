"""Use cases: logging time (one entry, a day, or a week grid) and reading it back.

Time is a person's own: they log it, edit it while the week is open, and submit the week (weeks.py). Managers with
'time.view' can read everyone's. An entry's minutes are a multiple of the company's minute step.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from ziira.modules.timebilling.domain.timesheet import MINUTES_PER_DAY
from ziira.modules.timebilling.permissions import TIME_LOG, TIME_VIEW
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry
from ziira.modules.timebilling.services import access, common, weeks
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, current_context

MAX_NOTE = 1000


def check_minutes(minutes: int, step: int) -> None:
    if minutes <= 0 or minutes > MINUTES_PER_DAY:
        raise ValidationFailed("Time is between 1 minute and 24 hours a day")
    if step > 1 and minutes % step:
        raise ValidationFailed(f"Time is entered in steps of {step} minutes")


def _day_total(session: Session, user_id: UUID, day: date, *, except_id: UUID | None = None) -> int:
    q = select(func.coalesce(func.sum(Entry.minutes), 0)).where(Entry.user_id == user_id, Entry.work_date == day)
    if except_id:
        q = q.where(Entry.id != except_id)
    return int(session.scalar(q) or 0)


def _check_day(session: Session, user_id: UUID, day: date, minutes: int, *, except_id: UUID | None = None) -> None:
    if _day_total(session, user_id, day, except_id=except_id) + minutes > MINUTES_PER_DAY:
        raise ValidationFailed("That is more than 24 hours on one day")


def create_entry(session: Session, *, project_id: UUID, work_date: date, minutes: int, task: str | None = None,
                 note: str | None = None, billable: bool = True, service_product_id: UUID | None = None,
                 source: str = "manual", started_at: Any = None, ended_at: Any = None,
                 user_id: UUID | None = None) -> Entry:
    """Log time for the signed-in person. Needs 'time.log'. The project must be active, the week still open, and the
    date not in the future."""
    ctx = current_context()
    me = access.user_id()
    if user_id is not None and user_id != me:
        raise ValidationFailed("You can only log your own time")
    project = common.usable_project(session, project_id)
    ctx.require(TIME_LOG, company_id=project.company_id, branch_id=project.branch_id)
    setting = common.settings(session, project.company_id)
    check_minutes(minutes, setting.minute_step if source != "timer" else 1)
    if work_date > common.today(session, project.company_id):
        raise ValidationFailed("Time cannot be logged for a day that has not happened yet")
    weeks.ensure_open(session, project.company_id, me, work_date, setting.week_starts_on)
    _check_day(session, me, work_date, minutes)
    entry = Entry(
        tenant_id=ctx.tenant_id, created_by=me, company_id=project.company_id, branch_id=project.branch_id,
        user_id=me, project_id=project.id, task=(task or "").strip()[:120] or None, work_date=work_date,
        minutes=minutes, billable=billable, note=(note or "").strip()[:MAX_NOTE] or None,
        service_product_id=service_product_id, source=source, started_at=started_at, ended_at=ended_at)
    repo.add(session, entry)
    audit_record(session, "create", "timebilling.entry", entry.id,
                 {"project": project.code, "date": work_date, "minutes": minutes})
    return entry


def get_entry(session: Session, entry_id: UUID, *, lock: bool = False) -> Entry:
    entry = repo.get(session, Entry, entry_id, lock=lock)
    if entry is None or not can_view_entry(entry):
        raise NotFound("Time entry not found")
    return entry


def can_view_entry(entry: Entry) -> bool:
    ctx = current_context()
    return entry.user_id == ctx.user_id or ctx.can(TIME_VIEW, company_id=entry.company_id, branch_id=entry.branch_id)


def _own_open(session: Session, entry_id: UUID) -> Entry:
    entry = get_entry(session, entry_id, lock=True)
    if entry.user_id != access.user_id():
        raise ValidationFailed("You can only change your own time")
    if entry.status != "draft" or entry.invoice_id is not None:
        raise Conflict("This time has been submitted: ask for the week to be sent back first")
    return entry


def update_entry(session: Session, entry_id: UUID, **changes: Any) -> Entry:
    """Change an entry of your own while its week is open."""
    entry = _own_open(session, entry_id)
    setting = common.settings(session, entry.company_id)
    if "project_id" in changes and changes["project_id"] not in (None, entry.project_id):
        project = common.usable_project(session, changes["project_id"], entry.company_id)
        entry.project_id, entry.branch_id = project.id, project.branch_id
    new_date = changes.get("work_date") or entry.work_date
    if new_date != entry.work_date:
        if new_date > common.today(session, entry.company_id):
            raise ValidationFailed("Time cannot be logged for a day that has not happened yet")
        weeks.ensure_open(session, entry.company_id, entry.user_id, new_date, setting.week_starts_on)
    minutes = changes.get("minutes") or entry.minutes
    if minutes != entry.minutes:
        check_minutes(minutes, setting.minute_step if entry.source != "timer" else 1)
    _check_day(session, entry.user_id, new_date, minutes, except_id=entry.id)
    entry.work_date, entry.minutes = new_date, minutes
    for key in ("task", "note", "billable", "service_product_id"):
        if key in changes:
            value = changes[key]
            setattr(entry, key, (str(value).strip()[:MAX_NOTE] or None) if isinstance(value, str) else value)
    entry.updated_by = entry.user_id
    session.flush()
    audit_record(session, "update", "timebilling.entry", entry.id, {k: str(v) for k, v in changes.items()})
    return entry


def delete_entry(session: Session, entry_id: UUID) -> None:
    entry = _own_open(session, entry_id)
    session.delete(entry)
    session.flush()
    audit_record(session, "delete", "timebilling.entry", entry_id,
                 {"date": entry.work_date, "minutes": entry.minutes})


@dataclass(frozen=True)
class GridCell:
    project_id: UUID
    work_date: date
    minutes: int                       # 0 clears the cell
    task: str | None = None
    billable: bool = True


def save_grid(session: Session, cells: list[GridCell]) -> list[Entry]:
    """Set many cells of a week grid at once. A cell is the time for (project, task, billable, day): the first time
    it is saved it makes an entry, later saves change that entry, and 0 removes it. Safe to send twice."""
    me = access.user_id()
    saved: list[Entry] = []
    for cell in cells:
        task = (cell.task or "").strip()[:120] or None
        existing = session.scalars(select(Entry).where(
            Entry.user_id == me, Entry.project_id == cell.project_id, Entry.work_date == cell.work_date,
            Entry.billable == cell.billable, Entry.source == "grid",
            Entry.task.is_(None) if task is None else Entry.task == task).with_for_update()).first()
        if existing is None and cell.minutes > 0:
            saved.append(create_entry(session, project_id=cell.project_id, work_date=cell.work_date,
                                      minutes=cell.minutes, task=task, billable=cell.billable, source="grid"))
        elif existing is not None and cell.minutes == 0:
            delete_entry(session, existing.id)
        elif existing is not None and existing.minutes != cell.minutes:
            saved.append(update_entry(session, existing.id, minutes=cell.minutes))
    return saved


def list_entries(session: Session, *, user_id: UUID | None = None, project_id: UUID | None = None,
                 client_id: UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                 status: str | None = None, billable: bool | None = None, limit: int = 100,
                 offset: int = 0) -> list[Entry]:
    """Your own entries, plus everyone's where you hold 'time.view'."""
    me = access.user_id()
    scopes = access.scopes_for(TIME_VIEW)
    q = select(Entry).where(or_(Entry.user_id == me, repo.in_scope(scopes, Entry.company_id, Entry.branch_id)))
    if user_id:
        q = q.where(Entry.user_id == user_id)
    if project_id:
        q = q.where(Entry.project_id == project_id)
    if client_id:
        from ziira.modules.timebilling.repository.models import Project

        q = q.where(Entry.project_id.in_(select(Project.id).where(Project.client_id == client_id)))
    if date_from:
        q = q.where(Entry.work_date >= date_from)
    if date_to:
        q = q.where(Entry.work_date <= date_to)
    if status:
        q = q.where(Entry.status == status)
    if billable is not None:
        q = q.where(Entry.billable == billable)
    return list(session.scalars(q.order_by(Entry.work_date.desc(), Entry.created_at.desc())
                                .limit(min(limit, 500)).offset(offset)))

