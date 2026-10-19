"""Platform behaviour settings the owner manages in the Super Admin (Platform > Settings): who may register, the
default edition and trial length, the public addresses and links. Same table as the billing settings
(`master.platform_setting`), but a separate key set: the billing settings route cannot change these.

Every value falls back to the environment when the owner has not set it (existing installs, development and tests keep
working), and an empty value means "not set". Reads are cached for a short time and the cache is cleared by every
change made in this process.
"""

import json
import re
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed

CACHE_SECONDS = 30.0
MODES = ("open", "invite", "closed")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _url(what: str) -> Callable[[Any], str]:
    def parse(value: Any) -> str:
        clean = str(value if value is not None else "").strip().rstrip("/")
        if not clean:
            return ""
        if len(clean) > 300 or not re.fullmatch(r"https?://[^\s/$.?#][^\s]*", clean):
            raise ValidationFailed(f"{what} must be a web address that starts with http:// or https://")
        if re.search(r"[<>\"']", clean):
            raise ValidationFailed(f"{what} has characters that are not allowed in an address")
        return clean

    return parse


def _mode(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if clean and clean not in MODES:
        raise ValidationFailed("Registration is open, invite or closed")
    return clean


def _edition(value: Any) -> str:
    from ziira.kernel import editions

    clean = str(value or "").strip().lower()
    if clean and clean not in editions.load_editions():
        raise ValidationFailed("Edition is one of: " + ", ".join(editions.load_editions()))
    return clean


def _trial(value: Any) -> int | str:
    if value is None or str(value).strip() == "":
        return ""
    try:
        days = int(str(value).strip())
    except ValueError:
        raise ValidationFailed("The trial length is a whole number of days (or empty to use each plan's own)") from None
    if not 0 <= days <= 365:
        raise ValidationFailed("The trial length is from 0 to 365 days")
    return days


def _email(value: Any) -> str:
    clean = str(value or "").strip()
    if clean and (len(clean) > 200 or not _EMAIL.match(clean)):
        raise ValidationFailed("That email address does not look right")
    return clean


# key -> parser. The default of every key is "" (not set: use the environment).
KEYS: dict[str, Callable[[Any], Any]] = {
    "registration.mode": _mode,
    "registration.default_edition": _edition,
    "registration.trial_days": _trial,
    "public.web_url": _url("The public web address"),
    "public.api_url": _url("The public API address"),
    "public.terms_url": _url("The terms link"),
    "public.privacy_url": _url("The privacy link"),
    "public.help_url": _url("The help link"),
    "public.site_url": _url("The website address"),
    "public.support_email": _email,
}

_cache: dict[str, Any] = {"at": 0.0, "values": {}}


def invalidate() -> None:
    """Forget what was read (called after every change; tests call it too)."""
    _cache["at"] = 0.0


def _stored() -> dict[str, Any]:
    if time.monotonic() - float(_cache["at"]) > CACHE_SECONDS:
        with master_session() as m:
            rows = m.execute(text("select key, value from master.platform_setting where key = any(:k)"),
                             {"k": list(KEYS)}).all()
        _cache["values"] = {r.key: r.value for r in rows}
        _cache["at"] = time.monotonic()
    values: dict[str, Any] = _cache["values"]
    return values


def get(key: str) -> Any:
    """The value the owner saved ("" when nothing is saved)."""
    value = _stored().get(key, "")
    return "" if value is None else value


def set_value(key: str, value: Any, by: str | None) -> Any:
    """Validate and save one value; returns what was saved."""
    if key not in KEYS:
        raise ValidationFailed("Unknown setting. Known: " + ", ".join(KEYS))
    clean = KEYS[key](value)
    with master_session() as m:
        m.execute(text(
            "insert into master.platform_setting (key, value, updated_by) values (:k, cast(:v as jsonb), :b) "
            "on conflict (key) do update set value = excluded.value, updated_at = now(), "
            "updated_by = excluded.updated_by"), {"k": key, "v": json.dumps(clean), "b": by})
    invalidate()
    return clean


# --------------------------------------------------------------------------- effective values (saved, else environment)
def _text(key: str, fallback: str) -> str:
    return str(get(key) or "").strip() or fallback


def registration_mode_set() -> str:
    """The mode as chosen: saved, else the environment's. Not yet limited by whether email works."""
    return _text("registration.mode", get_settings().registration_mode)


def registration_mode() -> str:
    """What registration does now: the mode as chosen. Without working email nothing is mailed and a new owner goes
    straight into the system after choosing a password (registration.register)."""
    return registration_mode_set()


def default_edition() -> str:
    return str(get("registration.default_edition") or "").strip()


def trial_days(plan_days: int) -> int:
    """The trial length: the owner's override when set, else the plan's own."""
    override = get("registration.trial_days")
    return int(override) if str(override) != "" else plan_days


def public_web_url() -> str:
    return _text("public.web_url", get_settings().public_web_url).rstrip("/")


def public_api_url() -> str:
    return _text("public.api_url", get_settings().public_base_url).rstrip("/")


def overview() -> dict[str, Any]:
    """Every value for the settings page: what is saved, what is used, and where it comes from."""
    env = get_settings()
    fallbacks = {"registration.mode": env.registration_mode, "public.web_url": env.public_web_url,
                 "public.api_url": env.public_base_url}
    return {key: {"value": get(key), "effective": str(get(key) or fallbacks.get(key, "")),
                  "source": "platform" if str(get(key)) != "" else ("environment" if fallbacks.get(key) else "unset")}
            for key in KEYS}
