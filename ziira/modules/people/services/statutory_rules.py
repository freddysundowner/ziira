"""Use cases: the business's statutory rules (taxes, contributions, levies), as effective-dated data.

A rule is created once and never edited (a change is a new rule with a later start date, so any past payroll can be
reproduced). A different person from the one who entered it must *verify* it against the official notice before a
payroll run that used it can be approved. A rule that no payslip has used can be deleted. Nothing about any country is
in code.
"""

import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text

from ziira.modules.people.domain import rules as domain
from ziira.modules.people.permissions import (
    EMPLOYEE_PAY_EDIT,
    PAYROLL_APPROVE,
    PAYROLL_PREPARE,
    PAYROLL_RATES,
    PAYROLL_VIEW,
)
from ziira.modules.people.repository import people_repo
from ziira.modules.people.repository.models import PayComponent, PayslipLine, RateTable
from ziira.modules.people.services import access
from ziira.sdk import (
    Conflict,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)

CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
READERS = (PAYROLL_RATES, PAYROLL_VIEW, PAYROLL_PREPARE, PAYROLL_APPROVE, EMPLOYEE_PAY_EDIT)


def _load(session: Session, rule_id: UUID, *, lock: bool = False) -> RateTable:
    query = select(RateTable).where(RateTable.id == rule_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    rule = session.scalars(query).first()
    companies = _readable()
    if rule is None or (companies is not None and rule.company_id not in companies):
        raise NotFound("Rule not found")
    return rule


def _readable() -> set[UUID] | None:
    ctx = current_context()
    found: set[UUID] = set()
    for permission in READERS:
        companies = ctx.companies_with(permission)
        if companies is None:
            return None
        found |= companies
    return found


def rows_for(session: Session, company_id: UUID) -> list[domain.RuleRow]:
    """Every stored table of the company, as plain rows for the domain."""
    return [domain.RuleRow(r.id, r.code, r.effective_from, r.effective_to, r.definition, r.is_verified,
                           r.payable_account_id)
            for r in session.scalars(select(RateTable).where(RateTable.company_id == company_id))]


def list_rules(session: Session, company_id: UUID, *, code: str | None = None) -> list[RateTable]:
    """The business's rules, newest start first. Anyone who works with payroll may read them."""
    companies = _readable()
    if companies is not None and company_id not in companies:
        raise NotFound("Company not found")
    query = select(RateTable).where(RateTable.company_id == company_id).order_by(
        RateTable.code, RateTable.effective_from.desc())
    if code:
        query = query.where(RateTable.code == code.strip().upper())
    return list(session.scalars(query))


def get_rule(session: Session, rule_id: UUID) -> RateTable:
    return _load(session, rule_id)


def create_rule(session: Session, *, company_id: UUID, code: str, effective_from: date, definition: dict[str, Any],
                source_reference: str, effective_to: date | None = None,
                payable_account_id: UUID | None = None) -> RateTable:
    """Add a rule (or a new version of one, from a date). It is saved unverified. Needs 'payroll.rates'."""
    ctx = current_context()
    check_company(session, company_id)
    access.require_company(PAYROLL_RATES, company_id)
    code = code.strip().upper()
    if not CODE.match(code) or code.endswith("_ER") or code in ("BASIC", "UNPAID_LEAVE", "OVERTIME"):
        raise ValidationFailed("A code is 1-20 capital letters, digits or '_', starting with a letter")
    reference = source_reference.strip()
    if len(reference) < 3 or len(reference) > 500:
        raise ValidationFailed("Say where the rule comes from (the law or notice), 3 to 500 characters")
    domain.parse_rule(code, definition)                                   # says what is wrong if it is not valid
    if session.scalar(select(func.count()).select_from(PayComponent).where(
            PayComponent.company_id == company_id, PayComponent.code == code)):
        raise Conflict(f"{code} is already a pay component; choose another code")
    domain.check_new(rows_for(session, company_id), code, effective_from, effective_to)
    rule = RateTable(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=code,
                     effective_from=effective_from, effective_to=effective_to, definition=definition,
                     source_reference=reference, payable_account_id=payable_account_id)
    people_repo.add(session, rule)
    audit_record(session, "create", "people.statutory_rule", rule.id,
                 {"code": code, "effective_from": effective_from, "name": definition.get("name")})
    return rule


def verify_rule(session: Session, rule_id: UUID, *, note: str | None = None) -> RateTable:
    """Say that the rule matches the official notice. Someone other than the person who entered it. Needs
    'payroll.rates'."""
    rule = _load(session, rule_id, lock=True)
    ctx = current_context()
    access.require_company(PAYROLL_RATES, rule.company_id)
    if rule.is_verified:
        raise Conflict("This rule is already verified")
    if ctx.user_id is not None and rule.created_by == ctx.user_id:
        raise Forbidden("A rule must be verified by someone other than the person who entered it")
    who = session.execute(text("select full_name from kernel.app_user where id = :u"),
                          {"u": str(ctx.user_id)}).scalar() if ctx.user_id else None
    rule.is_verified = True
    rule.verified_by = str(who or ctx.user_id or "system")[:200]
    rule.verified_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "verify", "people.statutory_rule", rule.id,
                 {"code": rule.code, "effective_from": rule.effective_from,
                  "note": (note or "").strip()[:300] or None})
    return rule


def delete_rule(session: Session, rule_id: UUID) -> None:
    """Remove a rule no payslip has used (to correct a mistake). Needs 'payroll.rates'."""
    rule = _load(session, rule_id, lock=True)
    access.require_company(PAYROLL_RATES, rule.company_id)
    if session.scalar(select(func.count()).select_from(PayslipLine).where(PayslipLine.rate_table_id == rule.id)):
        raise Conflict("Payslips already used this rule; add a newer version instead")
    audit_record(session, "delete", "people.statutory_rule", rule.id, {"code": rule.code})
    session.delete(rule)
    session.flush()
