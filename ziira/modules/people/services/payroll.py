"""Use cases: payroll runs.

    draft --calculate--> calculated --submit--> pending_approval --approve--> approved (and posted to the books)
                            ^   |                      |                           |
                            |   '--cancel--> cancelled '--reject--> calculated     '--pay--> paid

A run covers a period (a month, usually). *Calculate* works out every employee's pay from their approved terms, pay
items, attendance, unpaid leave and the business's statutory rules in force at the end of the period, and lists what a
person should review (new employees, pay and bank changes, deductions limited by the pay available ...). Anything that
makes the run unsafe (a rule nobody has verified, a negative net pay) stops it being submitted. The person who prepared
the run cannot approve it. On approval the figures are worked out again and must equal the ones that were reviewed;
Finance then posts the pay, employer costs and what is owed to the bodies that collect each rule, branch by branch.
*Pay* records that the salaries were paid and Finance moves the net pay out of the bank, mobile money or cash.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.people.domain import payroll as engine
from ziira.modules.people.domain import rules as domain_rules
from ziira.modules.people.permissions import PAYROLL_APPROVE, PAYROLL_PAY, PAYROLL_PREPARE, PAYROLL_VIEW
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import Employee, PayrollRun, Payslip, PayslipLine
from ziira.modules.people.services import access, leave, pay_setup, statutory_rules
from ziira.modules.people.services.common import finance_enabled
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_setting,
    current_context,
    publish,
)

READERS = (PAYROLL_VIEW, PAYROLL_PREPARE, PAYROLL_APPROVE, PAYROLL_PAY)
MAX_PERIOD_DAYS = 31
CHANGE_WARNING = Decimal("0.20")


def _readable() -> set[UUID] | None:
    ctx = current_context()
    found: set[UUID] = set()
    for permission in READERS:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def _load(session: Session, run_id: UUID, *, lock: bool = False) -> PayrollRun:
    run = people_repo.get_run(session, run_id, lock=lock)
    companies = _readable()
    if run is None or (companies is not None and run.company_id not in companies):
        raise NotFound("Payroll run not found")
    return run


def get_run(session: Session, run_id: UUID) -> PayrollRun:
    return _load(session, run_id)


def list_runs(session: Session, *, company_id: UUID | None = None, status: str | None = None, limit: int = 50,
              offset: int = 0) -> list[PayrollRun]:
    return people_repo.list_runs(session, _readable(), company_id=company_id, status=status, limit=min(limit, 200),
                                 offset=offset)


# --------------------------------------------------------------------------- creating a run
def create_run(session: Session, *, company_id: UUID, period_start: date, period_end: date,
               pay_date: date) -> PayrollRun:
    """Start a run for a period. Needs 'payroll.prepare' for the company."""
    ctx = current_context()
    check_company(session, company_id)
    access.require_company(PAYROLL_PREPARE, company_id)
    if period_end < period_start or (period_end - period_start).days >= MAX_PERIOD_DAYS:
        raise ValidationFailed(f"A period is at least a day and at most {MAX_PERIOD_DAYS} days")
    if pay_date < period_start:
        raise ValidationFailed("The pay date cannot be before the period starts")
    other = people_repo.overlapping_run(session, company_id, period_start, period_end)
    if other is not None:
        raise Conflict(f"This overlaps the run for {other.period_start} to {other.period_end} ({other.status})")
    run = PayrollRun(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                     period_start=period_start, period_end=period_end, pay_date=pay_date, totals={}, exceptions=[],
                     unpaid_day_divisor=int(company_setting(session, company_id, "payroll_unpaid_day_divisor")))
    people_repo.add(session, run)
    audit_record(session, "create", "people.payroll_run", run.id, {"period": f"{period_start} to {period_end}"})
    return run


# --------------------------------------------------------------------------- the calculation
@dataclass
class EmployeePay:
    employee: Employee
    result: engine.PayResult
    basic: Decimal
    pay_method: str | None
    detail: dict[str, Any]


def _exception(code: str, severity: str, message: str, employee: Employee | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message,
            "employee_id": str(employee.id) if employee else None,
            "employee_no": employee.employee_no if employee else None}


def _items_for(session: Session, employee: Employee, start: date, end: date, period_days: int, emp_start: date,
               emp_end: date) -> tuple[list[engine.Item], list[engine.Item], list[engine.Item], list[engine.Item]]:
    """The employee's pay items in the period, split into earnings, benefits, deductions and employer items. A recurring
    earning or benefit is paid for the days it and the employment overlap the period; a deduction or employer item is
    taken in full for a month it applies to."""
    earnings: list[engine.Item] = []
    benefits: list[engine.Item] = []
    deductions: list[engine.Item] = []
    employer: list[engine.Item] = []
    components: dict[UUID, Any] = {}
    for item in people_repo.pay_items_in_period(session, employee.id, start, end):
        component = components.get(item.component_id) or people_repo.get_component(session, item.component_id)
        if component is None:
            continue
        components[item.component_id] = component
        if item.recurring:
            first = max(item.valid_from, start, emp_start)
            last = min(item.valid_to or end, end, emp_end)
            days = (last - first).days + 1
            if days <= 0:
                continue
            share = engine.prorate(item.amount, days, period_days)
        else:
            if not emp_start <= item.valid_from <= emp_end:
                continue
            share = item.amount
        if component.kind == "earning":
            earnings.append(engine.Item(component.code, component.name, share, component.is_taxable))
        elif component.kind == "benefit":
            benefits.append(engine.Item(component.code, component.name, share))
        elif component.kind == "deduction":
            deductions.append(engine.Item(component.code, component.name, item.amount))
        else:
            employer.append(engine.Item(component.code, component.name, item.amount))
    return earnings, benefits, deductions, employer


def _compute(session: Session, run: PayrollRun) -> tuple[list[EmployeePay], list[dict[str, Any]],
                                                          list[domain_rules.ActiveRule]]:
    """Every payable employee's pay for the run's period, and what a reviewer should look at. Changes nothing."""
    start, end = run.period_start, run.period_end
    period_days = (end - start).days + 1
    rows = statutory_rules.rows_for(session, run.company_id)
    active = domain_rules.in_force(rows, end)
    multiplier = Decimal(str(company_setting(session, run.company_id, "overtime_multiplier")))
    hours_per_month = Decimal(str(company_setting(session, run.company_id, "overtime_hours_per_month")))
    exceptions: list[dict[str, Any]] = []
    for a in active:
        if not a.row.is_verified:
            exceptions.append(_exception(
                "unverified_rule", "blocker",
                f"The {a.rule.name} rule ({a.rule.code}, from {a.row.effective_from}) has not been verified"))
    results: list[EmployeePay] = []
    for employee in people_repo.payable_employees(session, run.company_id, start, end):
        emp_start = max(employee.hire_date, start)
        emp_end = min(employee.termination_date or end, end)
        days_worked = (emp_end - emp_start).days + 1
        terms = people_repo.terms_in_force(session, employee.id, end)
        if terms is None or terms.valid_from > emp_end:
            terms = people_repo.terms_in_force(session, employee.id, emp_end)
        if terms is None:
            exceptions.append(_exception("no_pay_terms", "warning", "No approved pay: no payslip", employee))
            continue
        if employee.hire_date > start:
            exceptions.append(_exception("new_employee", "info", f"Joined on {employee.hire_date}: paid "
                                         f"{days_worked} of {period_days} days", employee))
        if employee.termination_date and employee.termination_date < end:
            exceptions.append(_exception("left", "info", f"Left on {employee.termination_date}: paid "
                                         f"{days_worked} of {period_days} days", employee))
        for t in people_repo.terms_of(session, employee.id):
            if t.approved_by is not None and not t.rejected and start < t.valid_from <= end:
                exceptions.append(_exception(
                    "pay_changed", "warning", f"Basic pay changed on {t.valid_from} to {t.basic_pay}: paid at "
                    "the rate in force at the end of the period", employee))
        bank = people_repo.active_bank(session, employee.id)
        if bank is None:
            exceptions.append(_exception("no_payment_details", "warning", "No approved bank or mobile money "
                                         "details: cannot be paid electronically", employee))
        elif bank.valid_from.date() >= start:
            exceptions.append(_exception("bank_changed", "warning", f"Payment details changed on "
                                         f"{bank.valid_from.date()}: check with the employee", employee))
        basic = engine.prorate(terms.basic_pay, days_worked, period_days)
        unpaid_days = leave.unpaid_days(session, employee, emp_start, emp_end)
        unpaid = min(engine.unpaid_leave_amount(terms.basic_pay, unpaid_days, run.unpaid_day_divisor), basic)
        _, hours, overtime_hours = people_repo.attendance_totals(session, employee.id, emp_start, emp_end)
        earnings, benefits, deductions, employer_items = _items_for(session, employee, start, end, period_days,
                                                                    emp_start, emp_end)
        if overtime_hours > 0:
            earnings.append(engine.Item("OVERTIME", "Overtime", engine.overtime_pay(
                terms.basic_pay, overtime_hours, multiplier, hours_per_month)))
        result = engine.calculate(engine.PayInput(
            basic=basic, earnings=tuple(earnings), benefits=tuple(benefits), unpaid_leave=unpaid,
            deductions=tuple(deductions), employer_items=tuple(employer_items),
            resident=employee.residency == "resident", exempt=frozenset(employee.exempt_rules or [])), active)
        if result.net_pay < 0:
            exceptions.append(_exception("negative_net", "blocker",
                                         f"Deductions are more than the pay: net pay would be {result.net_pay}",
                                         employee))
        for r in result.rules:
            if r.capped:
                exceptions.append(_exception("deduction_limited", "warning", f"{r.name} was limited to the pay "
                                             "available", employee))
        previous = people_repo.previous_payslip(session, employee.id, start)
        if previous is not None and previous.net_pay > 0 and abs(result.net_pay - previous.net_pay) / \
                previous.net_pay > CHANGE_WARNING:
            exceptions.append(_exception(
                "net_pay_changed", "warning",
                f"Net pay is {result.net_pay}, against {previous.net_pay} last time", employee))
        results.append(EmployeePay(
            employee, result, basic, bank.method if bank else None,
            {"basic_pay_full": str(terms.basic_pay), "days_worked": days_worked, "days_in_period": period_days,
             "unpaid_leave_days": str(unpaid_days), "overtime_hours": str(overtime_hours),
             "hours_worked": str(hours)}))
    if not results:
        exceptions.append(_exception("nobody_to_pay", "blocker", "There is nobody to pay in this period"))
    return results, exceptions, active


def _totals(results: list[EmployeePay], active: list[domain_rules.ActiveRule]) -> dict[str, Any]:
    by_rule: dict[str, dict[str, Any]] = {}
    for a in active:
        by_rule[a.rule.code] = {"name": a.rule.name, "kind": a.rule.kind, "employee": Decimal(0),
                                "employer": Decimal(0),
                                "payable_account_id": str(a.row.payable_account_id) if a.row.payable_account_id
                                else None}
    for pay in results:
        for r in pay.result.rules:
            by_rule[r.code]["employee"] += r.employee
            by_rule[r.code]["employer"] += r.employer
    return {
        "employees": len(results),
        "gross_cash": str(sum((x.result.gross_cash for x in results), Decimal(0))),
        "benefits": str(sum((x.result.benefits for x in results), Decimal(0))),
        "total_deductions": str(sum((x.result.total_deductions for x in results), Decimal(0))),
        "net_pay": str(sum((x.result.net_pay for x in results), Decimal(0))),
        "employer_cost": str(sum((x.result.employer_cost for x in results), Decimal(0))),
        "other_deductions": str(sum((x.result.other_deductions for x in results), Decimal(0))),
        "by_rule": {c: {**v, "employee": str(v["employee"]), "employer": str(v["employer"])}
                    for c, v in by_rule.items()}}


def calculate_run(session: Session, run_id: UUID) -> PayrollRun:
    """Work out every payslip (replacing any earlier calculation) and list what needs reviewing. Needs
    'payroll.prepare'."""
    run = _load(session, run_id, lock=True)
    ctx = current_context()
    access.require_company(PAYROLL_PREPARE, run.company_id)
    if run.status not in ("draft", "calculated"):
        raise Conflict(f"This run is {run.status.replace('_', ' ')}, so it cannot be calculated again")
    results, exceptions, active = _compute(session, run)
    people_repo.delete_payslips(session, run.id)
    for pay in results:
        r = pay.result
        slip = Payslip(
            tenant_id=ctx.tenant_id, run_id=run.id, employee_id=pay.employee.id, gross_pay=r.gross_pay,
            taxable_pay=r.taxable_pay, total_deductions=r.total_deductions, net_pay=r.net_pay,
            employer_cost=r.employer_cost, branch_id=pay.employee.branch_id, benefits=r.benefits,
            detail={**r.detail, **pay.detail}, pay_method=pay.pay_method)
        people_repo.add(session, slip)
        for line in r.lines:
            people_repo.add(session, PayslipLine(
                tenant_id=ctx.tenant_id, payslip_id=slip.id, component_code=line.code, kind=line.kind,
                amount=line.amount, rate_table_id=line.table_id, description=line.name))
    run.totals = _totals(results, active)
    run.exceptions = exceptions
    run.status = "calculated"
    run.prepared_by = ctx.user_id
    run.reject_note = None
    run.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "calculate", "people.payroll_run", run.id,
                 {"employees": len(results), "net_pay": run.totals["net_pay"],
                  "blockers": sum(1 for e in exceptions if e["severity"] == "blocker")})
    return run


def blockers(run: PayrollRun) -> list[dict[str, Any]]:
    return [e for e in (run.exceptions or []) if e.get("severity") == "blocker"]


def submit_run(session: Session, run_id: UUID) -> PayrollRun:
    """Send a calculated run for approval. It cannot go while anything blocks it. Needs 'payroll.prepare'."""
    run = _load(session, run_id, lock=True)
    ctx = current_context()
    access.require_company(PAYROLL_PREPARE, run.company_id)
    if run.status != "calculated":
        raise Conflict(f"This run is {run.status.replace('_', ' ')}: only a calculated run can be submitted")
    found = blockers(run)
    if found:
        raise ValidationFailed("Resolve these before submitting: " + "; ".join(e["message"] for e in found))
    run.status = "pending_approval"
    run.prepared_by = ctx.user_id
    run.submitted_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "submit", "people.payroll_run", run.id, {"net_pay": run.totals.get("net_pay")})
    return run


def reject_run(session: Session, run_id: UUID, note: str) -> PayrollRun:
    """Send a run back to its preparer with a reason. Needs 'payroll.approve'."""
    run = _load(session, run_id, lock=True)
    access.require_company(PAYROLL_APPROVE, run.company_id)
    if run.status != "pending_approval":
        raise Conflict(f"This run is {run.status.replace('_', ' ')}, so it cannot be rejected")
    if not note.strip():
        raise ValidationFailed("Say why the run is being sent back")
    run.status = "calculated"
    run.reject_note = note.strip()[:300]
    session.flush()
    audit_record(session, "reject", "people.payroll_run", run.id, {"note": run.reject_note})
    return run


def cancel_run(session: Session, run_id: UUID) -> PayrollRun:
    """Abandon a run that has not been approved. Needs 'payroll.prepare'."""
    run = _load(session, run_id, lock=True)
    access.require_company(PAYROLL_PREPARE, run.company_id)
    if run.status not in ("draft", "calculated", "pending_approval"):
        raise Conflict(f"This run is {run.status.replace('_', ' ')}: an approved run cannot be cancelled")
    run.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", "people.payroll_run", run.id, {"period": f"{run.period_start}"})
    return run


# --------------------------------------------------------------------------- approval and posting
def _groups(session: Session, run: PayrollRun) -> list[dict[str, Any]]:
    """What each branch's payslips come to, for Finance."""
    by_rule = run.totals.get("by_rule", {})
    groups: dict[UUID | None, dict[str, Any]] = {}
    for slip, _ in people_repo.payslips_of(session, run.id):
        g = groups.setdefault(slip.branch_id, {"salaries": Decimal(0), "employer_costs": Decimal(0),
                                               "net_pay": Decimal(0), "other_deductions": Decimal(0),
                                               "payables": {}, "employer_other": Decimal(0)})
        d = slip.detail
        g["salaries"] += Decimal(slip.gross_pay) - Decimal(slip.benefits)
        g["employer_costs"] += slip.employer_cost
        g["net_pay"] += slip.net_pay
        g["other_deductions"] += Decimal(d.get("other_deductions", "0"))
        employer_rules = Decimal(0)
        for code, amounts in d.get("rules", {}).items():
            account = by_rule.get(code, {}).get("payable_account_id")
            owed = Decimal(amounts["employee"]) + Decimal(amounts["employer"])
            g["payables"][account] = g["payables"].get(account, Decimal(0)) + owed
            employer_rules += Decimal(amounts["employer"])
        g["payables"][None] = g["payables"].get(None, Decimal(0)) + slip.employer_cost - employer_rules
    return [{"branch_id": str(b) if b else None, "salaries": str(g["salaries"]),
             "employer_costs": str(g["employer_costs"]), "net_pay": str(g["net_pay"]),
             "other_deductions": str(g["other_deductions"]),
             "payables": [{"account_id": a, "amount": str(v)} for a, v in g["payables"].items() if v]}
            for b, g in groups.items()]


def approve_run(session: Session, run_id: UUID) -> PayrollRun:
    """Approve a submitted run (never its preparer) and post it to the books. The figures are worked out again and must
    equal the ones that were reviewed. Needs 'payroll.approve'."""
    run = _load(session, run_id, lock=True)
    ctx = current_context()
    access.require_company(PAYROLL_APPROVE, run.company_id)
    if run.status != "pending_approval":
        raise Conflict(f"This run is {run.status.replace('_', ' ')}: only a submitted run can be approved")
    if ctx.user_id is not None and run.prepared_by == ctx.user_id:
        raise Forbidden("A payroll run must be approved by someone other than the person who prepared it")
    results, exceptions, _ = _compute(session, run)
    if any(e["severity"] == "blocker" for e in exceptions):
        raise ValidationFailed("Something now blocks this run: " + "; ".join(
            e["message"] for e in exceptions if e["severity"] == "blocker"))
    stored = {s.employee_id: s for s, _ in people_repo.payslips_of(session, run.id)}
    now = {x.employee.id: x.result for x in results}
    if set(stored) != set(now) or any(
            (stored[i].gross_pay, stored[i].net_pay, stored[i].employer_cost) != (
                r.gross_pay, r.net_pay, r.employer_cost) for i, r in now.items()):
        raise Conflict("Pay, attendance, leave or rules changed since this run was calculated: calculate and "
                       "submit it again so the approver sees the current figures")
    run.status = "approved"
    run.approved_by = ctx.user_id
    run.approved_at = datetime.now(UTC)
    for slip in stored.values():
        slip.status = "approved"
    session.flush()
    audit_record(session, "approve", "people.payroll_run", run.id,
                 {"net_pay": run.totals.get("net_pay"), "employees": run.totals.get("employees")})
    publish(session, Event("payroll.approved", "people.payroll_run", run.id, {
        "company_id": run.company_id, "run_id": run.id, "period_start": run.period_start,
        "period_end": run.period_end, "pay_date": run.pay_date, "totals": run.totals,
        "groups": _groups(session, run)}))
    if finance_enabled(session):
        from ziira.modules.finance.public import entry_for_source

        run.journal_entry_id = entry_for_source(session, run.company_id, "payroll", run.id)
        run.status = "posted"
        session.flush()
    return run


# --------------------------------------------------------------------------- paying
def pay_run(session: Session, run_id: UUID, *, paid_on: date | None = None) -> PayrollRun:
    """Record that the salaries were paid. Finance moves the net pay out of the bank, mobile money or cash (what each
    employee's approved payment details say). Needs 'payroll.pay'."""
    run = _load(session, run_id, lock=True)
    ctx = current_context()
    access.require_company(PAYROLL_PAY, run.company_id)
    if run.status not in ("approved", "posted"):
        raise Conflict(f"This run is {run.status.replace('_', ' ')}: only an approved run can be paid")
    day = paid_on or date.today()
    if day < run.period_start:
        raise ValidationFailed("Salaries cannot be paid before the period starts")
    totals: dict[tuple[UUID | None, str], Decimal] = {}
    for slip, _ in people_repo.payslips_of(session, run.id):
        key = (slip.branch_id, slip.pay_method or "other")
        totals[key] = totals.get(key, Decimal(0)) + slip.net_pay
        slip.status = "paid"
    run.status = "paid"
    run.paid_at = datetime.now(UTC)
    run.paid_by = ctx.user_id
    session.flush()
    audit_record(session, "pay", "people.payroll_run", run.id, {"net_pay": run.totals.get("net_pay"), "paid_on": day})
    publish(session, Event("payroll.paid", "people.payroll_run", run.id, {
        "company_id": run.company_id, "run_id": run.id, "period_start": run.period_start,
        "period_end": run.period_end, "paid_on": day,
        "payments": [{"branch_id": str(b) if b else None, "method": m, "amount": str(a)}
                     for (b, m), a in totals.items()]}))
    return run


def payment_file(session: Session, run_id: UUID) -> list[dict[str, str]]:
    """One row per employee to pay by bank or mobile money, with the full account number: for the bank's bulk payment
    upload. Every download is audited. Needs 'payroll.pay'."""
    run = _load(session, run_id)
    access.require_company(PAYROLL_PAY, run.company_id)
    if run.status not in ("approved", "posted", "paid"):
        raise Conflict("Only an approved run has a payment file")
    rows = []
    for slip, employee in people_repo.payslips_of(session, run.id):
        if slip.net_pay <= 0:
            continue
        bank = people_repo.active_bank(session, employee.id)
        rows.append({
            "employee_no": employee.employee_no, "name": employee.full_name,
            "method": bank.method if bank else "none", "bank_name": (bank.bank_name or "") if bank else "",
            "account_no": pay_setup.reveal_account_number(bank) if bank else "", "amount": str(slip.net_pay),
            "reference": f"Salary {run.period_start} to {run.period_end}"})
    audit_record(session, "download_payment_file", "people.payroll_run", run.id, {"rows": len(rows)})
    return rows


# --------------------------------------------------------------------------- reading payslips
def payslips(session: Session, run_id: UUID) -> list[tuple[Payslip, Employee]]:
    run = _load(session, run_id)
    return people_repo.payslips_of(session, run.id)


def get_payslip(session: Session, payslip_id: UUID) -> tuple[Payslip, PayrollRun, Employee, list[PayslipLine]]:
    """A payslip with its lines: for people who work with payroll, or the employee it belongs to once the run has
    been approved."""
    slip = people_repo.get_payslip(session, payslip_id)
    run = people_repo.get_run(session, slip.run_id) if slip else None
    employee = people_repo.get_employee(session, slip.employee_id) if slip else None
    if slip is None or run is None or employee is None:
        raise NotFound("Payslip not found")
    companies = _readable()
    own = employee.user_id is not None and employee.user_id == current_context().user_id
    allowed = (companies is None or run.company_id in companies) or (own and run.status in (
        "approved", "posted", "paid"))
    if not allowed:
        raise NotFound("Payslip not found")
    return slip, run, employee, people_repo.payslip_lines(session, slip.id)


def my_payslips(session: Session) -> list[tuple[Payslip, PayrollRun]]:
    user_id = current_context().user_id
    employee = people_repo.employee_by_user(session, None, user_id) if user_id else None
    return people_repo.payslips_of_employee(session, employee.id) if employee else []
