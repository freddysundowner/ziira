"""The website assistant's fixed protections and spend accounting. There are no settings: the assistant is simply on.

The assistant answers visitors of the marketing site (no sign-in, no business data: `kernel/site_assistant.py`). Nothing
here can be changed from a screen. The limits are constants below, overridable only by environment variables
(`ZIIRA_SITE_ASSISTANT_*`, docs/operations.md):

- per address: 8 questions a minute, 60 a day, and a burst of 3 in 5 seconds;
- 2000 questions a day for everyone;
- a monthly spend ceiling of its own (default 25 USD), counted from the platform's AI usage table under one pseudo
  business (`WEBSITE`), on top of the platform-wide AI cap;
- a hard cap on the length of one answer and a limit on answers being written at once (`kernel/site_assistant.py`).

The greeting and the quick-reply suggestions are built in (English). Per-address counts are kept in
`master.auth_throttle` under keyed hashes (no address in the clear), with a window of their own. Nothing here keeps a
visitor's words.
"""

import hashlib
import hmac
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
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
BURST_LIMIT_DEFAULT, BURST_SECONDS = 3, 5  # at most three questions in five seconds from one address
BURST_LIMIT = BURST_LIMIT_DEFAULT
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


def limits() -> dict[str, Any]:
    """The fixed limits in force (built-in defaults, or the environment's values)."""
    s = get_settings()
    return {
        "per_minute": max(1, s.site_assistant_per_minute),
        "per_day": max(1, s.site_assistant_per_day),
        "daily_total": max(1, s.site_assistant_daily_total),
        "monthly_cap_usd": max(Decimal(0), s.site_assistant_monthly_cap_usd),
        "max_output_tokens": max(16, s.site_assistant_max_output_tokens),
        "max_parallel": max(1, s.site_assistant_max_parallel),
    }


_lock = threading.Lock()


def invalidate() -> None:
    _spend["at"] = 0.0


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
    """The assistant's own monthly ceiling is used up (the platform-wide AI cap is checked separately)."""
    ceiling: Decimal = limits()["monthly_cap_usd"]
    return month_spend() >= ceiling


def record(provider: str, model: str, tokens_in: int, tokens_out: int) -> None:
    """Count one model call in the platform's usage (under the pseudo business) and in the local running totals."""
    before = platform_ai.snapshot().spend_usd
    platform_ai.record_usage(WEBSITE, provider, model, tokens_in, tokens_out)
    with _lock:
        _usage()
        _spend["month"] = Decimal(_spend["month"]) + max(platform_ai.snapshot().spend_usd - before, Decimal(0))
        _spend["calls_today"] = int(_spend["calls_today"]) + 1


def usage_summary() -> dict[str, Any]:
    """This month's calls, tokens and estimated spend of the assistant (read-only, for the AI usage panel)."""
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
    """Why it cannot answer now: `off` (no usable AI provider), `budget` (a cap or the daily total reached), or None."""
    runtime = platform_ai.runtime("rank")
    if runtime is None or not runtime.terms_ok or not implementations_of(SITE_ASSISTANT_LLM):
        return "off"
    if not runtime.spend_ok or cap_reached():
        return "budget"
    if _usage()[1] >= limits()["daily_total"]:
        return "budget"
    return None


def public_config() -> dict[str, Any]:
    """What the website may know, no secrets: whether it can answer right now, the greeting and the quick replies.
    `enabled` is never false because of a switch (there is none): only no provider or a limit reached makes it false."""
    return {"enabled": blocked() is None, "greeting": DEFAULT_GREETING, "suggestions": list(DEFAULT_SUGGESTIONS)}


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
    cfg = limits()
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
