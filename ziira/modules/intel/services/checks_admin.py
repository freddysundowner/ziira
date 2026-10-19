"""The checks a business can see and tune: switch one off, change its limits."""

from decimal import Decimal, InvalidOperation
from typing import Any

from ziira.modules.intel.domain import plain
from ziira.modules.intel.domain.source import is_connected_check
from ziira.modules.intel.public import INTEL_CHECK, IntelCheck
from ziira.modules.intel.repository import findings_repo as repo
from ziira.sdk import Session, ValidationFailed, audit_record, current_context, implementations


def _plain(check: IntelCheck, lang: str) -> plain.PlainCheck:
    return plain.plain_check(
        check.code,
        lang,
        fallback_title=check.title,
        area=check.area,
        params=check.params,
        declared=(
            getattr(check, "plain_title", ""),
            getattr(check, "why_it_matters", ""),
            getattr(check, "what_to_do", ""),
        ),
    )


def plain_dictionary(session: Session, lang: str) -> dict[str, Any]:
    """Everything a screen needs to say checks, limits and facts in plain words (one language): cached by the
    web app."""
    checks = {}
    for check in implementations(session, INTEL_CHECK):
        p = _plain(check, lang)
        checks[check.code] = {
            "title": p.title,
            "why": p.why,
            "todo": p.todo,
            "topic": p.topic,
            "sentence": p.sentence,
            "units": p.units,
            "fallback": not p.why,
        }
    return {
        "topics": plain.topics(lang),
        "checks": checks,
        "figures": plain.figure_meta(lang),
        "params": plain.param_labels(lang),
    }


def topics_state(session: Session) -> dict[str, Any]:
    """Per topic: how many checks, how many are on; and whether the business has set Intelligence up at all."""
    settings = repo.check_settings(session)
    counts: dict[str, list[int]] = {t: [0, 0] for t in plain.TOPICS}
    for check in implementations(session, INTEL_CHECK):
        topic = _plain(check, "en").topic
        counts[topic][0] += 1
        counts[topic][1] += 1 if settings.get(check.code, (True, {}))[0] else 0
    return {
        "configured": bool(settings),
        "topics": [{"key": k, "checks": v[0], "enabled": v[1]} for k, v in counts.items()],
    }


def set_topics(session: Session, topics: dict[str, bool]) -> dict[str, Any]:
    """Switch whole topics on or off (every check of the topic), keeping any limits the business changed."""
    unknown = set(topics) - set(plain.TOPICS)
    if unknown:
        raise ValidationFailed(f"Unknown topic: {', '.join(sorted(unknown))}")
    settings = repo.check_settings(session)
    changed = 0
    for check in implementations(session, INTEL_CHECK):
        topic = _plain(check, "en").topic
        if topic not in topics:
            continue
        _, overrides = settings.get(check.code, (True, {}))
        repo.save_check_setting(session, check.code, topics[topic], overrides, current_context().user_id)
        changed += 1
    audit_record(session, "intel.topics_setting", "intel.check", None, {"topics": topics, "checks": changed})
    return topics_state(session)


def reset_check(session: Session, code: str) -> dict[str, Any]:
    """Back to the recommended settings for one check: on, with its own default limits."""
    check = next((c for c in implementations(session, INTEL_CHECK) if c.code == code), None)
    if check is None:
        raise ValidationFailed("Unknown check")
    repo.save_check_setting(session, code, True, {}, current_context().user_id)
    audit_record(session, "intel.check_setting", "intel.check", None, {"check": code, "reset": True})
    return next(c for c in list_checks(session) if c["code"] == code)


def list_checks(session: Session) -> list[dict[str, Any]]:
    settings = repo.check_settings(session)
    out = []
    for check in sorted(implementations(session, INTEL_CHECK), key=lambda c: (c.area, c.title)):
        enabled, overrides = settings.get(check.code, (True, {}))
        out.append(
            {
                "code": check.code,
                "title": check.title,
                "area": check.area,
                "description": check.description,
                "severity": check.default_severity,
                "enabled": enabled,
                "defaults": dict(check.params),
                "params": {**check.params, **{k: v for k, v in overrides.items() if k in check.params}},
                "auto_resolves": check.auto_resolves,
                "topic": _plain(check, "en").topic,
                "source": "connected" if is_connected_check(check.code) else "ziira",
            }
        )
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
    audit_record(
        session, "intel.check_setting", "intel.check", None, {"check": code, "enabled": new_enabled, "params": merged}
    )
    return next(c for c in list_checks(session) if c["code"] == code)


def apply_defaults(session: Session, defaults: dict[str, dict[str, Any]]) -> list[str]:
    """Set the limits an industry pack suggests for checks the business has never tuned (a check with a saved setting is
    left exactly as it is). Unknown checks and limits are ignored. Returns the codes that were set."""
    checks = {c.code: c for c in implementations(session, INTEL_CHECK)}
    saved = repo.check_settings(session)
    done: list[str] = []
    for code, wanted in defaults.items():
        check = checks.get(code)
        if check is None or code in saved:
            continue
        params = {name: _coerce(name, check.params[name], value) for name, value in wanted.items()
                  if name in check.params}
        if params:
            repo.save_check_setting(session, code, True, params, None)
            done.append(code)
    return done
