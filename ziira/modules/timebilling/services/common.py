"""Helpers shared by the timebilling services."""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Project, Setting
from ziira.modules.timebilling.services import access
from ziira.sdk import NotFound, Session, ValidationFailed, company_today, current_context


def settings(session: Session, company_id: UUID) -> Setting:
    """The company's time settings (created with defaults the first time they are needed)."""
    found = repo.settings_of(session, company_id)
    if found is None:
        found = Setting(tenant_id=current_context().tenant_id, company_id=company_id)
        repo.add(session, found)
    return found


def today(session: Session, company_id: UUID) -> date:
    return company_today(session, company_id)


def project_for_view(session: Session, project_id: UUID) -> Project:
    project = repo.get(session, Project, project_id)
    if project is None or not access.can_see_company(project.company_id):
        raise NotFound("Project not found")
    return project


def usable_project(session: Session, project_id: UUID, company_id: UUID | None = None) -> Project:
    """A project time can be logged to (active, in the company)."""
    project = repo.get(session, Project, project_id)
    if project is None or (company_id is not None and project.company_id != company_id) \
            or not access.can_see_company(project.company_id):
        raise ValidationFailed("Project not found in this company")
    if project.status != "active":
        raise ValidationFailed(f"{project.name} is {project.status.replace('_', ' ')}: time cannot be logged to it")
    return project


def user_names(session: Session, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = session.execute(text("select id, full_name from kernel.app_user where id = any(cast(:i as uuid[]))"),
                           {"i": [str(i) for i in ids]})
    return {r.id: str(r.full_name) for r in rows}


def customer_names(session: Session, ids: set[UUID]) -> dict[UUID, str]:
    """Names of CRM customers (the clients)."""
    if not ids:
        return {}
    from ziira.modules.crm.public import find_customers

    return {k: v.name for k, v in find_customers(session, ids).items()}


def currency(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar() or "")
