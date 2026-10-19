"""Use cases: recurring engagements and their dated work, engagement templates, activity lists and standard wording.

    recurrence   "monthly bookkeeping for Acme, due the 15th, with this checklist"
    task         one dated piece of work (made from a recurrence by the recurring task, or added by hand) with a
                 checklist that people tick off; open -> done | skipped
    template     a starting point for a new engagement (fee type, budget, recurrence, checklist, milestones)
    activity     the names people choose for what they did ("Bookkeeping", "Review call"), so time is comparable
    snippet      standard wording for an invoice note

Nothing here bills: fees are billed by the invoice reviews; the recurring task only prepares the dated work.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ziira.modules.timebilling.domain import engagement as rules
from ziira.modules.timebilling.permissions import PROJECTS_MANAGE
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import (
    Activity,
    EngagementTask,
    EngagementTemplate,
    Project,
    Recurrence,
    Snippet,
)
from ziira.modules.timebilling.services import access, common
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)

MAX_ITEMS = 40
MAX_ITEM = 200


def clean_items(raw: list[Any] | None) -> list[str]:
    """A checklist as plain lines: trimmed, no blanks, no repeats in a row, at most 40 of 200 characters."""
    out: list[str] = []
    for item in raw or []:
        label = str(item).strip()[:MAX_ITEM]
        if label and (not out or out[-1] != label):
            out.append(label)
    if len(out) > MAX_ITEMS:
        raise ValidationFailed(f"A checklist has at most {MAX_ITEMS} items")
    return out


def _items(labels: list[str]) -> list[dict[str, Any]]:
    return [{"label": x, "done": False, "by": None, "at": None} for x in labels]


# --------------------------------------------------------------------------- recurrences
def _project_to_manage(session: Session, project_id: UUID) -> Project:
    project = repo.get(session, Project, project_id)
    if project is None or not access.can_see_company(project.company_id):
        raise NotFound("Project not found")
    current_context().require(PROJECTS_MANAGE, company_id=project.company_id, branch_id=project.branch_id)
    return project


def _check_person(session: Session, user_id: UUID | None) -> None:
    if user_id is not None and common.user_names(session, {user_id}).get(user_id) is None:
        raise ValidationFailed("Person not found")


def create_recurrence(session: Session, project_id: UUID, *, name: str, frequency: str, due_day: int,
                      due_month: int | None = None, lead_days: int = 14, starts_on: date | None = None,
                      ends_on: date | None = None, assignee_id: UUID | None = None,
                      checklist: list[str] | None = None) -> Recurrence:
    """Make an engagement come back every month, quarter or year, with a due date and a checklist. Needs
    'projects.manage'. The recurring task then prepares each occurrence ahead of its due date."""
    project = _project_to_manage(session, project_id)
    if frequency not in rules.FREQUENCIES:
        raise ValidationFailed(f"Repeats are one of: {', '.join(rules.FREQUENCIES)}")
    if not name.strip():
        raise ValidationFailed("Give the work a name")
    if frequency != "monthly" and due_month is None:
        raise ValidationFailed("Say in which month it falls due")
    start = starts_on or common.today(session, project.company_id)
    if ends_on is not None and ends_on < start:
        raise ValidationFailed("It cannot end before it starts")
    _check_person(session, assignee_id)
    ctx = current_context()
    row = Recurrence(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=project.company_id,
                     project_id=project.id, name=name.strip()[:200], frequency=frequency, due_day=due_day,
                     due_month=due_month, lead_days=lead_days, starts_on=start, ends_on=ends_on,
                     assignee_id=assignee_id or project.manager_id, checklist=clean_items(checklist))
    repo.add(session, row)
    audit_record(session, "create", "timebilling.recurrence", row.id, {"project": project.code, "name": row.name})
    generate(session, project.company_id, common.today(session, project.company_id), only=row.id)
    return row


def update_recurrence(session: Session, recurrence_id: UUID, **changes: Any) -> Recurrence:
    """Change a recurrence (name, due date, checklist for future occurrences, who, pause with active=false)."""
    row = repo.get(session, Recurrence, recurrence_id, lock=True)
    if row is None:
        raise NotFound("Repeating work not found")
    _project_to_manage(session, row.project_id)
    if "checklist" in changes and changes["checklist"] is not None:
        changes["checklist"] = clean_items(changes["checklist"])
    if changes.get("frequency") is not None and changes["frequency"] not in rules.FREQUENCIES:
        raise ValidationFailed(f"Repeats are one of: {', '.join(rules.FREQUENCIES)}")
    if changes.get("assignee_id") is not None:
        _check_person(session, changes["assignee_id"])
    for key in ("name", "frequency", "due_day", "due_month", "lead_days", "ends_on", "assignee_id", "checklist",
                "active"):
        if key in changes and (changes[key] is not None or key in ("ends_on", "assignee_id", "due_month")):
            setattr(row, key, changes[key])
    if row.ends_on is not None and row.ends_on < row.starts_on:
        raise ValidationFailed("It cannot end before it starts")
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "timebilling.recurrence", row.id, {k: str(v)[:80] for k, v in changes.items()})
    return row


def list_recurrences(session: Session, *, company_id: UUID | None = None,
                     project_id: UUID | None = None) -> list[Recurrence]:
    q = select(Recurrence).where(repo.in_scope(access.scopes_for(*_all()), Recurrence.company_id, None))
    if company_id:
        q = q.where(Recurrence.company_id == company_id)
    if project_id:
        q = q.where(Recurrence.project_id == project_id)
    return list(session.scalars(q.order_by(Recurrence.active.desc(), Recurrence.name)))


def _all() -> tuple[str, ...]:
    from ziira.modules.timebilling.permissions import ALL

    return ALL


def generate(session: Session, company_id: UUID, today: date, *, only: UUID | None = None) -> int:
    """Make the dated tasks that are due to appear: every occurrence whose due date is within its lead time (and not
    before the recurrence started). Idempotent: an occurrence is made once, whoever asks. Returns how many were made."""
    q = select(Recurrence).where(Recurrence.company_id == company_id, Recurrence.active.is_(True))
    if only:
        q = q.where(Recurrence.id == only)
    made = 0
    for r in session.scalars(q):
        project = session.get(Project, r.project_id)
        if project is None or project.status in ("completed", "archived"):
            continue
        horizon = today + timedelta(days=r.lead_days)
        for period, due in rules.due_dates(r.frequency, r.due_day, r.due_month, r.starts_on, r.ends_on,
                                           max(r.starts_on, today - timedelta(days=60)), horizon):
            exists = session.scalar(select(EngagementTask.id).where(
                EngagementTask.recurrence_id == r.id, EngagementTask.period == period))
            if exists is not None:
                continue
            session.add(EngagementTask(
                tenant_id=r.tenant_id, company_id=company_id, project_id=r.project_id, recurrence_id=r.id,
                name=r.name, period=period, due_on=due, assignee_id=r.assignee_id or project.manager_id,
                items=_items(list(r.checklist or []))))
            made += 1
    session.flush()
    return made


# --------------------------------------------------------------------------- dated tasks
def add_task(session: Session, project_id: UUID, *, name: str, due_on: date, assignee_id: UUID | None = None,
             checklist: list[str] | None = None, note: str | None = None) -> EngagementTask:
    """Add one dated piece of work to an engagement by hand (a filing deadline, a hearing). Needs 'projects.manage'."""
    project = _project_to_manage(session, project_id)
    if not name.strip():
        raise ValidationFailed("Give the work a name")
    _check_person(session, assignee_id)
    ctx = current_context()
    row = EngagementTask(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=project.company_id,
                         project_id=project.id, name=name.strip()[:200], due_on=due_on,
                         assignee_id=assignee_id or project.manager_id, items=_items(clean_items(checklist)),
                         note=(note or "").strip()[:1000] or None)
    repo.add(session, row)
    audit_record(session, "create", "timebilling.task", row.id, {"project": project.code, "due": due_on})
    return row


def _task_for_work(session: Session, task_id: UUID, *, lock: bool = False) -> EngagementTask:
    row = repo.get(session, EngagementTask, task_id, lock=lock)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Work not found")
    return row


def get_task(session: Session, task_id: UUID) -> EngagementTask:
    return _task_for_work(session, task_id)


def update_task(session: Session, task_id: UUID, **changes: Any) -> EngagementTask:
    """Move a due date, change who does it, its note or its checklist (while it is open). Needs 'projects.manage'."""
    row = _task_for_work(session, task_id, lock=True)
    project = repo.get(session, Project, row.project_id)
    current_context().require(PROJECTS_MANAGE, company_id=row.company_id,
                              branch_id=project.branch_id if project else None)
    if row.status != "open":
        raise Conflict(f"This work is {row.status}")
    if changes.get("assignee_id") is not None:
        _check_person(session, changes["assignee_id"])
    for key in ("name", "due_on", "assignee_id", "note"):
        if key in changes and (changes[key] is not None or key in ("assignee_id", "note")):
            setattr(row, key, changes[key])
    if changes.get("checklist") is not None:
        done = {i["label"]: i for i in row.items}
        row.items = [done.get(x) or {"label": x, "done": False, "by": None, "at": None}
                     for x in clean_items(changes["checklist"])]
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "timebilling.task", row.id, {k: str(v)[:80] for k, v in changes.items()})
    return row


def tick(session: Session, task_id: UUID, index: int, done: bool) -> EngagementTask:
    """Tick an item of the checklist (or untick it). Anyone who works on the engagement may; who and when are kept."""
    row = _task_for_work(session, task_id, lock=True)
    if row.status != "open":
        raise Conflict(f"This work is {row.status}")
    if not 0 <= index < len(row.items):
        raise ValidationFailed("There is no such item on the checklist")
    items = [dict(i) for i in row.items]
    me = access.user_id()
    items[index].update({"done": done, "by": str(me) if done else None,
                         "at": datetime.now(UTC).isoformat() if done else None})
    row.items = items
    row.updated_by = me
    session.flush()
    audit_record(session, "tick", "timebilling.task", row.id, {"item": items[index]["label"], "done": done})
    return row


def finish_task(session: Session, task_id: UUID, *, skipped: bool = False, note: str | None = None) -> EngagementTask:
    """Mark the work done (every checklist item must be ticked) or skipped for this period (a note says why)."""
    row = _task_for_work(session, task_id, lock=True)
    if row.status != "open":
        raise Conflict(f"This work is already {row.status}")
    if skipped and not (note or "").strip():
        raise ValidationFailed("Say why it is skipped")
    if not skipped and any(not i.get("done") for i in row.items):
        raise ValidationFailed("Tick every item on the checklist first")
    row.status = "skipped" if skipped else "done"
    row.done_at, row.done_by = datetime.now(UTC), access.user_id()
    if note and note.strip():
        row.note = note.strip()[:1000]
    row.updated_by = row.done_by
    session.flush()
    audit_record(session, "finish", "timebilling.task", row.id, {"status": row.status})
    return row


def reopen_task(session: Session, task_id: UUID) -> EngagementTask:
    row = _task_for_work(session, task_id, lock=True)
    project = repo.get(session, Project, row.project_id)
    current_context().require(PROJECTS_MANAGE, company_id=row.company_id,
                              branch_id=project.branch_id if project else None)
    if row.status == "open":
        return row
    row.status, row.done_at, row.done_by = "open", None, None
    session.flush()
    audit_record(session, "reopen", "timebilling.task", row.id)
    return row


def list_tasks(session: Session, *, company_id: UUID | None = None, project_id: UUID | None = None,
               status: str | None = None, assignee_id: UUID | None = None, due_before: date | None = None,
               limit: int = 200, offset: int = 0) -> list[EngagementTask]:
    q = select(EngagementTask).where(repo.in_scope(access.scopes_for(*_all()), EngagementTask.company_id, None))
    if company_id:
        q = q.where(EngagementTask.company_id == company_id)
    if project_id:
        q = q.where(EngagementTask.project_id == project_id)
    if status:
        q = q.where(EngagementTask.status == status)
    if assignee_id:
        q = q.where(EngagementTask.assignee_id == assignee_id)
    if due_before:
        q = q.where(EngagementTask.due_on <= due_before)
    return list(session.scalars(q.order_by(EngagementTask.due_on, EngagementTask.name)
                                .limit(min(limit, 500)).offset(offset)))


# --------------------------------------------------------------------------- templates
def _template_milestones(raw: list[Any] | None) -> list[dict[str, Any]]:
    out = []
    for m in raw or []:
        name = str(m.get("name", "")).strip()
        if not name:
            continue
        out.append({"name": name[:200], "percent": str(m.get("percent", "0"))})
    return out


def save_template(session: Session, company_id: UUID, *, template_id: UUID | None = None, name: str,
                  description: str | None = None, billing_mode: str = "time_and_materials",
                  budget_minutes: int | None = None, frequency: str | None = None, due_day: int | None = None,
                  due_month: int | None = None, lead_days: int = 14, checklist: list[str] | None = None,
                  milestones: list[dict[str, Any]] | None = None, active: bool = True) -> EngagementTemplate:
    """Create or change an engagement template. Needs 'projects.manage'."""
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    if billing_mode not in ("time_and_materials", "fixed_fee", "capped_fee", "retainer"):
        raise ValidationFailed("That is not a kind of fee")
    if frequency is not None and frequency not in rules.FREQUENCIES:
        raise ValidationFailed(f"Repeats are one of: {', '.join(rules.FREQUENCIES)}")
    if not name.strip():
        raise ValidationFailed("Give the template a name")
    row = repo.get(session, EngagementTemplate, template_id, lock=True) if template_id else None
    if template_id and (row is None or row.company_id != company_id):
        raise NotFound("Template not found")
    if row is None:
        taken = session.scalar(select(EngagementTemplate.id).where(
            EngagementTemplate.company_id == company_id, EngagementTemplate.name == name.strip()))
        if taken is not None:
            raise Conflict("There is already a template with that name")
        row = EngagementTemplate(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                 name=name.strip())
        session.add(row)
    row.name, row.description = name.strip()[:120], (description or "").strip()[:500] or None
    row.billing_mode, row.budget_minutes, row.frequency = billing_mode, budget_minutes, frequency
    row.due_day, row.due_month, row.lead_days = due_day, due_month, lead_days
    row.checklist, row.milestones, row.active = clean_items(checklist), _template_milestones(milestones), active
    row.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "save", "timebilling.template", row.id, {"name": row.name})
    return row


def list_templates(session: Session, company_id: UUID, *, include_inactive: bool = False) -> list[EngagementTemplate]:
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    q = select(EngagementTemplate).where(EngagementTemplate.company_id == company_id)
    if not include_inactive:
        q = q.where(EngagementTemplate.active.is_(True))
    return list(session.scalars(q.order_by(EngagementTemplate.name)))


def delete_template(session: Session, template_id: UUID) -> None:
    row = repo.get(session, EngagementTemplate, template_id, lock=True)
    if row is None:
        raise NotFound("Template not found")
    current_context().require(PROJECTS_MANAGE, company_id=row.company_id)
    session.delete(row)
    session.flush()
    audit_record(session, "delete", "timebilling.template", template_id, {"name": row.name})


# --------------------------------------------------------------------------- activities
def save_activity(session: Session, company_id: UUID, *, activity_id: UUID | None = None, name: str,
                  group_name: str | None = None, billable: bool = True, sort_order: int = 0,
                  active: bool = True) -> Activity:
    """Create or change an activity (a name people pick for what they did). Needs 'projects.manage'."""
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    if not name.strip():
        raise ValidationFailed("Give the activity a name")
    row = repo.get(session, Activity, activity_id, lock=True) if activity_id else None
    if activity_id and (row is None or row.company_id != company_id):
        raise NotFound("Activity not found")
    if row is None:
        taken = session.scalar(select(Activity.id).where(Activity.company_id == company_id,
                                                         Activity.name == name.strip()))
        if taken is not None:
            raise Conflict("There is already an activity with that name")
        row = Activity(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, name=name.strip())
        session.add(row)
    row.name, row.group_name = name.strip()[:120], (group_name or "").strip()[:80] or None
    row.billable, row.sort_order, row.active = billable, sort_order, active
    row.updated_by = ctx.user_id
    session.flush()
    return row


def list_activities(session: Session, company_id: UUID, *, include_inactive: bool = False) -> list[Activity]:
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    q = select(Activity).where(Activity.company_id == company_id)
    if not include_inactive:
        q = q.where(Activity.active.is_(True))
    return list(session.scalars(q.order_by(Activity.group_name.nulls_last(), Activity.sort_order, Activity.name)))


def delete_activity(session: Session, activity_id: UUID) -> None:
    row = repo.get(session, Activity, activity_id, lock=True)
    if row is None:
        raise NotFound("Activity not found")
    current_context().require(PROJECTS_MANAGE, company_id=row.company_id)
    session.delete(row)
    session.flush()


# --------------------------------------------------------------------------- standard wording
def save_snippet(session: Session, company_id: UUID, *, snippet_id: UUID | None = None, kind: str, name: str,
                 language: str = "en", body: str, active: bool = True) -> Snippet:
    """Create or change a piece of standard wording (an invoice note). Needs 'projects.manage'."""
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    if kind not in ("invoice_note", "engagement_note"):
        raise ValidationFailed("Wording is for an invoice note or an engagement note")
    if not name.strip() or not body.strip():
        raise ValidationFailed("Give the wording a name and a text")
    row = repo.get(session, Snippet, snippet_id, lock=True) if snippet_id else None
    if snippet_id and (row is None or row.company_id != company_id):
        raise NotFound("Wording not found")
    if row is None:
        row = Snippet(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, kind=kind,
                      name=name.strip(), language=language, body=body.strip())
        session.add(row)
    row.name, row.language, row.body = name.strip()[:120], language[:8], body.strip()[:500]
    row.active = active
    row.updated_by = ctx.user_id
    session.flush()
    return row


def list_snippets(session: Session, company_id: UUID, *, kind: str | None = None) -> list[Snippet]:
    check_company(session, company_id)
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    q = select(Snippet).where(Snippet.company_id == company_id, Snippet.active.is_(True))
    if kind:
        q = q.where(Snippet.kind == kind)
    return list(session.scalars(q.order_by(Snippet.kind, Snippet.name, Snippet.language)))


def delete_snippet(session: Session, snippet_id: UUID) -> None:
    row = repo.get(session, Snippet, snippet_id, lock=True)
    if row is None:
        raise NotFound("Wording not found")
    current_context().require(PROJECTS_MANAGE, company_id=row.company_id)
    session.delete(row)
    session.flush()
