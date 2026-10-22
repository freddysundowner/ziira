"""The platform's chat bot, as the Super Admin sets it up (docs/ai.md section 15, docs/platform-admin.md "Chat bot").

One bot, one connected number. This module owns the settings and the connection: the provider's key (encrypted,
write-only),
connecting a number step by step, the inbound address and its signing secret (both made here, the secret never shown),
what the bot says, the on/off switch, a dry run ("try it"), a test message, hand-offs and the outcome counters.
The conversation itself is `chat_inbound.py` (deliveries) and `chat_brain.py` (what is said).

Secrets (`api_key`, `webhook_secret`) live in `master.chat_bot.secrets_encrypted` as one Fernet token. They are returned
by nothing, logged by nothing, audited by nothing, and a provider's reason is stripped of them before it is kept.
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, TooManyRequests, ValidationFailed
from ziira.kernel.platform import behaviour, chat_brain, chat_channel
from ziira.kernel.platform import site_assistant as limits
from ziira.kernel.platform.chat_channel import (
    ChatConnectionInfo,
    ChatConnectRequest,
    ChatConnectState,
    ChatContext,
    ChatError,
    ChatReply,
)
from ziira.kernel.security import decrypt, encrypt, hash_secret, new_secret

log = logging.getLogger("ziira.chat")
TENANT_REF = "ziira-platform"
INBOUND_PATH = "/api/v1/public/chat/inbound/"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
OPEN_STATES = ("pending", "awaiting_code")
TEXT_LIMITS = {"welcome": 600, "handoff": 400, "off_hours": 400}
PROFILE_LIMITS = {"about": 139, "description": 512, "website": 200}
DEFAULT_PROFILE = {
    "about": "Ziira: business software with a daily check on your business.",
    "description": "Ziira is business software for small and medium businesses. Ask this number about what Ziira does, "
    "its plans and prices, or how to sign up.",
}
OUTCOMES = ("answered", "unknown", "opted_out", "failed")
TRY_PER_MINUTE = 20
TEST_MESSAGES_PER_HOUR = 5


# --------------------------------------------------------------------------- the stored row
def _row() -> dict[str, Any] | None:
    with master_session() as m:
        row = m.execute(text("select * from master.chat_bot where id = 1")).first()
    return dict(row._mapping) if row else None


def _ensure(provider: str) -> dict[str, Any]:
    with master_session() as m:
        m.execute(
            text("insert into master.chat_bot (id, provider) values (1, :p) on conflict (id) do nothing"),
            {"p": provider},
        )
    row = _row()
    assert row is not None
    return row


def _put(by: str | None = None, **columns: Any) -> None:
    """Change columns of the one row. jsonb columns are given as Python values."""
    sets: list[str] = []
    params: dict[str, Any] = {}
    for name, value in columns.items():
        if name in ("config", "connection", "texts"):
            sets.append(f"{name} = cast(:{name} as jsonb)")
            params[name] = json.dumps(value)
        else:
            sets.append(f"{name} = :{name}")
            params[name] = value
    sets.append("updated_at = now()")
    sets.append("updated_by = coalesce(:by, updated_by)")
    params["by"] = by
    with master_session() as m:
        m.execute(text(f"update master.chat_bot set {', '.join(sets)} where id = 1"), params)


def _secrets(row: dict[str, Any] | None) -> dict[str, str]:
    if not row or not row["secrets_encrypted"]:
        return {}
    return {str(k): str(v) for k, v in json.loads(decrypt(row["secrets_encrypted"])).items()}


def _put_secrets(values: dict[str, str], by: str | None) -> None:
    clean = {k: v for k, v in values.items() if v}
    _put(by, secrets_encrypted=encrypt(json.dumps(clean)) if clean else None)


def _conn(row: dict[str, Any] | None) -> dict[str, Any]:
    return dict((row or {}).get("connection") or {})


def _provider(row: dict[str, Any] | None = None) -> chat_channel.PlatformChatProvider:
    provider = chat_channel.the_provider()
    if row is not None and row["provider"] != provider.name:
        raise ValidationFailed("The chat provider changed; connect again")
    return provider


def _config_of(provider: chat_channel.PlatformChatProvider, row: dict[str, Any] | None) -> dict[str, str]:
    stored = (row or {}).get("config") or {}
    return {f.name: str(stored.get(f.name, f.default)) for f in provider.config_fields if not f.secret}


def _ctx(row: dict[str, Any], provider: chat_channel.PlatformChatProvider) -> ChatContext:
    return ChatContext(
        config=_config_of(provider, row),
        secrets=_secrets(row),
        http=chat_channel.new_http_client(),
        connection={k: str(v) for k, v in _conn(row).items() if v is not None},
    )


def context() -> tuple[dict[str, Any], chat_channel.PlatformChatProvider, ChatContext]:
    """The saved row, the provider in use and a call context. Raises NotFound when nothing is set up."""
    row = _row()
    if row is None:
        raise NotFound("The chat bot is not set up")
    provider = _provider(row)
    return row, provider, _ctx(row, provider)


def scrub(message: str, secrets: list[str]) -> str:
    clean = " ".join(str(message).split())
    for secret in secrets:
        if len(secret) >= 4:
            clean = clean.replace(secret, "***")
    return clean[:300]


def _fail(error: ChatError, row: dict[str, Any] | None) -> ValidationFailed:
    """A provider's refusal as a plain message for the owner (secrets removed). Rate limits keep their wait."""
    secrets = list(_secrets(row).values())
    message = scrub(error.message, secrets)
    if error.code == "rate_limited" or error.retryable:
        return ValidationFailed(message, {"code": error.code, "retryable": True})
    return ValidationFailed(message, {"code": error.code})


def _call(row: dict[str, Any] | None, work: Callable[[], Any]) -> Any:
    try:
        return chat_channel.call(work)
    except ChatError as error:
        raise _fail(error, row) from None


# --------------------------------------------------------------------------- addresses and numbers
def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def inbound_address(token: str | None) -> tuple[str | None, str | None]:
    """The address the provider calls, and a plain problem when the public address cannot receive it. With no token the
    address is shown with the token hidden."""
    base = behaviour.public_api_url()
    if not base:
        return None, "Set the public API address in Platform settings first"
    host = base.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    local = host in LOCAL_HOSTS or host.endswith((".localhost", ".test")) or host == "[::1]"
    problem = None
    if not base.startswith("https://") and not (local and get_settings().env != "production"):
        problem = "The public API address must start with https:// for the provider to call it"
    return f"{base}{INBOUND_PATH}{token if token else '********'}", problem


def _needs_address(token: str) -> str:
    """The real inbound address, or a refusal when the platform's public address cannot work (the fake mode needs
    none)."""
    url, problem = inbound_address(token)
    if chat_channel.fake_mode():
        return url or f"http://localhost:8000{INBOUND_PATH}{token}"
    if url is None or problem:
        raise ValidationFailed(problem or "Set the public API address in Platform settings first")
    return url


def _new_endpoint() -> tuple[str, str, str]:
    """A fresh random token, its hash and a fresh signing secret."""
    token = new_secret()
    return token, hash_secret(token), new_secret()


# --------------------------------------------------------------------------- texts
def texts_of(row: dict[str, Any] | None) -> dict[str, Any]:
    stored = dict((row or {}).get("texts") or {})
    profile = {**DEFAULT_PROFILE, **{k: str(v) for k, v in (stored.get("profile") or {}).items() if str(v).strip()}}
    site = chat_brain.site_base()
    if not profile.get("website"):
        profile["website"] = site
    return {
        "welcome": str(stored.get("welcome", "")),
        "handoff": str(stored.get("handoff", "")),
        "off_hours": str(stored.get("off_hours", "")),
        "language": stored.get("language", "auto") if stored.get("language") in ("auto", "en", "sw") else "auto",
        "hours_start": str(stored.get("hours_start", "")),
        "hours_end": str(stored.get("hours_end", "")),
        "hours_timezone": str(stored.get("hours_timezone", "") or "UTC"),
        "profile": profile,
    }


def bot_texts(row: dict[str, Any] | None = None) -> chat_brain.BotTexts:
    t = texts_of(row if row is not None else _row())
    return chat_brain.BotTexts(
        t["welcome"], t["handoff"], t["off_hours"], t["language"], t["hours_start"], t["hours_end"], t["hours_timezone"]
    )


_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def save_texts(data: dict[str, Any], by: str) -> dict[str, Any]:
    """Validate and save what the bot says. Pushes the profile to the provider when a number is connected; a provider
    that cannot take it does not stop the save (the answer says so)."""
    row = _ensure(chat_channel.the_provider().name) if _row() is None else _row()
    assert row is not None
    current = texts_of(row)
    new: dict[str, Any] = {}
    for key, limit in TEXT_LIMITS.items():
        value = str(data.get(key, current[key]) or "").strip()
        if len(value) > limit:
            raise ValidationFailed(f"That text is too long (at most {limit} characters)")
        new[key] = value
    language = str(data.get("language", current["language"]) or "auto")
    if language not in ("auto", "en", "sw"):
        raise ValidationFailed("Language must be auto, en or sw")
    new["language"] = language
    for key in ("hours_start", "hours_end"):
        value = str(data.get(key, current[key]) or "").strip()
        if value and not _CLOCK.match(value):
            raise ValidationFailed("Opening hours are times like 08:00")
        new[key] = value
    if bool(new["hours_start"]) != bool(new["hours_end"]):
        raise ValidationFailed("Give both the opening and the closing time, or neither")
    zone = str(data.get("hours_timezone", current["hours_timezone"]) or "UTC").strip()
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(zone)
    except Exception:  # noqa: BLE001
        raise ValidationFailed("That time zone is not known (a region and city name)") from None
    new["hours_timezone"] = zone
    profile_in = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    profile: dict[str, str] = {}
    for key, limit in PROFILE_LIMITS.items():
        value = str((profile_in or {}).get(key, current["profile"].get(key, "")) or "").strip()
        if len(value) > limit:
            raise ValidationFailed(f"The {key} is too long (at most {limit} characters)")
        profile[key] = value
    if profile["website"] and not re.fullmatch(r"https?://[^\s<>\"']+", profile["website"]):
        raise ValidationFailed("The website must be a web address that starts with http:// or https://")
    new["profile"] = profile
    _put(by, texts=new)
    warning = None
    if _conn(row).get("status") == "connected":
        provider = _provider(row)
        if provider.supports_profile:
            try:
                chat_channel.call(lambda: provider.update_profile(_ctx(row, provider), profile))
            except ChatError as error:
                warning = scrub(error.message, list(_secrets(row).values()))
    return {**texts_of(_row()), "profile_warning": warning}


# --------------------------------------------------------------------------- the key
def save_key(api_key: str, by: str) -> dict[str, Any]:
    """Store the provider's key (write-only). Clears the 'tested' mark: the new key has not been tried."""
    key = api_key.strip()
    if not 8 <= len(key) <= 400 or re.search(r"\s", key):
        raise ValidationFailed("That does not look like a key: paste it exactly as the provider shows it")
    row = _ensure(chat_channel.the_provider().name)
    secrets = _secrets(row)
    secrets["api_key"] = key
    _put_secrets(secrets, by)
    _put(by, key_tested_at=None, key_tested_ok=None)
    return {"is_set": True, "tested_ok": None}


def test_key(by: str) -> dict[str, Any]:
    """The lightest authenticated read at the provider. Records the result; the message is the provider's, cleaned."""
    row = _row()
    if row is None or not _secrets(row).get("api_key"):
        raise ValidationFailed("Paste the key first")
    provider = _provider(row)
    try:
        result = chat_channel.call(lambda: provider.test_key(_ctx(row, provider)))
        ok, message = result.ok, scrub(result.message, list(_secrets(row).values()))
    except ChatError as error:
        ok, message = False, scrub(error.message, list(_secrets(row).values()))
    _put(by, key_tested_at=datetime.now(UTC), key_tested_ok=ok)
    return {"ok": ok, "message": message}


# --------------------------------------------------------------------------- connecting
def _state_dict(row: dict[str, Any] | None) -> dict[str, Any]:
    c = _conn(row)
    return {
        "state": c.get("status") or "none",
        "mode": c.get("mode"),
        "message": c.get("message") or "",
        "code": c.get("code") or "",
        "number": c.get("number"),
        "display_phone": c.get("display_phone"),
        "has_request": bool(c.get("request_ref")),
        "active": c.get("status") == "connected",
    }


def _apply(row: dict[str, Any], state: ChatConnectState, by: str | None) -> None:
    c = _conn(row)
    c.update(
        status=state.status,
        message=state.message[:300],
        code=state.code[:60],
        request_ref=state.request_ref or c.get("request_ref"),
        checked_at=datetime.now(UTC).isoformat(),
    )
    if state.phone_number_id:
        c["phone_number_id"] = state.phone_number_id
    if state.display_phone:
        c["display_phone"] = state.display_phone
    if state.status in ("failed", "cancelled"):
        c.pop("request_ref", None)
    _put(by, connection=c)


def start_connect(data: dict[str, Any], by: str) -> dict[str, Any]:
    """Begin connecting a number: `new` (not yet at the provider) or `existing` (claim it with a code)."""
    row = _row()
    if row is None or not _secrets(row).get("api_key"):
        raise ValidationFailed("Paste and test the key first")
    provider = _provider(row)
    current = _conn(row).get("status")
    if current in OPEN_STATES:
        raise Conflict("A request is already waiting. Wait for it or cancel it first")
    if current == "connected":
        raise Conflict("A number is already connected. Disconnect it first")
    mode = str(data.get("mode") or "new")
    if mode not in ("new", "existing") or (mode == "existing" and not provider.supports_existing_number):
        raise ValidationFailed("Choose a new number or one already at the provider")
    country, number = _digits(str(data.get("country_code") or "")), _digits(str(data.get("phone_number") or ""))
    if not 1 <= len(country) <= 4 or not 5 <= len(number) <= 14:
        raise ValidationFailed("Enter the country calling code (digits only) and the number without it")
    business = " ".join(str(data.get("business_name") or "").split())
    display = " ".join(str(data.get("display_name") or "").split())
    if mode == "new" and (not business or not display or len(business) > 100 or len(display) > 100):
        raise ValidationFailed("Enter the business name and the name people will see in the chat")
    token, token_hash, secret = _new_endpoint()
    url = _needs_address(token)
    profile = texts_of(row)["profile"]
    tenant_ref, connection_ref = TENANT_REF, "bot-" + uuid4().hex[:10]
    request = ChatConnectRequest(
        mode=mode,
        country_code=country,
        phone_number=number,
        business_name=business,
        display_name=display,
        webhook_url=url,
        webhook_secret=secret,
        profile=profile,
        tenant_ref=tenant_ref,
        connection_ref=connection_ref,
    )
    state: ChatConnectState = _call(row, lambda: provider.start_connect(_ctx(row, provider), request))
    secrets = _secrets(row)
    secrets["webhook_secret"] = secret
    _put_secrets(secrets, by)
    _put(by, token_hash=token_hash, enabled=False)
    fresh = _row()
    assert fresh is not None
    c = {
        "tenant_ref": tenant_ref,
        "connection_ref": connection_ref,
        "mode": mode,
        "number": f"+{country}{number}",
        "country_code": country,
        "request_ref": state.request_ref,
    }
    _put(by, connection=c)
    _apply(_row() or fresh, state, by)
    return connect_status_view()


def connect_status_view() -> dict[str, Any]:
    return _state_dict(_row())


def poll_connect(by: str | None = None) -> dict[str, Any]:
    """Ask the provider where connecting stands, and finish the job when it is done: a connected number must be reported
    active by the provider before the bot may be switched on."""
    row = _row()
    if row is None:
        return _state_dict(None)
    c = _conn(row)
    if c.get("status") in OPEN_STATES and c.get("request_ref"):
        provider = _provider(row)
        before = row
        state: ChatConnectState = _call(
            before, lambda: provider.poll_connect(_ctx(before, provider), str(c["request_ref"]))
        )
        _apply(before, state, by)
        fresh = _row()
        assert fresh is not None
        if state.status == "connected":
            _confirm_active(fresh, provider, by)
    return _state_dict(_row())


def _confirm_active(row: dict[str, Any], provider: chat_channel.PlatformChatProvider, by: str | None) -> None:
    """The provider says connected: check the connection itself shows active and keep the number's id."""
    info = chat_channel.call(lambda: provider.connection_info(_ctx(row, provider)))
    c = _conn(row)
    if info.active:
        c.update(
            status="connected",
            message="",
            phone_number_id=info.phone_number_id or c.get("phone_number_id"),
            display_phone=info.display_phone or c.get("display_phone"),
        )
    else:
        c.update(status="pending", message="The number is connected but not active yet")
    _put(by, connection=c)


def submit_code(code: str, by: str) -> dict[str, Any]:
    clean = _digits(code)
    if not 4 <= len(clean) <= 8:
        raise ValidationFailed("Enter the code that was sent to the number (digits only)")
    row = _row()
    c = _conn(row)
    if row is None or c.get("status") not in OPEN_STATES or not c.get("request_ref"):
        raise Conflict("No request is waiting for a code")
    provider = _provider(row)
    state: ChatConnectState = _call(
        row, lambda: provider.verify_code(_ctx(row, provider), str(c["request_ref"]), clean)
    )
    _apply(row, state, by)
    fresh = _row()
    assert fresh is not None
    if state.status == "connected":
        _confirm_active(fresh, provider, by)
    return _state_dict(_row())


def cancel_connect(by: str) -> dict[str, Any]:
    row = _row()
    c = _conn(row)
    if row is None or c.get("status") not in OPEN_STATES:
        raise Conflict("Nothing is waiting")
    provider = _provider(row)
    if c.get("request_ref"):
        _call(row, lambda: provider.cancel_connect(_ctx(row, provider), str(c["request_ref"])))
    _apply(row, ChatConnectState("cancelled", None, "Cancelled"), by)
    return _state_dict(_row())


def find_existing(country_code: str, phone_number: str) -> dict[str, Any]:
    """Look for a number that is already connected at the provider (to recover it after a lost set-up)."""
    row = _row()
    if row is None or not _secrets(row).get("api_key"):
        raise ValidationFailed("Paste and test the key first")
    provider = _provider(row)
    country, number = _digits(country_code), _digits(phone_number)
    if not 1 <= len(country) <= 4 or not 5 <= len(number) <= 14:
        raise ValidationFailed("Enter the country calling code (digits only) and the number without it")
    info: ChatConnectionInfo | None = _call(row, lambda: provider.find_connection(_ctx(row, provider), country, number))
    if info is None:
        return {"found": False, "active": False, "status": None, "display_phone": None}
    return {"found": True, "active": info.active, "status": info.status, "display_phone": info.display_phone}


def adopt_existing(country_code: str, phone_number: str, by: str) -> dict[str, Any]:
    """Take over a connection found at the provider: point it at this platform's inbound address with a new secret."""
    row = _row()
    if row is None or not _secrets(row).get("api_key"):
        raise ValidationFailed("Paste and test the key first")
    if _conn(row).get("status") in (*OPEN_STATES, "connected"):
        raise Conflict("A number is already connected or waiting. Disconnect it first")
    provider = _provider(row)
    country, number = _digits(country_code), _digits(phone_number)
    info: ChatConnectionInfo | None = _call(row, lambda: provider.find_connection(_ctx(row, provider), country, number))
    if info is None or not info.active:
        raise ValidationFailed("No active connection was found for that number at the provider")
    token, token_hash, secret = _new_endpoint()
    url = _needs_address(token)
    found_conn = {
        "tenant_ref": info.tenant_ref,
        "connection_ref": info.connection_ref,
        "phone_number_id": info.phone_number_id or "",
    }
    ctx = ChatContext(
        config=_config_of(provider, row),
        secrets=_secrets(row),
        http=chat_channel.new_http_client(),
        connection=found_conn,
    )
    _call(row, lambda: provider.update_webhook(ctx, url, secret))
    secrets = _secrets(row)
    secrets["webhook_secret"] = secret
    _put_secrets(secrets, by)
    _put(
        by,
        token_hash=token_hash,
        enabled=False,
        connection={
            **found_conn,
            "status": "connected",
            "mode": "existing",
            "number": f"+{country}{number}",
            "country_code": country,
            "display_phone": info.display_phone,
        },
    )
    return _state_dict(_row())


def rotate_secret(by: str) -> dict[str, Any]:
    """A new signing secret and a new address token, given to the provider first; the old ones are replaced only after
    the provider accepted the new ones."""
    row, provider, ctx = context()
    if _conn(row).get("status") != "connected":
        raise Conflict("Connect a number first")
    token, token_hash, secret = _new_endpoint()
    url = _needs_address(token)
    _call(row, lambda: provider.update_webhook(ctx, url, secret))
    secrets = _secrets(row)
    secrets["webhook_secret"] = secret
    _put_secrets(secrets, by)
    _put(by, token_hash=token_hash)
    return {"rotated": True}


def disconnect(confirm: str, by: str) -> dict[str, Any]:
    """Remove the number at the provider and forget it here. `confirm` must be the number."""
    row = _row()
    c = _conn(row)
    if row is None or not c.get("tenant_ref") or c.get("status") in (None, "none", "cancelled", "failed"):
        raise Conflict("No number is connected")
    if _digits(confirm) != _digits(str(c.get("number") or "")):
        raise ValidationFailed("Type the number to confirm, exactly as it is shown")
    provider = _provider(row)
    if c.get("status") in OPEN_STATES and c.get("request_ref"):
        chat_channel.call(lambda: provider.cancel_connect(_ctx(row, provider), str(c["request_ref"])))
    elif c.get("status") == "connected":
        _call(row, lambda: provider.disconnect(_ctx(row, provider)))
    secrets = _secrets(row)
    secrets.pop("webhook_secret", None)
    _put_secrets(secrets, by)
    _put(by, connection={}, token_hash=None, enabled=False)
    return {"disconnected": True}


# --------------------------------------------------------------------------- on and off
def why_not_ready(row: dict[str, Any] | None) -> str | None:
    if row is None or not _secrets(row).get("api_key"):
        return "key"
    if row["key_tested_ok"] is not True:
        return "test"
    if _conn(row).get("status") != "connected":
        return "connect"
    return None


def set_enabled(on: bool, by: str) -> dict[str, Any]:
    row = _row()
    if on:
        why = why_not_ready(row)
        if why:
            raise Conflict(
                {"key": "Paste the key first", "test": "Test the key first", "connect": "Connect a number first"}[why]
            )
    elif row is None:
        return {"enabled": False}
    _put(by, enabled=on)
    return {"enabled": on}


# --------------------------------------------------------------------------- try it and test message
def try_it(message: str, lang: str | None) -> dict[str, Any]:
    """What the bot would say to this message, exactly as it would be sent. Nothing is sent, stored or counted as a
    conversation (the model call is counted in the usage like any other)."""
    used, wait = limits.count_use("chat-try", "operator", 60)
    if used > TRY_PER_MINUTE:
        raise TooManyRequests("Too many tries. Wait a moment.", {"retry_after": wait})
    clean = message.strip()
    if not clean:
        raise ValidationFailed("Type a question to try")
    row = _row()
    texts = bot_texts(row)
    forced = lang if lang in ("en", "sw") else None
    reply = chat_brain.compose(
        "text",
        clean,
        None,
        texts=texts if not forced else _with_language(texts, forced),
        history=[],
        last_lang=forced,
        first_contact=False,
    )
    return {
        "text": reply.text,
        "buttons": [{"id": b.id, "title": b.title} for b in reply.buttons],
        "outcome": reply.outcome,
        "lang": reply.lang,
    }


def _with_language(texts: chat_brain.BotTexts, lang: str) -> chat_brain.BotTexts:
    from dataclasses import replace

    return replace(texts, language=lang)


def send_test_message(to: str, by: str) -> dict[str, Any]:
    """A real message to a number the owner types. It works only inside the 24-hour window after that number wrote to
    the
    bot, which is the provider's rule; a refusal is reported in plain words."""
    row, provider, ctx = context()
    if _conn(row).get("status") != "connected":
        raise Conflict("Connect a number first")
    digits = _digits(to)
    if not 8 <= len(digits) <= 15:
        raise ValidationFailed("Type the number to send to, with its country code")
    used, wait = limits.count_use("chat-test", "operator", 3600)
    if used > TEST_MESSAGES_PER_HOUR:
        raise TooManyRequests("Too many test messages. Try again later.", {"retry_after": wait})
    from ziira.kernel.platform import chat_inbound

    if chat_inbound.is_opted_out(digits):
        raise ValidationFailed("That number asked not to be messaged")
    reply = ChatReply("This is a test message from the Ziira bot. You can ignore it.")
    _call(row, lambda: provider.send(ctx, digits, reply, f"test-{uuid4().hex}"))
    return {"sent": True, "to": chat_brain.mask_number(digits)}


# --------------------------------------------------------------------------- hand-offs and counters
def handoffs(status: str | None, limit: int = 50) -> list[dict[str, Any]]:
    if status not in (None, "open", "done"):
        raise ValidationFailed("Status is open or done")
    with master_session() as m:
        rows = m.execute(
            text(
                "select id, sender_masked, snippet, status, created_at, done_at, done_by from master.chat_handoff "
                "where (cast(:s as text) is null or status = :s) order by created_at desc limit :l"
            ),
            {"s": status, "l": limit},
        ).all()
    return [dict(r._mapping) for r in rows]


def mark_handoff_done(handoff_id: UUID, by: str) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(
            text(
                "update master.chat_handoff set status = 'done', done_at = now(), done_by = :b where id = :i "
                "returning id, sender_masked, snippet, status, created_at, done_at, done_by"
            ),
            {"i": str(handoff_id), "b": by},
        ).first()
    if row is None:
        raise NotFound("No such request")
    return dict(row._mapping)


def counters(last: int = 50) -> dict[str, Any]:
    """Outcomes of the last conversations (counts only): answered, unknown, opted_out, failed, and everything else."""
    with master_session() as m:
        rows = m.execute(
            text(
                "select outcome, count(*) as n from (select outcome from master.chat_event "
                "where outcome <> 'received' order by received_at desc limit :l) x group by outcome"
            ),
            {"l": last},
        ).all()
        open_n = m.execute(text("select count(*) from master.chat_handoff where status = 'open'")).scalar() or 0
    by = {r.outcome: int(r.n) for r in rows}
    known = {k: by.pop(k, 0) for k in OUTCOMES}
    return {
        "last": last,
        "answered": known["answered"]
        + by.pop("answered_checked", 0)
        + by.pop("welcome", 0)
        + by.pop("smalltalk", 0)
        + by.pop("handoff", 0),
        "unknown": known["unknown"],
        "opted_out": known["opted_out"],
        "failed": known["failed"] + by.pop("provider_failed", 0),
        "other": sum(by.values()),
        "open_handoffs": int(open_n),
    }


# --------------------------------------------------------------------------- the whole picture
def overview() -> dict[str, Any]:
    row = _row()
    options = chat_channel.installed()
    provider = options[0]() if options else None
    secrets = _secrets(row)
    url, problem = inbound_address(None)
    why = why_not_ready(row)
    fields = []
    if provider is not None:
        config = _config_of(provider, row)
        for f in provider.config_fields:
            fields.append(
                {
                    "name": f.name,
                    "label": f.label,
                    "secret": f.secret,
                    "required": f.required,
                    "help": f.help,
                    "value": None if f.secret else config.get(f.name, ""),
                    "is_set": bool(secrets.get(f.name)) if f.secret else bool(config.get(f.name, "").strip()),
                }
            )
    return {
        "provider": None
        if provider is None
        else {"name": provider.name, "title": provider.title, "description": provider.description, "fields": fields},
        "fake": chat_channel.fake_mode(),
        "key": {
            "is_set": bool(secrets.get("api_key")),
            "tested_ok": (row or {}).get("key_tested_ok"),
            "tested_at": (row or {}).get("key_tested_at"),
        },
        "connection": _state_dict(row),
        "webhook": {"url": url, "problem": problem, "secret_set": bool(secrets.get("webhook_secret"))},
        "bot": {
            "enabled": bool(row and row["enabled"]),
            "can_enable": why is None,
            "not_ready_because": why,
            "texts": texts_of(row),
        },
        "stats": counters(),
        "updated_at": (row or {}).get("updated_at"),
        "updated_by": (row or {}).get("updated_by"),
    }


# --------------------------------------------------------------------------- development only (ZIIRA_CHAT_FAKE=1)
def _dev_only() -> None:
    if not chat_channel.fake_mode():
        raise NotFound("Not found")


def dev_state() -> dict[str, Any]:
    """What the practice provider holds: the messages it was asked to send. Development only."""
    _dev_only()
    provider = chat_channel.the_provider()
    return {"sent": provider.captured_sends()}


def dev_simulate(sender: str, message: str, button_id: str | None) -> dict[str, Any]:
    """A signed delivery from `sender`, run through the real inbound path. Returns the answer the provider would have
    received (`status`, `reply`) and what the practice provider has been asked to send since. Development only."""
    _dev_only()
    from ziira.kernel.platform import chat_inbound

    row, provider, ctx = context()
    secret = _secrets(row).get("webhook_secret")
    if not secret or _conn(row).get("status") != "connected":
        raise Conflict("Connect a number first")
    digits = _digits(sender)
    if not 8 <= len(digits) <= 15:
        raise ValidationFailed("Type a sender number with its country code")
    headers, body = provider.simulate_delivery(
        secret, digits, message, button_id, ctx.connection.get("phone_number_id")
    )
    result = chat_inbound.process(row, provider, headers, body, None)
    chat_inbound.run_pending()
    return {"status": result.status, "reply": result.body, "sent": provider.captured_sends()[-5:]}
