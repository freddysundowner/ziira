"""Public interface of the Ziira Intelligence store module.

Units plug into Intelligence through two extension points:

- `intel.check`: a unit supplies checks over its own data (subclass `IntelCheck`, decorate with `@provides(INTEL_CHECK)`
  in its hooks.py, list "intel.check" under `[extends] implements` and "intel" under `optional` in its manifest).
- `intel.baseline_metric`: a unit supplies observations of a metric per day (subclass `BaselineMetric`) so Intelligence
  can learn what is normal for the business.

- `intel.ask_tool`: a unit supplies a question Ask Ziira may put to its data (subclass `AskTool`; see
  `docs/ai.md`). The tool filters by the asking person's permissions (`branch_scope`) and returns a bounded result.
- `intel.llm`: an AI provider (subclass `LlmProvider`), for plugins such as `ai_anthropic`.
- `intel.action`: something Intelligence may propose for a finding and, once a person approves (or the owner has set a
  rule for it), do through the owning unit's own services (subclass `ActionProvider`; see `docs/intelligence.md`,
  "Levels of action").

Other units also read findings through the functions here (the Command Center shows the top ones).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.intel.domain.action_rules import MONEY_PERMISSIONS, Proposal
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
from ziira.modules.intel.services.nudges import Nudged
from ziira.sdk import RequestContext, Session

INTEL_CHECK = "intel.check"
INTEL_BASELINE_METRIC = "intel.baseline_metric"
INTEL_LLM = "intel.llm"
INTEL_ASK_TOOL = "intel.ask_tool"
INTEL_ACTION = "intel.action"

__all__ = [
    "ActionContext", "ActionProvider", "ActionResult", "AREAS", "FindingInfo", "Nudged", "INTEL_ACTION",
    "INTEL_ASK_TOOL",
    "MONEY_PERMISSIONS", "Proposal", "INTEL_BASELINE_METRIC", "INTEL_CHECK", "INTEL_LLM", "SEVERITIES", "AskTool",
    "Baseline", "BaselineMetric", "BranchScope", "Candidate", "CheckContext", "FindingBrief", "IntelCheck", "LlmError",
    "LlmMessage", "LlmProvider", "LlmReply", "LlmUsage", "Record", "Sample", "ToolCall", "ToolResult", "ToolSpec",
    "branch_scope", "company_visible", "date_range", "findings_summary", "fingerprint", "hide_secrets", "is_unusual",
    "nudge_people", "requested_branch", "scope_from_pairs", "top_findings",
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
class FindingInfo:
    """A finding as an action provider sees it: what was found, where, and the records and figures behind it."""

    id: UUID
    check_code: str
    severity: str
    company_id: UUID
    branch_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    amount: Decimal | None
    value: Decimal | None
    summary: str
    records: tuple[Record, ...]
    figures: dict[str, str]

    def record_id(self, record_type: str) -> UUID | None:
        """The id of the first record of this kind among the finding's evidence (or None)."""
        for r in self.records:
            if r.type == record_type and r.id is not None:
                return r.id
        return None


@dataclass(frozen=True)
class ActionContext:
    """What an action is told when it runs: whose finding, which proposal, and whether a person approved it or a rule
    of the owner's did. The permissions are those of whoever (or whatever) is acting: the approver, or, for an
    automatic action, a context holding only the provider's own `needs_permission`."""

    company_id: UUID
    branch_id: UUID | None
    finding_id: UUID
    proposal_id: UUID
    automatic: bool
    today: date
    finding_summary: str = ""


@dataclass(frozen=True)
class ActionResult:
    """What an action did. `created_refs` are (record type, id, label) of what it made, for the screen to link to."""

    ok: bool
    message: str
    created_refs: tuple[tuple[str, UUID | None, str], ...] = ()


class ActionProvider(ABC):
    """Something Intelligence may do about a finding, supplied by the unit that owns the effect.

    `proposes` looks at a finding and returns what could be done about it, with the concrete parameters, a plain
    sentence saying what will happen and the facts behind it (or nothing). `execute` does it **by calling the owning
    unit's normal services** (never SQL into another unit's tables), inside the caller's transaction, after checking the
    parameters again: the world may have changed since the proposal. It must be safe to run twice.

    `needs_permission` is what the approver must hold for the finding's company and branch. `auto_allowed` is True only
    for routine, reversible actions that move no money and change no price, credit limit or stock (a reminder, a
    message to an approver): only those may ever run without a person, and only under a rule the owner has made.
    `params_schema` and `rule_schema` use the small schema vocabulary of `domain/action_rules.py`.
    """

    type: str                               # "<unit>.<name>", unique
    title: str
    description: str = ""
    check_codes: tuple[str, ...] = ()       # the checks whose findings it can act on
    needs_permission: str
    auto_allowed: bool = False
    params_schema: dict[str, Any] = {}
    rule_schema: dict[str, Any] = {}        # the conditions an automation rule may set (empty: none)

    @abstractmethod
    def proposes(self, session: Session, finding: FindingInfo) -> list[Proposal]:
        """What could be done about this finding. Read only; zero or more proposals."""

    @abstractmethod
    def execute(self, session: Session, context: ActionContext, params: dict[str, Any]) -> ActionResult:
        """Do it, through the owning unit's services, as the current context."""

    def covered_by(self, conditions: dict[str, Any], params: dict[str, Any], finding: FindingInfo) -> bool:
        """Whether a rule's conditions (validated against `rule_schema`) cover this proposal. The engine already checks
        the generic `branch_id` and `max_amount` conditions; a provider checks the ones that are its own."""
        return True


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


def nudge_people(session: Session, *, company_id: UUID, branch_id: UUID | None, permission: str, text: str,
                 finding_id: UUID, today: date) -> Nudged:
    """Message the people who hold `permission` for the company or branch, through the business's alert channel (an
    action provider uses it to nudge an approver). Opt-outs apply; the same nudge on the same day is sent once."""
    from ziira.modules.intel.services import nudges

    return nudges.nudge_people(session, company_id=company_id, branch_id=branch_id, permission=permission, text=text,
                               finding_id=finding_id, today=today)


def top_findings(session: Session, context: RequestContext, limit: int = 5) -> list[FindingBrief]:
    """The open findings that matter most to this user, within what their role lets them see."""
    from ziira.modules.intel.services import findings

    return findings.top_for(session, context, limit)


def findings_summary(session: Session, context: RequestContext) -> dict[str, int]:
    """How many open findings per severity the user may see, e.g. {"high": 2, "medium": 5}."""
    from ziira.modules.intel.services import findings

    return findings.counts_by_severity(session, context)
