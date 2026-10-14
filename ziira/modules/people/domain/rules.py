"""Statutory deduction rules: taxes, contributions and levies, defined by each business as data. Pure Python.

Nothing here knows any country's law. A business adds the rules that apply to it (an income tax, a pension, a health
levy, a housing levy ...), each with an effective date, and payroll applies them in order. A rule has a `code`, a
`name`, where it is charged and how:

    base         what it is charged on: `gross` (taxable cash pay), `basic` (basic pay) or `taxable` (taxable pay after
                 the earlier rules that reduce it)
    applies_to   all, resident or non_resident employees
    reduces_taxable   the employee's amount is taken off taxable pay for the rules that follow (so the order matters)
    order        the sequence rules run in (lowest first)
    employee, employer   how much each side pays, each a *method* (or absent when that side pays nothing):
        rate   {rate, base_minimum?, base_maximum?, minimum?, maximum?}   a share of the base, with optional limits
        bands  {bands: [{up_to, rate}, ... last up_to null], credit?}      progressive tax, less a fixed credit (relief)
        fixed  {amount}                                                     the same amount each month

Money and rates are strings in the stored definition, so no value passes through a float. A rule's `payable_account_id`
(optional, on the stored row) is the ledger account the amount is owed through.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from ziira.sdk import ValidationFailed

CENT = Decimal("0.01")
BASES = ("gross", "basic", "taxable")
APPLIES = ("all", "resident", "non_resident")
METHODS = ("rate", "bands", "fixed")
KINDS = ("tax", "contribution", "levy", "other")
ZERO = Decimal(0)


def money(value: Decimal) -> Decimal:
    """Round to a cent, halves up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal(value: Any, what: str, *, high: Decimal | None = None) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValidationFailed(f"{what} must be a number") from None
    if not number.is_finite() or number < 0 or (high is not None and number > high):
        raise ValidationFailed(f"{what} is out of range")
    return number


def _optional(value: Any, what: str) -> Decimal | None:
    return None if value is None else _decimal(value, what)


@dataclass(frozen=True)
class Band:
    up_to: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class Method:
    """How one side's amount is worked out."""

    kind: str                                  # rate | bands | fixed
    rate: Decimal = ZERO
    base_minimum: Decimal | None = None        # below this base nothing is due
    base_maximum: Decimal | None = None        # the base is capped here
    minimum: Decimal | None = None             # the amount is at least this (when there is a base)
    maximum: Decimal | None = None             # and at most this
    bands: tuple[Band, ...] = ()
    credit: Decimal = ZERO                     # fixed relief taken off the tax from bands
    amount: Decimal = ZERO                     # for fixed


@dataclass(frozen=True)
class Rule:
    code: str
    name: str
    kind: str
    order: int
    base: str
    applies_to: str
    reduces_taxable: bool
    employee: Method | None
    employer: Method | None


def _method(raw: Any, side: str) -> Method | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("method") not in METHODS:
        raise ValidationFailed(f"The {side} part needs a method: {', '.join(METHODS)}")
    kind = raw["method"]
    if kind == "fixed":
        return Method("fixed", amount=_decimal(raw.get("amount"), f"The {side} amount"))
    if kind == "rate":
        rate = Method("rate", rate=_decimal(raw.get("rate"), f"The {side} rate", high=Decimal(1)),
                      base_minimum=_optional(raw.get("base_minimum"), "The base minimum"),
                      base_maximum=_optional(raw.get("base_maximum"), "The base maximum"),
                      minimum=_optional(raw.get("minimum"), "The minimum"),
                      maximum=_optional(raw.get("maximum"), "The maximum"))
        if rate.base_maximum is not None and rate.base_minimum is not None and rate.base_maximum < rate.base_minimum:
            raise ValidationFailed("The base maximum is below the base minimum")
        if rate.maximum is not None and rate.minimum is not None and rate.maximum < rate.minimum:
            raise ValidationFailed("The maximum is below the minimum")
        return rate
    items = raw.get("bands")
    if not isinstance(items, list) or not items:
        raise ValidationFailed(f"The {side} part needs a list of bands")
    bands: list[Band] = []
    previous = ZERO
    for index, item in enumerate(items):
        last = index == len(items) - 1
        limit = item.get("up_to") if isinstance(item, dict) else None
        if (limit is None) != last:
            raise ValidationFailed("Only the last band has no upper limit")
        upper = None if limit is None else _decimal(limit, "A band limit")
        if upper is not None and upper <= previous:
            raise ValidationFailed("Band limits must increase")
        bands.append(Band(upper, _decimal(item.get("rate"), "A band rate", high=Decimal(1))))
        previous = upper if upper is not None else previous
    return Method("bands", bands=tuple(bands), credit=_decimal(raw.get("credit", 0), "The credit"))


def parse_rule(code: str, definition: dict[str, Any]) -> Rule:
    """Check a stored definition and turn it into a rule. Raises ValidationFailed saying what is wrong."""
    if not isinstance(definition, dict):
        raise ValidationFailed("A definition is an object")
    name = str(definition.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValidationFailed("A rule needs a name (at most 100 characters)")
    kind = definition.get("kind", "other")
    if kind not in KINDS:
        raise ValidationFailed(f"Kind must be one of: {', '.join(KINDS)}")
    base, applies = definition.get("base", "gross"), definition.get("applies_to", "all")
    if base not in BASES:
        raise ValidationFailed(f"Base must be one of: {', '.join(BASES)}")
    if applies not in APPLIES:
        raise ValidationFailed(f"Applies to must be one of: {', '.join(APPLIES)}")
    order = definition.get("order", 100)
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10000:
        raise ValidationFailed("The order is a whole number from 0 to 10000")
    employee = _method(definition.get("employee"), "employee")
    employer = _method(definition.get("employer"), "employer")
    if employee is None and employer is None:
        raise ValidationFailed("A rule needs an employee part, an employer part, or both")
    reduces = definition.get("reduces_taxable", False)
    if not isinstance(reduces, bool):
        raise ValidationFailed("Reduces taxable pay is true or false")
    if reduces and employee is None:
        raise ValidationFailed("Only a rule with an employee part can reduce taxable pay")
    if reduces and base == "taxable":
        raise ValidationFailed("A rule charged on taxable pay cannot also reduce it")
    return Rule(code, name, kind, order, base, applies, reduces, employee, employer)


@dataclass(frozen=True)
class RuleRow:
    """A stored rule table."""

    id: UUID
    code: str
    effective_from: date
    effective_to: date | None
    definition: dict[str, Any]
    is_verified: bool
    payable_account_id: UUID | None = None


@dataclass(frozen=True)
class ActiveRule:
    rule: Rule
    row: RuleRow


def in_force(rows: list[RuleRow], day: date) -> list[ActiveRule]:
    """The rules that apply on a day: for each code the latest table that has started and not ended, in run order."""
    chosen: dict[str, RuleRow] = {}
    for row in rows:
        started = row.effective_from <= day and (row.effective_to is None or day <= row.effective_to)
        if started and (row.code not in chosen or row.effective_from > chosen[row.code].effective_from):
            chosen[row.code] = row
    active = [ActiveRule(parse_rule(row.code, row.definition), row) for row in chosen.values()]
    return sorted(active, key=lambda a: (a.rule.order, a.rule.code))


def check_new(rows: list[RuleRow], code: str, effective_from: date, effective_to: date | None) -> None:
    for row in rows:
        if row.code == code and row.effective_from == effective_from:
            raise ValidationFailed(f"There is already a {code} rule starting {effective_from}")
    if effective_to is not None and effective_to < effective_from:
        raise ValidationFailed("The end date is before the start date")


def apply_method(method: Method, base: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """The amount a method gives for a base: (amount, tax before credit, credit used). The last two are only
    meaningful for bands. Never negative; nothing is due on a zero base."""
    if method.kind == "fixed":
        return (money(method.amount) if base > 0 else ZERO), ZERO, ZERO
    if base <= 0:
        return ZERO, ZERO, ZERO
    if method.kind == "rate":
        if method.base_minimum is not None and base < method.base_minimum:
            return ZERO, ZERO, ZERO
        charged = min(base, method.base_maximum) if method.base_maximum is not None else base
        amount = money(charged * method.rate)
        if method.minimum is not None:
            amount = max(amount, method.minimum)
        if method.maximum is not None:
            amount = min(amount, method.maximum)
        return min(amount, base), ZERO, ZERO
    tax, floor = ZERO, ZERO
    for band in method.bands:
        if base <= floor:
            break
        top = base if band.up_to is None else min(base, band.up_to)
        tax += (top - floor) * band.rate
        if band.up_to is None:
            break
        floor = band.up_to
    tax = money(tax)
    credit = min(method.credit, tax)
    return tax - credit, tax, credit
