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


def _late_posting(value: Any) -> str:
    if value not in ("redirect", "reject"):
        raise ValidationFailed("Expected 'redirect' or 'reject'")
    return str(value)


SETTINGS: dict[str, Setting] = {s.key: s for s in (
    Setting("negative_stock_allowed", False, _boolean,
            "Sell stock the system thinks is not there: the sale posts and an exception is raised for review"),
    Setting("count_variance_threshold", Decimal("0"), _non_negative_amount,
            "Stock count variances worth more than this (in the company currency) need approval before posting"),
    Setting("late_posting", "redirect", _late_posting,
            "A document dated in a closed accounting period is posted to the current period ('redirect') or "
            "refused ('reject')"),
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
