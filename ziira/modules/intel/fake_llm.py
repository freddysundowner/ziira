"""A scriptable AI provider for tests and local development (`ZIIRA_AI_PROVIDER=fake`; refused in production).

    FakeLlm.reset()
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", {"date_from": "2026-10-01", "date_to": "2026-10-07"}),
                           FakeLlm.say("Sales were 1,250.00.")])

Each call takes the next scripted item: an `LlmReply`, an `LlmError` to raise, or a function of the call (a dict with
`messages`, `tools`, `system`, `max_tokens`) returning either. With nothing scripted it answers with `default_text`.
Every call is recorded in `FakeLlm.calls`.
"""

from collections.abc import Callable, Sequence
from typing import Any, ClassVar
from uuid import uuid4

from ziira.modules.intel.domain.llm import LlmError, LlmMessage, LlmProvider, LlmReply, LlmUsage, ToolCall, ToolSpec

Scripted = LlmReply | LlmError | Callable[[dict[str, Any]], LlmReply | LlmError]


class FakeLlm(LlmProvider):
    name = "fake"
    label = "Fake provider (development)"
    script: ClassVar[list[Scripted]] = []
    calls: ClassVar[list[dict[str, Any]]] = []
    default_text: ClassVar[str] = "This is a reply from the fake AI provider."
    usage: ClassVar[LlmUsage] = LlmUsage(100, 20)

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
        item: Scripted = self.script.pop(0) if self.script else self.say(self.default_text)
        if callable(item):
            item = item(call)
        if isinstance(item, LlmError):
            raise item
        return item
