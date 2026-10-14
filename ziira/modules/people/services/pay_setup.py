"""Use cases: what an employee is paid and where it goes.

Basic pay (employment terms) and salary bank details are versioned and *proposed* by one person and *approved* by
another (both hold `employee.pay_edit` for the whole company); nothing is used by payroll until approved. Recurring and
one-off pay items (allowances, loans, SACCO, union dues) are changed by the same permission and audited. Statutory
deductions are never items: they come from the business's statutory rules.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from ziira.modules.people.domain import identity
from ziira.modules.people.permissions import EMPLOYEE_PAY_EDIT
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import (
    Employee,
    EmployeeBankAccount,
    EmployeePayItem,
    EmploymentTerms,
    PayComponent,
    RateTable,
)
from ziira.modules.people.services import access
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
    decrypt_text,
    encrypt_text,
    publish,
)

KINDS = ("earning", "deduction", "benefit", "employer_contribution")
CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
RESERVED = {"BASIC", "UNPAID_LEAVE", "OVERTIME"}


def _pay_employee(session: Session, employee_id: UUID, *, lock: bool = False) -> Employee:
    """The employee, for a user who may see and change pay (company-wide 'employee.pay_edit')."""
    employee = access.load_employee(session, employee_id, lock=lock)
    access.require_company(EMPLOYEE_PAY_EDIT, employee.company_id)
    return employee


# --------------------------------------------------------------------------- pay components
def create_component(session: Session, *, company_id: UUID, code: str, name: str, kind: str,
                     is_taxable: bool = True) -> PayComponent:
    """Define a kind of pay item (HOUSE allowance, SACCO deduction ...). Needs 'employee.pay_edit'."""
    ctx = current_context()
    check_company(session, company_id)
    access.require_company(EMPLOYEE_PAY_EDIT, company_id)
    code = code.strip().upper()
    name = name.strip()
    if not code or len(code) > 20 or not set(code) <= CODE_CHARS or code[0].isdigit():
        raise ValidationFailed("A code is 1-20 capital letters, digits or '_', starting with a letter")
    if code in RESERVED or code.endswith("_ER"):
        raise ValidationFailed(f"{code} is used by payroll itself")
    if session.scalar(select(func.count()).select_from(RateTable).where(
            RateTable.company_id == company_id, RateTable.code == code)):
        raise Conflict(f"{code} is already a statutory rule; choose another code")
    if not name or len(name) > 100:
        raise ValidationFailed("A component needs a name (at most 100 characters)")
    if kind not in KINDS:
        raise ValidationFailed(f"Kind must be one of: {', '.join(KINDS)}")
    if people_repo.component_by_code(session, company_id, code) is not None:
        raise Conflict(f"There is already a component with code {code}")
    component = PayComponent(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=code,
                             name=name, kind=kind, is_taxable=is_taxable, is_statutory=False)
    people_repo.add(session, component)
    audit_record(session, "create", "people.pay_component", component.id, {"code": code, "kind": kind})
    return component


def list_components(session: Session, company_id: UUID | None = None) -> list[PayComponent]:
    return people_repo.list_components(session, access.visible_companies(), company_id)


# --------------------------------------------------------------------------- employment terms (basic pay)
def list_terms(session: Session, employee_id: UUID) -> list[EmploymentTerms]:
    _pay_employee(session, employee_id)
    return people_repo.terms_of(session, employee_id)


def propose_terms(session: Session, employee_id: UUID, *, basic_pay: Decimal, valid_from: date,
                  note: str | None = None) -> EmploymentTerms:
    """Propose basic pay from a date. It changes nothing until someone else approves it. Needs 'employee.pay_edit'."""
    employee = _pay_employee(session, employee_id, lock=True)
    ctx = current_context()
    if employee.status == "terminated":
        raise Conflict("This employee has left")
    if basic_pay < 0 or basic_pay > Decimal("100000000"):
        raise ValidationFailed("Basic pay must be between 0 and 100,000,000")
    if valid_from < employee.hire_date:
        raise ValidationFailed("Pay cannot start before the employee was hired")
    if people_repo.pending_terms(session, employee_id) is not None:
        raise Conflict("A pay change for this employee is already waiting for approval")
    latest = next((t for t in people_repo.terms_of(session, employee_id)
                   if t.approved_by is not None and not t.rejected), None)
    if latest is not None and valid_from <= latest.valid_from:
        raise ValidationFailed(f"The new pay must start after the current terms began ({latest.valid_from})")
    terms = EmploymentTerms(tenant_id=ctx.tenant_id, created_by=ctx.user_id, employee_id=employee_id,
                            basic_pay=basic_pay, valid_from=valid_from, note=(note or "").strip()[:300] or None)
    people_repo.add(session, terms)
    audit_record(session, "propose_pay", "people.employment_terms", terms.id,
                 {"employee": employee.employee_no, "basic_pay": basic_pay, "valid_from": valid_from})
    return terms


def decide_terms(session: Session, terms_id: UUID, *, approve: bool) -> EmploymentTerms:
    """Approve or reject proposed pay. The approver cannot be the proposer. Needs 'employee.pay_edit'."""
    terms = people_repo.get_terms(session, terms_id, lock=True)
    if terms is None:
        raise NotFound("Pay change not found")
    employee = _pay_employee(session, terms.employee_id)
    ctx = current_context()
    if terms.approved_by is not None or terms.rejected:
        raise Conflict("This pay change has already been decided")
    if ctx.user_id is not None and terms.created_by == ctx.user_id:
        raise Forbidden("A pay change must be approved by someone other than the person who proposed it")
    if not approve:
        terms.rejected = True
        session.flush()
        audit_record(session, "reject_pay", "people.employment_terms", terms.id, {"employee": employee.employee_no})
        return terms
    current = people_repo.terms_in_force(session, terms.employee_id, terms.valid_from)
    for old in people_repo.terms_of(session, terms.employee_id):
        if old.approved_by is not None and not old.rejected and old.valid_to is None and old.id != terms.id:
            old.valid_to = terms.valid_from - timedelta(days=1)
    terms.approved_by = ctx.user_id
    session.flush()
    audit_record(session, "approve_pay", "people.employment_terms", terms.id,
                 {"employee": employee.employee_no, "basic_pay": terms.basic_pay,
                  "previous": current.basic_pay if current else None})
    publish(session, Event("employee.pay_changed", "people.employee", employee.id, {
        "company_id": employee.company_id, "employee_id": employee.id, "basic_pay": terms.basic_pay,
        "valid_from": terms.valid_from}))
    return terms


# --------------------------------------------------------------------------- pay items
def list_pay_items(session: Session, employee_id: UUID) -> list[EmployeePayItem]:
    _pay_employee(session, employee_id)
    return people_repo.pay_items_of(session, employee_id)


def add_pay_item(session: Session, employee_id: UUID, *, component_id: UUID, amount: Decimal, valid_from: date,
                 recurring: bool = True, valid_to: date | None = None,
                 description: str | None = None) -> EmployeePayItem:
    """Give an employee an allowance, deduction, benefit or employer contribution. Recurring items apply every month
    they are valid; a one-off applies in the month of its date. Needs 'employee.pay_edit'."""
    employee = _pay_employee(session, employee_id, lock=True)
    ctx = current_context()
    component = people_repo.get_component(session, component_id)
    if component is None or component.company_id != employee.company_id:
        raise ValidationFailed("Pay component not found in this company")
    if component.is_statutory:
        raise ValidationFailed("Statutory deductions are calculated from the rate tables, not entered")
    if amount <= 0 or amount > Decimal("100000000"):
        raise ValidationFailed("An amount must be more than 0")
    if valid_to is not None and (recurring is False or valid_to < valid_from):
        raise ValidationFailed("A one-off item has no end date, and an end date is not before the start")
    item = EmployeePayItem(tenant_id=ctx.tenant_id, created_by=ctx.user_id, employee_id=employee_id,
                           component_id=component_id, amount=amount, recurring=recurring, valid_from=valid_from,
                           valid_to=valid_to, description=(description or "").strip()[:200] or None)
    people_repo.add(session, item)
    audit_record(session, "add_pay_item", "people.employee_pay_item", item.id,
                 {"employee": employee.employee_no, "component": component.code, "amount": amount})
    publish(session, Event("employee.pay_changed", "people.employee", employee.id, {
        "company_id": employee.company_id, "employee_id": employee.id, "component": component.code,
        "amount": amount, "valid_from": valid_from}))
    return item


def end_pay_item(session: Session, item_id: UUID, *, valid_to: date) -> EmployeePayItem:
    """Stop a recurring item after a date (history is kept). Needs 'employee.pay_edit'."""
    item = people_repo.get_pay_item(session, item_id, lock=True)
    if item is None:
        raise NotFound("Pay item not found")
    employee = _pay_employee(session, item.employee_id)
    if not item.recurring:
        raise ValidationFailed("A one-off item cannot be ended; it applies once")
    if item.valid_to is not None and item.valid_to <= valid_to:
        raise Conflict(f"This item already ends on {item.valid_to}")
    if valid_to < item.valid_from:
        raise ValidationFailed("It cannot end before it began")
    item.valid_to = valid_to
    session.flush()
    audit_record(session, "end_pay_item", "people.employee_pay_item", item.id,
                 {"employee": employee.employee_no, "valid_to": valid_to})
    return item


# --------------------------------------------------------------------------- salary bank details
def list_banks(session: Session, employee_id: UUID) -> list[EmployeeBankAccount]:
    _pay_employee(session, employee_id)
    return people_repo.banks_of(session, employee_id)


def propose_bank(session: Session, employee_id: UUID, *, method: str, account_no: str,
                 bank_name: str | None = None) -> EmployeeBankAccount:
    """Propose where the salary is paid. Changing bank details is the classic route for payroll fraud, so they change
    nothing until someone other than the proposer approves them. Needs 'employee.pay_edit'."""
    employee = _pay_employee(session, employee_id, lock=True)
    ctx = current_context()
    if employee.status == "terminated":
        raise Conflict("This employee has left")
    if method not in ("bank", "mobile_money"):
        raise ValidationFailed("Method must be 'bank' or 'mobile_money'")
    if method == "bank" and not (bank_name and bank_name.strip()):
        raise ValidationFailed("A bank account needs the bank's name")
    number = identity.account_number(method, account_no, str(company_setting(session, employee.company_id,
                                                                              "phone_country_code")))
    if people_repo.pending_bank(session, employee_id) is not None:
        raise Conflict("A change to this employee's payment details is already waiting for approval")
    account = EmployeeBankAccount(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, employee_id=employee_id, method=method,
        bank_name=(bank_name or "").strip()[:100] or None, account_no_ciphertext=encrypt_text(number).encode(),
        account_no_masked=identity.mask(number, 4), valid_from=datetime.now(UTC))
    people_repo.add(session, account)
    audit_record(session, "propose_bank", "people.employee_bank_account", account.id,
                 {"employee": employee.employee_no, "method": method, "account": account.account_no_masked})
    return account


def decide_bank(session: Session, bank_id: UUID, *, approve: bool) -> EmployeeBankAccount:
    """Approve or reject proposed payment details. The approver cannot be the proposer. Needs 'employee.pay_edit'."""
    account = people_repo.get_bank(session, bank_id, lock=True)
    if account is None:
        raise NotFound("Payment details not found")
    employee = _pay_employee(session, account.employee_id)
    ctx = current_context()
    if account.approved_by is not None or account.rejected:
        raise Conflict("These payment details have already been decided")
    if ctx.user_id is not None and account.created_by == ctx.user_id:
        raise Forbidden("Payment details must be approved by someone other than the person who proposed them")
    if not approve:
        account.rejected = True
        session.flush()
        audit_record(session, "reject_bank", "people.employee_bank_account", account.id,
                     {"employee": employee.employee_no})
        return account
    now = datetime.now(UTC)
    old = people_repo.active_bank(session, account.employee_id)
    if old is not None:
        old.valid_to = now
    account.approved_by = ctx.user_id
    account.valid_from = now
    session.flush()
    audit_record(session, "approve_bank", "people.employee_bank_account", account.id,
                 {"employee": employee.employee_no, "account": account.account_no_masked})
    publish(session, Event("employee.bank_changed", "people.employee", employee.id, {
        "company_id": employee.company_id, "employee_id": employee.id, "method": account.method,
        "account": account.account_no_masked}))
    return account


def reveal_account_number(account: EmployeeBankAccount) -> str:
    """The full account number, for the payment file only (never returned by the API)."""
    if account.account_no_ciphertext is None:
        raise ValidationFailed("These payment details have no account number")
    return decrypt_text(bytes(account.account_no_ciphertext).decode())
