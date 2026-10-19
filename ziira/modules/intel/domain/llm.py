"""The contract between Intelligence and an AI provider, and the shape of a question the assistant may ask for data.

Provider-neutral on purpose: a conversation is a list of messages in which an assistant turn may ask for tools to be
run and the next user turn carries their results. A provider plugin maps this to its own wire format
(the `ai_*` plugins). Plain data and abstract classes only: no database, no HTTP.
"""

import inspect
import tomllib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Literal

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


TIERS = ("best_value", "higher_quality", "cheapest")
FEATURES = ("explain", "rank", "ask")
MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelInfo:
    """A model a provider offers, from the plugin's `models.toml`: price per million tokens (editable data, never the
    only truth: the provider's live list and the operator's overrides come first), the badges it carries, and any
    provider-specific request options (`options`)."""

    id: str
    title: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    tiers: tuple[str, ...] = ()
    notes: str = ""
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCatalog:
    """What a provider plugin declares about itself, as data."""

    name: str
    title: str
    capabilities: tuple[str, ...]
    base_url: str
    auth: str                                  # how the key is sent, for the operator's information
    terms_url: str
    docs_url: str
    verified_on: str
    prices_updated: str
    price_source: str
    models: tuple[ModelInfo, ...]
    defaults: dict[str, str]                   # feature -> model id
    live_prefixes: tuple[str, ...] = ()        # of the live list, show only ids starting with one of these (if any)

    def model(self, model_id: str) -> ModelInfo | None:
        return next((m for m in self.models if m.id == model_id), None)

    def default_model(self, feature: str = "ask") -> str:
        return self.defaults.get(feature) or self.defaults.get("ask") or (self.models[0].id if self.models else "")


def estimate_cost(input_per_mtok: Decimal, output_per_mtok: Decimal, tokens_in: int, tokens_out: int) -> Decimal:
    """Estimated spend in USD for a call, from token counts and the price per million tokens."""
    return (input_per_mtok * tokens_in + output_per_mtok * tokens_out) / MILLION


def load_catalog(name: str, models_file: Path) -> ProviderCatalog:
    """Read a plugin's `models.toml`."""
    data = tomllib.loads(models_file.read_text(encoding="utf-8"))
    head = data["provider"]
    models = tuple(
        ModelInfo(id=m["id"], title=m.get("title", m["id"]), input_per_mtok=Decimal(str(m["input_per_mtok"])),
                  output_per_mtok=Decimal(str(m["output_per_mtok"])), tiers=tuple(m.get("tiers", ())),
                  notes=m.get("notes", ""), options=dict(m.get("options", {})))
        for m in data.get("models", []))
    return ProviderCatalog(
        name=name, title=head["title"], capabilities=tuple(head.get("capabilities", ())), base_url=head["base_url"],
        auth=head.get("auth", ""), terms_url=head.get("terms_url", ""), docs_url=head.get("docs_url", ""),
        verified_on=head.get("verified_on", ""), prices_updated=head.get("prices_updated", ""),
        price_source=head.get("price_source", ""), models=models, defaults=dict(data.get("defaults", {})),
        live_prefixes=tuple(head.get("live_prefixes", ())))


@dataclass(frozen=True)
class LiveModel:
    """A model as the provider's own list-models endpoint reports it."""

    id: str
    title: str = ""


class LlmProvider(ABC):
    """An AI provider (extension point `intel.llm`). `name` is the provider's code in the platform's settings."""

    name: str
    label: str = ""
    models_file: ClassVar[str] = "models.toml"          # next to the plugin's module; plugins without one declare none

    @classmethod
    def from_settings(cls, *, api_key: str, model: str, base_url: str | None, timeout: float, max_retries: int,
                      options: dict[str, Any]) -> "LlmProvider":
        """The provider as the platform's settings describe it (a provider that needs none ignores them)."""
        return cls()

    @classmethod
    def catalog(cls) -> ProviderCatalog | None:
        """The provider's data (title, capabilities, base URL, models and prices), or None for one that declares none
        (the fake provider)."""
        path = Path(inspect.getfile(cls)).parent / cls.models_file
        return load_catalog(cls.name, path) if path.is_file() else None

    def list_models(self) -> list[LiveModel]:
        """The models the provider says exist for this key (its list-models endpoint). Raises LlmError."""
        raise LlmError("This provider cannot list its models")

    def ping(self) -> LlmReply:
        """The cheapest possible real call, to prove the key and the model work."""
        return self.complete([LlmMessage("user", "Reply with the single word: ok")], [], "", 16)

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
    `plain_label` / `plain_label_sw` say in plain words what the tool is doing; the chat shows them as a status line
    (no technical terms, no figures).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    permissions: tuple[str, ...]
    personal_fields: tuple[str, ...] = ()
    plain_label: str = ""                      # what the person sees while the tool runs ("Checking stock levels")
    plain_label_sw: str = ""                   # the same in Swahili

    @abstractmethod
    def run(self, session: Session, context: RequestContext, params: dict[str, Any]) -> dict[str, Any]:
        """The result. `params` holds what the model sent (checked against `parameters`) and `company_id`, set by
        Ask Ziira (never by the model). Money and quantities as strings."""

