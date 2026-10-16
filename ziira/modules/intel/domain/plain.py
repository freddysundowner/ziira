"""Plain-language text of Intelligence, in English and Swahili: what a check is called, why it matters, what to
do, how its
limits read as a sentence, what its facts are called and how to show them. The text lives in
`plain_checks.json` (the single
source: tests/test_intel_plain.py fails when a check has none); a check may also declare `plain_title`,
`why_it_matters` and
`what_to_do` itself (a plugin's check). Pure: no database."""

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

LANGS = ("en", "sw")
TOPICS = ("cash", "stock", "customers", "suppliers", "staff", "books")
# Which of the six topics a check belongs to when the text file does not say (a plugin's check): by its area.
AREA_TOPIC = {
    "cash_sales": "cash",
    "cash_planning": "cash",
    "general": "cash",
    "stock": "stock",
    "customers": "customers",
    "suppliers": "suppliers",
    "people": "staff",
    "controls": "staff",
    "books": "books",
}
PLACEHOLDER = re.compile(r"\{([a-z_0-9]+)\}")

# Checks whose limit a business may nudge upwards when it says "this is normal" (the limit and the finding's own `value`
# are measured the same way). Only existing limits are changed, through the normal check settings.
TUNABLE: dict[str, str] = {
    "payments.close_variance": "variance_limit",
    "pos.till_cash_variance": "limit",
    "inventory.count_variance": "value_limit",
    "inventory.large_write_down": "value_limit",
    "finance.unusual_expense": "min_amount",
    "pos.cashier_void_rate": "min_rate",
    "pos.cashier_refund_rate": "min_rate",
    "pos.cashier_discount_rate": "min_rate",
}

# Kinds of record a finding can be "about" that a person would name (not documents): used by "ignore this at <who>".
SUBJECT_KINDS = {
    "kernel.app_user": "person",
    "people.employee": "person",
    "crm.customer": "customer",
    "purchasing.supplier": "supplier",
    "products.product": "product",
    "payments.payment_account": "account",
}


@cache
def _data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(__file__).with_name("plain_checks.json").read_text(encoding="utf-8"))
    return data


def pick(value: Any, lang: str) -> str:
    """A text in the language asked for, falling back to English; a plain string is returned as it is."""
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("en") or "")
    return str(value or "")


def entry_of(code: str) -> dict[str, Any]:
    """The text entry of a check, with whatever it lacks taken from the check named by its `like`."""
    entries = _data()
    entry = dict(entries.get(code) or {})
    twin = entry.get("like")
    if twin and twin in entries and twin != code:
        base = dict(entries[twin])
        base.pop("like", None)
        entry = {**base, **{k: v for k, v in entry.items() if k != "like"}}
    return entry


@dataclass(frozen=True)
class PlainCheck:
    title: str
    why: str
    todo: str
    topic: str
    sentence: str | None = None
    units: dict[str, str] = field(default_factory=dict)


def plain_check(
    code: str,
    lang: str,
    *,
    fallback_title: str,
    area: str,
    params: dict[str, Any],
    declared: tuple[str, str, str] = ("", "", ""),
) -> PlainCheck:
    """The plain text of a check: what the check itself declares, else the text file, else its own title."""
    e = entry_of(code)
    sentence = pick(e.get("sentence"), lang) or None
    if sentence and not set(PLACEHOLDER.findall(sentence)) <= set(params):
        sentence = None  # a sentence naming a limit the check lacks is never shown
    topic = str(e.get("topic") or AREA_TOPIC.get(area, "cash"))
    return PlainCheck(
        title=declared[0] or pick(e.get("title"), lang) or fallback_title,
        why=declared[1] or pick(e.get("why"), lang),
        todo=declared[2] or pick(e.get("todo"), lang),
        topic=topic if topic in TOPICS else AREA_TOPIC.get(area, "cash"),
        sentence=sentence,
        units={k: str(v) for k, v in (e.get("units") or {}).items() if sentence and k in sentence},
    )


def topics(lang: str) -> list[dict[str, str]]:
    meta = _data().get("_topics", {})
    return [
        {
            "key": k,
            "title": pick(meta.get(k, {}).get("title"), lang) or k,
            "lead": pick(meta.get(k, {}).get("lead"), lang),
        }
        for k in TOPICS
    ]


def param_labels(lang: str) -> dict[str, str]:
    return {k: pick(v, lang) for k, v in _data().get("_params", {}).items()}


def figure_meta(lang: str) -> dict[str, dict[str, str]]:
    return {
        k: {"label": pick(v.get("label"), lang), "kind": str(v.get("kind", "text"))}
        for k, v in _data().get("_figures", {}).items()
    }


def known_codes() -> set[str]:
    return {k for k in _data() if not k.startswith("_")}


def subject_kind(entity_type: str | None) -> str | None:
    return SUBJECT_KINDS.get(entity_type or "")
