"""AI providers managed by the platform owner in the Super Admin (docs/ai.md, "Providers and the Super Admin").

A provider is a plugin implementing the `intel.llm` extension point; it declares its title, capabilities, base URL and
models (with prices) as data in its own `models.toml`. This module holds what the owner decides about each one:

- switched on or off, the API key (encrypted, write-only; only its last four characters are ever shown), an optional
  base URL, which model each feature uses (`explain`, `rank`, `ask`) and price overrides;
- the default provider for the whole platform (changing it ends every business's consent: see `change_default`), and a
  per-business exception an operator can make for a stated reason;
- a monthly spend cap in USD, and the estimated spend per day/provider/model/business (token counts times the price
  table: counts and money only, no personal data);
- the data-use acknowledgement per provider: in production no call is made for a provider until it is recorded.

The business-facing gateway (`intel/services/ai.py`) asks `runtime(feature, tenant_id)` which provider, key and model to
use; the answer is cached for 30 seconds and dropped at once when anything changes here. With nothing configured in the
Super Admin it falls back to the `ZIIRA_AI_*` environment settings (development, and installations that predate this).

This module names no provider: titles, ids and prices come from the plugins' data.
"""

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations, implementations_of
from ziira.kernel.security import decrypt, encrypt

log = logging.getLogger("ziira.platform.ai")
INTEL_LLM = "intel.llm"
AI_PLATFORM = "kernel.ai_platform"
FEATURES = ("explain", "rank", "ask")
PLATFORM_TESTS = UUID(int=0)                  # usage of the Super Admin's own tests and quality checks
CACHE_SECONDS = 30.0
MILLION = Decimal(1_000_000)


class AiPlatformHooks(ABC):
    """What the platform asks Intelligence for (`@provides("kernel.ai_platform")`): how many businesses hold a valid
    consent for a provider, and a scored quality check of a provider. Kernel code never reads a unit's tables."""

    @abstractmethod
    def valid_consents(self, session: Any, provider: str) -> int:
        """Companies of this business whose AI consent is valid for `provider`."""

    @abstractmethod
    def quality_plan(self, level: str) -> dict[str, Any]:
        """`{"questions": n, "tokens_in": estimate, "tokens_out": estimate}` for a level (`quick` or `full`)."""

    @abstractmethod
    def quality_check(self, provider: Any, level: str) -> dict[str, Any]:
        """Run the check against a synthetic fixture with this provider instance; returns the scored report."""


define_extension_point(AI_PLATFORM, AiPlatformHooks, "What the Super Admin asks the AI layer for")


def _now() -> datetime:
    return datetime.now(UTC)


def month_start(today: date | None = None) -> date:
    return (today or _now().date()).replace(day=1)


def is_production() -> bool:
    return get_settings().env == "production"


# --------------------------------------------------------------------------- the plugins
def installed() -> list[type]:
    """Every provider plugin that declares a catalog (the fake provider declares none)."""
    return sorted((c for c in implementations_of(INTEL_LLM) if c.catalog() is not None), key=lambda c: c.name)  # type: ignore[attr-defined]


def plugin(name: str) -> type:
    found = next((c for c in installed() if c.name == name), None)  # type: ignore[attr-defined]
    if found is None:
        raise NotFound("No such AI provider")
    return found


def catalog_of(cls: type) -> Any:
    return cls.catalog()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- stored settings
@dataclass
class Row:
    provider: str
    enabled: bool = False
    key: str = ""
    key_last4: str = ""
    base_url: str = ""
    models: dict[str, str] = field(default_factory=dict)
    price_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    live_models: list[dict[str, str]] | None = None
    live_models_at: datetime | None = None
    last_tested_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_message: str | None = None
    terms_ack_by: str | None = None
    terms_ack_at: datetime | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


def _read_row(r: Any) -> Row:
    key = ""
    if r.secret_encrypted:
        try:
            key = decrypt(r.secret_encrypted)
        except RuntimeError:
            key = ""
    return Row(r.provider, r.enabled, key, r.key_last4 or "", r.base_url or "", dict(r.models or {}),
               dict(r.price_overrides or {}), r.live_models, r.live_models_at, r.last_tested_at, r.last_test_ok,
               r.last_test_message, r.terms_ack_by, r.terms_ack_at, r.updated_at, r.updated_by)


def _setting(m: Any, key: str) -> Any:
    row = m.execute(text("select value from master.platform_setting where key = :k"), {"k": key}).first()
    return row.value if row else None


def _stored_default() -> str | None:
    with master_session() as m:
        return _setting(m, "ai.default_provider") or None


def _put_setting(m: Any, key: str, value: Any, by: str) -> None:
    m.execute(text("insert into master.platform_setting (key, value, updated_by) values (:k, cast(:v as jsonb), :b) "
                   "on conflict (key) do update set value = excluded.value, updated_at = now(), "
                   "updated_by = excluded.updated_by"), {"k": key, "v": json.dumps(value), "b": by})


@dataclass
class Snapshot:
    taken: float
    rows: dict[str, Row]
    default: str | None
    cap_usd: Decimal | None
    spend_usd: Decimal
    overrides: dict[UUID, str]


_lock = threading.Lock()
_snapshot: Snapshot | None = None


def invalidate() -> None:
    """Forget what was read from the settings (this process; others notice within 30 seconds)."""
    global _snapshot
    with _lock:
        _snapshot = None


def _load() -> Snapshot:
    with master_session() as m:
        rows = {r.provider: _read_row(r) for r in m.execute(text("select * from master.ai_provider"))}
        default = _setting(m, "ai.default_provider")
        cap = _setting(m, "ai.monthly_cap_usd")
        spend = m.execute(text("select coalesce(sum(cost_usd), 0) from master.ai_usage where day >= :d"),
                          {"d": month_start()}).scalar() or Decimal(0)
        overrides = {r.tenant_id: r.provider for r in m.execute(
            text("select tenant_id, provider from master.ai_tenant_provider"))}
    return Snapshot(time.monotonic(), rows, default or None, Decimal(str(cap)) if cap not in (None, "") else None,
                    Decimal(spend), overrides)


def snapshot() -> Snapshot:
    global _snapshot
    with _lock:
        current = _snapshot
    if current is None or time.monotonic() - current.taken > CACHE_SECONDS:
        current = _load()
        with _lock:
            _snapshot = current
    return current


# --------------------------------------------------------------------------- prices
def price_of(row: Row | None, cls: type, model: str) -> tuple[Decimal, Decimal] | None:
    """USD per million input and output tokens for a model: the owner's override, else the plugin's data, else None."""
    if row and model in row.price_overrides:
        o = row.price_overrides[model]
        return Decimal(str(o["input"])), Decimal(str(o["output"]))
    info = catalog_of(cls).model(model)
    return (info.input_per_mtok, info.output_per_mtok) if info else None


def cost_of(prices: tuple[Decimal, Decimal] | None, tokens_in: int, tokens_out: int) -> Decimal:
    if prices is None:
        return Decimal(0)
    return (prices[0] * tokens_in + prices[1] * tokens_out) / MILLION


def chosen_model(row: Row | None, cls: type, feature: str) -> str:
    return (row.models.get(feature) if row else None) or catalog_of(cls).default_model(feature)


# --------------------------------------------------------------------------- what the gateway uses
@dataclass(frozen=True)
class Runtime:
    """Which provider, key and model to use for one feature, and whether the platform lets the call happen."""

    provider: str
    cls: type
    api_key: str
    model: str
    base_url: str | None
    options: dict[str, Any]
    source: str                         # "platform" (Super Admin) or "environment"
    terms_ok: bool
    spend_ok: bool

    def build(self) -> Any:
        s = get_settings()
        return self.cls.from_settings(api_key=self.api_key, model=self.model, base_url=self.base_url,  # type: ignore[attr-defined]
                                      timeout=s.ai_timeout_seconds, max_retries=s.ai_max_retries,
                                      options=self.options)


def runtime(feature: str = "ask", tenant_id: UUID | None = None) -> Runtime | None:
    """The provider to use now, or None when nothing is set up (or the chosen provider is not installed)."""
    snap = snapshot()
    name = (snap.overrides.get(tenant_id) if tenant_id else None) or snap.default
    spend_ok = snap.cap_usd is None or snap.spend_usd < snap.cap_usd
    if name:
        row = snap.rows.get(name)
        cls = next((c for c in installed() if c.name == name), None)  # type: ignore[attr-defined]
        if cls is None or row is None or not row.enabled or not row.key:
            return None
        model = chosen_model(row, cls, feature)
        info = catalog_of(cls).model(model)
        return Runtime(name, cls, row.key, model, row.base_url or None, dict(info.options) if info else {},
                       "platform", (not is_production()) or row.terms_ack_at is not None, spend_ok)
    s = get_settings()
    if not s.ai_provider:
        return None
    env_cls = next((c for c in implementations_of(INTEL_LLM) if getattr(c, "name", None) == s.ai_provider), None)
    if env_cls is None or (s.ai_provider == "fake" and is_production()):
        return None
    cat = env_cls.catalog()  # type: ignore[attr-defined]
    model = s.ai_model or (cat.default_model(feature) if cat else "")
    info = cat.model(model) if cat else None
    return Runtime(s.ai_provider, env_cls, s.ai_api_key, model, s.ai_base_url or None,
                   dict(info.options) if info else {}, "environment",
                   (not is_production()) or s.ai_terms_confirmed, spend_ok)


def active_secrets() -> list[str]:
    """Every key the platform holds (to remove from any text before it is stored or shown)."""
    return [r.key for r in snapshot().rows.values() if r.key] + [get_settings().ai_api_key]


def record_usage(tenant_id: UUID, provider: str, model: str, tokens_in: int, tokens_out: int) -> None:
    """Add one call to the day's estimate, and flag the cap when this call reaches it."""
    snap = snapshot()
    cls = next((c for c in installed() if c.name == provider), None)  # type: ignore[attr-defined]
    cost = cost_of(price_of(snap.rows.get(provider), cls, model), tokens_in, tokens_out) if cls else Decimal(0)
    with master_session() as m:
        m.execute(text(
            "insert into master.ai_usage (day, provider, model, tenant_id, calls, tokens_in, tokens_out, cost_usd) "
            "values (:d, :p, :m, :t, 1, :i, :o, :c) on conflict (day, provider, model, tenant_id) do update set "
            "calls = master.ai_usage.calls + 1, tokens_in = master.ai_usage.tokens_in + excluded.tokens_in, "
            "tokens_out = master.ai_usage.tokens_out + excluded.tokens_out, "
            "cost_usd = master.ai_usage.cost_usd + excluded.cost_usd"),
            {"d": _now().date(), "p": provider, "m": model[:100], "t": str(tenant_id), "i": tokens_in,
             "o": tokens_out, "c": cost})
        snap.spend_usd += cost
        if snap.cap_usd is not None and snap.spend_usd >= snap.cap_usd:
            _put_setting(m, "ai.cap_reached_month", month_start().isoformat(), "system")


# --------------------------------------------------------------------------- the Super Admin's view
def _live(row: Row | None, cls: type) -> list[dict[str, str]]:
    return list(row.live_models or []) if row else []


def _choice(row: Row | None, cls: type, model_id: str, title: str, tiers: list[str], notes: str, in_catalog: bool,
            live: bool | None) -> dict[str, Any]:
    price = price_of(row, cls, model_id)
    return {"id": model_id, "title": title, "tiers": tiers, "notes": notes,
            "input_per_mtok": str(price[0]) if price else None, "output_per_mtok": str(price[1]) if price else None,
            "price_overridden": bool(row and model_id in row.price_overrides), "in_catalog": in_catalog, "live": live}


def _model_view(row: Row | None, cls: type) -> list[dict[str, Any]]:
    """The models to pick from: the plugin's recommended ones, then any others in the live list or already chosen."""
    live_ids = {m["id"] for m in row.live_models} if row and row.live_models is not None else None
    out = [_choice(row, cls, i.id, i.title, list(i.tiers), i.notes, True,
                   None if live_ids is None else i.id in live_ids) for i in catalog_of(cls).models]
    known = {c["id"] for c in out}
    for entry in _live(row, cls):
        if entry["id"] not in known:
            out.append(_choice(row, cls, entry["id"], entry.get("title") or entry["id"], [], "", False, True))
            known.add(entry["id"])
    wanted = {row.models.get(f) for f in FEATURES} if row else set()
    for extra in sorted(m for m in wanted if m and m not in known):
        out.append(_choice(row, cls, extra, extra, [], "", False, None))
    return out


def overview() -> dict[str, Any]:
    """Every installed provider with its settings, and the platform-wide settings. Keys are never included."""
    invalidate()
    snap = snapshot()
    providers = []
    for cls in installed():
        row = snap.rows.get(cls.name)  # type: ignore[attr-defined]
        cat = catalog_of(cls)
        providers.append({
            "name": cat.name, "title": cat.title, "capabilities": list(cat.capabilities), "auth": cat.auth,
            "default_base_url": cat.base_url, "base_url": row.base_url if row else "",
            "terms_url": cat.terms_url, "docs_url": cat.docs_url, "verified_on": cat.verified_on,
            "prices_updated": cat.prices_updated, "price_source": cat.price_source,
            "enabled": bool(row and row.enabled), "key_set": bool(row and row.key),
            "key_last4": row.key_last4 if row else "",
            "models": {f: chosen_model(row, cls, f) for f in FEATURES},
            "model_choices": _model_view(row, cls),
            "live_models_at": row.live_models_at if row else None,
            "last_tested_at": row.last_tested_at if row else None,
            "last_test_ok": row.last_test_ok if row else None,
            "last_test_message": row.last_test_message if row else None,
            "terms_ack_by": row.terms_ack_by if row else None,
            "terms_ack_at": row.terms_ack_at if row else None,
            "is_default": snap.default == cat.name,
            "updated_at": row.updated_at if row else None, "updated_by": row.updated_by if row else None,
        })
    env = get_settings()
    reached = snap.cap_usd is not None and snap.spend_usd >= snap.cap_usd
    return {
        "providers": providers, "default_provider": snap.default,
        "environment_provider": env.ai_provider or None if not snap.default else None,
        "monthly_cap_usd": str(snap.cap_usd) if snap.cap_usd is not None else None,
        "month_spend_usd": str(snap.spend_usd.quantize(Decimal("0.0001"))), "cap_reached": reached,
        "production": is_production(),
    }


# --------------------------------------------------------------------------- changing settings
def _clean_url(value: str) -> str:
    clean = value.strip().rstrip("/")
    if not clean:
        return ""
    host = clean.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
    local = host in ("localhost", "127.0.0.1", "[::1]") or host.endswith((".localhost", ".test"))
    if not (clean.startswith("https://") or (clean.startswith("http://") and local)) or len(clean) > 300:
        raise ValidationFailed("The base URL must be an https address")
    return clean


def _check_model(row: Row | None, model: str, live_override: list[dict[str, str]] | None = None) -> str:
    clean = model.strip()
    if not clean or len(clean) > 100 or any(c.isspace() for c in clean):
        raise ValidationFailed("A model id is a short name without spaces")
    live = live_override if live_override is not None else (row.live_models if row else None)
    if live is not None and clean not in {m["id"] for m in live}:
        raise ValidationFailed(f"'{clean}' is not in the live model list: refresh the models or pick another")
    return clean


def _price(value: Any, what: str) -> str:
    try:
        number = Decimal(str(value))
    except Exception:  # noqa: BLE001
        raise ValidationFailed(f"{what} is a number of US dollars per million tokens") from None
    if not Decimal(0) <= number <= Decimal(10000):
        raise ValidationFailed(f"{what} is from 0 to 10000")
    return format(number.normalize(), "f")


def save_provider(name: str, *, enabled: bool | None, api_key: str | None, clear_key: bool, base_url: str | None,
                  models: dict[str, str] | None, price_overrides: dict[str, dict[str, Any] | None] | None,
                  terms_acknowledged: bool | None, by: str) -> dict[str, Any]:
    """Change one provider's settings. A key left out is kept; `clear_key` removes it and switches the provider off."""
    cls = plugin(name)
    with master_session() as m:
        existing = m.execute(text("select * from master.ai_provider where provider = :p"), {"p": name}).first()
    row = _read_row(existing) if existing else Row(name)
    for feature in models or {}:
        if feature not in FEATURES:
            raise ValidationFailed("Features are: " + ", ".join(FEATURES))
    new_models = {**row.models, **{f: _check_model(row, v) for f, v in (models or {}).items()}}
    new_prices = dict(row.price_overrides)
    for model_id, value in (price_overrides or {}).items():
        if value is None:
            new_prices.pop(model_id, None)
        else:
            new_prices[model_id] = {"input": _price(value.get("input"), "The input price"),
                                    "output": _price(value.get("output"), "The output price")}
    key, last4 = row.key, row.key_last4
    if clear_key:
        key, last4 = "", ""
    if api_key is not None and api_key.strip():
        clean = api_key.strip()
        if len(clean) < 8 or len(clean) > 500 or any(c.isspace() for c in clean):
            raise ValidationFailed("That does not look like an API key: paste it exactly as the provider shows it")
        key, last4 = clean, clean[-4:]
    now_enabled = row.enabled if enabled is None else enabled
    if clear_key:
        now_enabled = False
    if now_enabled and not key:
        raise ValidationFailed("Save an API key before switching this provider on")
    url = _clean_url(base_url) if base_url is not None else row.base_url
    ack_by, ack_at = row.terms_ack_by, row.terms_ack_at
    if terms_acknowledged is True and ack_at is None:
        ack_by, ack_at = by, _now()
    elif terms_acknowledged is False:
        ack_by, ack_at = None, None
    if key != row.key or url != row.base_url:                 # a new key or address: the old list and test are stale
        live, live_at, tested_at, tested_ok, tested_msg = None, None, None, None, None
    else:
        live, live_at, tested_at, tested_ok, tested_msg = (row.live_models, row.live_models_at, row.last_tested_at,
                                                           row.last_test_ok, row.last_test_message)
    if not now_enabled and _stored_default() == name:
        raise ValidationFailed("This is the default provider: choose another default before switching it off")
    with master_session() as m:
        m.execute(text(
            "insert into master.ai_provider (provider, enabled, secret_encrypted, key_last4, base_url, models, "
            "price_overrides, live_models, live_models_at, last_tested_at, last_test_ok, last_test_message, "
            "terms_ack_by, terms_ack_at, updated_by) values (:p, :e, :s, :l, :u, cast(:m as jsonb), cast(:o as jsonb), "
            "cast(:lm as jsonb), :lma, :lt, :lo, :lmsg, :ab, :aa, :b) on conflict (provider) do update set "
            "enabled = excluded.enabled, secret_encrypted = excluded.secret_encrypted, key_last4 = excluded.key_last4, "
            "base_url = excluded.base_url, models = excluded.models, price_overrides = excluded.price_overrides, "
            "live_models = excluded.live_models, live_models_at = excluded.live_models_at, "
            "last_tested_at = excluded.last_tested_at, last_test_ok = excluded.last_test_ok, "
            "last_test_message = excluded.last_test_message, terms_ack_by = excluded.terms_ack_by, "
            "terms_ack_at = excluded.terms_ack_at, updated_at = now(), updated_by = excluded.updated_by"),
            {"p": name, "e": now_enabled, "s": encrypt(key) if key else None, "l": last4 or None, "u": url or None,
             "m": json.dumps(new_models), "o": json.dumps(new_prices),
             "lm": json.dumps(live) if live is not None else None, "lma": live_at, "lt": tested_at, "lo": tested_ok,
             "lmsg": tested_msg, "ab": ack_by, "aa": ack_at, "b": by})
    invalidate()
    return next(p for p in overview()["providers"] if p["name"] == cls.name)  # type: ignore[attr-defined]


def _provider_instance(name: str, model: str | None = None) -> tuple[Any, type, Row]:
    cls = plugin(name)
    with master_session() as m:
        found = m.execute(text("select * from master.ai_provider where provider = :p"), {"p": name}).first()
    row = _read_row(found) if found else Row(name)
    if not row.key:
        raise ValidationFailed("Save an API key first")
    chosen = model or chosen_model(row, cls, "ask")
    cat = catalog_of(cls)
    info = cat.model(chosen)
    s = get_settings()
    instance = cls.from_settings(api_key=row.key, model=chosen, base_url=row.base_url or None,  # type: ignore[attr-defined]
                                 timeout=s.ai_timeout_seconds, max_retries=s.ai_max_retries,
                                 options=dict(info.options) if info else {})
    return instance, cls, row


def _safe(message: str, row: Row) -> str:
    from ziira.modules.intel.domain.ai_rules import hide_secrets  # noqa: PLC0415 - shared key-shape scrubber
    return hide_secrets(message, [row.key])[:300]


def refresh_models(name: str, by: str) -> dict[str, Any]:
    """Ask the provider which models exist for this key and keep the list (to check choices and to offer them)."""
    instance, cls, row = _provider_instance(name)
    cat = catalog_of(cls)
    try:
        found = instance.list_models()
    except Exception as error:  # noqa: BLE001 - shown to the operator, with any key removed
        raise ValidationFailed(f"The provider's model list could not be read: {_safe(str(error), row)}") from None
    kept = [{"id": m.id, "title": m.title} for m in found
            if not cat.live_prefixes or m.id.startswith(tuple(cat.live_prefixes))]
    kept.sort(key=lambda m: m["id"])
    with master_session() as m:
        m.execute(text("update master.ai_provider set live_models = cast(:l as jsonb), live_models_at = now(), "
                       "updated_by = :b where provider = :p"), {"l": json.dumps(kept), "b": by, "p": name})
    invalidate()
    missing = [mid for mid in {chosen_model(row, cls, f) for f in FEATURES} if mid not in {k["id"] for k in kept}]
    return {"count": len(kept), "missing_chosen": sorted(missing)}


def check_connection(name: str) -> dict[str, Any]:
    """A tiny real call with the saved key and the Ask model: ok or not, how long, what it cost (an estimate)."""
    instance, cls, row = _provider_instance(name)
    started = time.monotonic()
    ok, message, tin, tout = True, "The provider answered.", 0, 0
    try:
        reply = instance.ping()
        tin, tout = reply.usage.input_tokens, reply.usage.output_tokens
    except Exception as error:  # noqa: BLE001
        ok, message = False, _safe(str(error), row)
    latency = int((time.monotonic() - started) * 1000)
    model = instance.model_id()
    cost = cost_of(price_of(row, cls, model), tin, tout)
    if ok or tin or tout:
        record_usage(PLATFORM_TESTS, name, model, tin, tout)
    with master_session() as m:
        m.execute(text("update master.ai_provider set last_tested_at = now(), last_test_ok = :o, "
                       "last_test_message = :m where provider = :p"), {"o": ok, "m": message, "p": name})
    invalidate()
    return {"ok": ok, "message": message, "latency_ms": latency, "model": model, "tokens_in": tin, "tokens_out": tout,
            "cost_usd": str(cost.quantize(Decimal("0.000001")))}


# --------------------------------------------------------------------------- the default provider
def _tenants() -> list[UUID]:
    with master_session() as m:
        return [r.id for r in m.execute(text("select id from master.tenant where status = 'active'"))]


def consents_for(provider: str) -> int:
    """How many companies hold a valid AI consent for `provider` (asked of Intelligence, business by business)."""
    total = 0
    for tenant_id in _tenants():
        try:
            with tenant_session(tenant_id, admin=True) as s:
                for hook in implementations(s, AI_PLATFORM):
                    total += int(hook.valid_consents(s, provider))
        except Exception:  # noqa: BLE001 - one unreadable business must not block the owner's decision
            log.warning("Could not count AI consents for tenant %s", tenant_id)
    return total


def default_change_preview(provider: str) -> dict[str, Any]:
    """What switching the default to `provider` would do: the provider now in use and how many consents end."""
    plugin(provider)
    current = runtime("ask")
    now_name = current.provider if current else None
    affected = consents_for(now_name) if now_name and now_name != provider else 0
    return {"from_provider": now_name, "to_provider": provider, "consents_affected": affected}


def change_default(provider: str, *, confirm: str, reason: str, by: str) -> dict[str, Any]:
    """Make `provider` the platform's default. Every business's consent names the provider it was given for, so those
    given for the old one stop working until an Owner agrees again; the owner types the provider's code to confirm."""
    cls = plugin(provider)
    if confirm.strip().lower() != provider:
        raise ValidationFailed(f"Type '{provider}' to confirm")
    if len(reason.strip()) < 3:
        raise ValidationFailed("Say why the default provider is changing")
    snap = snapshot()
    row = snap.rows.get(provider)
    if not (row and row.enabled and row.key):
        raise ValidationFailed("Switch the provider on and save its key before making it the default")
    preview = default_change_preview(provider)
    with master_session() as m:
        _put_setting(m, "ai.default_provider", provider, by)
    invalidate()
    return {**preview, "provider": cls.name}  # type: ignore[attr-defined]


def set_cap(cap_usd: str | None, by: str) -> dict[str, Any]:
    """Set (or with None remove) the platform's monthly spend cap in USD. Setting it clears a reached-cap flag."""
    value: str | None = None
    if cap_usd not in (None, ""):
        value = _price(cap_usd, "The monthly cap")
    with master_session() as m:
        _put_setting(m, "ai.monthly_cap_usd", value, by)
        _put_setting(m, "ai.cap_reached_month", None, by)
    invalidate()
    return overview()


def cap_reached_flag() -> str | None:
    """The month (YYYY-MM-01) in which the cap was reached, if so and it is still this month: the operator's flag."""
    with master_session() as m:
        flag = _setting(m, "ai.cap_reached_month")
    return flag if flag == month_start().isoformat() else None


# --------------------------------------------------------------------------- per-business exceptions
def set_tenant_provider(tenant_code: str, provider: str | None, reason: str, by: str) -> dict[str, Any]:
    """Make one business use another provider than the default (or, with None, go back to the default)."""
    with master_session() as m:
        tenant = m.execute(text("select id from master.tenant where code = :c"), {"c": tenant_code}).first()
    if tenant is None:
        raise NotFound("No such business")
    if len(reason.strip()) < 3:
        raise ValidationFailed("Say why this business is an exception")
    if provider is not None:
        plugin(provider)
    with master_session() as m:
        if provider is None:
            m.execute(text("delete from master.ai_tenant_provider where tenant_id = :t"), {"t": str(tenant.id)})
        else:
            m.execute(text(
                "insert into master.ai_tenant_provider (tenant_id, provider, reason, set_by) values (:t, :p, :r, :b) "
                "on conflict (tenant_id) do update set provider = excluded.provider, reason = excluded.reason, "
                "set_by = excluded.set_by, set_at = now()"),
                {"t": str(tenant.id), "p": provider, "r": reason.strip()[:300], "b": by})
    invalidate()
    return {"tenant": tenant_code, "provider": provider}


def tenant_overrides() -> list[dict[str, Any]]:
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text(
            "select t.code, t.name, o.provider, o.reason, o.set_by, o.set_at from master.ai_tenant_provider o "
            "join master.tenant t on t.id = o.tenant_id order by t.code"))]


# --------------------------------------------------------------------------- usage
def usage_report() -> dict[str, Any]:
    """This month's tokens and estimated spend per provider, the ten busiest businesses, and spend per day."""
    start = month_start()
    with master_session() as m:
        per_provider = [dict(r._mapping) for r in m.execute(text(
            "select provider, sum(calls)::int as calls, sum(tokens_in)::bigint as tokens_in, "
            "sum(tokens_out)::bigint as tokens_out, sum(cost_usd) as cost_usd from master.ai_usage "
            "where day >= :d group by provider order by provider"), {"d": start})]
        top = [dict(r._mapping) for r in m.execute(text(
            "select t.code, t.name, sum(u.calls)::int as calls, sum(u.tokens_in + u.tokens_out)::bigint as tokens, "
            "sum(u.cost_usd) as cost_usd from master.ai_usage u join master.tenant t on t.id = u.tenant_id "
            "where u.day >= :d group by t.code, t.name order by sum(u.cost_usd) desc, t.code limit 10"), {"d": start})]
        days = [dict(r._mapping) for r in m.execute(text(
            "select day, sum(cost_usd) as cost_usd, sum(tokens_in + tokens_out)::bigint as tokens from master.ai_usage "
            "where day >= :d group by day order by day"), {"d": start})]
    for item in per_provider + top + days:
        item["cost_usd"] = str(Decimal(item["cost_usd"] or 0).quantize(Decimal("0.0001")))
    snap = snapshot()
    return {"month": start, "providers": per_provider, "top_businesses": top, "days": days,
            "cap_usd": str(snap.cap_usd) if snap.cap_usd is not None else None,
            "spend_usd": str(snap.spend_usd.quantize(Decimal("0.0001"))), "cap_flag": cap_reached_flag()}


# --------------------------------------------------------------------------- quality check
def _hooks() -> AiPlatformHooks:
    found = implementations_of(AI_PLATFORM)
    if not found:
        raise ValidationFailed("The AI layer is not installed on this platform")
    hooks: AiPlatformHooks = found[0]()
    return hooks


def quality_estimate(name: str, level: str, model: str | None) -> dict[str, Any]:
    """What a quality check would cost, before anything is spent."""
    cls = plugin(name)
    with master_session() as m:
        found = m.execute(text("select * from master.ai_provider where provider = :p"), {"p": name}).first()
    row = _read_row(found) if found else None
    chosen = model or chosen_model(row, cls, "ask")
    plan = _hooks().quality_plan(level)
    prices = price_of(row, cls, chosen)
    cost = cost_of(prices, plan["tokens_in"], plan["tokens_out"])
    return {"provider": name, "model": chosen, "level": level, "questions": plan["questions"],
            "tokens_in": plan["tokens_in"], "tokens_out": plan["tokens_out"],
            "estimated_cost_usd": str(cost.quantize(Decimal("0.0001"))), "price_known": prices is not None}


def run_quality_check(name: str, level: str, model: str | None) -> dict[str, Any]:
    """Run the check with real calls (real spend): the routes require the owner's confirmation first."""
    instance, cls, row = _provider_instance(name, model)
    report = _hooks().quality_check(instance, level)
    prices = price_of(row, cls, instance.model_id())
    tin, tout = int(report["tokens_in"]), int(report["tokens_out"])
    cost = cost_of(prices, tin, tout)
    if tin or tout:
        record_usage(PLATFORM_TESTS, name, instance.model_id(), tin, tout)
    return {**report, "model": instance.model_id(), "provider": name,
            "cost_usd": str(cost.quantize(Decimal("0.0001"))), "price_known": prices is not None}
