"""What the Super Admin asks the AI layer for (extension point `kernel.ai_platform`): how many businesses hold a valid
consent for a provider (so switching the default can warn the owner), and the scored quality check."""

from typing import Any

from sqlalchemy import text

from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.domain.llm import LlmProvider
from ziira.modules.intel.services import quality_check
from ziira.sdk import AiPlatformHooks, Session, provides


@provides("kernel.ai_platform")
class IntelAiPlatform(AiPlatformHooks):
    def valid_consents(self, session: Session, provider: str) -> int:
        return int(session.execute(text(
            "select count(*) from (select distinct on (company_id) company_id, action, text_version, provider "
            "from intel.ai_consent order by company_id, created_at desc, id desc) c "
            "where c.action = 'granted' and c.provider = :p and c.text_version = :v "
            "and exists (select 1 from kernel.company k where k.id = c.company_id "
            "and coalesce((k.settings ->> 'ai_enabled')::boolean, false))"),
            {"p": provider, "v": ai_rules.CONSENT_VERSION}).scalar() or 0)

    def quality_plan(self, level: str) -> dict[str, Any]:
        return quality_check.plan(level)

    def quality_check(self, provider: Any, level: str) -> dict[str, Any]:
        assert isinstance(provider, LlmProvider)
        return quality_check.run(provider, level)
