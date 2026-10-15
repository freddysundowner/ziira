"""The contract between Intelligence and an AI provider, and the shape of a question the assistant may ask for data.

Provider-neutral on purpose: a conversation is a list of messages in which an assistant turn may ask for tools to be
run and the next user turn carries their results. A provider plugin maps this to its own wire format
(`ziira/plugins/ai_anthropic`). Plain data and abstract classes only: no database, no HTTP.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ziira.sdk import RequestContext, Session


@dataclass(frozen=True)
class ToolSpec:
    """A tool offered to the model: its name, what it does, and a JSON schema of its parameters."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """The model asking for a tool to be run."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The answer to a ToolCall (text the model reads); `is_error` says the tool was refused or failed."""

    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class LlmMessage:
    """One turn. A user turn has `text` or `tool_results`; an assistant turn has `text` and/or `tool_calls`."""

    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class LlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class LlmReply:
    """What the model said: text, and/or tools it wants run. `stop_reason` is the provider's own word for why it
    stopped ("end_turn", "tool_use", "max_tokens", "refusal" ...)."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: LlmUsage = field(default_factory=LlmUsage)
    stop_reason: str | None = None
    model: str | None = None


class LlmError(Exception):
    """A call to the provider failed. `retryable` says that trying again later may work (a rate limit, an outage);
    the message is safe to show and to store (it never holds a key)."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LlmProvider(ABC):
    """An AI provider (extension point `intel.llm`). `name` is what `ZIIRA_AI_PROVIDER` selects."""

    name: str
    label: str = ""

    def configured(self) -> bool:
        """True when the platform has what this provider needs (its key); one that has not is never called."""
        return True

    def model_id(self) -> str:
        """The model this provider will use (for the log and the consent record)."""
        return ""

    @abstractmethod
    def complete(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                 max_tokens: int) -> LlmReply:
        """One round trip. Raises LlmError on failure. Called with no database transaction open."""


class AskTool(ABC):
    """A question Ask Ziira may put to a unit's data (extension point `intel.ask_tool`).

    The model sees `name`, `description` and `parameters` and may call the tool; nothing else reaches the data. `run`
    must filter by what the asking user may see (`context`; see `BranchScope`), return a bounded JSON-able result, and
    never take SQL or free text into a query. `permissions` are any-of: the tool is offered only to people who hold one
    of them somewhere. Names of people (customers, suppliers, employees) in the result go in the fields listed in
    `personal_fields`: they are replaced by labels such as "Customer A" before anything is sent to the provider.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    permissions: tuple[str, ...]
    personal_fields: tuple[str, ...] = ()

    @abstractmethod
    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        """The result. `params` holds what the model sent (checked against `parameters`) and `company_id`, set by
        Ask Ziira (never by the model). Money and quantities as strings."""

