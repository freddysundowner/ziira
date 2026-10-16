"""The AI provider plugins as data and as a family: their model catalogs make sense, no provider's name leaks into
kernel or module code, and no provider ever echoes a key into an error (Hypothesis)."""

import re
from decimal import Decimal
from pathlib import Path

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.ai_provider_helpers import Pretend, ask, reply
from ziira.modules.intel.domain.llm import TIERS
from ziira.modules.intel.public import LlmError
from ziira.plugins.ai_anthropic.provider import AnthropicMessages
from ziira.plugins.ai_gemini.provider import GeminiGenerateContent
from ziira.plugins.ai_openai.provider import OpenAIResponses

PROVIDERS = (AnthropicMessages, GeminiGenerateContent, OpenAIResponses)
ROOT = Path(__file__).resolve().parents[1] / "ziira"


def test_every_catalog_is_complete_and_defaults_to_a_cheaper_tier_not_the_flagship() -> None:
    for cls in PROVIDERS:
        catalog = cls.catalog()
        assert catalog is not None and catalog.models and catalog.base_url.startswith("https://")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", catalog.verified_on) and catalog.prices_updated
        assert {"tool_calling", "system_prompt"} <= set(catalog.capabilities)
        for model in catalog.models:
            assert set(model.tiers) <= set(TIERS)
            assert model.input_per_mtok > 0 and model.output_per_mtok > 0 and isinstance(model.input_per_mtok, Decimal)
        ids = {m.id for m in catalog.models}
        for feature in ("explain", "rank", "ask"):
            assert catalog.defaults[feature] in ids
        best = [m for m in catalog.models if "best_value" in m.tiers]
        assert len(best) == 1 and catalog.model(catalog.default_model("ask")) == best[0]
        higher = [m for m in catalog.models if "higher_quality" in m.tiers]
        assert higher and all(h.output_per_mtok >= best[0].output_per_mtok for h in higher)
        # the default is never the most expensive model on the list
        assert best[0].output_per_mtok < max(m.output_per_mtok for m in catalog.models)


def test_provider_names_live_in_plugins_and_data_only() -> None:
    words = re.compile(r"(?i)\b(anthropic|gemini|openai|gpt-[0-9a-z.]+)\b|\bclaude(?![.]md)\b|\bgoogle\b")
    hits = []
    for area in ("kernel", "modules", "sdk"):
        for f in (ROOT / area).rglob("*"):
            parts = set(f.relative_to(ROOT).parts)
            if (not f.is_file() or f.suffix not in (".py", ".toml") or "__pycache__" in parts
                    or {"tests", "data", "migrations", "master_migrations"} & parts):
                continue
            for number, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if words.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{number}")
    assert not hits, "Provider names belong in the plugins' code and models.toml, not here: " + ", ".join(hits)


key_chars = st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=16, max_size=60)


@settings(max_examples=40, deadline=None)
@given(key=key_chars, status=st.sampled_from([400, 401, 403, 404, 429, 500, 503]),
       style=st.sampled_from(["message", "string", "nested"]))
def test_no_provider_echoes_a_key_into_an_error(key: str, status: int, style: str) -> None:
    echo = f"Invalid key {key} (x-api-key: {key}, Bearer {key})"
    body = ({"error": {"type": "invalid", "message": echo, "status": "BAD"}} if style == "message"
            else {"error": echo} if style == "string" else {"error": {"message": echo, "type": echo}})
    for cls in PROVIDERS:
        net = Pretend(reply(status, body))
        try:
            ask(net.provider(cls, key, model="m", max_retries=1))
        except LlmError as error:
            assert key not in str(error)
        else:
            raise AssertionError("a failure must raise")


def test_a_timeout_is_a_retryable_error_without_the_key() -> None:
    key = "sk-test-0123456789abcdefghij"
    for cls in PROVIDERS:
        net = Pretend(httpx.ReadTimeout(f"timed out talking with {key}"))
        try:
            ask(net.provider(cls, key, model="m", max_retries=1))
        except LlmError as error:
            assert error.retryable and key not in str(error)
        assert len(net.requests) == 2
