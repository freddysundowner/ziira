"""The website assistant's settings and limits, managed by the platform owner in the Super Admin (Platform > AI).

The assistant answers visitors of the marketing site (no sign-in, no business data: `kernel/site_assistant.py`). It is
**off until the owner switches it on**, and it has its own limits, separate from the AI that businesses use:

- a monthly spend cap in USD, counted from the platform's AI usage table under one pseudo business (`WEBSITE`);
- how many requests one address may make per minute and per day, and a total per day for everyone;
- the greeting and the quick-reply suggestions the site shows.

Values are `master.platform_setting` rows under `site_assistant.*` (cached briefly; any change clears the cache here).
Per-address counts are kept in `master.auth_throttle` under keyed hashes (no address in the clear), with a window of
their own. Nothing here keeps a visitor's words.
"""

import hashlib
import hmac
import json
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations_of
from ziira.kernel.platform import ai as platform_ai

SITE_ASSISTANT_LLM = "kernel.site_assistant_llm"


class SiteAssistantFailed(Exception):
    """The provider could not answer. The message is safe to log (it never holds a key or the visitor's words)."""


@dataclass(frozen=True)
class SiteReply:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    stop_reason: str | None


class SiteAssistantLlm(ABC):
    """What the website assistant asks the AI layer for (`@provides("kernel.site_assistant_llm")`): one plain-text
    completion with the platform's provider. The AI layer owns the provider contract; kernel code does not."""

    @abstractmethod
    def complete(self, runtime: Any, system: str, user: str, max_tokens: int) -> SiteReply:
        """Ask the model (no tools, no tenant). Scrubs `user`; raises SiteAssistantFailed when it cannot answer."""


define_extension_point(SITE_ASSISTANT_LLM, SiteAssistantLlm, "One plain-text AI completion for the website assistant")

WEBSITE = UUID(int=1)  # the pseudo business the assistant's usage is recorded under
LABEL = "Website assistant"
CACHE_SECONDS = 15.0
DEFAULT_PER_MINUTE = 8
DEFAULT_PER_DAY = 60
DEFAULT_DAILY_TOTAL = 2000
BURST_LIMIT, BURST_SECONDS = 3, 5  # at most three questions in five seconds from one address
MAX_SUGGESTIONS = 6
DEFAULT_GREETING = (
    "Hi, I am Ziira's assistant. Ask me about what Ziira does, who it is for, how the AI works or what it costs."
)
DEFAULT_SUGGESTIONS = [
    "What does Ziira do?",
    "Who is Ziira for?",
    "How does the AI work?",
    "How much does it cost?",
    "Is my data safe?",
    "How do I get started?",
]


def _int(low: int, high: int, what: str) -> Any:
    def parse(value: Any) -> int:
        try:
            number = int(str(value).strip())
        except ValueError:
            raise ValidationFailed(f"{what} is a whole number") from None
        if not low <= number <= high:
            raise ValidationFailed(f"{what} is from {low} to {high}")
        return number

    return parse


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValidationFailed("On or off must be true or false")


def _cap(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValidationFailed("The monthly cap is an amount in USD, such as 5 or 12.50") from None
    if not amount.is_finite() or amount < 0 or amount > Decimal("100000"):
        raise ValidationFailed("The monthly cap is from 0 to 100000 USD")
    return str(amount.quantize(Decimal("0.01")))


def _plain(text_value: str) -> str:
    """Plain text only: no tags, no control characters."""
    clean = re.sub(r"[\x00-\x1f\x7f]", " ", str(text_value))
    if re.search(r"[<>]", clean):
        raise ValidationFailed("Text here is plain words: no < or > please")
    return re.sub(r"\s+", " ", clean).strip()


def _greeting(value: Any) -> str:
    clean = _plain(str(value or ""))
    if len(clean) > 300:
        raise ValidationFailed("The greeting is at most 300 characters")
    return clean


def _suggestions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationFailed("The suggestions are a list of short questions")
    out: list[str] = []
    for item in value:
        clean = _plain(str(item))
        if not clean:
            continue
        if len(clean) > 80:
            raise ValidationFailed("Each suggestion is at most 80 characters")
        if clean not in out:
            out.append(clean)
    if len(out) > MAX_SUGGESTIONS:
        raise ValidationFailed(f"At most {MAX_SUGGESTIONS} suggestions")
    return out


KEYS = {
    "enabled": _bool,
    "monthly_cap_usd": _cap,
    "per_minute": _int(1, 60, "Requests per minute"),
    "per_day": _int(1, 2000, "Requests per day"),
    "daily_total": _int(1, 1_000_000, "The daily total"),
    "greeting": _greeting,
    "suggestions": _suggestions,
}
_cache: dict[str, Any] = {"at": 0.0, "values": {}}
_lock = threading.Lock()


def invalidate() -> None:
    _cache["at"] = 0.0
    _spend["at"] = 0.0


def _stored() -> dict[str, Any]:
    if time.monotonic() - float(_cache["at"]) > CACHE_SECONDS:
        with master_session() as m:
            rows = m.execute(
                text("select key, value from master.platform_setting where key like 'site_assistant.%'")
            ).all()
        _cache["values"] = {r.key.split(".", 1)[1]: r.value for r in rows}
        _cache["at"] = time.monotonic()
    values: dict[str, Any] = _cache["values"]
    return values


def get_all() -> dict[str, Any]:
    """The effective settings (a saved value, else the default)."""
    s = _stored()
    suggestions = s.get("suggestions")
    return {
        "enabled": s.get("enabled") is True,
        "monthly_cap_usd": s.get("monthly_cap_usd") or None,
        "per_minute": int(s.get("per_minute") or DEFAULT_PER_MINUTE),
        "per_day": int(s.get("per_day") or DEFAULT_PER_DAY),
        "daily_total": int(s.get("daily_total") or DEFAULT_DAILY_TOTAL),
        "greeting": str(s.get("greeting") or DEFAULT_GREETING),
        "suggestions": list(suggestions)
        if isinstance(suggestions, list) and suggestions
        else list(DEFAULT_SUGGESTIONS),
    }


def save(changes: dict[str, Any], by: str) -> dict[str, Any]:
    """Validate and save the given settings (only the keys present); returns the overview."""
    unknown = sorted(set(changes) - set(KEYS))
    if unknown:
        raise ValidationFailed("Unknown setting: " + ", ".join(unknown))
    clean = {key: KEYS[key](value) for key, value in changes.items()}
    with master_session() as m:
        for key, value in clean.items():
            m.execute(
                text(
                    "insert into master.platform_setting (key, value, updated_by) values (:k, cast(:v as jsonb), :b) "
                    "on conflict (key) do update set value = excluded.value, updated_at = now(), "
                    "updated_by = excluded.updated_by"
                ),
                {"k": f"site_assistant.{key}", "v": json.dumps(value), "b": by},
            )
    invalidate()
    return overview()


# --------------------------------------------------------------------------- spend
_spend: dict[str, Any] = {"at": 0.0, "month": Decimal(0), "calls_today": 0}


def _usage() -> tuple[Decimal, int]:
    if time.monotonic() - float(_spend["at"]) > CACHE_SECONDS:
        with master_session() as m:
            month = m.execute(
                text("select coalesce(sum(cost_usd), 0) from master.ai_usage where tenant_id = :t and day >= :d"),
                {"t": str(WEBSITE), "d": platform_ai.month_start()},
            ).scalar() or Decimal(0)
            calls = (
                m.execute(
                    text("select coalesce(sum(calls), 0) from master.ai_usage where tenant_id = :t and day = :d"),
                    {"t": str(WEBSITE), "d": datetime.now(UTC).date()},
                ).scalar()
                or 0
            )
        _spend.update(at=time.monotonic(), month=Decimal(month), calls_today=int(calls))
    return Decimal(_spend["month"]), int(_spend["calls_today"])


def month_spend() -> Decimal:
    return _usage()[0]


def cap_reached() -> bool:
    cap = get_all()["monthly_cap_usd"]
    return cap is not None and month_spend() >= Decimal(cap)


def record(provider: str, model: str, tokens_in: int, tokens_out: int) -> None:
    """Count one model call in the platform's usage (under the pseudo business) and in the local running totals."""
    before = platform_ai.snapshot().spend_usd
    platform_ai.record_usage(WEBSITE, provider, model, tokens_in, tokens_out)
    with _lock:
        _usage()
        _spend["month"] = Decimal(_spend["month"]) + max(platform_ai.snapshot().spend_usd - before, Decimal(0))
        _spend["calls_today"] = int(_spend["calls_today"]) + 1


def usage_summary() -> dict[str, Any]:
    """This month's calls, tokens and estimated spend of the assistant (for the usage panel)."""
    with master_session() as m:
        row = m.execute(
            text(
                "select coalesce(sum(calls), 0)::int as calls, coalesce(sum(tokens_in), 0)::bigint as tokens_in, "
                "coalesce(sum(tokens_out), 0)::bigint as tokens_out, coalesce(sum(cost_usd), 0) as cost_usd "
                "from master.ai_usage where tenant_id = :t and day >= :d"
            ),
            {"t": str(WEBSITE), "d": platform_ai.month_start()},
        ).one()
    return {
        "label": LABEL,
        "calls": row.calls,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "cost_usd": str(Decimal(row.cost_usd).quantize(Decimal("0.0001"))),
    }


# --------------------------------------------------------------------------- availability
def blocked() -> str | None:
    """Why it cannot answer now: `off` (switched off or no provider set up), `budget` (a cap reached), or None."""
    cfg = get_all()
    if not cfg["enabled"]:
        return "off"
    runtime = platform_ai.runtime("rank")
    if runtime is None or not runtime.terms_ok or not implementations_of(SITE_ASSISTANT_LLM):
        return "off"
    if not runtime.spend_ok or cap_reached():
        return "budget"
    if _usage()[1] >= cfg["daily_total"]:
        return "budget"
    return None


def public_config() -> dict[str, Any]:
    """What the website may know, no secrets: whether to show the button, the greeting and the quick replies."""
    cfg = get_all()
    return {"enabled": blocked() is None, "greeting": cfg["greeting"], "suggestions": cfg["suggestions"]}


def overview() -> dict[str, Any]:
    """Every setting and this month's use, for the Super Admin."""
    cfg = get_all()
    runtime = platform_ai.runtime("rank")
    spent = month_spend()
    return {
        **cfg,
        "provider": runtime.provider if runtime else None,
        "model": runtime.model if runtime else None,
        "available": blocked() is None,
        "blocked_reason": blocked(),
        "month_spend_usd": str(spent.quantize(Decimal("0.0001"))),
        "cap_reached": cap_reached(),
        "usage": usage_summary(),
        "defaults": {"per_minute": DEFAULT_PER_MINUTE, "per_day": DEFAULT_PER_DAY, "daily_total": DEFAULT_DAILY_TOTAL},
    }


# --------------------------------------------------------------------------- per-address limits
def _hash(kind: str, value: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"wa-{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def _hit(key: str, window: int) -> tuple[int, int]:
    """Count one use in a window of `window` seconds: (uses so far in this window, seconds until it restarts)."""
    with master_session() as m:
        row = m.execute(
            text(
                "insert into master.auth_throttle (key, failures, window_started, updated_at) "
                "values (:k, 1, now(), now()) "
                "on conflict (key) do update set "
                "failures = case when master.auth_throttle.window_started < now() - make_interval(secs => :w) "
                "                then 1 else master.auth_throttle.failures + 1 end, "
                "window_started = case when master.auth_throttle.window_started < now() - make_interval(secs => :w) "
                "                      then now() else master.auth_throttle.window_started end, updated_at = now() "
                "returning failures, extract(epoch from (window_started + make_interval(secs => :w) - now())) as wait"
            ),
            {"k": key, "w": window},
        ).one()
    return int(row.failures), max(int(row.wait) + 1, 1)


def visitor_check(ip_address: str | None) -> int | None:
    """Count one question from this address. None when it may go on; else the seconds to wait (it is over a limit).
    An address that cannot be told is treated as one shared visitor (strict, never a way round the limits)."""
    cfg = get_all()
    who = ip_address or "unknown"
    for kind, window, limit in (
        ("burst", BURST_SECONDS, BURST_LIMIT),
        ("min", 60, cfg["per_minute"]),
        ("day", 86400, cfg["per_day"]),
    ):
        used, wait = _hit(f"wa-{kind}:" + _hash(kind, who), window)
        if used > limit:
            return wait
    return None
