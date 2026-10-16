"""The one door to the AI provider. Everything that talks to a model goes through `call`.

Before a call: the business must have switched the assistant on *and* an Owner must have consented to the current text,
the purpose must be allowed, the month's token budget must not be spent, and the platform must have a provider set up.
What is sent is scrubbed of personal data. Every call, and every refusal, is logged (who, why, a hash of what was
sent, tools called, tokens, time, outcome; never the text and never a key). The provider is called with **no database
transaction open**: this module opens its own short ones around the check and the record.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.domain.llm import LlmError, LlmMessage, LlmProvider, LlmReply, ToolCall, ToolSpec
from ziira.modules.intel.repository import ai_repo as repo
from ziira.sdk import (
    Session,
    ZiiraError,
    ai_active_secrets,
    ai_record_usage,
    ai_runtime,
    company_setting,
    tenant_transaction,
)

log = logging.getLogger("ziira.intel.ai")
FEATURES = ("explain", "rank", "ask")

REASONS = {
    "not_enabled": "The AI assistant is switched off for this business.",
    "no_consent": "The AI assistant has no valid consent from an Owner.",
    "purpose_off": "This use of the AI assistant is switched off in Settings.",
    "not_configured": "The platform has no AI provider set up.",
    "terms_unconfirmed": "The platform has not confirmed its AI provider's data terms.",
    "spend_cap": "The platform's AI spending limit for this month has been reached.",
    "budget": "This month's AI token limit has been reached.",
}


class AiUnavailable(ZiiraError):
    """The assistant cannot be used now (off, no consent, over budget, no provider). `details['reason']` says which."""

    status = 409
    code = "ai_unavailable"

    def __init__(self, reason: str) -> None:
        super().__init__(REASONS.get(reason, "The AI assistant is not available."), {"reason": reason})
        self.reason = reason


class AiRejected(ZiiraError):
    """The provider answered but the answer was not accepted (its numbers were not in the data, or it was not in the
    shape asked for): it was discarded and the deterministic text stays."""

    status = 422
    code = "ai_rejected"


class AiFailed(ZiiraError):
    """The provider could not answer (after retries): nothing was changed; try again later."""

    status = 502
    code = "ai_failed"


@dataclass(frozen=True)
class AiState:
    """Whether the assistant may be used for a company, and why not."""

    company_id: UUID
    enabled: bool
    consent_valid: bool
    explanations: bool
    auto_explain: bool
    ask: bool
    token_limit: int
    tokens_used: int
    calls: int
    provider: str
    model: str
    configured: bool
    terms_ok: bool
    consent: Row[Any] | None
    provider_label: str = ""
    spend_ok: bool = True

    def blocked(self, purpose: str) -> str | None:
        """The reason the assistant cannot be used for `purpose` now, or None when it can."""
        if not self.enabled:
            return "not_enabled"
        if not self.consent_valid:
            return "no_consent"
        if not (self.ask if purpose == "ask" else self.explanations):
            return "purpose_off"
        if not self.configured:
            return "not_configured"
        if not self.terms_ok:
            return "terms_unconfirmed"
        if not self.spend_ok:
            return "spend_cap"
        if self.tokens_used >= self.token_limit:
            return "budget"
        return None

    @property
    def remaining(self) -> int:
        return max(self.token_limit - self.tokens_used, 0)


def this_month() -> date:
    """The first day of the current month (UTC): the budget period."""
    return datetime.now(UTC).date().replace(day=1)


def _tenant_of(session: Session) -> UUID | None:
    value = session.execute(text("select kernel.current_tenant()")).scalar()
    return UUID(str(value)) if value else None


def provider(feature: str = "ask", tenant_id: UUID | None = None) -> LlmProvider | None:
    """The provider the platform has set up for this feature (and business): from the Super Admin's settings, else the
    environment's. None when nothing is set up or no plugin offers it."""
    runtime = ai_runtime(feature if feature in FEATURES else "ask", tenant_id)
    return runtime.build() if runtime else None


def get_state(session: Session, company_id: UUID) -> AiState:
    """What the assistant may do for the company right now."""
    tenant_id = _tenant_of(session)
    runtime = ai_runtime("ask", tenant_id)
    chosen = runtime.build() if runtime else None
    name = runtime.provider if runtime else ""
    consent = repo.latest_consent(session, company_id)
    valid = bool(consent and consent.action == "granted" and consent.text_version == ai_rules.CONSENT_VERSION
                 and consent.provider == name)
    used_in, used_out, calls = repo.month_used(session, company_id, this_month())
    catalog = chosen.catalog() if chosen else None
    return AiState(
        company_id=company_id, enabled=bool(company_setting(session, company_id, "ai_enabled")), consent_valid=valid,
        explanations=bool(company_setting(session, company_id, "ai_explanations")),
        auto_explain=bool(company_setting(session, company_id, "ai_auto_explain")),
        ask=bool(company_setting(session, company_id, "ai_ask")),
        token_limit=int(company_setting(session, company_id, "ai_monthly_token_limit")),
        tokens_used=used_in + used_out, calls=calls, provider=name, model=chosen.model_id() if chosen else "",
        configured=bool(chosen and chosen.configured()),
        terms_ok=runtime.terms_ok if runtime else True, consent=consent,
        provider_label=(catalog.title if catalog else (chosen.label if chosen else "")) or name,
        spend_ok=runtime.spend_ok if runtime else True)


def gate(session: Session, company_id: UUID, purpose: str, user_id: UUID | None, ref_type: str | None = None,
         ref_id: UUID | None = None) -> tuple[AiState, str | None]:
    """The state and, when the assistant cannot be used for `purpose`, why. A refusal is written to the call log (the
    caller raises AiUnavailable after its transaction has been committed, so the log row is kept)."""
    state = get_state(session, company_id)
    reason = state.blocked(purpose)
    if reason:
        repo.log_call(session, company_id=company_id, user_id=user_id, purpose=purpose, ref_type=ref_type,
                      ref_id=ref_id, provider=state.provider, model=state.model, prompt_hash=None, tool_calls=[],
                      input_tokens=0, output_tokens=0, latency_ms=None, status=f"blocked:{reason}",
                      detail=REASONS.get(reason))
    return state, reason


# --------------------------------------------------------------------------- the call
def _scrub_message(message: LlmMessage) -> LlmMessage:
    return replace(message, text=ai_rules.scrub_personal(message.text))


def _tool_log(calls: tuple[ToolCall, ...]) -> list[dict[str, Any]]:
    """The tools the model asked for: their names and which arguments it gave, never the values (a value can be a
    person's name typed as a search; the conversation keeps those where they can be erased)."""
    return [{"name": c.name, "arguments": sorted(c.arguments)} for c in calls]


def call(tenant_id: UUID, *, company_id: UUID, user_id: UUID | None, purpose: str, messages: list[LlmMessage],
         tools: list[ToolSpec], system: str, max_tokens: int, ref_type: str | None = None,
         ref_id: UUID | None = None, tools_called: list[dict[str, Any]] | None = None,
         check: Callable[[LlmReply], str | None] | None = None) -> LlmReply:
    """Ask the model, if the business allows it. Raises AiUnavailable (not allowed now), AiFailed (the provider did
    not answer) or AiRejected (`check` found a problem with the reply). Tokens are counted and the call logged
    whatever happens."""
    secrets = ai_active_secrets()
    with tenant_transaction(tenant_id) as s:
        state, reason = gate(s, company_id, purpose, user_id, ref_type, ref_id)
    if reason:
        raise AiUnavailable(reason)
    chosen = provider(purpose, tenant_id)
    assert chosen is not None                      # get_state found it configured
    safe_system = ai_rules.scrub_personal(system)
    safe_messages = [_scrub_message(m) for m in messages]
    digest = ai_rules.prompt_hash(safe_system, [(m.role, m.text, [(t.name, t.arguments) for t in m.tool_calls],
                                                 [(r.call_id, r.content) for r in m.tool_results])
                                                for m in safe_messages], [t.name for t in tools])
    budget = max(min(max_tokens, state.remaining), 1)
    started = time.monotonic()
    reply: LlmReply | None = None
    status, detail = "ok", None
    try:
        reply = chosen.complete(safe_messages, tools, safe_system, budget)
        if reply.stop_reason == "refusal":
            status, detail = "refused", "The provider declined to answer"
        elif check and (problem := check(reply)):
            status, detail = "rejected", problem
    except LlmError as error:
        status, detail = "error", ai_rules.hide_secrets(str(error), secrets)
    except Exception as error:  # noqa: BLE001 - never let a provider's failure reach the person as a stack trace
        log.exception("AI provider %s failed", chosen.name)
        status, detail = "error", ai_rules.hide_secrets(f"{type(error).__name__}: {error}", secrets)
    latency = int((time.monotonic() - started) * 1000)
    usage = reply.usage if reply else None
    with tenant_transaction(tenant_id) as s:
        if usage and usage.total:
            repo.add_usage(s, company_id, this_month(), usage.input_tokens, usage.output_tokens)
        repo.log_call(s, company_id=company_id, user_id=user_id, purpose=purpose, ref_type=ref_type, ref_id=ref_id,
                      provider=chosen.name, model=(reply.model if reply and reply.model else state.model) or None,
                      prompt_hash=digest,
                      tool_calls=(tools_called or []) + (_tool_log(reply.tool_calls) if reply else []),
                      input_tokens=usage.input_tokens if usage else 0,
                      output_tokens=usage.output_tokens if usage else 0,
                      latency_ms=latency, status=status, detail=detail)
    if usage and usage.total:
        try:
            ai_record_usage(tenant_id, chosen.name, chosen.model_id(), usage.input_tokens, usage.output_tokens)
        except Exception:  # noqa: BLE001 - the estimate must never fail a call that already happened
            log.exception("Could not record AI usage in the platform estimate")
    log.info("AI call purpose=%s provider=%s status=%s tokens=%s ms=%s", purpose, chosen.name, status,
             usage.total if usage else 0, latency)
    if status == "rejected":
        raise AiRejected("The AI's reply was discarded because it did not match the data. Nothing was changed.")
    if reply is None or status != "ok":
        raise AiFailed("The AI assistant could not answer just now. Nothing was changed; try again later.")
    return reply

