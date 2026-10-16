"""Request and response shapes for the Intelligence API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasPath, BaseModel, ConfigDict, Field, computed_field, field_validator

from ziira.modules.intel.domain.source import is_connected_check


class RecordOut(BaseModel):
    type: str
    id: str | None
    label: str


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: UUID
    check_code: str | None
    area: str | None
    company_id: UUID | None
    branch_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    period_start: date | None
    period_end: date | None
    value: Decimal | None
    expected_value: Decimal | None
    amount: Decimal | None
    severity: str
    summary: str | None
    recommended_action: str | None
    explanation: str | None
    explanation_ai: str | None = Field(
        default=None, description="Written by the AI layer from this finding's own figures; show it as AI-written")
    explanation_ai_at: datetime | None = None
    status: str
    owner_user_id: UUID | None
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    snoozed_until: datetime | None = Field(default=None, description="Put aside until then (null: not put aside)")
    figures: dict[str, str] = Field(
        default_factory=dict, validation_alias=AliasPath("evidence", "figures"),
        description="The figures behind the finding (names are in GET /intel/plain)")

    @field_validator("figures", mode="before")
    @classmethod
    def _figures_as_text(cls, value: object) -> dict[str, str]:
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source(self) -> Literal["connected", "ziira"]:
        """Where the data behind this finding lives: `connected` (the system the business keeps) or `ziira`."""
        return "connected" if is_connected_check(self.check_code) else "ziira"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def explanation_ai_label(self) -> str | None:
        """"AI-written" whenever `explanation_ai` is present: show it next to that text, always."""
        return "AI-written" if self.explanation_ai else None


class FindingEventOut(BaseModel):
    id: UUID
    created_at: datetime
    event: str
    user_id: UUID | None
    user_name: str | None
    channel: str | None
    note: str | None


class FindingDetailOut(FindingOut):
    check_title: str | None = Field(default=None, description="The check's plain title (the code is for support)")
    value_kind: Literal["money", "percent", "count", "days", "number"] = Field(
        default="number", description="What `value` and `expected_value` measure, so a screen can format them")
    records: list[RecordOut]
    events: list[FindingEventOut]
    owner_name: str | None = Field(default=None, description="Who the finding is given to")


class FindingsSummaryOut(BaseModel):
    open: int
    by_severity: dict[str, int]
    by_area: dict[str, int]
    by_status: dict[str, int]
    amount_at_stake: Decimal
    snoozed: int = Field(default=0, description="Open findings put aside for now (not counted in `open`)")


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ExplainIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000, description="What happened")


class DismissIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AssignIn(BaseModel):
    user_id: UUID | None = None


class AskIn(BaseModel):
    user_id: UUID
    message: str = Field(default="", max_length=1000)


class CheckOut(BaseModel):
    code: str
    title: str
    area: str
    description: str
    severity: str
    enabled: bool
    auto_resolves: bool
    defaults: dict[str, Any]
    params: dict[str, Any]
    topic: Literal["cash", "stock", "customers", "suppliers", "staff", "books"] = "cash"
    source: Literal["connected", "ziira"] = "ziira"


class CheckUpdateIn(BaseModel):
    enabled: bool | None = None
    params: dict[str, Any] | None = None


class RunIn(BaseModel):
    company_id: UUID
    checks: list[str] | None = Field(default=None, description="Only these checks (all by default)")


class RunOut(BaseModel):
    checks_run: int
    created: int
    updated: int
    resolved: int
    reopened: int
    failed: list[str]


class AiExplainIn(BaseModel):
    language: Literal["en", "sw"] = "en"


class AiStatusOut(BaseModel):
    company_id: UUID
    ask_available: bool
    explanations_available: bool
    reason: str | None = Field(description="Why the assistant cannot be used now: not_enabled, no_consent, budget, ...")


class AiConsentOut(BaseModel):
    created_at: datetime
    user_name: str | None
    action: str
    text_version: str
    language: str
    provider: str
    model: str | None


class AiUsageOut(BaseModel):
    month: date
    input_tokens: int
    output_tokens: int
    calls: int


class AiSettingsOut(BaseModel):
    company_id: UUID
    enabled: bool = Field(description="Switched on and covered by a valid consent")
    consent_valid: bool
    explanations: bool
    auto_explain: bool
    ask: bool
    monthly_token_limit: int
    tokens_used: int
    calls: int
    provider: str
    model: str
    configured: bool = Field(description="The platform has what the provider needs (its key)")
    terms_confirmed: bool
    consent_version: str
    consent_text: dict[str, str] = Field(description="The words to agree to, by language")
    consents: list[AiConsentOut]
    usage: list[AiUsageOut]
    unavailable_reason: str | None


class AiSettingsIn(BaseModel):
    company_id: UUID
    enabled: bool | None = None
    accept_version: str | None = Field(
        default=None, description="The consent_version being accepted (needed to switch on)")
    language: Literal["en", "sw"] = Field(default="en", description="The language of the consent text the person read")
    explanations: bool | None = None
    auto_explain: bool | None = None
    ask: bool | None = None
    monthly_token_limit: int | None = Field(default=None, ge=0, le=2_000_000_000)


class AiCallOut(BaseModel):
    id: UUID
    created_at: datetime
    user_name: str | None
    purpose: str
    ref_type: str | None
    ref_id: UUID | None
    provider: str | None
    model: str | None
    prompt_hash: str | None
    tool_calls: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    latency_ms: int | None
    status: str
    detail: str | None


class AskQuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    company_id: UUID | None = Field(
        default=None, description="Needed only when the person can ask about several companies")
    session_id: UUID | None = Field(default=None, description="Continue this conversation (the page keeps it together)")
    language: Literal["en", "sw"] = "en"


class AskSourceOut(BaseModel):
    tool: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]
    summary: dict[str, Any]


class AskAnswerOut(BaseModel):
    session_id: UUID
    message_id: UUID
    answer: str
    sources: list[AskSourceOut]
    ai_generated: bool = True
    flagged: bool
    flag_reason: str | None
    capped: str | None


class AskMessageOut(BaseModel):
    id: UUID
    created_at: datetime
    role: str
    content: str
    sources: list[AskSourceOut]
    tools_used: list[dict[str, Any]]
    flagged: bool
    flag_reason: str | None
    ai_generated: bool


class AskSessionOut(BaseModel):
    id: UUID
    company_id: UUID
    user_id: UUID
    user_name: str | None
    title: str
    created_at: datetime
    last_at: datetime


class AskConversationOut(AskSessionOut):
    messages: list[AskMessageOut]


# --------------------------------------------------------------------------- actions (levels 3 and 4)
class ActionTypeOut(BaseModel):
    type: str
    title: str
    description: str
    check_codes: list[str]
    needs_permission: str
    can_run_by_rule: bool = Field(description="True only for routine actions that move no money and change no price, "
                                              "credit limit or stock: an owner may let these run by themselves")
    why_not_by_rule: str | None
    params_schema: dict[str, Any] = Field(description="The parameters of the action: type, title, limits, editable")
    rule_schema: dict[str, Any] = Field(description="The conditions a rule for this action may set")


class ActionResultOut(BaseModel):
    ok: bool
    message: str
    created: list[RecordOut] = []


class ProposalOut(BaseModel):
    id: UUID
    finding_id: UUID
    finding_summary: str | None
    finding_severity: str
    finding_status: str
    company_id: UUID
    branch_id: UUID | None
    action_type: str
    action_title: str
    description: str
    facts: dict[str, str]
    params: dict[str, Any]
    params_schema: dict[str, Any]
    status: str
    level_at_proposal: int
    proposed_at: datetime
    decided_by: UUID | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    executed_at: datetime | None
    result: ActionResultOut | None
    needs_permission: str
    can_decide: bool = Field(description="The signed-in user holds the permission to approve it where it applies")


class ApproveIn(BaseModel):
    params: dict[str, Any] | None = Field(default=None, description="Changed parameters (only those marked editable)")
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class RuleIn(BaseModel):
    company_id: UUID
    action_type: str = Field(max_length=100)
    conditions: dict[str, Any] = Field(default_factory=dict)
    daily_cap: int = Field(default=20, ge=1, le=1000, description="Most times this rule may act in one day")
    note: str | None = Field(default=None, max_length=300)


class RuleUpdateIn(BaseModel):
    conditions: dict[str, Any] | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=1000)
    note: str | None = Field(default=None, max_length=300)
    enabled: bool | None = None
    paused: bool | None = Field(default=None, description="Pause or resume the rule without losing it")


class RuleOut(BaseModel):
    id: UUID
    company_id: UUID
    action_type: str
    action_title: str
    enabled: bool
    paused: bool
    conditions: dict[str, Any]
    daily_cap: int
    note: str | None
    created_at: datetime
    times_used: int


class ActionLogOut(BaseModel):
    id: UUID
    created_at: datetime
    proposal_id: UUID | None
    finding_id: UUID | None
    finding_summary: str | None
    company_id: UUID
    branch_id: UUID | None
    action_type: str
    action_title: str
    mode: Literal["manual", "automatic"]
    actor_user_id: UUID | None
    actor_name: str | None
    rule_id: UUID | None
    level: int
    params: dict[str, Any]
    outcome: Literal["executed", "failed"]
    message: str
    result: ActionResultOut | None
    channel: str = "app"


# --------------------------------------------------------------------------- plain words, less noise
class PlainCheckOut(BaseModel):
    title: str = Field(description="What was noticed, as a short headline")
    why: str = Field(description="Why it matters, one sentence")
    todo: str = Field(description="The first practical step")
    topic: str
    sentence: str | None = Field(
        default=None, description="The check's limits as a sentence with {limit_name} placeholders"
    )
    units: dict[str, str] = Field(
        default_factory=dict, description="Placeholder name -> money, days, hours, percent, count, number, text"
    )
    fallback: bool = Field(
        default=False, description="True when no plain text was written for this check (its own title is used)"
    )


class TopicTextOut(BaseModel):
    key: str
    title: str
    lead: str


class FigureMetaOut(BaseModel):
    label: str
    kind: str = Field(description="money, count, percent, days, date, yesno, number or text: how to show the value")


class PlainOut(BaseModel):
    topics: list[TopicTextOut]
    checks: dict[str, PlainCheckOut]
    figures: dict[str, FigureMetaOut]
    params: dict[str, str]


class TopicStateOut(BaseModel):
    key: str
    checks: int
    enabled: int


class TopicsOut(BaseModel):
    configured: bool = Field(description="False until the business has chosen what to watch (Quick start)")
    topics: list[TopicStateOut]


class TopicsIn(BaseModel):
    topics: dict[str, bool] = Field(description="Topic -> on or off: every check of the topic is switched")


class FindingGroupOut(BaseModel):
    key: str = Field(description="Same kind of thing, same branch, first noticed the same day")
    check_code: str | None
    area: str | None
    company_id: UUID | None
    branch_id: UUID | None
    day: date
    count: int
    severity: str = Field(description="The most serious of the members")
    amount: Decimal = Field(description="Money involved, all members together")
    last_seen_at: datetime
    members: list[FindingOut] = Field(description="The findings in the group, most serious first (at most 25)")


class GroupedFindingsOut(BaseModel):
    total_groups: int
    total_findings: int
    urgent_groups: int
    groups: list[FindingGroupOut]


class SnoozeIn(BaseModel):
    days: int | None = Field(default=3, ge=1, le=90, description="Days to put it aside; null brings it back now")


class NamedOut(BaseModel):
    id: UUID
    name: str


class SubjectOut(BaseModel):
    type: str
    kind: str
    id: UUID
    label: str


class IgnoreOptionsOut(BaseModel):
    branch: NamedOut | None
    subject: SubjectOut | None
    tunable: bool = Field(
        description="The check allows its limit to be raised a little when something is called normal"
    )


class IgnoreIn(BaseModel):
    scope: Literal["branch", "person", "everywhere"]
    days: int | None = Field(default=30, ge=1, le=3650, description="Days the rule lasts; null: always")
    reason: str | None = Field(default=None, max_length=2000)
    tune: bool = Field(default=False, description="Also raise the check's limit a little (only checks that allow it)")


class IgnoreOut(BaseModel):
    rule_id: UUID
    closed: int = Field(description="Other open findings the rule closed")
    tuned: dict[str, str] | None = None
    finding: "FindingDetailOut"


class SuppressionOut(BaseModel):
    id: UUID
    created_at: datetime
    created_by_name: str | None
    company_id: UUID
    check_code: str
    branch_id: UUID | None
    entity_type: str | None
    scope_label: str
    until_date: date | None
    reason: str | None
