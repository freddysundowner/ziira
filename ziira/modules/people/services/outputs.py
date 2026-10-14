"""Use cases: what payroll hands out: printable payslips, the yearly tax deduction card of an employee, the return of
each statutory rule (who is owed what, with their registration numbers), and payslips sent by email or SMS.

Nothing here assumes a country. A return is the business's own rule, listed per employee, as a CSV the business adapts
to the form its authority asks for.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.people.domain.payslip_print import PayslipDocument, render_html, render_text
from ziira.modules.people.permissions import PAYROLL_PAY, PAYROLL_VIEW
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import Employee, PayrollRun
from ziira.modules.people.services import access, payroll
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, current_context, send_notification


def _header(session: Session, company_id: UUID) -> list[str]:
    row = session.execute(text("select name, kra_pin from kernel.company where id = :c"),
                          {"c": str(company_id)}).first()
    return [x for x in ((row.name, f"Tax number {row.kra_pin}" if row.kra_pin else None) if row else ()) if x]


def payslip_document(session: Session, payslip_id: UUID, *, copy: bool = False) -> PayslipDocument:
    """A payslip laid out for printing: for payroll staff, or its employee once the run is approved."""
    slip, run, employee, lines = payroll.get_payslip(session, payslip_id)
    branch = session.execute(text("select name from kernel.branch where id = :b"),
                             {"b": str(employee.branch_id)}).scalar() if employee.branch_id else None
    who = [("Name", employee.full_name), ("Employee no", employee.employee_no)]
    if employee.tax_id:
        who.append(("Tax number", employee.tax_id))
    if branch:
        who.append(("Branch", str(branch)))
    earnings = [(x.description or x.component_code, x.amount) for x in lines if x.kind == "earning"]
    benefits = [(x.description or x.component_code, x.amount) for x in lines if x.kind == "benefit"]
    deductions = [(x.description or x.component_code, x.amount) for x in lines if x.kind == "deduction"]
    cash = slip.gross_pay - slip.benefits
    notes = ["Payroll run not yet approved: figures may change"] if run.status in ("draft", "calculated") else []
    return PayslipDocument(
        header=_header(session, run.company_id), title="Payslip", period=f"{run.period_start} to {run.period_end}",
        employee=who, earnings=earnings, benefits=benefits, deductions=deductions,
        totals=[("Gross pay", cash), ("Total deductions", slip.total_deductions), ("NET PAY", slip.net_pay)],
        notes=notes, copy=copy)


def render(doc: PayslipDocument, fmt: str, width: int) -> str:
    if fmt == "text":
        return render_text(doc, width)
    if fmt == "html":
        return render_html(doc)
    raise ValidationFailed(f"Unknown format '{fmt}'")


# --------------------------------------------------------------------------- the yearly tax deduction card
@dataclass(frozen=True)
class CardRow:
    period_start: date
    period_end: date
    gross_pay: Decimal                    # cash pay before deductions
    benefits: Decimal
    taxable_pay: Decimal
    by_rule: dict[str, Decimal]           # what each rule took from the employee
    total_deductions: Decimal
    net_pay: Decimal


@dataclass(frozen=True)
class TaxCard:
    employee: Employee
    year: int
    rules: list[str]                      # the rule codes that appear, for the columns
    rows: list[CardRow]


def tax_card(session: Session, employee_id: UUID, year: int) -> TaxCard:
    """An employee's pay and what each rule took, month by month, for a year of approved runs (the document an employee
    needs for their own tax return). Payroll staff, or the employee themselves."""
    employee = people_repo.get_employee(session, employee_id)
    ctx = current_context()
    own = employee is not None and employee.user_id is not None and employee.user_id == ctx.user_id
    if employee is None or not (own or ctx.can(PAYROLL_VIEW, company_id=employee.company_id)):
        raise NotFound("Employee not found")
    rows: list[CardRow] = []
    codes: set[str] = set()
    for slip, run in sorted(people_repo.payslips_of_employee(session, employee.id), key=lambda x: x[1].period_start):
        if run.period_end.year != year:
            continue
        rules = {c: Decimal(v["employee"]) for c, v in slip.detail.get("rules", {}).items()}
        codes |= set(rules)
        rows.append(CardRow(run.period_start, run.period_end, slip.gross_pay - slip.benefits, slip.benefits,
                            slip.taxable_pay, rules, slip.total_deductions, slip.net_pay))
    return TaxCard(employee, year, sorted(codes), rows)


# --------------------------------------------------------------------------- returns per rule
@dataclass(frozen=True)
class ReturnRow:
    employee_no: str
    name: str
    tax_id: str | None
    registration_no: str | None
    base: Decimal
    employee_amount: Decimal
    employer_amount: Decimal


@dataclass(frozen=True)
class Return:
    run: PayrollRun
    code: str
    name: str
    rows: list[ReturnRow]

    @property
    def employee_total(self) -> Decimal:
        return sum((r.employee_amount for r in self.rows), Decimal(0))

    @property
    def employer_total(self) -> Decimal:
        return sum((r.employer_amount for r in self.rows), Decimal(0))


def statutory_return(session: Session, run_id: UUID, code: str) -> Return:
    """What a run owes under one rule, employee by employee, with the registration numbers they gave. Needs payroll
    access for the company."""
    run = payroll.get_run(session, run_id)                    # payroll staff only: anyone else gets a 404
    if run.status not in ("approved", "posted", "paid"):
        raise Conflict("Returns are made from approved runs")
    code = code.strip().upper()
    info = (run.totals.get("by_rule") or {}).get(code)
    if info is None:
        raise NotFound(f"The run applied no rule {code}")
    rows = []
    for slip, employee in people_repo.payslips_of(session, run.id):
        found: dict[str, Any] | None = slip.detail.get("rules", {}).get(code)
        if found is None:
            continue
        rows.append(ReturnRow(employee.employee_no, employee.full_name, employee.tax_id,
                              (employee.registrations or {}).get(code), Decimal(found["base"]),
                              Decimal(found["employee"]), Decimal(found["employer"])))
    return Return(run, code, str(info.get("name") or code), rows)


# --------------------------------------------------------------------------- sending payslips
@dataclass(frozen=True)
class SendResult:
    queued: int
    already_sent: int
    without_contact: int


def send_payslips(session: Session, run_id: UUID, channel: str) -> SendResult:
    """Queue each employee's payslip by email (the payslip as text) or SMS (a short notice with the net pay). Payslips
    are personal: only send to addresses and numbers you trust. Each payslip is sent once per channel. Needs
    'payroll.pay'."""
    run = payroll.get_run(session, run_id)
    access.require_company(PAYROLL_PAY, run.company_id)
    if channel not in ("email", "sms"):
        raise ValidationFailed("Channel must be email or sms")
    if run.status not in ("approved", "posted", "paid"):
        raise Conflict("Payslips are sent once the run is approved")
    queued = already = missing = 0
    for slip, employee in people_repo.payslips_of(session, run.id):
        recipient = employee.email if channel == "email" else employee.phone
        if not recipient:
            missing += 1
            continue
        period = f"{run.period_start} to {run.period_end}"
        if channel == "email":
            body = render_text(payslip_document(session, slip.id), 48)
            subject = f"Payslip {period}"
        else:
            body = f"Your payslip for {period} is ready. Net pay {slip.net_pay:,.2f}."
            subject = None
        made = send_notification(session, company_id=run.company_id, channel=channel, recipient=recipient,
                                 body=body, subject=subject, ref_type="payslip", ref_id=slip.id,
                                 dedupe_key=f"payslip:{slip.id}:{channel}")
        if made is None:
            already += 1
        else:
            queued += 1
    audit_record(session, "send_payslips", "people.payroll_run", run.id,
                 {"channel": channel, "queued": queued, "without_contact": missing})
    return SendResult(queued, already, missing)

