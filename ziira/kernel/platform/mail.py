"""The platform's own email, managed in the Super Admin (docs/platform-admin.md, "Email").

The owner picks a provider (`mail_providers.py`), enters its credentials (stored encrypted in the master database,
write-only: never returned, logged, audited or put in the mail log), sets the sender, sends a test message and then
makes the provider live. Until then the environment settings (`ZIIRA_PLATFORM_EMAIL_*`) keep working, and development
and tests use a fake provider that only records what it was asked to send.

The active configuration is read from the master tables and cached for 30 seconds; every change here clears the cache.
Each send leaves a line in `master.platform_mail_log` (kind, masked recipient, status, the provider's reason): never the
message and never a secret.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from ziira.kernel import mail_providers
from ziira.kernel.channels import NOTIFICATION_CHANNEL
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import NotFound, TooManyRequests, Unavailable, ValidationFailed
from ziira.kernel.extensions import provider_named
from ziira.kernel.notifications import Outgoing
from ziira.kernel.platform import behaviour
from ziira.kernel.security import decrypt, encrypt

log = logging.getLogger("ziira.platform_mail")
CACHE_SECONDS = 30.0
EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
KINDS = ("registration", "password_reset", "billing", "security", "test", "other")
FREE_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com")
TESTS_PER_HOUR = 10
DEFAULT_RETENTION_DAYS = 90

_cache: dict[str, Any] = {"at": 0.0, "active": None}


def invalidate() -> None:
    """Forget the cached configuration (every change calls this; tests do too)."""
    _cache["at"] = 0.0
    behaviour.invalidate()


def mask(address: str) -> str:
    """j***@gmail.com: enough for an operator to recognise, not enough to read back."""
    local, at, domain = address.strip().partition("@")
    if not at or not local or not domain:
        return "***"
    return f"{local[0]}***@{domain.lower()}"


def _scrub(message: str, secrets: list[str]) -> str:
    """A provider's reason, shortened, with any secret it echoed back removed."""
    clean = " ".join(str(message).split())
    for secret in secrets:
        if len(secret) >= 4:
            clean = clean.replace(secret, "***")
    return clean[:300]


# --------------------------------------------------------------------------- stored settings
def _setting(key: str, default: Any) -> Any:
    with master_session() as m:
        row = m.execute(text("select value from master.platform_setting where key = :k"), {"k": key}).first()
    return row.value if row is not None else default


def _put_setting(key: str, value: Any, by: str | None) -> None:
    with master_session() as m:
        m.execute(text(
            "insert into master.platform_setting (key, value, updated_by) values (:k, cast(:v as jsonb), :b) "
            "on conflict (key) do update set value = excluded.value, updated_at = now(), "
            "updated_by = excluded.updated_by"), {"k": key, "v": json.dumps(value), "b": by})


def _row(provider: str) -> dict[str, Any] | None:
    with master_session() as m:
        row = m.execute(text("select * from master.platform_email_provider where provider = :p"),
                        {"p": provider}).first()
    return dict(row._mapping) if row else None


def _secrets_of(row: dict[str, Any] | None) -> dict[str, str]:
    if not row or not row["secrets_encrypted"]:
        return {}
    return {str(k): str(v) for k, v in json.loads(decrypt(row["secrets_encrypted"])).items()}


def sender() -> dict[str, str]:
    stored = _setting("email.sender", {}) or {}
    return {k: str(stored.get(k, "")) for k in ("from_address", "from_name", "reply_to")}


def _installed(name: str) -> mail_providers.MailProvider:
    spec = mail_providers.get(name)
    if spec is None or provider_named(NOTIFICATION_CHANNEL, name) is None:
        raise NotFound("No such email provider")
    return spec


def _missing(spec: mail_providers.MailProvider, values: dict[str, str], secrets: dict[str, str]) -> list[str]:
    return [f.label for f in spec.fields
            if f.required and not (secrets.get(f.name) if f.secret else values.get(f.name, "").strip())]


def _provider_state(spec: mail_providers.MailProvider) -> dict[str, Any]:
    row = _row(spec.name)
    values = spec.check_values((row or {}).get("config") or {}) if row else spec.check_values({})
    secrets = _secrets_of(row)
    return {"spec": spec, "row": row, "values": values, "secrets": secrets, "missing": _missing(spec, values, secrets)}


# --------------------------------------------------------------------------- the configuration in use
@dataclass(frozen=True)
class Active:
    source: str                     # platform | environment | development
    provider: str
    secret: dict[str, Any]
    config: dict[str, Any]


def _env_json(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value) if value.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _build(spec: mail_providers.MailProvider, state: dict[str, Any], snd: dict[str, str]) -> Active:
    built = spec.build(state["values"], state["secrets"])
    config = {**built["config"], "from_address": snd["from_address"], "from_name": snd["from_name"],
              "reply_to": snd["reply_to"]}
    return Active("platform", spec.name, built["secret"], config)


def active() -> Active | None:
    """The configuration mail is sent with now, or None when nothing can send. The owner's choice is read from the
    master tables (cached); the environment and the development fake are the fallback."""
    if time.monotonic() - float(_cache["at"]) > CACHE_SECONDS:
        _cache["active"] = _load_platform()
        _cache["at"] = time.monotonic()
    chosen: Active | None = _cache["active"]
    if chosen is not None:
        return chosen
    env = get_settings()
    if env.platform_email_provider:
        return Active("environment", env.platform_email_provider,
                      _env_json(env.platform_email_secret) or {"api_key": "development"},
                      _env_json(env.platform_email_config))
    if env.env != "production":
        return Active("development", "fake", {"api_key": "development"}, {})
    return None


def _load_platform() -> Active | None:
    chosen = str(_setting("email.provider", "") or "")
    spec = mail_providers.get(chosen) if chosen else None
    if spec is None or provider_named(NOTIFICATION_CHANNEL, spec.name) is None:
        return None
    state = _provider_state(spec)
    return None if state["missing"] else _build(spec, state, sender())


# --------------------------------------------------------------------------- the mail log
def _log(kind: str, to: str, ok: bool, provider: str | None, detail: str | None) -> None:
    try:
        with master_session() as m:
            m.execute(text(
                "insert into master.platform_mail_log (kind, recipient_masked, status, provider, detail) "
                "values (:k, :r, :s, :p, :d)"),
                {"k": kind if kind in KINDS else "other", "r": mask(to), "s": "sent" if ok else "failed",
                 "p": provider, "d": detail})
    except Exception:  # noqa: BLE001 - a log problem must never stop a message
        log.warning("Could not write the mail log", exc_info=True)


def log_lines(limit: int = 50) -> list[dict[str, Any]]:
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text(
            "select id, sent_at, kind, recipient_masked, status, provider, detail from master.platform_mail_log "
            "order by id desc limit :n"), {"n": max(1, min(limit, 200))})]


def purge_log(*, days: int | None = None) -> int:
    """Delete log lines older than the retention period (default 90 days). Returns how many went."""
    keep = DEFAULT_RETENTION_DAYS if days is None else days
    with master_session() as m:
        gone = m.execute(text("delete from master.platform_mail_log where sent_at < :t returning id"),
                         {"t": datetime.now(UTC) - timedelta(days=keep)}).all()
    return len(gone)


# --------------------------------------------------------------------------- sending
def _secret_values(cfg: Active) -> list[str]:
    return [str(v) for v in cfg.secret.values() if v]


def deliver(cfg: Active, to: str, subject: str, body: str) -> tuple[bool, str]:
    """One send; never raises. Returns (accepted, reason with any echoed secret removed)."""
    channel = provider_named(NOTIFICATION_CHANNEL, cfg.provider)
    if channel is None or getattr(channel, "channel", None) != "email":
        return False, f"The email provider '{cfg.provider}' is not installed"
    try:
        result = channel().send(Outgoing(uuid4(), uuid4(), to, subject, body), cfg.secret, cfg.config)
    except Exception as error:  # noqa: BLE001 - any provider failure is a failed send, not a crash
        return False, _scrub(f"The provider could not be reached ({type(error).__name__})", _secret_values(cfg))
    if not result.accepted:
        return False, _scrub(result.message or "The provider refused the message", _secret_values(cfg))
    return True, "Accepted by the provider"


def send(to: str, subject: str, body: str, kind: str = "other") -> None:
    """Send one email as the platform. Raises Unavailable if it cannot; the reason goes to the mail log only."""
    cfg = active()
    if cfg is None:
        _log(kind, to, False, None, "No email provider is configured")
        log.error("No platform email provider is configured")
        raise Unavailable("Email cannot be sent right now, so registration is unavailable. Please try again later.")
    ok, reason = deliver(cfg, to, subject, body)
    _log(kind, to, ok, cfg.provider, None if ok else reason)
    if not ok:
        log.error("The platform email provider refused the message: %s", reason)
        raise Unavailable("Email cannot be sent right now. Please try again later.")


# --------------------------------------------------------------------------- the page
def overview() -> dict[str, Any]:
    """Everything the Email page shows. Secrets only as set / not set."""
    chosen = str(_setting("email.provider", "") or "")
    last = _setting("email.last_test", None)
    out = []
    for spec in mail_providers.all_providers():
        if provider_named(NOTIFICATION_CHANNEL, spec.name) is None:
            continue
        state = _provider_state(spec)
        row, values, secrets = state["row"], state["values"], state["secrets"]
        out.append({
            "name": spec.name, "label": spec.label, "description": spec.description, "dns_hint": spec.dns_hint,
            "fields": [{"name": f.name, "label": f.label, "secret": f.secret, "required": f.required, "help": f.help,
                        "kind": f.kind, "options": list(f.options),
                        "value": None if f.secret else values.get(f.name, ""),
                        "is_set": bool(secrets.get(f.name)) if f.secret else bool(values.get(f.name, "").strip())}
                       for f in spec.fields],
            "configured": not state["missing"], "missing": state["missing"], "selected": spec.name == chosen,
            "tested_ok": bool(last and last.get("provider") == spec.name and last.get("ok")),
            "updated_at": (row or {}).get("updated_at"), "updated_by": (row or {}).get("updated_by")})
    env = get_settings()
    env_config = _env_json(env.platform_email_config)
    env_secret = _env_json(env.platform_email_secret)
    cfg = active()
    return {
        "source": cfg.source if cfg else "none", "providers": out, "sender": sender(),
        "environment": ({"provider": env.platform_email_provider,
                         "from_address": str(env_config.get("from_address", "")),
                         "from_name": str(env_config.get("from_name", "")), "host": str(env_secret.get("host", "")),
                         "port": str(env_secret.get("port", "")), "username": str(env_secret.get("username", "")),
                         "has_secret": bool(env_secret)} if env.platform_email_provider else None),
        "status": status(), "last_test": last}


def status() -> dict[str, Any]:
    """configured / working / last test / last success / failures in the last day."""
    cfg = active()
    last = _setting("email.last_test", None)
    with master_session() as m:
        row = m.execute(text(
            "select (select max(sent_at) from master.platform_mail_log "
            "  where status = 'sent' and kind <> 'test') as ok_at,"
            " (select count(*) from master.platform_mail_log where status = 'failed' and kind <> 'test' "
            "  and sent_at > now() - interval '24 hours') as failed")).one()
    if cfg is None:
        working = False
    elif cfg.source == "platform":
        working = bool(last and last.get("ok") and last.get("provider") == cfg.provider)
    else:
        working = True              # the environment (or the development fake) is set up by whoever runs the server
    return {"source": cfg.source if cfg else "none", "provider": cfg.provider if cfg else None,
            "configured": cfg is not None, "working": working, "last_success_at": row.ok_at,
            "failures_24h": int(row.failed)}


def working_reason() -> str:
    """Why email is not working, in words for the registration guard."""
    cfg = active()
    if cfg is None:
        return "No email provider is set up. Add one on the Email page and send a test message first."
    return "The email settings have not passed a test message yet. Send a test on the Email page first."


def save_provider(name: str, *, config: dict[str, str] | None, secrets: dict[str, str] | None,
                  clear_secrets: list[str] | None, by: str) -> dict[str, Any]:
    """Change one provider's fields. An empty secret keeps the old one; naming it in `clear_secrets` removes it. Any
    change starts the test again."""
    spec = _installed(name)
    secret_names = {f.name for f in spec.fields if f.secret}
    for key in {*(secrets or {}), *(clear_secrets or [])}:
        if key not in secret_names:
            raise ValidationFailed(f"'{key}' is not a secret of {spec.label}")
    state = _provider_state(spec)
    values = spec.check_values({**state["values"], **(config or {})})
    new_secrets = dict(state["secrets"])
    for key in clear_secrets or []:
        new_secrets.pop(key, None)
    for key, value in (secrets or {}).items():
        if str(value).strip():
            if len(str(value)) > 2000:
                raise ValidationFailed("A secret is too long")
            new_secrets[key] = str(value).strip()
    with master_session() as m:
        m.execute(text(
            "insert into master.platform_email_provider (provider, config, secrets_encrypted, updated_by) "
            "values (:p, cast(:c as jsonb), :s, :b) on conflict (provider) do update set config = excluded.config, "
            "secrets_encrypted = excluded.secrets_encrypted, updated_at = now(), updated_by = excluded.updated_by"),
            {"p": name, "c": json.dumps(values), "s": encrypt(json.dumps(new_secrets)) if new_secrets else None,
             "b": by})
    _forget_test(name, by)
    invalidate()
    return next(p for p in overview()["providers"] if p["name"] == name)


def _forget_test(provider: str | None, by: str | None) -> None:
    last = _setting("email.last_test", None)
    if last and (provider is None or last.get("provider") == provider):
        _put_setting("email.last_test", None, by)


def save_sender(*, from_address: str, from_name: str, reply_to: str, by: str) -> dict[str, str]:
    address, name, reply = from_address.strip(), " ".join(from_name.split()), reply_to.strip()
    if address and not EMAIL.match(address):
        raise ValidationFailed("The from address does not look right", {"field": "from_address"})
    if reply and not EMAIL.match(reply):
        raise ValidationFailed("The reply-to address does not look right", {"field": "reply_to"})
    if len(name) > 100 or any(c in name for c in "<>\r\n\"") or len(address) > 200 or len(reply) > 200:
        raise ValidationFailed("The sender name has characters that are not allowed", {"field": "from_name"})
    _put_setting("email.sender", {"from_address": address, "from_name": name, "reply_to": reply}, by)
    _forget_test(None, by)
    invalidate()
    return sender()


def _platform_config(name: str) -> Active:
    spec = _installed(name)
    state = _provider_state(spec)
    if state["missing"]:
        raise ValidationFailed("Enter every required field first: " + ", ".join(state["missing"]))
    snd = sender()
    if not snd["from_address"]:
        raise ValidationFailed("Set the from address first")
    return _build(spec, state, snd)


def set_active(name: str, *, by: str) -> dict[str, Any]:
    """Make a provider live (it must be filled in and have passed a test), or go back to the environment with ''."""
    if name:
        _platform_config(name)
        last = _setting("email.last_test", None)
        if not (last and last.get("ok") and last.get("provider") == name):
            raise ValidationFailed("Send a test email through this provider and see it delivered before making it live")
    _put_setting("email.provider", name, by)
    invalidate()
    return overview()


def send_test(provider: str | None, to: str, *, by: str) -> dict[str, Any]:
    """A test message through a provider's saved settings (the live one when none is named). Records the result."""
    address = to.strip()
    if not EMAIL.match(address):
        raise ValidationFailed("That email address does not look right", {"field": "to"})
    with master_session() as m:
        recent = m.execute(text("select count(*) from master.platform_mail_log where kind = 'test' "
                                "and sent_at > now() - interval '1 hour'")).scalar_one()
    if recent >= TESTS_PER_HOUR:
        raise TooManyRequests("Too many test emails: try again later", {"retry_after": 3600})
    live = active()
    if provider:
        cfg = _platform_config(provider)
    elif live is not None:
        cfg = live
    else:
        # Nothing is live yet (the normal state before the first test): when exactly one provider has been filled in and
        # saved, that is the one the person means. With several, they must test from the provider's own card.
        filled = []
        for spec in mail_providers.all_providers():
            try:
                filled.append(_platform_config(spec.name))
            except ValidationFailed:
                continue
        if len(filled) == 1:
            cfg = filled[0]
        elif not filled:
            raise ValidationFailed("There is no email provider to test: fill in a provider below, set the from address "
                                   "and press Save first")
        else:
            raise ValidationFailed("Several providers are filled in: use the test button on the provider you want")
    ok, reason = deliver(cfg, address, "Ziira test email",
                         "This is a test email from the Ziira Super Admin. If you can read it, sending works.\n")
    _log("test", address, ok, cfg.provider, None if ok else reason)
    result = {"provider": cfg.provider, "at": datetime.now(UTC).isoformat(), "ok": ok,
              "message": "Delivered to the provider" if ok else reason, "to": mask(address)}
    if cfg.source == "platform":
        _put_setting("email.last_test", result, by)
    invalidate()
    return result


def check_configuration(provider: str | None = None) -> list[dict[str, str]]:
    """Plain checks of the saved settings, as advice. Nothing is looked up on the internet."""
    out: list[dict[str, str]] = []

    def add(level: str, message: str) -> None:
        out.append({"level": level, "message": message})

    name = provider or str(_setting("email.provider", "") or "")
    spec = mail_providers.get(name) if name else None
    if spec is None:
        add("bad", "No provider is chosen. Fill in one below and make it live.")
        return out
    state = _provider_state(spec)
    if state["missing"]:
        add("bad", "Missing: " + ", ".join(state["missing"]))
    else:
        add("ok", f"{spec.label} has every field it needs.")
    snd = sender()
    if not snd["from_address"]:
        add("bad", "The from address is empty.")
    else:
        domain = snd["from_address"].rpartition("@")[2].lower()
        add("ok", f"Messages will be sent from {snd['from_address']}.")
        if domain in FREE_MAIL:
            add("warn", f"{domain} is a free mailbox domain: many providers refuse it as a sender and recipients' "
                        "servers may mark the mail as spam. Use an address on your own domain.")
        user = state["values"].get("username", "")
        if spec.name == "smtp" and "@" in user and user.rpartition("@")[2].lower() != domain:
            add("warn", "The SMTP username belongs to a different domain than the from address; some servers "
                        "refuse that.")
    if snd["reply_to"] and not EMAIL.match(snd["reply_to"]):
        add("bad", "The reply-to address does not look right.")
    if spec.name == "smtp":
        port, security = state["values"].get("port", ""), state["values"].get("security", "")
        if security == "none":
            add("warn", "Security is off: the password and the messages cross the network unencrypted. Use it "
                        "only to a relay on this machine.")
        if (port == "465" and security != "ssl") or (port == "587" and security == "ssl"):
            add("warn", "The port and the security setting usually go together: 587 with STARTTLS, "
                        "465 with SSL.")
    add("info", spec.dns_hint + " Whether they are published is not checked here; the test email shows whether the "
                "provider accepts your sender.")
    return out


def move_from_environment(*, by: str) -> dict[str, Any]:
    """Copy the environment's non-secret mail settings into the platform's, for the owner to add the secret and test.
    The environment keeps being used until a platform provider is made live."""
    env = get_settings()
    spec = mail_providers.get(env.platform_email_provider)
    if spec is None:
        raise ValidationFailed("The environment does not name an email provider this page knows")
    _installed(spec.name)
    secret, config = _env_json(env.platform_email_secret), _env_json(env.platform_email_config)
    values: dict[str, str] = {}
    if spec.name == "smtp":
        port = str(secret.get("port", "") or "587")
        values = {"host": str(secret.get("host", "")), "port": port, "username": str(secret.get("username", "")),
                  "security": "ssl" if port == "465" else ("none" if config.get("starttls") is False else "starttls")}
    save_provider(spec.name, config=values, secrets=None, clear_secrets=None, by=by)
    save_sender(from_address=str(config.get("from_address", "")), from_name=str(config.get("from_name", "")),
                reply_to=str(config.get("reply_to", "")), by=by)
    return overview()
