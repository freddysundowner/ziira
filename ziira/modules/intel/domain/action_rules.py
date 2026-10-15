"""Rules for the actions Intelligence may propose and carry out. Plain data and checks; no database.

A provider describes the parameters of its action (and the conditions of an automation rule) with a small schema:

    {"properties": {"quantity": {"type": "number", "title": "Quantity", "minimum": "1", "editable": True},
                    "channel": {"type": "string", "enum": ["sms", "email"]}},
     "required": ["quantity"]}

Types: string, integer, number (a decimal, kept as text so money never becomes a float), boolean, uuid, date.
Other keys: title, description, enum, minimum, maximum, max_length, editable (a person may change it before approving;
default true). The same description drives the validation here and the form on screen.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

STATUSES = ("proposed", "approved", "executed", "failed", "rejected", "expired", "cancelled")
LIVE_STATUSES = ("proposed", "approved")
LEVEL_PREPARE, LEVEL_ACT = 3, 4

# Permissions that mean money, prices, credit or stock: a provider that needs one of them may be proposed and
# approved by a person, but never run by a rule, whatever it says about itself.
MONEY_PERMISSIONS = frozenset({
    "prices.manage", "price.override", "credit.approve", "stock.adjust", "stock.approve", "stock.transfer",
    "journal.post_manual", "journal.approve", "period.close", "expenses.approve", "payroll.approve", "payroll.pay",
    "employee.pay_edit", "bills.pay", "bills.approve", "po.approve", "sales.refund", "sales.void", "payments.record",
    "payments.collect", "payments.manage", "recon.match", "close.reopen",
})

# Names that must not appear in the code of an action that runs without a person: posting to the books, moving stock,
# paying, changing a price or a credit limit.
FORBIDDEN_FOR_AUTO = (
    "ziira.modules.finance", "ziira.modules.payments", "ziira.modules.inventory", "post_entry", "post_movement",
    "set_price", "request_credit_change", "set_selling_price", "change_credit_limit", "pay_bill", "refund",
)


@dataclass(frozen=True)
class Proposal:
    """One thing that could be done about a finding: concrete parameters, a plain sentence saying what will happen, and
    the facts behind it (label -> value) so the person approving can check it."""

    params: dict[str, Any]
    description: str
    facts: dict[str, str] = field(default_factory=dict)


class ParamError(ValueError):
    """A parameter is missing or wrong; the message says which and why."""


def _decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ParamError(f"{name} must be a number")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ParamError(f"{name} must be a number") from None
    if not number.is_finite():
        raise ParamError(f"{name} must be a number")
    return number


def _clean(name: str, spec: dict[str, Any], value: Any) -> Any:
    kind = spec.get("type", "string")
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ParamError(f"{name} must be true or false")
        return value
    if kind == "integer":
        number = _decimal(name, value)
        if number != number.to_integral_value():
            raise ParamError(f"{name} must be a whole number")
        out: Any = int(number)
    elif kind == "number":
        number = _decimal(name, value)
        out = format(number.normalize(), "f") if number != 0 else "0"
    elif kind == "uuid":
        try:
            out = str(UUID(str(value)))
        except ValueError:
            raise ParamError(f"{name} must be an identifier") from None
    elif kind == "date":
        try:
            out = date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise ParamError(f"{name} must be a date (YYYY-MM-DD)") from None
    elif kind == "string":
        if not isinstance(value, str):
            raise ParamError(f"{name} must be text")
        out = value.strip()
        if len(out) > int(spec.get("max_length", 500)):
            raise ParamError(f"{name} is too long")
    else:
        raise ParamError(f"{name} has an unknown type '{kind}'")
    if "enum" in spec and out not in spec["enum"]:
        raise ParamError(f"{name} must be one of: {', '.join(str(x) for x in spec['enum'])}")
    if kind in ("integer", "number"):
        number = Decimal(str(out))
        if "minimum" in spec and number < Decimal(str(spec["minimum"])):
            raise ParamError(f"{name} must be at least {spec['minimum']}")
        if "maximum" in spec and number > Decimal(str(spec["maximum"])):
            raise ParamError(f"{name} must be at most {spec['maximum']}")
    return out


def validate_values(schema: dict[str, Any], values: dict[str, Any], *, label: str = "Parameter") -> dict[str, Any]:
    """The values cleaned against the schema (numbers as text, ids and dates as text); raises ParamError. Unknown names
    are refused; missing required ones are named."""
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})
    unknown = sorted(set(values) - set(properties))
    if unknown:
        raise ParamError(f"{label} not known: {', '.join(unknown)}")
    clean: dict[str, Any] = {}
    for name, spec in properties.items():
        if name not in values or values[name] is None or values[name] == "":
            if name in schema.get("required", []):
                raise ParamError(f"{spec.get('title', name)} is needed")
            continue
        clean[name] = _clean(spec.get("title", name), spec, values[name])
    return clean


def apply_edits(schema: dict[str, Any], proposed: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    """The proposal's parameters with a person's changes applied and the whole checked again. A parameter marked
    `editable: false` keeps the proposed value (asking to change it is refused)."""
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})
    merged = dict(proposed)
    for name, value in edits.items():
        if name not in properties:
            raise ParamError(f"Parameter not known: {name}")
        spec = properties[name]
        if not spec.get("editable", True):
            if str(value) != str(proposed.get(name)):
                raise ParamError(f"{spec.get('title', name)} cannot be changed here")
            continue
        merged[name] = value
    return validate_values(schema, merged)


def params_hash(params: dict[str, Any]) -> str:
    """Identifies a proposal's parameters, so the same proposal made twice is one."""
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:32]


def check_type_name(type_name: str) -> bool:
    """An action type is "<unit>.<name>" in lower case."""
    unit, _, name = type_name.partition(".")
    return bool(unit) and bool(name) and type_name == type_name.lower() and " " not in type_name


def rule_covers(conditions: dict[str, Any], *, finding_branch: UUID | None, finding_amount: Decimal | None) -> bool:
    """The generic conditions every provider's rule may use: `branch_id` (only findings of that branch) and
    `max_amount` (only when the money at stake is no more than this; an unknown amount counts as nothing)."""
    wanted = conditions.get("branch_id")
    if wanted is not None and (finding_branch is None or str(finding_branch) != str(wanted)):
        return False
    limit = conditions.get("max_amount")
    return not (limit is not None and (finding_amount or Decimal(0)) > Decimal(str(limit)))


def auto_refusal(*, auto_allowed: bool, needs_permission: str) -> str | None:
    """Why a provider may never run without a person, or None when it may (under an owner's rule)."""
    if not auto_allowed:
        return "This action always needs a person's approval"
    if needs_permission in MONEY_PERMISSIONS:
        return "This action involves money, prices, credit or stock and always needs a person's approval"
    return None
