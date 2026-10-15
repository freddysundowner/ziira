"""Public interface of the Ziira Intelligence store module.

Units plug into Intelligence through two extension points:

- `intel.check`: a unit supplies checks over its own data (subclass `IntelCheck`, decorate with `@provides(INTEL_CHECK)`
  in its hooks.py, list "intel.check" under `[extends] implements` and "intel" under `optional` in its manifest).
- `intel.baseline_metric`: a unit supplies observations of a metric per day (subclass `BaselineMetric`) so Intelligence
  can learn what is normal for the business.

- `intel.ask_tool`: a unit supplies a question Ask Ziira may put to its data (subclass `AskTool`; see
  `docs/ai.md`). The tool filters by the asking person's permissions (`branch_scope`) and returns a bounded result.
- `intel.llm`: an AI provider (subclass `LlmProvider`), for plugins such as `ai_anthropic`.

Other units also read findings through the functions here (the Command Center shows the top ones).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.intel.domain.ai_rules import hide_secrets
from ziira.modules.intel.domain.llm import (
    AskTool,
    LlmError,
    LlmMessage,
    LlmProvider,
    LlmReply,
    LlmUsage,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from ziira.modules.intel.domain.model import AREAS, SEVERITIES, Baseline, Candidate, Record, Sample
from ziira.modules.intel.domain.rules import fingerprint, is_unusual
from ziira.modules.intel.domain.scope import (
    BranchScope,
    branch_scope,
    company_visible,
    date_range,
    requested_branch,
    scope_from_pairs,
)
from ziira.sdk import RequestContext, Session

INTEL_CHECK = "intel.check"
INTEL_BASELINE_METRIC = "intel.baseline_metric"
INTEL_LLM = "intel.llm"
INTEL_ASK_TOOL = "intel.ask_tool"

__all__ = [
    "AREAS", "INTEL_ASK_TOOL", "INTEL_BASELINE_METRIC", "INTEL_CHECK", "INTEL_LLM", "SEVERITIES", "AskTool",
    "Baseline", "BaselineMetric", "BranchScope", "Candidate", "CheckContext", "FindingBrief", "IntelCheck", "LlmError",
    "LlmMessage", "LlmProvider", "LlmReply", "LlmUsage", "Record", "Sample", "ToolCall", "ToolResult", "ToolSpec",
    "branch_scope", "company_visible", "date_range", "findings_summary", "fingerprint", "hide_secrets", "is_unusual",
    "requested_branch", "scope_from_pairs", "top_findings",
]


@dataclass(frozen=True)
class CheckContext:
    """What a check is told when it runs: which company, what day it is, its limits, and what is normal."""

    company_id: UUID
    today: date
    params: dict[str, Any]
    baseline: Callable[[str, str], Baseline | None]
    timezone: str = "UTC"

    def number(self, name: str) -> Decimal:
        """A numeric limit of the check (its default, or what the business set)."""
        return Decimal(str(self.params[name]))


class IntelCheck(ABC):
    """A check over a unit's data. Deterministic: the numbers in what it reports come from records, never from a guess.

    `params` are the check's limits with their defaults (the business may change them); `auto_resolves` says that a
    finding this check no longer reports is closed by itself (true for states like "out of stock", false for one-off
    events like "a void on Tuesday", which stay until a person deals with them).
    """

    code: str
    title: str
    area: str
    description: str = ""
    default_severity: str = "medium"
    params: dict[str, Any] = {}
    auto_resolves: bool = True

    @abstractmethod
    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        """Problems found for ctx.company_id. Read through the session; never write."""


class BaselineMetric(ABC):
    """Observations of one metric, from which Intelligence learns the normal range per dimension."""

    code: str
    title: str

    @abstractmethod
    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        """One value per dimension key per observation (for example a cashier's void rate on each day)."""


@dataclass(frozen=True)
class FindingBrief:
    """A finding in short, for briefs and dashboards."""

    id: UUID
    severity: str
    area: str | None
    summary: str
    recommended_action: str | None
    status: str
    company_id: UUID | None
    branch_id: UUID | None
    amount: Decimal | None
    reason: str | None = None            # the AI layer's one-line reason for its place, when it ranked this finding


def top_findings(session: Session, context: RequestContext, limit: int = 5) -> list[FindingBrief]:
    """The open findings that matter most to this user, within what their role lets them see."""
    from ziira.modules.intel.services import findings

    return findings.top_for(session, context, limit)


def findings_summary(session: Session, context: RequestContext) -> dict[str, int]:
    """How many open findings per severity the user may see, e.g. {"high": 2, "medium": 5}."""
    from ziira.modules.intel.services import findings

    return findings.counts_by_severity(session, context)
