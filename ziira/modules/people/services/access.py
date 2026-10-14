"""Who may see and change employee records. Pay, bank and payroll data need their own permissions (company-wide), which
general manager roles do not carry; branch grants reach only the employees of their branch."""

from uuid import UUID

from ziira.modules.people.permissions import (
    ATTENDANCE_MANAGE,
    EMPLOYEE_PAY_EDIT,
    EMPLOYEES_MANAGE,
    EMPLOYEES_VIEW,
    LEAVE_APPROVE,
    PAYROLL_APPROVE,
    PAYROLL_PREPARE,
    PAYROLL_VIEW,
)
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import Employee
from ziira.sdk import Forbidden, NotFound, Session, current_context

READERS = (EMPLOYEES_VIEW, EMPLOYEES_MANAGE, ATTENDANCE_MANAGE, LEAVE_APPROVE, EMPLOYEE_PAY_EDIT, PAYROLL_PREPARE,
           PAYROLL_APPROVE, PAYROLL_VIEW)


def scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    """Where the user may read employee records: (company, branch) pairs, or None for everywhere."""
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in READERS:
        granted = ctx.scopes_with(permission)
        if granted is None:
            return None
        found.update(granted)
    return sorted(found, key=str)


def visible_companies() -> set[UUID] | None:
    ctx = current_context()
    found: set[UUID] = set()
    for permission in READERS:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def can_see(employee: Employee) -> bool:
    granted = scopes()
    return granted is None or any((c is None or c == employee.company_id) and (b is None or b == employee.branch_id)
                                  for c, b in granted)


def load_employee(session: Session, employee_id: UUID, *, lock: bool = False) -> Employee:
    employee = people_repo.get_employee(session, employee_id, lock=lock)
    if employee is None or not can_see(employee):
        raise NotFound("Employee not found")
    return employee


def require_company(permission: str, company_id: UUID) -> None:
    """The permission held for the whole company (not just a branch): pay and payroll are never branch-level."""
    ctx = current_context()
    if not ctx.can(permission, company_id=company_id):
        raise Forbidden(f"You need '{permission}' for this company")


def holds_company(permission: str, company_id: UUID) -> bool:
    return current_context().can(permission, company_id=company_id)


def require_company_visible(company_id: UUID) -> None:
    companies = visible_companies()
    if companies is not None and company_id not in companies:
        raise NotFound("Company not found")
