"""Database access for the people schema. Row-level security scopes every query to the tenant."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, or_, select, true
from sqlalchemy.orm import Session

from ziira.modules.people.repository.models import (
    Attendance,
    Department,
    Employee,
    EmployeeBankAccount,
    EmployeePayItem,
    EmploymentTerms,
    LeaveRequest,
    LeaveType,
    PayComponent,
    PayrollRun,
    Shift,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None


def add(session: Session, record: object) -> None:
    session.add(record)
    session.flush()


def employee_scope(scopes: Scopes) -> ColumnElement[bool]:
    """Employees a user may see: company-wide grants see the company's employees, a branch grant only that branch's."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(Employee.company_id == c, true() if b is None else Employee.branch_id == b)
                          for c, b in scopes))


# --------------------------------------------------------------------------- departments and employees
def department_by_name(session: Session, company_id: UUID, name: str) -> Department | None:
    return session.scalars(select(Department).where(Department.company_id == company_id,
                                                    Department.name == name)).first()


def get_department(session: Session, department_id: UUID) -> Department | None:
    return session.get(Department, department_id)


def list_departments(session: Session, company_ids: set[UUID] | None, company_id: UUID | None) -> list[Department]:
    query = select(Department).order_by(Department.name)
    if company_ids is not None:
        query = query.where(Department.company_id.in_(company_ids))
    if company_id:
        query = query.where(Department.company_id == company_id)
    return list(session.scalars(query))


def get_employee(session: Session, employee_id: UUID, *, lock: bool = False) -> Employee | None:
    query = select(Employee).where(Employee.id == employee_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def employee_by_no(session: Session, company_id: UUID, employee_no: str) -> Employee | None:
    return session.scalars(select(Employee).where(Employee.company_id == company_id,
                                                  Employee.employee_no == employee_no)).first()


def employee_by_user(session: Session, company_id: UUID | None, user_id: UUID) -> Employee | None:
    query = select(Employee).where(Employee.user_id == user_id, Employee.status != "terminated")
    if company_id:
        query = query.where(Employee.company_id == company_id)
    return session.scalars(query).first()


def list_employees(session: Session, scopes: Scopes, *, company_id: UUID | None, branch_id: UUID | None,
                   department_id: UUID | None, status: str | None, search: str | None, limit: int,
                   offset: int) -> list[Employee]:
    query = select(Employee).where(employee_scope(scopes)).order_by(Employee.employee_no).limit(limit).offset(offset)
    if company_id:
        query = query.where(Employee.company_id == company_id)
    if branch_id:
        query = query.where(Employee.branch_id == branch_id)
    if department_id:
        query = query.where(Employee.department_id == department_id)
    if status:
        query = query.where(Employee.status == status)
    if search:
        like = f"%{search.strip().replace('%', '').replace('_', '')}%"
        query = query.where(or_(Employee.full_name.ilike(like), Employee.employee_no.ilike(like)))
    return list(session.scalars(query))


def payable_employees(session: Session, company_id: UUID, start: date, end: date) -> list[Employee]:
    """Employees employed at some point in a period: hired by its end and not left before its start."""
    return list(session.scalars(
        select(Employee).where(Employee.company_id == company_id, Employee.hire_date <= end,
                               or_(Employee.termination_date.is_(None), Employee.termination_date >= start))
        .order_by(Employee.employee_no)))


# --------------------------------------------------------------------------- pay components, terms, items, bank
def get_component(session: Session, component_id: UUID) -> PayComponent | None:
    return session.get(PayComponent, component_id)


def component_by_code(session: Session, company_id: UUID, code: str) -> PayComponent | None:
    return session.scalars(select(PayComponent).where(PayComponent.company_id == company_id,
                                                      PayComponent.code == code)).first()


def list_components(session: Session, company_ids: set[UUID] | None, company_id: UUID | None) -> list[PayComponent]:
    query = select(PayComponent).order_by(PayComponent.code)
    if company_ids is not None:
        query = query.where(PayComponent.company_id.in_(company_ids))
    if company_id:
        query = query.where(PayComponent.company_id == company_id)
    return list(session.scalars(query))


def get_terms(session: Session, terms_id: UUID, *, lock: bool = False) -> EmploymentTerms | None:
    query = select(EmploymentTerms).where(EmploymentTerms.id == terms_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def terms_of(session: Session, employee_id: UUID) -> list[EmploymentTerms]:
    return list(session.scalars(select(EmploymentTerms).where(EmploymentTerms.employee_id == employee_id)
                                .order_by(EmploymentTerms.valid_from.desc(), EmploymentTerms.created_at.desc())))


def terms_in_force(session: Session, employee_id: UUID, day: date) -> EmploymentTerms | None:
    """The approved terms that apply on a day."""
    return session.scalars(
        select(EmploymentTerms).where(
            EmploymentTerms.employee_id == employee_id, EmploymentTerms.approved_by.is_not(None),
            EmploymentTerms.rejected.is_(False), EmploymentTerms.valid_from <= day,
            or_(EmploymentTerms.valid_to.is_(None), EmploymentTerms.valid_to >= day))
        .order_by(EmploymentTerms.valid_from.desc())).first()


def pending_terms(session: Session, employee_id: UUID) -> EmploymentTerms | None:
    return session.scalars(select(EmploymentTerms).where(
        EmploymentTerms.employee_id == employee_id, EmploymentTerms.approved_by.is_(None),
        EmploymentTerms.rejected.is_(False))).first()


def get_pay_item(session: Session, item_id: UUID, *, lock: bool = False) -> EmployeePayItem | None:
    query = select(EmployeePayItem).where(EmployeePayItem.id == item_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def pay_items_of(session: Session, employee_id: UUID) -> list[EmployeePayItem]:
    return list(session.scalars(select(EmployeePayItem).where(EmployeePayItem.employee_id == employee_id)
                                .order_by(EmployeePayItem.valid_from.desc(), EmployeePayItem.created_at.desc())))


def pay_items_in_period(session: Session, employee_id: UUID, start: date, end: date) -> list[EmployeePayItem]:
    """Items that apply in a period: recurring ones valid at some point in it, one-off ones dated inside it."""
    return list(session.scalars(select(EmployeePayItem).where(
        EmployeePayItem.employee_id == employee_id,
        or_(and_(EmployeePayItem.recurring.is_(True), EmployeePayItem.valid_from <= end,
                 or_(EmployeePayItem.valid_to.is_(None), EmployeePayItem.valid_to >= start)),
            and_(EmployeePayItem.recurring.is_(False), EmployeePayItem.valid_from >= start,
                 EmployeePayItem.valid_from <= end)))
        .order_by(EmployeePayItem.created_at)))


def get_bank(session: Session, bank_id: UUID, *, lock: bool = False) -> EmployeeBankAccount | None:
    query = select(EmployeeBankAccount).where(EmployeeBankAccount.id == bank_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def banks_of(session: Session, employee_id: UUID) -> list[EmployeeBankAccount]:
    return list(session.scalars(select(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == employee_id)
                                .order_by(EmployeeBankAccount.valid_from.desc(),
                                          EmployeeBankAccount.created_at.desc())))


def active_bank(session: Session, employee_id: UUID) -> EmployeeBankAccount | None:
    """The approved details in use now (the newest approved one not ended)."""
    return session.scalars(select(EmployeeBankAccount).where(
        EmployeeBankAccount.employee_id == employee_id, EmployeeBankAccount.approved_by.is_not(None),
        EmployeeBankAccount.rejected.is_(False), EmployeeBankAccount.valid_to.is_(None))
        .order_by(EmployeeBankAccount.valid_from.desc())).first()


def pending_bank(session: Session, employee_id: UUID) -> EmployeeBankAccount | None:
    return session.scalars(select(EmployeeBankAccount).where(
        EmployeeBankAccount.employee_id == employee_id, EmployeeBankAccount.approved_by.is_(None),
        EmployeeBankAccount.rejected.is_(False))).first()


# --------------------------------------------------------------------------- shifts and attendance
def get_shift(session: Session, shift_id: UUID) -> Shift | None:
    return session.get(Shift, shift_id)


def shift_by_name(session: Session, company_id: UUID, branch_id: UUID | None, name: str) -> Shift | None:
    query = select(Shift).where(Shift.company_id == company_id, Shift.name == name)
    query = query.where(Shift.branch_id == branch_id) if branch_id else query.where(Shift.branch_id.is_(None))
    return session.scalars(query).first()


def list_shifts(session: Session, company_ids: set[UUID] | None, company_id: UUID | None) -> list[Shift]:
    query = select(Shift).order_by(Shift.name)
    if company_ids is not None:
        query = query.where(Shift.company_id.in_(company_ids))
    if company_id:
        query = query.where(Shift.company_id == company_id)
    return list(session.scalars(query))


def get_attendance(session: Session, attendance_id: UUID, *, lock: bool = False) -> Attendance | None:
    query = select(Attendance).where(Attendance.id == attendance_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def attendance_on(session: Session, employee_id: UUID, day: date, shift_id: UUID | None) -> Attendance | None:
    query = select(Attendance).where(Attendance.employee_id == employee_id, Attendance.work_date == day)
    query = query.where(Attendance.shift_id == shift_id) if shift_id else query.where(Attendance.shift_id.is_(None))
    return session.scalars(query).first()


def list_attendance(session: Session, scopes: Scopes, *, employee_id: UUID | None, branch_id: UUID | None,
                    date_from: date | None, date_to: date | None, limit: int, offset: int) -> list[Attendance]:
    query = (select(Attendance).join(Employee, Employee.id == Attendance.employee_id).where(employee_scope(scopes))
             .order_by(Attendance.work_date.desc(), Employee.employee_no).limit(limit).offset(offset))
    if employee_id:
        query = query.where(Attendance.employee_id == employee_id)
    if branch_id:
        query = query.where(Attendance.branch_id == branch_id)
    if date_from:
        query = query.where(Attendance.work_date >= date_from)
    if date_to:
        query = query.where(Attendance.work_date <= date_to)
    return list(session.scalars(query))


def attendance_totals(session: Session, employee_id: UUID, start: date, end: date) -> tuple[int, Decimal, Decimal]:
    """Days present, hours and overtime hours of an employee in a period."""
    row = session.execute(select(
        func.count(), func.coalesce(func.sum(Attendance.hours), 0),
        func.coalesce(func.sum(Attendance.overtime_hours), 0)
    ).where(Attendance.employee_id == employee_id, Attendance.work_date >= start, Attendance.work_date <= end)).one()
    return int(row[0]), Decimal(str(row[1])), Decimal(str(row[2]))


def locked_run_covering(session: Session, company_id: UUID, day: date) -> PayrollRun | None:
    """A payroll run that has been approved (or paid) for a period containing the day: its inputs are final."""
    return session.scalars(select(PayrollRun).where(
        PayrollRun.company_id == company_id, PayrollRun.period_start <= day, PayrollRun.period_end >= day,
        PayrollRun.status.in_(("approved", "posted", "paid")))).first()


# --------------------------------------------------------------------------- leave
def get_leave_type(session: Session, leave_type_id: UUID) -> LeaveType | None:
    return session.get(LeaveType, leave_type_id)


def leave_type_by_name(session: Session, company_id: UUID, name: str) -> LeaveType | None:
    return session.scalars(select(LeaveType).where(LeaveType.company_id == company_id,
                                                   LeaveType.name == name)).first()


def list_leave_types(session: Session, company_ids: set[UUID] | None, company_id: UUID | None) -> list[LeaveType]:
    query = select(LeaveType).order_by(LeaveType.name)
    if company_ids is not None:
        query = query.where(LeaveType.company_id.in_(company_ids))
    if company_id:
        query = query.where(LeaveType.company_id == company_id)
    return list(session.scalars(query))


def get_leave(session: Session, leave_id: UUID, *, lock: bool = False) -> LeaveRequest | None:
    query = select(LeaveRequest).where(LeaveRequest.id == leave_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalars(query).first()


def leave_of(session: Session, employee_id: UUID, *, statuses: tuple[str, ...] | None = None) -> list[LeaveRequest]:
    query = select(LeaveRequest).where(LeaveRequest.employee_id == employee_id).order_by(
        LeaveRequest.start_date.desc())
    if statuses:
        query = query.where(LeaveRequest.status.in_(statuses))
    return list(session.scalars(query))


def list_leave(session: Session, scopes: Scopes, *, employee_id: UUID | None, status: str | None,
               date_from: date | None, date_to: date | None, limit: int, offset: int) -> list[LeaveRequest]:
    query = (select(LeaveRequest).join(Employee, Employee.id == LeaveRequest.employee_id)
             .where(employee_scope(scopes)).order_by(LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc())
             .limit(limit).offset(offset))
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id)
    if status:
        query = query.where(LeaveRequest.status == status)
    if date_from:
        query = query.where(LeaveRequest.end_date >= date_from)
    if date_to:
        query = query.where(LeaveRequest.start_date <= date_to)
    return list(session.scalars(query))


def approved_leave_in(session: Session, employee_id: UUID, start: date,
                      end: date) -> list[tuple[LeaveRequest, LeaveType]]:
    """Approved leave overlapping a period, with its type."""
    rows = session.execute(select(LeaveRequest, LeaveType).join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
                           .where(LeaveRequest.employee_id == employee_id, LeaveRequest.status == "approved",
                                  LeaveRequest.start_date <= end, LeaveRequest.end_date >= start))
    return [(r, t) for r, t in rows]


def days_taken(session: Session, employee_id: UUID, leave_type_id: UUID, year: int) -> Decimal:
    value = session.scalar(select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(
        LeaveRequest.employee_id == employee_id, LeaveRequest.leave_type_id == leave_type_id,
        LeaveRequest.status == "approved", func.extract("year", LeaveRequest.start_date) == year))
    return Decimal(value or 0)


def attendance_summary(session: Session, scopes: Scopes, company_id: UUID, start: date,
                       end: date) -> list[tuple[Employee, int, Decimal, Decimal]]:
    """Per employee: days present, hours and overtime hours in a period (employees with no attendance are left out)."""
    rows = session.execute(
        select(Employee, func.count(Attendance.id), func.coalesce(func.sum(Attendance.hours), 0),
               func.coalesce(func.sum(Attendance.overtime_hours), 0))
        .join(Attendance, Attendance.employee_id == Employee.id)
        .where(employee_scope(scopes), Employee.company_id == company_id, Attendance.work_date >= start,
               Attendance.work_date <= end)
        .group_by(Employee.id).order_by(Employee.employee_no))
    return [(e, int(n), Decimal(str(h)), Decimal(str(o))) for e, n, h, o in rows]
