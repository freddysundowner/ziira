"""What the website assistant may know: the site's own facts, and a way to find the few pieces that answer a question.

The marketing site's build writes `assistant-knowledge.json` (a list of `{id, title, url, text}` chunks) into its output
folder; `ZIIRA_SITE_DIST_DIR` says where that is. The file is re-read when it changes. When it is missing or unreadable
the assistant falls back to a short built-in text (`BUILT_IN`) and says it is limited. The live public plans and prices
are added as one more chunk (`plans_chunk`), so a price is never taken from a stale page.

Retrieval is a plain BM25 score over words (no dependency, no index to maintain): enough for a few hundred short chunks.
No country, vendor or customer is named here: facts about those come from the site's own text.
"""

import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ziira.kernel.config import get_settings

log = logging.getLogger("ziira.site_knowledge")
FILE_NAME = "assistant-knowledge.json"
MAX_CHUNKS = 600
MAX_CHUNK_CHARS = 3000
MAX_FILE_BYTES = 8_000_000
TOP_CHUNKS = 6
PROMPT_CHUNK_CHARS = 1200


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    url: str
    text: str


@dataclass(frozen=True)
class Knowledge:
    chunks: tuple[Chunk, ...]
    limited: bool  # True when only the built-in text is available


BUILT_IN: tuple[Chunk, ...] = (
    Chunk(
        "about",
        "What Ziira is",
        "/",
        "Ziira is business software for small and medium businesses: a till, stock, purchasing, customers, accounting "
        "and payroll in one place. Ziira Intelligence checks the business data every day and tells the owner by "
        "message "
        "when something needs attention, such as unusual voids, missing stock or customers who are paying late.",
    ),
    Chunk(
        "who",
        "Who it is for",
        "/solutions",
        "Ziira is for shops, distributors and businesses with several branches, and also for salons, garages, clinics, "
        "gyms and consultants. A business can start with only the parts it needs.",
    ),
    Chunk(
        "ai",
        "How the AI helps",
        "/ai",
        "The AI writes sentences and never supplies figures: every number comes from the business's own records. "
        "Businesses choose whether to switch the AI on, an owner must consent first, and personal data is removed "
        "before anything is sent. The AI does not move money, change prices or change stock by itself.",
    ),
    Chunk(
        "security",
        "Security and privacy",
        "/security",
        "Each business has its own database. Access is by role and by branch, every change is recorded in an audit "
        "log, and posted records are corrected by reversals, never edited. Business data is not used to train models.",
    ),
    Chunk(
        "start",
        "How to start",
        "/get-started",
        "A business registers itself in a few steps: what it needs, the business details, and the owner account. "
        "There is a free trial on the plans that offer one. Please see the pricing page for current plans and prices.",
    ),
)

_cache: dict[str, Any] = {"key": None, "value": None}


def _clean_url(value: Any) -> str:
    """A link the site may show: a path on the site, or an http(s) address. Anything else is dropped."""
    url = str(value or "").strip()
    if re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/#?-]{0,300}", url) and not url.startswith("//"):
        return url
    if re.fullmatch(r"https?://[^\s<>\"']{1,300}", url):
        return url
    return ""


def _read(path: Path) -> tuple[Chunk, ...]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file too large")
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("chunks") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("not a list of chunks")
    out: list[Chunk] = []
    for item in items[:MAX_CHUNKS]:
        if not isinstance(item, dict):
            continue
        body = str(item.get("text") or "").strip()
        if not body:
            continue
        out.append(
            Chunk(
                str(item.get("id") or f"chunk-{len(out)}")[:80],
                str(item.get("title") or "")[:160],
                _clean_url(item.get("url")),
                body[:MAX_CHUNK_CHARS],
            )
        )
    if not out:
        raise ValueError("no chunks")
    return tuple(out)


def load() -> Knowledge:
    """The site's chunks (re-read when the file changes), else the built-in text."""
    folder = get_settings().site_dist_dir.strip()
    if not folder:
        return Knowledge(BUILT_IN, True)
    path = Path(folder) / FILE_NAME
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return Knowledge(BUILT_IN, True)
    if _cache["key"] == stamp and _cache["value"] is not None:
        value: Knowledge = _cache["value"]
        return value
    try:
        known = Knowledge(_read(path), False)
    except (OSError, ValueError) as error:
        log.warning("Website assistant knowledge file unusable (%s); using the built-in text", type(error).__name__)
        known = Knowledge(BUILT_IN, True)
    _cache["key"], _cache["value"] = stamp, known
    return known


# --------------------------------------------------------------------------- plans
def plans_chunk(data: dict[str, Any]) -> Chunk | None:
    """The live public plans and prices as one chunk of plain sentences (None when there are none)."""
    lines: list[str] = []
    for plan in data.get("plans", []):
        prices = "; ".join(
            f"{p['currency']} {p['amount']} per {p['interval']}" + (" (tax included)" if p.get("tax_inclusive") else "")
            for p in plan.get("prices", [])
        )
        limits = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in (plan.get("limits") or {}).items() if v is not None)
        parts = [f"Plan {plan['name']}"]
        if plan.get("description"):
            parts.append(str(plan["description"]).rstrip("."))
        if plan.get("highlights"):
            parts.append("includes " + ", ".join(str(h).rstrip(".") for h in plan["highlights"]))
        if limits:
            parts.append("limits: " + limits)
        parts.append(f"free trial {plan['trial_days']} days" if plan.get("trial_days") else "no free trial")
        parts.append("price: " + prices if prices else "price: not listed")
        lines.append(". ".join(parts) + ".")
    for addon in data.get("addons", []):
        prices = "; ".join(f"{p['currency']} {p['amount']} per {p['interval']}" for p in addon.get("prices", []))
        lines.append(
            f"Add-on {addon['name']}: {addon.get('description', '')}".rstrip(": ").rstrip(".")
            + (f". Price: {prices}." if prices else ".")
        )
    if not lines:
        return None
    return Chunk("plans", "Plans and prices", "/pricing", " ".join(lines)[:MAX_CHUNK_CHARS])


# --------------------------------------------------------------------------- retrieval
_WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "this",
        "to",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "about",
        "get",
        "have",
        "has",
        "there",
        "their",
        "they",
        "them",
        "tell",
        "please",
        "hi",
        "hello",
    ]
)
SYNONYMS = {
    "cost": "price pricing plan",
    "costs": "price pricing plan",
    "much": "price pricing",
    "pay": "price pricing",
    "cheap": "price pricing",
    "free": "trial price",
    "subscribe": "plan pricing",
    "subscription": "plan pricing",
    "safe": "security privacy",
    "secure": "security",
    "data": "privacy security",
    "contact": "contact support",
    "help": "support contact",
    "register": "sign start",
    "sign": "register start",
    "signup": "sign start",
    "join": "sign start",
    "ai": "intelligence ai",
    "smart": "intelligence ai",
    "alert": "intelligence alerts message",
    "who": "customers business",
    "shop": "retail",
    "store": "retail",
    "pos": "till retail",
}


def words(text: str) -> list[str]:
    """The meaningful words of a text, lower case (no stemming: that happens when scoring)."""
    return [w for w in _WORD.findall(text.lower()) if w not in STOP]


def _stem(word: str) -> str:
    """A light stem so that price, prices and pricing meet (not a language tool, just enough for short site text)."""
    if len(word) > 4:
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not word.endswith("ss"):
                word = word[: -len(suffix)]
                break
    return word[:-1] if len(word) > 3 and word.endswith("e") else word


def _expand(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for t in tokens:
        out.extend(SYNONYMS.get(t, "").split())
    return [_stem(t) for t in out]


def search(
    query: str, chunks: list[Chunk] | tuple[Chunk, ...], *, page: str | None = None, limit: int = TOP_CHUNKS
) -> list[tuple[Chunk, float]]:
    """The best chunks for a question, best first, with their scores. Only chunks that share at least one word with the
    question are returned (so an unrelated question finds nothing). A chunk of the page the visitor is on gets a small
    lift once it matches at all."""
    q = _expand(words(query))
    if not q or not chunks:
        return []
    docs = [(c, [_stem(w) for w in words(c.title + " " + c.title + " " + c.text)]) for c in chunks]
    n = len(docs)
    avg = sum(len(d) for _, d in docs) / n or 1.0
    df: dict[str, int] = {}
    for _, d in docs:
        for term in set(d):
            df[term] = df.get(term, 0) + 1
    k1, b = 1.4, 0.75
    scored: list[tuple[Chunk, float]] = []
    for chunk, d in docs:
        if not d:
            continue
        tf: dict[str, int] = {}
        for term in d:
            tf[term] = tf.get(term, 0) + 1
        score = 0.0
        for term in set(q):
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * len(d) / avg))
        if score > 0 and page and chunk.url and chunk.url.rstrip("/") == page.rstrip("/"):
            score *= 1.25
        if score > 0:
            scored.append((chunk, score))
    scored.sort(key=lambda x: (-x[1], x[0].id))
    return scored[:limit]
