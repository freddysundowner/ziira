"""Use cases: projects and their milestones.

    project: active <-> on_hold -> completed -> archived        (time can be logged only while active)
    billing modes: time_and_materials (hours at the rate card), fixed_fee (milestones), capped_fee (hours at the rate
    card, never more than the cap), retainer (prepaid hours or a monthly fee: see retainers.py)
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from ziira.modules.timebilling.permissions import PROJECTS_MANAGE
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry, Milestone, Project
from ziira.modules.timebilling.services import access, common
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, check_company, current_context

STATUSES = ("active", "on_hold", "completed", "archived")
MODES = ("time_and_materials", "fixed_fee", "capped_fee", "retainer")


def _check_client(session: Session, company_id: UUID, client_id: UUID) -> None:
    from ziira.modules.crm.public import find_customer

    customer = find_customer(session, client_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("Client not found in this company: add them as a customer first")


def _check_manager(session: Session, manager_id: UUID | None) -> None:
    if manager_id is not None and common.user_names(session, {manager_id}).get(manager_id) is None:
        raise ValidationFailed("The project manager was not found")


def create_project(session: Session, *, company_id: UUID, client_id: UUID, code: str, name: str,
                   branch_id: UUID | None = None, billing_mode: str = "time_and_materials",
                   budget_minutes: int | None = None, budget_amount: Decimal | None = None,
                   fixed_fee: Decimal | None = None, fee_cap: Decimal | None = None,
                   service_product_id: UUID | None = None, manager_id: UUID | None = None,
                   starts_on: date | None = None, ends_on: date | None = None, notes: str | None = None,
                   template_id: UUID | None = None) -> Project:
    """Open a project (an engagement or matter) for a client. Needs 'projects.manage'. With a `template_id` the
    engagement template's repeats, checklist and milestones are set up with it."""
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    _check_client(session, company_id, client_id)
    _check_manager(session, manager_id)
    code = code.strip().upper()
    if not code or not name.strip():
        raise ValidationFailed("A project needs a code and a name")
    if billing_mode not in MODES:
        raise ValidationFailed(f"Billing is one of: {', '.join(MODES)}")
    if starts_on and ends_on and ends_on < starts_on:
        raise ValidationFailed("The project cannot end before it starts")
    if billing_mode == "capped_fee" and (fee_cap is None or fee_cap <= 0):
        raise ValidationFailed("A capped fee needs the most it can come to")
    if repo.project_by_code(session, company_id, code) is not None:
        raise Conflict(f"A project with code {code} already exists")
    project = Project(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        client_id=client_id, code=code, name=name.strip(), billing_mode=billing_mode, budget_minutes=budget_minutes,
        budget_amount=budget_amount, fixed_fee=fixed_fee, fee_cap=fee_cap if billing_mode == "capped_fee" else None,
        service_product_id=service_product_id, manager_id=manager_id, starts_on=starts_on, ends_on=ends_on,
        notes=(notes or "").strip()[:2000] or None)
    repo.add(session, project)
    audit_record(session, "create", "timebilling.project", project.id, {"code": code, "client_id": client_id})
    if template_id is not None:
        _apply_template(session, project, template_id)
    return project


def _apply_template(session: Session, project: Project, template_id: UUID) -> None:
    """Set a new project up from an engagement template: budget hours, repeats with their checklist, and (for a fixed
    fee) milestones that split the fee by the template's percentages, the last one taking the rounding."""
    from ziira.modules.timebilling.repository.models import EngagementTemplate
    from ziira.modules.timebilling.services import engagements

    template = repo.get(session, EngagementTemplate, template_id)
    if template is None or template.company_id != project.company_id:
        raise ValidationFailed("Template not found")
    if project.budget_minutes is None and template.budget_minutes:
        project.budget_minutes = template.budget_minutes
    if template.frequency and template.due_day:
        engagements.create_recurrence(
            session, project.id, name=template.name, frequency=template.frequency, due_day=template.due_day,
            due_month=template.due_month, lead_days=template.lead_days, checklist=list(template.checklist or []),
            assignee_id=project.manager_id)
    if project.billing_mode == "fixed_fee" and project.fixed_fee and template.milestones:
        left = project.fixed_fee
        rows = list(template.milestones)
        for i, m in enumerate(rows):
            amount = left if i == len(rows) - 1 else (project.fixed_fee * Decimal(str(m.get("percent", 0))) / 100
                                                      ).quantize(Decimal("0.01"))
            amount = min(amount, left)
            left -= amount
            add_milestone(session, project.id, name=str(m["name"]), amount=amount, sort_order=i)


def update_project(session: Session, project_id: UUID, **changes: Any) -> Project:
    """Change a project. Needs 'projects.manage'. Moving to `completed` or `archived` stops new time being logged."""
    project = repo.get(session, Project, project_id, lock=True)
    if project is None or not access.can_see_company(project.company_id):
        raise NotFound("Project not found")
    current_context().require(PROJECTS_MANAGE, company_id=project.company_id, branch_id=project.branch_id)
    if changes.get("status") is not None and changes["status"] not in STATUSES:
        raise ValidationFailed(f"Status is one of: {', '.join(STATUSES)}")
    if changes.get("billing_mode") is not None and changes["billing_mode"] not in MODES:
        raise ValidationFailed(f"Billing is one of: {', '.join(MODES)}")
    if changes.get("manager_id") is not None:
        _check_manager(session, changes["manager_id"])
    if changes.get("name") is not None:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise ValidationFailed("A project needs a name")
    done: dict[str, object] = {}
    for key in ("name", "status", "billing_mode", "budget_minutes", "budget_amount", "fixed_fee", "fee_cap",
                "service_product_id", "manager_id", "starts_on", "ends_on", "notes"):
        if key in changes and getattr(project, key) != changes[key]:
            done[key] = changes[key]
            setattr(project, key, changes[key])
    if project.starts_on and project.ends_on and project.ends_on < project.starts_on:
        raise ValidationFailed("The project cannot end before it starts")
    if project.billing_mode == "capped_fee" and (project.fee_cap is None or project.fee_cap <= 0):
        raise ValidationFailed("A capped fee needs the most it can come to")
    if project.billing_mode != "capped_fee":
        project.fee_cap = None
    project.updated_by = current_context().user_id
    session.flush()
    if done:
        audit_record(session, "update", "timebilling.project", project.id, done)
    return project


def get_project(session: Session, project_id: UUID) -> Project:
    return common.project_for_view(session, project_id)


def list_projects(session: Session, *, company_id: UUID | None = None, client_id: UUID | None = None,
                  status: str | None = None, search: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[Project]:
    q = select(Project).where(repo.in_scope(access.scopes_for(*_all()), Project.company_id, Project.branch_id))
    if company_id:
        q = q.where(Project.company_id == company_id)
    if client_id:
        q = q.where(Project.client_id == client_id)
    if status:
        q = q.where(Project.status == status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.where(Project.name.ilike(like) | Project.code.ilike(like))
    return list(session.scalars(q.order_by(Project.status, Project.code).limit(min(limit, 200)).offset(offset)))


def _all() -> tuple[str, ...]:
    from ziira.modules.timebilling.permissions import ALL

    return ALL


def logged_minutes(session: Session, project_id: UUID) -> int:
    """Every minute logged to the project, billable or not, approved or not."""
    return int(session.scalar(select(func.coalesce(func.sum(Entry.minutes), 0)).where(
        Entry.project_id == project_id)) or 0)


# --------------------------------------------------------------------------- milestones
def _project_to_manage(session: Session, project_id: UUID) -> Project:
    project = repo.get(session, Project, project_id)
    if project is None or not access.can_see_company(project.company_id):
        raise NotFound("Project not found")
    current_context().require(PROJECTS_MANAGE, company_id=project.company_id, branch_id=project.branch_id)
    return project


def add_milestone(session: Session, project_id: UUID, *, name: str, amount: Decimal, due_on: date | None = None,
                  sort_order: int = 0) -> Milestone:
    """Add a part of a fixed-fee project that can be billed when it is done. Needs 'projects.manage'."""
    project = _project_to_manage(session, project_id)
    if project.billing_mode != "fixed_fee":
        raise ValidationFailed("Milestones are for fixed-fee projects")
    if not name.strip():
        raise ValidationFailed("A milestone needs a name")
    ctx = current_context()
    milestone = Milestone(tenant_id=ctx.tenant_id, created_by=ctx.user_id, project_id=project.id, name=name.strip(),
                          amount=amount, due_on=due_on, sort_order=sort_order)
    repo.add(session, milestone)
    audit_record(session, "create", "timebilling.milestone", milestone.id, {"project": project.code, "amount": amount})
    return milestone


def list_milestones(session: Session, project_id: UUID) -> list[Milestone]:
    common.project_for_view(session, project_id)
    return list(session.scalars(select(Milestone).where(Milestone.project_id == project_id)
                                .order_by(Milestone.sort_order, Milestone.created_at)))


def update_milestone(session: Session, milestone_id: UUID, **changes: Any) -> Milestone:
    """Rename, re-price, reschedule a milestone, or mark it `ready` (to bill) or back to `planned`. An invoiced
    milestone is fixed."""
    milestone = repo.get(session, Milestone, milestone_id, lock=True)
    if milestone is None:
        raise NotFound("Milestone not found")
    _project_to_manage(session, milestone.project_id)
    if milestone.status == "invoiced":
        raise Conflict("This milestone has been invoiced")
    if changes.get("status") not in (None, "planned", "ready"):
        raise ValidationFailed("A milestone is planned or ready; it becomes invoiced when you invoice it")
    for key in ("name", "amount", "due_on", "status", "sort_order"):
        if key in changes and changes[key] is not None or key == "due_on" and key in changes:
            setattr(milestone, key, changes[key])
    milestone.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "timebilling.milestone", milestone.id, {k: v for k, v in changes.items()})
    return milestone


def delete_milestone(session: Session, milestone_id: UUID) -> None:
    milestone = repo.get(session, Milestone, milestone_id, lock=True)
    if milestone is None:
        raise NotFound("Milestone not found")
    _project_to_manage(session, milestone.project_id)
    if milestone.status == "invoiced" or milestone.batch_id is not None:
        raise Conflict("This milestone is on an invoice")
    session.delete(milestone)
    session.flush()
    audit_record(session, "delete", "timebilling.milestone", milestone_id, {"name": milestone.name})
