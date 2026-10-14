"""Use cases: departments and employees.

An employee record holds who the person is and where they work. What they are paid and where it goes (terms, pay items,
bank details) lives in `pay_setup`, behind its own permission. The national ID is stored encrypted and shown masked.
"""

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.people.domain import identity
from ziira.modules.people.permissions import EMPLOYEES_MANAGE
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import Department, Employee
from ziira.modules.people.services import access
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_setting,
    current_context,
    decrypt_text,
    encrypt_text,
    next_document_number,
)

RESIDENCY = ("resident", "non_resident")


def create_department(session: Session, *, company_id: UUID, name: str) -> Department:
    """Add a department. Needs 'employees.manage' for the company."""
    ctx = current_context()
    check_company(session, company_id)
    access.require_company(EMPLOYEES_MANAGE, company_id)
    name = name.strip()
    if not name or len(name) > 100:
        raise ValidationFailed("A department needs a name (at most 100 characters)")
    if people_repo.department_by_name(session, company_id, name) is not None:
        raise Conflict(f"There is already a department called {name}")
    department = Department(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, name=name)
    people_repo.add(session, department)
    audit_record(session, "create", "people.department", department.id, {"name": name})
    return department


def list_departments(session: Session, company_id: UUID | None = None) -> list[Department]:
    if company_id is not None:
        access.require_company_visible(company_id)
    return people_repo.list_departments(session, access.visible_companies(), company_id)


def _check_links(session: Session, company_id: UUID, branch_id: UUID | None, department_id: UUID | None,
                 user_id: UUID | None, *, own_id: UUID | None = None) -> None:
    check_company(session, company_id, branch_id)
    if department_id is not None:
        department = people_repo.get_department(session, department_id)
        if department is None or department.company_id != company_id:
            raise ValidationFailed("Department not found in this company")
    if user_id is not None:
        found = session.execute(text("select 1 from kernel.app_user where id = :u"), {"u": str(user_id)}).first()
        if found is None:
            raise ValidationFailed("That user does not exist")
        other = people_repo.employee_by_user(session, None, user_id)
        if other is not None and other.id != own_id:
            raise Conflict(f"That user is already linked to employee {other.employee_no}")


def _calling_code(session: Session, company_id: UUID) -> str:
    return str(company_setting(session, company_id, "phone_country_code"))


def masked_id(employee: Employee) -> str | None:
    """The national ID with all but its last three characters hidden."""
    if employee.national_id_ciphertext is None:
        return None
    return identity.mask(decrypt_text(bytes(employee.national_id_ciphertext).decode()))


def create_employee(session: Session, *, company_id: UUID, full_name: str, hire_date: date,
                    branch_id: UUID | None = None, department_id: UUID | None = None, user_id: UUID | None = None,
                    employee_no: str | None = None, national_id: str | None = None, tax_id: str | None = None,
                    registrations: dict[str, str] | None = None, exempt_rules: list[str] | None = None,
                    phone: str | None = None, email: str | None = None, residency: str = "resident",
                    is_director: bool = False) -> Employee:
    """Register an employee. Needs 'employees.manage' for the company (or the branch they work at)."""
    ctx = current_context()
    _check_links(session, company_id, branch_id, department_id, user_id)
    ctx.require(EMPLOYEES_MANAGE, company_id=company_id, branch_id=branch_id)
    full_name = " ".join(full_name.split())
    if not full_name or len(full_name) > 200:
        raise ValidationFailed("An employee needs a name (at most 200 characters)")
    if residency not in RESIDENCY:
        raise ValidationFailed("Residency is resident or non_resident")
    number = (employee_no or "").strip().upper() or next_document_number(
        session, company_id=company_id, branch_id=None, doc_type="employee", prefix="EMP")
    if len(number) > 30:
        raise ValidationFailed("An employee number is at most 30 characters")
    if people_repo.employee_by_no(session, company_id, number) is not None:
        raise Conflict(f"Employee number {number} is already used")
    clean_id = identity.national_id(national_id)
    employee = Employee(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        department_id=department_id, user_id=user_id, employee_no=number, full_name=full_name,
        national_id_ciphertext=encrypt_text(clean_id).encode() if clean_id else None,
        tax_id=identity.tax_id(tax_id), registrations=identity.registrations(registrations),
        exempt_rules=_exempt(exempt_rules), phone=identity.phone(phone, _calling_code(session, company_id)),
        email=identity.email(email), hire_date=hire_date, residency=residency, is_director=is_director)
    people_repo.add(session, employee)
    audit_record(session, "create", "people.employee", employee.id, {"employee_no": number, "name": full_name})
    return employee


def _exempt(codes: list[str] | None) -> list[str]:
    clean = sorted({c.strip().upper() for c in (codes or []) if c.strip()})
    if len(clean) > 30 or any(len(c) > 20 for c in clean):
        raise ValidationFailed("Too many exemptions, or a code that is too long")
    return clean


def get_employee(session: Session, employee_id: UUID) -> Employee:
    return access.load_employee(session, employee_id)


def list_employees(session: Session, *, company_id: UUID | None = None, branch_id: UUID | None = None,
                   department_id: UUID | None = None, status: str | None = None, search: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[Employee]:
    return people_repo.list_employees(session, access.scopes(), company_id=company_id, branch_id=branch_id,
                                      department_id=department_id, status=status, search=search,
                                      limit=min(limit, 200), offset=offset)


def update_employee(session: Session, employee_id: UUID, changes: dict[str, Any]) -> Employee:
    """Change an employee's details. Needs 'employees.manage'. Pay and bank details are changed elsewhere."""
    employee = access.load_employee(session, employee_id, lock=True)
    ctx = current_context()
    ctx.require(EMPLOYEES_MANAGE, company_id=employee.company_id, branch_id=employee.branch_id)
    if employee.status == "terminated":
        raise Conflict("This employee has left; their record can no longer be changed")
    code = _calling_code(session, employee.company_id)
    cleaners: dict[str, Callable[[Any], Any]] = {
        "tax_id": identity.tax_id, "phone": lambda v: identity.phone(v, code), "email": identity.email,
        "registrations": identity.registrations, "exempt_rules": _exempt}
    done: dict[str, Any] = {}
    for key, value in changes.items():
        if key in cleaners:
            setattr(employee, key, cleaners[key](value))
        elif key == "full_name":
            name = " ".join(str(value).split())
            if not name or len(name) > 200:
                raise ValidationFailed("An employee needs a name (at most 200 characters)")
            employee.full_name = name
        elif key == "national_id":
            clean = identity.national_id(value if isinstance(value, str) else None)
            employee.national_id_ciphertext = encrypt_text(clean).encode() if clean else None
        elif key in ("branch_id", "department_id", "user_id"):
            target = {"branch_id": employee.branch_id, "department_id": employee.department_id,
                      "user_id": employee.user_id} | {key: value}
            _check_links(session, employee.company_id, target["branch_id"], target["department_id"],
                         target["user_id"], own_id=employee.id)
            if key == "branch_id" and value is not None:
                ctx.require(EMPLOYEES_MANAGE, company_id=employee.company_id, branch_id=value)
            setattr(employee, key, value)
        elif key in ("residency", "is_director"):
            if key == "residency" and value not in RESIDENCY:
                raise ValidationFailed("Residency is resident or non_resident")
            setattr(employee, key, value)
        else:
            raise ValidationFailed(f"'{key}' cannot be changed here")
        done[key] = "***" if key in ("national_id", "tax_id") else value
    employee.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "people.employee", employee.id, done)
    return employee


def terminate_employee(session: Session, employee_id: UUID, *, termination_date: date,
                       reason: str | None = None) -> Employee:
    """Record that an employee has left. Final pay still runs for the part of the month they worked. Needs
    'employees.manage'."""
    employee = access.load_employee(session, employee_id, lock=True)
    current_context().require(EMPLOYEES_MANAGE, company_id=employee.company_id, branch_id=employee.branch_id)
    if employee.status == "terminated":
        raise Conflict("This employee has already left")
    if termination_date < employee.hire_date:
        raise ValidationFailed("They cannot leave before they were hired")
    employee.termination_date = termination_date
    employee.status = "terminated"
    session.flush()
    audit_record(session, "terminate", "people.employee", employee.id,
                 {"date": termination_date, "reason": (reason or "").strip()[:300] or None})
    return employee


def require_found(employee: Employee | None) -> Employee:
    if employee is None:
        raise NotFound("Employee not found")
    return employee


def get_employee_for_self(session: Session, employee_id: UUID) -> Employee:
    """An employee record, for its own owner (used to label their payslips)."""
    employee = people_repo.get_employee(session, employee_id)
    if employee is None or employee.user_id != current_context().user_id:
        raise NotFound("Employee not found")
    return employee
