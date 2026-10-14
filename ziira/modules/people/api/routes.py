"""HTTP endpoints of the People, HR and Payroll module. Routes only convert HTTP to service calls."""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from ziira.modules.people.api import schemas as sc
from ziira.modules.people.permissions import (
    EMPLOYEE_PAY_EDIT,
    EMPLOYEES_MANAGE,
    PAYROLL_RATES,
)
from ziira.modules.people.repository.models import Employee
from ziira.modules.people.services import access, employees, pay_setup, statutory_rules
from ziira.sdk import Forbidden, RequestContext, Session, db_session, page_limit, page_offset, request_context

router = APIRouter()
NO_CONTENT = status.HTTP_204_NO_CONTENT


def any_of(*permissions: str) -> Callable[[RequestContext], RequestContext]:
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


READ = [Depends(any_of(*access.READERS))]
MANAGE = [Depends(any_of(EMPLOYEES_MANAGE))]
PAY = [Depends(any_of(EMPLOYEE_PAY_EDIT))]
RULES_READ = [Depends(any_of(*statutory_rules.READERS))]
RULES_WRITE = [Depends(any_of(PAYROLL_RATES))]


# --------------------------------------------------------------------------- departments and employees
@router.post("/departments", response_model=sc.DepartmentOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_department(body: sc.DepartmentIn, session: Session = Depends(db_session)) -> object:
    return employees.create_department(session, company_id=body.company_id, name=body.name)


@router.get("/departments", response_model=list[sc.DepartmentOut], dependencies=READ)
def get_departments(company_id: UUID | None = None, session: Session = Depends(db_session)) -> object:
    return employees.list_departments(session, company_id)


def _employee_out(e: Employee) -> sc.EmployeeOut:
    return sc.EmployeeOut(
        id=e.id, company_id=e.company_id, branch_id=e.branch_id, department_id=e.department_id, user_id=e.user_id,
        employee_no=e.employee_no, full_name=e.full_name, national_id_masked=employees.masked_id(e), tax_id=e.tax_id,
        registrations=dict(e.registrations or {}), exempt_rules=list(e.exempt_rules or []), phone=e.phone,
        email=e.email, hire_date=e.hire_date, termination_date=e.termination_date, status=e.status,
        residency=e.residency, is_director=e.is_director)


@router.post("/employees", response_model=sc.EmployeeOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
def post_employee(body: sc.EmployeeIn, session: Session = Depends(db_session)) -> object:
    return _employee_out(employees.create_employee(session, **body.model_dump()))


@router.get("/employees", response_model=list[sc.EmployeeOut], dependencies=READ)
def get_employees(company_id: UUID | None = None, branch_id: UUID | None = None, department_id: UUID | None = None,
                  status_: str | None = Query(default=None, alias="status", pattern="^(active|on_leave|terminated)$"),
                  search: str | None = Query(default=None, max_length=100), limit: int = page_limit(50),
                  offset: int = page_offset(), session: Session = Depends(db_session)) -> object:
    found = employees.list_employees(session, company_id=company_id, branch_id=branch_id,
                                     department_id=department_id, status=status_, search=search, limit=limit,
                                     offset=offset)
    return [_employee_out(e) for e in found]


@router.get("/employees/{employee_id}", response_model=sc.EmployeeOut, dependencies=READ)
def get_employee(employee_id: UUID, session: Session = Depends(db_session)) -> object:
    return _employee_out(employees.get_employee(session, employee_id))


@router.patch("/employees/{employee_id}", response_model=sc.EmployeeOut, dependencies=MANAGE)
def patch_employee(employee_id: UUID, body: sc.EmployeeUpdateIn, session: Session = Depends(db_session)) -> object:
    return _employee_out(employees.update_employee(session, employee_id, body.model_dump(exclude_unset=True)))


@router.post("/employees/{employee_id}/terminate", response_model=sc.EmployeeOut, dependencies=MANAGE)
def post_terminate(employee_id: UUID, body: sc.TerminateIn, session: Session = Depends(db_session)) -> object:
    return _employee_out(employees.terminate_employee(session, employee_id, termination_date=body.termination_date,
                                                      reason=body.reason))


# --------------------------------------------------------------------------- pay components, terms, items, bank
@router.post("/pay-components", response_model=sc.ComponentOut, status_code=status.HTTP_201_CREATED, dependencies=PAY)
def post_component(body: sc.ComponentIn, session: Session = Depends(db_session)) -> object:
    return pay_setup.create_component(session, company_id=body.company_id, code=body.code, name=body.name,
                                      kind=body.kind, is_taxable=body.is_taxable)


@router.get("/pay-components", response_model=list[sc.ComponentOut], dependencies=RULES_READ)
def get_components(company_id: UUID | None = None, session: Session = Depends(db_session)) -> object:
    return pay_setup.list_components(session, company_id)


@router.get("/employees/{employee_id}/terms", response_model=list[sc.TermsOut], dependencies=PAY)
def get_terms(employee_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.list_terms(session, employee_id)


@router.post("/employees/{employee_id}/terms", response_model=sc.TermsOut, status_code=status.HTTP_201_CREATED,
             dependencies=PAY)
def post_terms(employee_id: UUID, body: sc.TermsIn, session: Session = Depends(db_session)) -> object:
    """Propose basic pay from a date; someone else approves it."""
    return pay_setup.propose_terms(session, employee_id, basic_pay=body.basic_pay, valid_from=body.valid_from,
                                   note=body.note)


@router.post("/terms/{terms_id}/approve", response_model=sc.TermsOut, dependencies=PAY)
def post_approve_terms(terms_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.decide_terms(session, terms_id, approve=True)


@router.post("/terms/{terms_id}/reject", response_model=sc.TermsOut, dependencies=PAY)
def post_reject_terms(terms_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.decide_terms(session, terms_id, approve=False)


@router.get("/employees/{employee_id}/pay-items", response_model=list[sc.PayItemOut], dependencies=PAY)
def get_pay_items(employee_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.list_pay_items(session, employee_id)


@router.post("/employees/{employee_id}/pay-items", response_model=sc.PayItemOut, status_code=status.HTTP_201_CREATED,
             dependencies=PAY)
def post_pay_item(employee_id: UUID, body: sc.PayItemIn, session: Session = Depends(db_session)) -> object:
    return pay_setup.add_pay_item(session, employee_id, component_id=body.component_id, amount=body.amount,
                                  valid_from=body.valid_from, recurring=body.recurring, valid_to=body.valid_to,
                                  description=body.description)


@router.post("/pay-items/{item_id}/end", response_model=sc.PayItemOut, dependencies=PAY)
def post_end_pay_item(item_id: UUID, body: sc.PayItemEndIn, session: Session = Depends(db_session)) -> object:
    return pay_setup.end_pay_item(session, item_id, valid_to=body.valid_to)


@router.get("/employees/{employee_id}/bank-accounts", response_model=list[sc.BankOut], dependencies=PAY)
def get_banks(employee_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.list_banks(session, employee_id)


@router.post("/employees/{employee_id}/bank-accounts", response_model=sc.BankOut,
             status_code=status.HTTP_201_CREATED, dependencies=PAY)
def post_bank(employee_id: UUID, body: sc.BankIn, session: Session = Depends(db_session)) -> object:
    """Propose where the salary is paid; someone else approves it."""
    return pay_setup.propose_bank(session, employee_id, method=body.method, account_no=body.account_no,
                                  bank_name=body.bank_name)


@router.post("/bank-accounts/{bank_id}/approve", response_model=sc.BankOut, dependencies=PAY)
def post_approve_bank(bank_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.decide_bank(session, bank_id, approve=True)


@router.post("/bank-accounts/{bank_id}/reject", response_model=sc.BankOut, dependencies=PAY)
def post_reject_bank(bank_id: UUID, session: Session = Depends(db_session)) -> object:
    return pay_setup.decide_bank(session, bank_id, approve=False)


# --------------------------------------------------------------------------- statutory rules
@router.post("/rules", response_model=sc.RuleOut, status_code=status.HTTP_201_CREATED, dependencies=RULES_WRITE)
def post_rule(body: sc.RuleIn, session: Session = Depends(db_session)) -> object:
    """Define a tax, contribution or levy (or a new version of one from a date). Saved unverified."""
    return statutory_rules.create_rule(
        session, company_id=body.company_id, code=body.code, effective_from=body.effective_from,
        effective_to=body.effective_to, definition=body.definition, source_reference=body.source_reference,
        payable_account_id=body.payable_account_id)


@router.get("/rules", response_model=list[sc.RuleOut], dependencies=RULES_READ)
def get_rules(company_id: UUID, code: str | None = Query(default=None, max_length=20),
              session: Session = Depends(db_session)) -> object:
    return statutory_rules.list_rules(session, company_id, code=code)


@router.get("/rules/{rule_id}", response_model=sc.RuleOut, dependencies=RULES_READ)
def get_rule(rule_id: UUID, session: Session = Depends(db_session)) -> object:
    return statutory_rules.get_rule(session, rule_id)


@router.post("/rules/{rule_id}/verify", response_model=sc.RuleOut, dependencies=RULES_WRITE)
def post_verify_rule(rule_id: UUID, body: sc.VerifyIn, session: Session = Depends(db_session)) -> object:
    """Confirm the rule matches the official notice (someone other than the person who entered it)."""
    return statutory_rules.verify_rule(session, rule_id, note=body.note)


@router.delete("/rules/{rule_id}", status_code=NO_CONTENT, dependencies=RULES_WRITE)
def delete_rule(rule_id: UUID, session: Session = Depends(db_session)) -> None:
    statutory_rules.delete_rule(session, rule_id)

