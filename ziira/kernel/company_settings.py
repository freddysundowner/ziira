"""Company policies kept in `kernel.company.settings` (negative stock, count variance limit, ...).

Each setting has a default, so a company with an empty settings column behaves sensibly.
Units read them through `ziira.sdk.company_setting`; people change them through the settings
endpoint (permission `settings.manage` for that company).

Adding a setting: add a `Setting` to SETTINGS below with a parser that raises ValidationFailed.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.context import get_context
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.phone import check_calling_code

log = logging.getLogger("ziira.settings")


@dataclass(frozen=True)
class Setting:
    """One company policy: its default, a parser for new values, and what it means."""

    key: str
    default: Any
    parse: Callable[[Any], Any]
    description: str


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValidationFailed("Expected true or false")
    return value


def _non_negative_amount(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValidationFailed("Expected an amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValidationFailed("Amount cannot be negative")
    return amount


def _percent(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValidationFailed("Expected a percentage") from None
    if not amount.is_finite() or amount < 0 or amount > 100:
        raise ValidationFailed("A percentage is between 0 and 100")
    return amount


def _reminder_channel(value: Any) -> str:
    if value not in ("off", "sms", "email"):
        raise ValidationFailed("Expected 'off', 'sms' or 'email'")
    return str(value)


def _days(maximum: int) -> Callable[[Any], int]:
    def parse(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum:
            raise ValidationFailed(f"Expected a whole number of days from 0 to {maximum}")
        return value

    return parse


def _footer(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 200 or "\n" in value:
        raise ValidationFailed("Expected one line of text, up to 200 characters")
    return value.strip()


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _weekend(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValidationFailed("Expected a list of weekday names, such as ['sat', 'sun']")
    days = {x.strip().lower()[:3] for x in value}
    if not days <= set(WEEKDAYS) or len(days) > 3:
        raise ValidationFailed("Weekend days are up to three of: " + ", ".join(WEEKDAYS))
    return [d for d in WEEKDAYS if d in days]


def _day_divisor(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 20 <= value <= 31:
        raise ValidationFailed("Expected a whole number of days from 20 to 31")
    return value


def _multiplier(value: Any) -> Decimal:
    amount = _non_negative_amount(value)
    if amount < 1 or amount > 5:
        raise ValidationFailed("Expected a multiplier from 1 to 5")
    return amount


def _positive_hours(value: Any) -> Decimal:
    amount = _non_negative_amount(value)
    if amount < 1 or amount > 400:
        raise ValidationFailed("Expected hours from 1 to 400")
    return amount


def _calling_code(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationFailed("Expected the country calling code as text, such as '44'")
    return check_calling_code(value)


def _late_posting(value: Any) -> str:
    if value not in ("redirect", "reject"):
        raise ValidationFailed("Expected 'redirect' or 'reject'")
    return str(value)


def _timezone(value: Any) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if not isinstance(value, str):
        raise ValidationFailed("Expected a time zone name such as 'Europe/London'")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationFailed("Unknown time zone; use a name such as 'Europe/London' or 'UTC'") from None
    return value


def _alert_channel(value: Any) -> str:
    if value not in ("off", "sms", "email"):
        raise ValidationFailed("Expected 'off', 'sms' or 'email'")
    return str(value)


def _alert_severity(value: Any) -> str:
    if value not in ("low", "medium", "high", "critical"):
        raise ValidationFailed("Expected 'low', 'medium', 'high' or 'critical'")
    return str(value)


def _action_level(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise ValidationFailed("Expected an action level from 1 to 4")
    return value


SETTINGS: dict[str, Setting] = {s.key: s for s in (
    Setting("negative_stock_allowed", False, _boolean,
            "Sell stock the system thinks is not there: the sale posts and an exception is raised for review"),
    Setting("count_variance_threshold", Decimal("0"), _non_negative_amount,
            "Stock count variances worth more than this (in the company currency) need approval before posting"),
    Setting("late_posting", "redirect", _late_posting,
            "A document dated in a closed accounting period is posted to the current period ('redirect') or "
            "refused ('reject')"),
    Setting("bill_match_tolerance_percent", Decimal("2"), _percent,
            "A supplier bill whose cost per unit is more than this percentage away from what was ordered or "
            "received is an exception that needs approval before it posts"),
    Setting("reminder_channel", "off", _reminder_channel,
            "Chase customers with overdue invoices automatically every day by this channel ('off' to chase by hand)"),
    Setting("reminder_min_days_overdue", 1, _days(365),
            "An invoice is chased once it is this many days past its due date"),
    Setting("reminder_repeat_days", 7, _days(365),
            "A customer is not chased about the same invoice more often than this"),
    Setting("phone_country_code", "", _calling_code,
            "The country calling code of the business's phone numbers (such as 44): national numbers are read with it"),
    Setting("weekend_days", ["sat", "sun"], _weekend,
            "The days of the week that are not working days (leave and absence are counted without them)"),
    Setting("payroll_unpaid_day_divisor", 30, _day_divisor,
            "A day of unpaid leave takes off the basic pay divided by this many days"),
    Setting("overtime_multiplier", Decimal("1.5"), _multiplier,
            "Overtime is paid at this multiple of the normal hourly rate"),
    Setting("overtime_hours_per_month", Decimal("173.33"), _positive_hours,
            "The normal hours in a month: basic pay divided by this is the hourly rate for overtime"),
    Setting("receipt_footer", "Thank you for shopping with us", _footer,
            "The line printed at the bottom of till receipts and payment receipts"),
    Setting("invoice_footer", "", _footer,
            "The line printed at the bottom of invoices (bank details, payment terms)"),
    Setting("timezone", "UTC", _timezone,
            "The company's time zone: the times of daily briefs and 'unusual hour' checks are read in it"),
    Setting("intel_alert_channel", "off", _alert_channel,
            "Send urgent findings to the people who should see them by this channel ('off': only in the app)"),
    Setting("intel_alert_min_severity", "high", _alert_severity,
            "Findings at or above this severity are sent as alerts; the rest wait for the daily brief"),
    Setting("intel_action_level", 1, _action_level,
            "What Intelligence may do: 1 reports only, 2 also asks people to explain a finding on your instruction"),
)}


def _stored(session: Session, company_id: UUID) -> dict[str, Any]:
    row = session.execute(text("select settings from kernel.company where id = :c"), {"c": str(company_id)}).first()
    if row is None:
        raise NotFound("Company not found")
    return dict(row.settings or {})


def get_settings(session: Session, company_id: UUID) -> dict[str, Any]:
    """Every setting of the company, defaults filled in. Decimals come back as Decimal.

    A stored value that cannot be read (edited by hand, or from an older version) falls back to the default
    and is logged: a bad setting must never stop sales or stock postings.
    """
    stored = _stored(session, company_id)
    result: dict[str, Any] = {}
    for key, setting in SETTINGS.items():
        try:
            result[key] = setting.parse(stored[key]) if key in stored else setting.default
        except ValidationFailed:
            log.warning("Company %s: setting %s has an unreadable value %r; using the default", company_id, key,
                        stored[key])
            result[key] = setting.default
    return result


def get_setting(session: Session, company_id: UUID, key: str) -> Any:
    """One setting of the company (its default if never changed)."""
    if key not in SETTINGS:
        raise KeyError(f"Unknown company setting '{key}'")
    return get_settings(session, company_id)[key]


def update_settings(session: Session, company_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
    """Change some settings of a company, audited. Unknown keys and bad values are refused."""
    unknown = sorted(set(changes) - set(SETTINGS))
    if unknown:
        raise ValidationFailed(f"Unknown setting: {', '.join(unknown)}")
    stored = _stored(session, company_id)
    before = get_settings(session, company_id)
    parsed = {key: SETTINGS[key].parse(value) for key, value in changes.items()}
    stored.update({key: str(v) if isinstance(v, Decimal) else v for key, v in parsed.items()})
    user_id = get_context().user_id
    session.execute(text(
        "update kernel.company set settings = cast(:s as jsonb), updated_at = now(), updated_by = :u where id = :c"),
        {"s": json.dumps(stored), "u": str(user_id) if user_id else None, "c": str(company_id)})
    after = get_settings(session, company_id)
    audit.record(session, "update", "kernel.company_settings", company_id,
                 {key: {"from": before[key], "to": after[key]} for key in parsed if before[key] != after[key]})
    return after
