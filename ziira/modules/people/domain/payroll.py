"""The payroll calculation for one employee and one month. Pure Python: no database, no HTTP.

Pipeline (specification section 12), with the statutory rules supplied as data (domain/rules.py):
    1  gross pay            = basic + allowances + overtime - unpaid leave   (cash; benefits in kind are added to tax)
    2  taxable pay starts as the statutory base (gross pay less non-taxable allowances) plus taxable benefits
    3  each rule in order: it is charged on its base, the employee's amount is taken off taxable pay if the rule says so
       (so which deductions reduce tax, and in what order, is part of the rule definitions)
    4  other deductions     = loans, advances, SACCO, union dues and so on, taken after the rules
    5  net pay              = gross pay - all deductions
    6  employer costs       = the rules' employer amounts + other employer contributions

An amount a rule takes from the employee is never more than the pay still available (it is reported as capped).
Amounts are rounded to the cent, halves up.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ziira.modules.people.domain.rules import ActiveRule, apply_method, money

ZERO = Decimal(0)


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    amount: Decimal
    taxable: bool = True


@dataclass(frozen=True)
class PayInput:
    basic: Decimal
    earnings: tuple[Item, ...] = ()           # allowances, overtime, one-off pay: paid in cash
    benefits: tuple[Item, ...] = ()           # taxable benefits in kind: added to taxable pay, not paid out
    unpaid_leave: Decimal = ZERO              # what unpaid leave takes off the pay
    deductions: tuple[Item, ...] = ()         # loans, advances, SACCO, union dues: taken after the rules
    employer_items: tuple[Item, ...] = ()     # other employer contributions
    resident: bool = True
    exempt: frozenset[str] = frozenset()      # codes of rules this employee is exempt from


@dataclass(frozen=True)
class Line:
    code: str
    name: str
    kind: str                                 # earning | deduction | benefit | employer_contribution
    amount: Decimal
    table_id: Any = None                      # the stored rule that produced it, for rule lines


@dataclass(frozen=True)
class RuleResult:
    code: str
    name: str
    kind: str                                 # tax | contribution | levy | other
    base: Decimal                             # what it was charged on
    employee: Decimal
    employer: Decimal
    before_credit: Decimal                    # tax by bands before the credit (equals employee when there is none)
    credit: Decimal
    capped: bool                              # the employee's amount was limited to the pay available
    table_id: Any = None


@dataclass(frozen=True)
class PayResult:
    lines: list[Line]
    rules: list[RuleResult]
    gross_cash: Decimal                       # what is paid before deductions
    benefits: Decimal
    gross_pay: Decimal                        # cash pay plus taxable benefits (the specification's gross)
    statutory_base: Decimal
    taxable_pay: Decimal                      # after the rules that reduce it
    statutory_employee: Decimal               # everything the rules took from the employee
    other_deductions: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    employer_statutory: Decimal
    employer_cost: Decimal
    detail: dict[str, Any] = field(default_factory=dict)

    def rule(self, code: str) -> RuleResult | None:
        return next((r for r in self.rules if r.code == code), None)


def calculate(pay: PayInput, rules: list[ActiveRule]) -> PayResult:
    """One employee's pay for a month, by the pipeline above."""
    lines: list[Line] = [Line("BASIC", "Basic pay", "earning", money(pay.basic))]
    for item in pay.earnings:
        lines.append(Line(item.code, item.name, "earning", money(item.amount)))
    if pay.unpaid_leave:
        lines.append(Line("UNPAID_LEAVE", "Unpaid leave", "earning", -money(pay.unpaid_leave)))
    gross_cash = sum((x.amount for x in lines), ZERO)
    non_taxable = sum((money(x.amount) for x in pay.earnings if not x.taxable), ZERO)
    benefits = sum((money(x.amount) for x in pay.benefits), ZERO)
    for item in pay.benefits:
        lines.append(Line(item.code, item.name, "benefit", money(item.amount)))
    base = max(gross_cash - non_taxable, ZERO)
    basic = max(money(pay.basic) - pay.unpaid_leave, ZERO)

    taxable = base + benefits
    available = gross_cash
    results: list[RuleResult] = []
    for active in rules:
        rule = active.rule
        if rule.code in pay.exempt or (rule.applies_to == "resident" and not pay.resident) \
                or (rule.applies_to == "non_resident" and pay.resident):
            continue
        charged = {"gross": base, "basic": basic, "taxable": taxable}[rule.base]
        employee = before = credit = ZERO
        capped = False
        if rule.employee is not None:
            employee, before, credit = apply_method(rule.employee, charged)
            if employee > available:
                employee, capped = max(available, ZERO), True
            available -= employee
        employer = apply_method(rule.employer, charged)[0] if rule.employer is not None else ZERO
        if rule.reduces_taxable:
            taxable = max(taxable - employee, ZERO)
        results.append(RuleResult(rule.code, rule.name, rule.kind, charged, employee, employer,
                                  before or employee, credit, capped, active.row.id))

    for r in results:
        if any(a.rule.code == r.code and a.rule.employee is not None for a in rules):
            lines.append(Line(r.code, r.name, "deduction", r.employee, r.table_id))
    other = sum((money(x.amount) for x in pay.deductions), ZERO)
    for item in pay.deductions:
        lines.append(Line(item.code, item.name, "deduction", money(item.amount)))
    for r in results:
        if any(a.rule.code == r.code and a.rule.employer is not None for a in rules):
            lines.append(Line(f"{r.code}_ER", f"{r.name} (employer)", "employer_contribution", r.employer,
                              r.table_id))
    employer_other = sum((money(x.amount) for x in pay.employer_items), ZERO)
    for item in pay.employer_items:
        lines.append(Line(item.code, item.name, "employer_contribution", money(item.amount)))

    statutory = sum((r.employee for r in results), ZERO)
    employer_statutory = sum((r.employer for r in results), ZERO)
    total_deductions = statutory + other
    return PayResult(
        lines=lines, rules=results, gross_cash=gross_cash, benefits=benefits, gross_pay=gross_cash + benefits,
        statutory_base=base, taxable_pay=taxable, statutory_employee=statutory, other_deductions=other,
        total_deductions=total_deductions, net_pay=gross_cash - total_deductions,
        employer_statutory=employer_statutory, employer_cost=employer_statutory + employer_other,
        detail={"statutory_base": str(base), "rules": {
            r.code: {"base": str(r.base), "employee": str(r.employee), "employer": str(r.employer),
                     "before_credit": str(r.before_credit), "credit": str(r.credit), "capped": r.capped}
            for r in results}})


def prorate(amount: Decimal, days_worked: int, days_in_period: int) -> Decimal:
    """A month's amount for part of the month (an employee who joined or left in it), by calendar days."""
    if days_in_period <= 0 or days_worked >= days_in_period:
        return amount
    return money(amount * max(days_worked, 0) / days_in_period)


def unpaid_leave_amount(basic: Decimal, days: Decimal, divisor: int) -> Decimal:
    """What unpaid leave takes off: the days times a day's pay (basic over the company's day divisor, 30 by default)."""
    return min(money(basic / divisor * days), basic)


def overtime_pay(basic: Decimal, hours: Decimal, multiplier: Decimal, hourly_divisor: Decimal) -> Decimal:
    """Overtime: hours times an hour's pay (basic over the hours divisor) times the multiplier."""
    return money(basic / hourly_divisor * hours * multiplier)
