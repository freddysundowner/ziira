"""A scriptable AI provider for tests and local development (`ZIIRA_AI_PROVIDER=fake`; refused in production).

    FakeLlm.reset()
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", {"date_from": "2026-10-01", "date_to": "2026-10-07"}),
                           FakeLlm.say("Sales were 1,250.00.")])

Each call takes the next scripted item: an `LlmReply`, an `LlmError` to raise, or a function of the call (a dict with
`messages`, `tools`, `system`, `max_tokens`) returning either. With nothing scripted it answers with `default_text`.
Every call is recorded in `FakeLlm.calls`. `FakeLlm.delay` makes each call take that many seconds (to measure speed).

With `ZIIRA_AI_FAKE=1` (development only) and nothing scripted, it plays a small demo brain: it picks a tool from the
words of the question, then answers in sentences made only of figures that tool returned.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any, ClassVar
from uuid import uuid4

from ziira.modules.intel.domain.llm import LlmError, LlmMessage, LlmProvider, LlmReply, LlmUsage, ToolCall, ToolSpec
from ziira.sdk import is_production, platform_settings

Scripted = LlmReply | LlmError | Callable[[dict[str, Any]], LlmReply | LlmError]


class FakeLlm(LlmProvider):
    name = "fake"
    label = "Fake provider (development)"
    script: ClassVar[list[Scripted]] = []
    calls: ClassVar[list[dict[str, Any]]] = []
    default_text: ClassVar[str] = "This is a reply from the fake AI provider."
    usage: ClassVar[LlmUsage] = LlmUsage(100, 20)
    delay: ClassVar[float] = 0.0                       # seconds each call takes (tests that measure speed)

    @classmethod
    def reset(cls) -> None:
        cls.script.clear()
        cls.calls.clear()

    @classmethod
    def say(cls, text: str, usage: LlmUsage | None = None) -> LlmReply:
        return LlmReply(text=text, usage=usage or cls.usage, stop_reason="end_turn", model="fake-model")

    @classmethod
    def tool(cls, name: str, arguments: dict[str, Any] | None = None, *more: tuple[str, dict[str, Any]]) -> LlmReply:
        calls = tuple(ToolCall(f"call_{uuid4().hex[:8]}", n, a) for n, a in ((name, arguments or {}), *more))
        return LlmReply(tool_calls=calls, usage=cls.usage, stop_reason="tool_use", model="fake-model")

    def model_id(self) -> str:
        return "fake-model"

    def complete(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                 max_tokens: int) -> LlmReply:
        call = {"messages": list(messages), "tools": [t.name for t in tools], "system": system,
                "max_tokens": max_tokens}
        self.calls.append(call)
        wait = self.delay or (platform_settings().ai_fake_delay_seconds if not is_production() else 0.0)
        if wait:
            time.sleep(wait)
        item: Scripted
        if self.script:
            item = self.script.pop(0)
        elif platform_settings().ai_fake and not is_production():
            item = website_demo_reply(system) if WEBSITE_MARK in system else demo_reply(messages, tools)
        else:
            item = self.say(self.default_text)
        if callable(item):
            item = item(call)
        if isinstance(item, LlmError):
            raise item
        return item


# --------------------------------------------------------------------------- the website assistant's demo brain
WEBSITE_MARK = "[ziira-website-assistant]"
_SOURCE = re.compile(r"<source[^>]*>\n(.*?)\n</source>", re.S)


def website_demo_reply(system: str) -> LlmReply:
    """For the website assistant (development only): the first one or two sentences of the best matching source
    (the first one in the prompt). It repeats the knowledge, so it never invents a figure."""
    found = _SOURCE.search(system)
    if not found:
        return FakeLlm.say("UNKNOWN")
    sentences = re.split(r"(?<=[.!?])\s+", found.group(1).strip())
    return FakeLlm.say(" ".join(sentences[:2]))


# --------------------------------------------------------------------------- the development demo brain
_WORDS = (("stock", "inventory_low_stock"), ("low", "inventory_low_stock"), ("void", "pos_voids"),
          ("cancel", "pos_voids"), ("best", "pos_top_products"), ("top", "pos_top_products"),
          ("owe", "crm_overdue_customers"), ("overdue", "crm_overdue_customers"), ("attention", "intel_list_findings"),
          ("cash", "finance_cash_position"), ("profit", "finance_profit_and_loss"), ("sales", "pos_sales_summary"),
          ("sold", "pos_sales_summary"), ("week", "pos_sales_summary"))
_NUMERIC = re.compile(r"-?\d+(\.\d+)?")


def _question(messages: Sequence[LlmMessage]) -> str:
    return next((m.text for m in reversed(messages) if m.role == "user" and m.text), "").lower()


def demo_reply(messages: Sequence[LlmMessage], tools: Sequence[ToolSpec]) -> LlmReply:
    """Pick a tool from the words of the question (first turn) or turn the tool's result into sentences (second turn).
    Only for development: it never invents a figure, it repeats what the tool returned."""
    last = messages[-1]
    if not last.tool_results:
        offered = {t.name for t in tools}
        question = _question(messages)
        name = next((n for w, n in _WORDS if w in question and n in offered), None)
        if name is None:
            return FakeLlm.say("I can help with sales, stock, customers who owe you, and what needs attention. "
                               "Try asking about one of those.")
        today = date.today()
        days = 7 if "week" in question else 1 if "today" in question else 30
        end = today - timedelta(days=7) if "last week" in question else today
        args: dict[str, Any] = {"date_from": (end - timedelta(days=days - 1)).isoformat(),
                                "date_to": end.isoformat()}
        wanted = next((t for t in tools if t.name == name), None)
        keep = set(wanted.parameters.get("properties", {})) if wanted else set()
        return FakeLlm.tool(name, {k: v for k, v in args.items() if k in keep})
    parts: list[str] = []
    for result in last.tool_results:
        try:
            data = json.loads(result.content)
        except ValueError:
            continue
        if result.is_error or not isinstance(data, dict):
            return FakeLlm.say("I could not get that from your data just now.")
        for key, value in data.items():
            is_figure = (isinstance(value, str) and bool(_NUMERIC.fullmatch(value))) or (
                isinstance(value, int) and not isinstance(value, bool))
            if is_figure and len(parts) < 3:
                parts.append(f"The {key.replace('_', ' ')} is {value}.")
        rows = next((v for v in data.values() if isinstance(v, list)), [])
        if not rows and not parts:
            parts.append("There is nothing to report for that.")
        elif rows and isinstance(rows[0], dict):
            label = next((str(v) for v in rows[0].values() if isinstance(v, str) and not _NUMERIC.fullmatch(v)), "")
            parts.append(f"{label} comes first." if label else "The details are listed under how I know.")
    return FakeLlm.say(" ".join(parts) or "I found nothing to report.")
