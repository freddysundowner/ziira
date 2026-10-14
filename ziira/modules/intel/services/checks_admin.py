"""The checks a business can see and tune: switch one off, change its limits."""

from decimal import Decimal, InvalidOperation
from typing import Any

from ziira.modules.intel.public import INTEL_CHECK, IntelCheck
from ziira.modules.intel.repository import findings_repo as repo
from ziira.sdk import Session, ValidationFailed, audit_record, current_context, implementations


def list_checks(session: Session) -> list[dict[str, Any]]:
    settings = repo.check_settings(session)
    out = []
    for check in sorted(implementations(session, INTEL_CHECK), key=lambda c: (c.area, c.title)):
        enabled, overrides = settings.get(check.code, (True, {}))
        out.append({"code": check.code, "title": check.title, "area": check.area, "description": check.description,
                    "severity": check.default_severity, "enabled": enabled, "defaults": dict(check.params),
                    "params": {**check.params, **{k: v for k, v in overrides.items() if k in check.params}},
                    "auto_resolves": check.auto_resolves})
    return out


def _coerce(name: str, default: Any, value: Any) -> Any:
    """A limit the person typed, as the same kind of value as the default (a number stays a number)."""
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValidationFailed(f"'{name}' must be true or false")
        return value
    if isinstance(default, int | float | Decimal):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValidationFailed(f"'{name}' must be a number") from None
        if number < 0:
            raise ValidationFailed(f"'{name}' cannot be negative")
        if isinstance(default, int):
            if number != number.to_integral_value():
                raise ValidationFailed(f"'{name}' must be a whole number")
            return int(number)
        return str(number)
    return str(value)


def update_check(session: Session, code: str, enabled: bool | None, params: dict[str, Any] | None) -> dict[str, Any]:
    check: IntelCheck | None = next((c for c in implementations(session, INTEL_CHECK) if c.code == code), None)
    if check is None:
        raise ValidationFailed("Unknown check")
    current_enabled, current = repo.check_settings(session).get(code, (True, {}))
    merged = dict(current)
    for name, value in (params or {}).items():
        if name not in check.params:
            raise ValidationFailed(f"'{name}' is not a limit of this check")
        merged[name] = _coerce(name, check.params[name], value)
    new_enabled = current_enabled if enabled is None else enabled
    repo.save_check_setting(session, code, new_enabled, merged, current_context().user_id)
    audit_record(session, "intel.check_setting", "intel.check", None, {"check": code, "enabled": new_enabled,
                                                                       "params": merged})
    return next(c for c in list_checks(session) if c["code"] == code)
