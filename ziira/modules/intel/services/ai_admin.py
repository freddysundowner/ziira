"""Turning the AI assistant on and off for a business: the consent, the budget, and what an Owner may look at."""

from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row

from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.permissions import AI_MANAGE
from ziira.modules.intel.repository import ai_repo as repo
from ziira.modules.intel.services import ai
from ziira.sdk import Session, ValidationFailed, audit_record, check_company, current_context, update_company_settings


def provider_label(state: ai.AiState) -> str:
    """How the consent text names the provider and model."""
    if not state.provider:
        return "the platform's AI provider"
    return f"{state.provider_label or state.provider}, model {state.model}".strip(", ")


def consent_texts(state: ai.AiState) -> dict[str, str]:
    """The current consent text in each language."""
    label = provider_label(state)
    return {lang: ai_rules.consent_text(lang, label) for lang in ai_rules.LANGUAGES}


def settings_view(session: Session, company_id: UUID) -> tuple[ai.AiState, list[Row[Any]], list[Row[Any]]]:
    """The state with the consent history and the recent months' usage, for the owner's screen."""
    check_company(session, company_id)
    current_context().require(AI_MANAGE, company_id=company_id)
    return (ai.get_state(session, company_id), repo.consents(session, company_id),
            repo.usage_history(session, company_id))


def update(session: Session, company_id: UUID, *, enabled: bool | None, accept_version: str | None, language: str,
           explanations: bool | None, auto_explain: bool | None, ask: bool | None,
           monthly_token_limit: int | None) -> ai.AiState:
    """Change the assistant's settings. Switching it on needs the current consent text accepted (and is recorded:
    who, when, the text); switching it off is recorded too and stops every call at once."""
    check_company(session, company_id)
    ctx = current_context()
    ctx.require(AI_MANAGE, company_id=company_id)
    state = ai.get_state(session, company_id)
    changes: dict[str, Any] = {}
    if enabled is True and not (state.enabled and state.consent_valid):
        if not state.provider or not state.configured:
            raise ValidationFailed("The platform has no AI provider set up yet, so the assistant cannot be switched on")
        if accept_version != ai_rules.CONSENT_VERSION or language not in ai_rules.LANGUAGES:
            raise ValidationFailed("Read the current consent text and accept it to switch the assistant on")
        text = ai_rules.consent_text(language, provider_label(state))
        repo.add_consent(session, company_id=company_id, user_id=ctx.user_id, action="granted",
                         version=ai_rules.CONSENT_VERSION, language=language, consent_text=text,
                         text_hash=ai_rules.consent_hash(text), provider=state.provider, model=state.model or None)
    if enabled is not None:
        changes["ai_enabled"] = enabled
    if enabled is False and (state.enabled or state.consent_valid):
        repo.add_consent(session, company_id=company_id, user_id=ctx.user_id, action="revoked",
                         version=ai_rules.CONSENT_VERSION,
                         language=language if language in ai_rules.LANGUAGES else "en",
                         consent_text="Consent withdrawn", text_hash=ai_rules.consent_hash("withdrawn"),
                         provider=state.provider, model=state.model or None)
    for key, value in (("ai_explanations", explanations), ("ai_auto_explain", auto_explain), ("ai_ask", ask),
                       ("ai_monthly_token_limit", monthly_token_limit)):
        if value is not None:
            changes[key] = value
    if changes:
        update_company_settings(session, company_id, changes)
    audit_record(session, "ai.settings_changed", "kernel.company", company_id, {k: str(v) for k, v in changes.items()})
    return ai.get_state(session, company_id)
