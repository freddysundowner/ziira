"""Request and response shapes for the Intelligence API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class RecordOut(BaseModel):
    type: str
    id: str | None
    label: str


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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
    records: list[RecordOut]
    figures: dict[str, str]
    events: list[FindingEventOut]


class FindingsSummaryOut(BaseModel):
    open: int
    by_severity: dict[str, int]
    by_area: dict[str, int]
    by_status: dict[str, int]
    amount_at_stake: Decimal


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
