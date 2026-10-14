"""Use cases: shifts and daily attendance.

Attendance is entered by hand, or recorded from the till (a cashier opening their till clocks in, closing it clocks
out). Hours and overtime feed payroll, so a day inside a payroll run that has been approved can no longer be changed.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.people.domain import time as work
from ziira.modules.people.permissions import ATTENDANCE_MANAGE
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import Attendance, Employee, Shift
from ziira.modules.people.services import access
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)

SOURCES = ("pos_login", "device", "manual")


def create_shift(session: Session, *, company_id: UUID, name: str, start_time: time, end_time: time,
                 branch_id: UUID | None = None) -> Shift:
    """Define a shift for the company, or for one branch. Needs 'attendance.manage'."""
    ctx = current_context()
    check_company(session, company_id, branch_id)
    ctx.require(ATTENDANCE_MANAGE, company_id=company_id, branch_id=branch_id)
    name = name.strip()
    if not name or len(name) > 60:
        raise ValidationFailed("A shift needs a name (at most 60 characters)")
    if start_time == end_time:
        raise ValidationFailed("A shift cannot start and end at the same time")
    if people_repo.shift_by_name(session, company_id, branch_id, name) is not None:
        raise Conflict(f"There is already a shift called {name} here")
    shift = Shift(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
                  name=name, start_time=start_time, end_time=end_time)
    people_repo.add(session, shift)
    audit_record(session, "create", "people.shift", shift.id, {"name": name})
    return shift


def list_shifts(session: Session, company_id: UUID | None = None) -> list[Shift]:
    if company_id is not None:
        access.require_company_visible(company_id)
    return people_repo.list_shifts(session, access.visible_companies(), company_id)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _fill(session: Session, employee: Employee, *, work_date: date, clock_in: datetime | None,
          clock_out: datetime | None, hours: Decimal | None, overtime_hours: Decimal | None,
          shift_id: UUID | None) -> tuple[datetime | None, datetime | None, Decimal | None, Decimal]:
    """Check one day's figures and complete them: hours from the clock times, overtime from the shift."""
    if work_date < employee.hire_date or (employee.termination_date and work_date > employee.termination_date):
        raise ValidationFailed("That day is outside this person's employment")
    if work_date > date.today():
        raise ValidationFailed("Attendance cannot be recorded for a day that has not happened")
    clock_in, clock_out = _aware(clock_in), _aware(clock_out)
    if clock_in and clock_out:
        hours = work.hours_between(clock_in, clock_out)
    elif (clock_in or clock_out) and hours is None:
        raise ValidationFailed("Give both clock-in and clock-out, or the hours worked")
    if hours is not None and (hours < 0 or hours > 24):
        raise ValidationFailed("Hours are between 0 and 24")
    normal: Decimal | None = None
    if shift_id is not None:
        shift = people_repo.get_shift(session, shift_id)
        if shift is None or shift.company_id != employee.company_id:
            raise ValidationFailed("Shift not found in this company")
        normal = work.shift_hours(shift.start_time, shift.end_time)
    if overtime_hours is None:
        overtime_hours = work.overtime_for(hours, normal) if hours is not None and normal is not None else Decimal(0)
    if overtime_hours < 0 or overtime_hours > (hours if hours is not None else Decimal(24)):
        raise ValidationFailed("Overtime cannot be more than the hours worked")
    locked = people_repo.locked_run_covering(session, employee.company_id, work_date)
    if locked is not None:
        raise Conflict(f"Payroll for {locked.period_start} to {locked.period_end} has been approved: that day is final")
    return clock_in, clock_out, hours, overtime_hours


def record_attendance(session: Session, *, employee_id: UUID, work_date: date, clock_in: datetime | None = None,
                      clock_out: datetime | None = None, hours: Decimal | None = None,
                      overtime_hours: Decimal | None = None, shift_id: UUID | None = None) -> Attendance:
    """Record that an employee worked on a day. Needs 'attendance.manage' for the employee's company or branch."""
    employee = access.load_employee(session, employee_id)
    ctx = current_context()
    ctx.require(ATTENDANCE_MANAGE, company_id=employee.company_id, branch_id=employee.branch_id)
    clock_in, clock_out, hours, overtime_hours = _fill(
        session, employee, work_date=work_date, clock_in=clock_in, clock_out=clock_out, hours=hours,
        overtime_hours=overtime_hours, shift_id=shift_id)
    if people_repo.attendance_on(session, employee_id, work_date, shift_id) is not None:
        raise Conflict("Attendance is already recorded for that day (correct it instead)")
    row = Attendance(tenant_id=ctx.tenant_id, created_by=ctx.user_id, employee_id=employee_id,
                     branch_id=employee.branch_id, work_date=work_date, shift_id=shift_id, clock_in=clock_in,
                     clock_out=clock_out, hours=hours, overtime_hours=overtime_hours, source="manual")
    people_repo.add(session, row)
    audit_record(session, "record", "people.attendance", row.id,
                 {"employee": employee.employee_no, "date": work_date, "hours": hours, "overtime": overtime_hours})
    return row


def update_attendance(session: Session, attendance_id: UUID, changes: dict[str, Any]) -> Attendance:
    """Correct a day's attendance. Needs 'attendance.manage'."""
    row = people_repo.get_attendance(session, attendance_id, lock=True)
    if row is None:
        raise NotFound("Attendance not found")
    employee = access.load_employee(session, row.employee_id)
    ctx = current_context()
    ctx.require(ATTENDANCE_MANAGE, company_id=employee.company_id, branch_id=employee.branch_id)
    unknown = set(changes) - {"clock_in", "clock_out", "hours", "overtime_hours"}
    if unknown:
        raise ValidationFailed(f"'{sorted(unknown)[0]}' cannot be changed here")
    merged = {"clock_in": row.clock_in, "clock_out": row.clock_out, "hours": row.hours,
              "overtime_hours": None if "hours" in changes or "clock_in" in changes or "clock_out" in changes
              else row.overtime_hours} | changes
    clock_in, clock_out, hours, overtime = _fill(
        session, employee, work_date=row.work_date, clock_in=merged["clock_in"], clock_out=merged["clock_out"],
        hours=merged["hours"], overtime_hours=merged["overtime_hours"], shift_id=row.shift_id)
    row.clock_in, row.clock_out, row.hours, row.overtime_hours, row.updated_by = (
        clock_in, clock_out, hours, overtime, ctx.user_id)
    session.flush()
    audit_record(session, "correct", "people.attendance", row.id,
                 {"employee": employee.employee_no, "hours": hours, "overtime": overtime})
    return row


def list_attendance(session: Session, *, employee_id: UUID | None = None, branch_id: UUID | None = None,
                    date_from: date | None = None, date_to: date | None = None, limit: int = 100,
                    offset: int = 0) -> list[Attendance]:
    return people_repo.list_attendance(session, access.scopes(), employee_id=employee_id, branch_id=branch_id,
                                       date_from=date_from, date_to=date_to, limit=min(limit, 500), offset=offset)


def attendance_summary(session: Session, company_id: UUID, date_from: date,
                       date_to: date) -> list[tuple[Employee, int, Decimal, Decimal]]:
    """Per employee: days present, hours and overtime in a period."""
    if date_to < date_from:
        raise ValidationFailed("The end date is before the start date")
    access.require_company_visible(company_id)
    return people_repo.attendance_summary(session, access.scopes(), company_id, date_from, date_to)


# --------------------------------------------------------------------------- from the till
def clock_in_from_till(session: Session, *, user_id: UUID | None, branch_id: UUID | None, day: date,
                       at: datetime) -> None:
    """A cashier opened a till: that is their clock-in for the day (the first one counts)."""
    employee = people_repo.employee_by_user(session, None, user_id) if user_id else None
    if employee is None or day < employee.hire_date:
        return
    if people_repo.locked_run_covering(session, employee.company_id, day) is not None:
        return
    row = people_repo.attendance_on(session, employee.id, day, None)
    if row is None:
        people_repo.add(session, Attendance(
            tenant_id=employee.tenant_id, employee_id=employee.id, branch_id=branch_id or employee.branch_id,
            work_date=day, clock_in=at, overtime_hours=Decimal(0), source="pos_login"))


def clock_out_from_till(session: Session, *, user_id: UUID | None, day: date, at: datetime) -> None:
    """A cashier closed their till: that is their clock-out (the last one counts)."""
    employee = people_repo.employee_by_user(session, None, user_id) if user_id else None
    if employee is None:
        return
    row = people_repo.attendance_on(session, employee.id, day, None)
    if row is None or row.source != "pos_login" or row.clock_in is None or at < row.clock_in:
        return
    if people_repo.locked_run_covering(session, employee.company_id, day) is not None:
        return
    hours = work.hours_between(row.clock_in, at) if (at - row.clock_in).total_seconds() <= 24 * 3600 else None
    row.clock_out, row.hours = at, hours
    session.flush()
