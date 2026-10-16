"""The platform owner's settings (`master.platform_setting`): who the vendor is on an invoice, tax lines, payment
instructions, the dunning schedule, proration, retention and the default plan.

Each key has a default and a validator. Rates, days and wording are the vendor's data, never code (rule 15); the
defaults
below are only day counts and empty text, never a country, a currency or a tax rate.
"""

import json
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text

from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed

DEFAULT_DUNNING: dict[str, Any] = {
    "reminders": [-7, 0, 3, 7],  # days from the due date (negative = before) on which a reminder is emailed
    "past_due_after_days": 1,  # days after the due date at which the subscription is marked past due
    "grace_after_days": 7,  # ... and at which it enters the grace period
    "suspend_after_days": 21,  # ... and at which it is suspended
    "expire_after_days": 90,  # days suspended after which it is marked expired
}


def _days(value: Any, what: str, low: int = 0, high: int = 3650) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationFailed(f"{what} must be a whole number of days") from None
    if not low <= number <= high:
        raise ValidationFailed(f"{what} must be from {low} to {high}")
    return number


def _text(limit: int, what: str, *, allow_empty: bool = True) -> Callable[[Any], str]:
    def parse(value: Any) -> str:
        clean = str(value if value is not None else "").strip()
        if not clean and not allow_empty:
            raise ValidationFailed(f"{what} cannot be empty")
        if len(clean) > limit:
            raise ValidationFailed(f"{what} is at most {limit} characters")
        return clean

    return parse


def _vendor(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationFailed("Vendor details are name, address, tax number, email and phone")
    keys = ("name", "address", "tax_id", "email", "phone")
    unknown = set(value) - set(keys)
    if unknown:
        raise ValidationFailed("Vendor details have: " + ", ".join(keys))
    return {k: _text(300, k)(value.get(k, "")) for k in keys}


def _tax_lines(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 5:
        raise ValidationFailed("Tax lines are a list of at most 5: a name and a rate in percent")
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"name", "rate_percent"}:
            raise ValidationFailed("A tax line has a name and rate_percent")
        name = _text(60, "Tax name", allow_empty=False)(item.get("name"))
        try:
            rate = Decimal(str(item.get("rate_percent")))
        except InvalidOperation:
            raise ValidationFailed("A tax rate is a number such as 16 or 7.5") from None
        if not Decimal(0) <= rate <= Decimal(100):
            raise ValidationFailed("A tax rate is from 0 to 100 percent")
        out.append({"name": name, "rate_percent": format(rate.normalize(), "f")})
    return out


def _dunning(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(DEFAULT_DUNNING):
        raise ValidationFailed("Dunning has: " + ", ".join(DEFAULT_DUNNING))
    merged = {**DEFAULT_DUNNING, **value}
    reminders = merged["reminders"]
    if not isinstance(reminders, list) or len(reminders) > 10:
        raise ValidationFailed("Reminders are a list of at most 10 day offsets")
    merged["reminders"] = sorted({_days(r, "A reminder offset", -90, 365) for r in reminders})
    for key in ("past_due_after_days", "grace_after_days", "suspend_after_days", "expire_after_days"):
        merged[key] = _days(merged[key], key, 0, 3650)
    if not (
        merged["past_due_after_days"]
        <= merged["grace_after_days"]
        <= merged["suspend_after_days"]
        <= merged["expire_after_days"]
    ):
        raise ValidationFailed("The steps must go in order: past due, then grace, then suspended, then expired")
    return merged


def _proration(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {"downgrade"}:
        raise ValidationFailed("Proration has: downgrade")
    when = value.get("downgrade", "period_end")
    if when not in ("period_end", "now"):
        raise ValidationFailed("A downgrade takes effect at 'period_end' or 'now'")
    return {"downgrade": when}


def _code(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if clean and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,39}", clean):
        raise ValidationFailed("A plan code is 2-40 lowercase letters, digits, '-' or '_'")
    return clean


# key -> (default, parser)
SETTINGS: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "vendor": ({"name": "", "address": "", "tax_id": "", "email": "", "phone": ""}, _vendor),
    "billing.tax_lines": ([], _tax_lines),
    "billing.payment_instructions": ("", _text(2000, "Payment instructions")),
    "billing.invoice_prefix": ("INV-", _text(12, "Invoice prefix")),
    "billing.due_days": (14, lambda v: _days(v, "Days until an invoice is due", 0, 365)),
    "billing.renewal_lead_days": (14, lambda v: _days(v, "Days before the period ends to invoice", 0, 365)),
    "billing.dunning": (DEFAULT_DUNNING, _dunning),
    "billing.proration": ({"downgrade": "period_end"}, _proration),
    "billing.default_plan_code": ("", _code),
    "billing.retention_days": (90, lambda v: _days(v, "Retention days after a subscription ends", 0, 3650)),
    "billing.cooling_off_days": (7, lambda v: _days(v, "Cooling-off days before a deletion", 0, 365)),
    "billing.notify_emails": ("", _text(500, "Extra billing notification emails")),
}


def get(key: str) -> Any:
    """The value of a setting (its default when never set)."""
    default = SETTINGS[key][0]
    with master_session() as m:
        row = m.execute(text("select value from master.platform_setting where key = :k"), {"k": key}).first()
    return row.value if row is not None else default


def get_all() -> dict[str, Any]:
    with master_session() as m:
        stored = {r.key: r.value for r in m.execute(text("select key, value from master.platform_setting"))}
    return {key: stored.get(key, default) for key, (default, _) in SETTINGS.items()}


def set_value(key: str, value: Any, by: str | None) -> Any:
    """Validate and store one setting; returns what was stored."""
    if key not in SETTINGS:
        raise ValidationFailed("Unknown setting. Known: " + ", ".join(SETTINGS))
    clean = SETTINGS[key][1](value)
    with master_session() as m:
        m.execute(
            text(
                "insert into master.platform_setting (key, value, updated_by) values (:k, cast(:v as jsonb), :b) "
                "on conflict (key) do update set value = excluded.value, updated_at = now(), updated_by = "
                "excluded.updated_by"
            ),
            {"k": key, "v": json.dumps(clean), "b": by},
        )
    return clean
