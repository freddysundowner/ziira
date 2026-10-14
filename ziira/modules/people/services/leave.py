"""Use cases: leave types, leave requests, approval and balances.

    pending --approve--> approved --cancel (before it starts)--> cancelled
       |
       '--reject--> rejected      pending --cancel--> cancelled

An employee asks for leave for themselves (anyone with an employee record linked to their user); HR can ask for them.
It is approved by someone with `leave.approve` for the employee's branch, never by the employee themselves. Days are
counted as working days (the business's weekend is a setting) unless the request says otherwise (half days). Approved
*unpaid* leave takes pay off in payroll.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.people.domain import time as work
from ziira.modules.people.permissions import EMPLOYEES_MANAGE, LEAVE_APPROVE
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import Employee, LeaveRequest, LeaveType
from ziira.modules.people.services import access
from ziira.sdk import (
    Conflict,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_setting,
    current_context,
)


def weekend(session: Session, company_id: UUID) -> frozenset[int]:
    return work.weekend_numbers(company_setting(session, company_id, "weekend_days"))


# --------------------------------------------------------------------------- leave types
def create_leave_type(session: Session, *, company_id: UUID, name: str, days_per_year: Decimal | None = None,
                      is_paid: bool = True) -> LeaveType:
    """Define a kind of leave (annual, sick, unpaid ...). `days_per_year` is the yearly entitlement (none: unlimited).
    Needs 'employees.manage'."""
    ctx = current_context()
    check_company(session, company_id)
    access.require_company(EMPLOYEES_MANAGE, company_id)
    name = " ".join(name.split())
    if not name or len(name) > 60:
        raise ValidationFailed("A leave type needs a name (at most 60 characters)")
    if days_per_year is not None and not 0 < days_per_year <= 366:
        raise ValidationFailed("Days per year is more than 0 and at most 366")
    if people_repo.leave_type_by_name(session, company_id, name) is not None:
        raise Conflict(f"There is already a leave type called {name}")
    leave_type = LeaveType(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, name=name,
                           days_per_year=days_per_year, is_paid=is_paid)
    people_repo.add(session, leave_type)
    audit_record(session, "create", "people.leave_type", leave_type.id,
                 {"name": name, "days_per_year": days_per_year, "is_paid": is_paid})
    return leave_type


def list_leave_types(session: Session, company_id: UUID | None = None) -> list[LeaveType]:
    """The kinds of leave: for people who work with employee records, and for any employee (their own company's)."""
    companies = access.visible_companies()
    own = _own_employee(session)
    if companies is not None:
        companies = companies | ({own.company_id} if own else set())
    if company_id is not None and companies is not None and company_id not in companies:
        raise NotFound("Company not found")
    return people_repo.list_leave_types(session, companies, company_id)


# --------------------------------------------------------------------------- requests
def _own_employee(session: Session) -> Employee | None:
    user_id = current_context().user_id
    return people_repo.employee_by_user(session, None, user_id) if user_id else None


def _is_self(employee: Employee) -> bool:
    user_id = current_context().user_id
    return user_id is not None and employee.user_id == user_id


def _load(session: Session, leave_id: UUID, *, lock: bool = False) -> tuple[LeaveRequest, Employee]:
    leave = people_repo.get_leave(session, leave_id, lock=lock)
    employee = people_repo.get_employee(session, leave.employee_id) if leave else None
    if leave is None or employee is None or not (_is_self(employee) or access.can_see(employee)):
        raise NotFound("Leave request not found")
    return leave, employee


def request_leave(session: Session, *, employee_id: UUID | None, leave_type_id: UUID, start_date: date,
                  end_date: date, days: Decimal | None = None, reason: str | None = None) -> LeaveRequest:
    """Ask for leave. With no `employee_id` it is for the person's own employee record; asking for someone else needs
    'employees.manage' (HR) or 'leave.approve' for their branch."""
    ctx = current_context()
    if employee_id is None:
        employee = _own_employee(session)
        if employee is None:
            raise ValidationFailed("You have no employee record; say which employee this is for")
    else:
        found = people_repo.get_employee(session, employee_id)
        if found is None or not (_is_self(found) or access.can_see(found)):
            raise NotFound("Employee not found")
        employee = found
        if not _is_self(employee) and not (
                ctx.can(EMPLOYEES_MANAGE, company_id=employee.company_id, branch_id=employee.branch_id)
                or ctx.can(LEAVE_APPROVE, company_id=employee.company_id, branch_id=employee.branch_id)):
            raise Forbidden("You can ask for leave only for yourself, unless you manage or approve leave here")
    if employee.status == "terminated":
        raise Conflict("This employee has left")
    leave_type = people_repo.get_leave_type(session, leave_type_id)
    if leave_type is None or leave_type.company_id != employee.company_id:
        raise ValidationFailed("Leave type not found in this company")
    if end_date < employee.hire_date:
        raise ValidationFailed("That is before the employee was hired")
    count = work.requested_days(start_date, end_date, days, weekend(session, employee.company_id))
    for other in people_repo.leave_of(session, employee.id, statuses=("pending", "approved")):
        if work.overlaps(start_date, end_date, other.start_date, other.end_date):
            raise Conflict(f"This overlaps leave already asked for ({other.start_date} to {other.end_date})")
    leave = LeaveRequest(tenant_id=ctx.tenant_id, created_by=ctx.user_id, employee_id=employee.id,
                         leave_type_id=leave_type_id, start_date=start_date, end_date=end_date, days=count,
                         reason=(reason or "").strip()[:300] or None)
    people_repo.add(session, leave)
    audit_record(session, "request", "people.leave_request", leave.id,
                 {"employee": employee.employee_no, "days": count, "start": start_date, "end": end_date})
    return leave


def decide_leave(session: Session, leave_id: UUID, *, approve: bool, note: str | None = None) -> LeaveRequest:
    """Approve or reject a pending request. Not the employee themselves. Needs 'leave.approve' for their branch."""
    leave, employee = _load(session, leave_id, lock=True)
    ctx = current_context()
    ctx.require(LEAVE_APPROVE, company_id=employee.company_id, branch_id=employee.branch_id)
    if leave.status != "pending":
        raise Conflict(f"This request is {leave.status}, so it cannot be decided")
    if _is_self(employee):
        raise Forbidden("Leave cannot be approved by the person taking it")
    if approve:
        leave_type = people_repo.get_leave_type(session, leave.leave_type_id)
        if leave_type is not None and leave_type.days_per_year is not None:
            taken = people_repo.days_taken(session, employee.id, leave.leave_type_id, leave.start_date.year)
            if taken + leave.days > leave_type.days_per_year:
                raise ValidationFailed(f"That is more than the {leave_type.days_per_year} days a year of "
                                       f"{leave_type.name} ({taken} already taken)")
    leave.status = "approved" if approve else "rejected"
    leave.approved_by = ctx.user_id
    leave.decided_note = (note or "").strip()[:300] or None
    session.flush()
    audit_record(session, "approve" if approve else "reject", "people.leave_request", leave.id,
                 {"employee": employee.employee_no, "days": leave.days, "note": leave.decided_note})
    return leave


def cancel_leave(session: Session, leave_id: UUID) -> LeaveRequest:
    """Withdraw a request: the employee (or whoever manages leave) before it starts, or while it is pending."""
    leave, employee = _load(session, leave_id, lock=True)
    ctx = current_context()
    allowed = _is_self(employee) or ctx.can(EMPLOYEES_MANAGE, company_id=employee.company_id,
                                            branch_id=employee.branch_id) or ctx.can(
        LEAVE_APPROVE, company_id=employee.company_id, branch_id=employee.branch_id)
    if not allowed:
        raise Forbidden("You cannot cancel this leave")
    if leave.status not in ("pending", "approved"):
        raise Conflict(f"This request is {leave.status}, so it cannot be cancelled")
    if leave.status == "approved" and leave.start_date <= date.today():
        raise Conflict("Leave that has started cannot be cancelled")
    if people_repo.locked_run_covering(session, employee.company_id, leave.start_date) is not None and (
            leave.status == "approved"):
        raise Conflict("Payroll for that period has been approved: the leave is final")
    leave.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", "people.leave_request", leave.id, {"employee": employee.employee_no})
    return leave


def get_leave(session: Session, leave_id: UUID) -> LeaveRequest:
    return _load(session, leave_id)[0]


def list_leave(session: Session, *, employee_id: UUID | None = None, status: str | None = None,
               date_from: date | None = None, date_to: date | None = None, limit: int = 50,
               offset: int = 0) -> list[LeaveRequest]:
    return people_repo.list_leave(session, access.scopes(), employee_id=employee_id, status=status,
                                  date_from=date_from, date_to=date_to, limit=min(limit, 200), offset=offset)


def my_leave(session: Session) -> list[LeaveRequest]:
    """The signed-in person's own requests."""
    employee = _own_employee(session)
    return people_repo.leave_of(session, employee.id) if employee else []


def balances(session: Session, employee_id: UUID, year: int) -> list[tuple[LeaveType, Decimal, Decimal | None]]:
    """For each leave type of the employee's company: days taken in the year and days left (none: unlimited)."""
    employee = people_repo.get_employee(session, employee_id)
    if employee is None or not (_is_self(employee) or access.can_see(employee)):
        raise NotFound("Employee not found")
    out = []
    for leave_type in people_repo.list_leave_types(session, {employee.company_id}, employee.company_id):
        taken = people_repo.days_taken(session, employee.id, leave_type.id, year)
        left = None if leave_type.days_per_year is None else leave_type.days_per_year - taken
        out.append((leave_type, taken, left))
    return out


def unpaid_days(session: Session, employee: Employee, start: date, end: date) -> Decimal:
    """Days of approved unpaid leave inside a period (for payroll)."""
    days = weekend(session, employee.company_id)
    total = Decimal(0)
    for leave, leave_type in people_repo.approved_leave_in(session, employee.id, start, end):
        if not leave_type.is_paid:
            total += work.days_in_period(leave.start_date, leave.end_date, leave.days, start, end, days)
    return total
