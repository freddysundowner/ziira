"""The AI layer's part of the website assistant (extension point `kernel.site_assistant_llm`): one plain-text completion
with the platform's provider. No business, no consent record and no tools: the visitor's words are scrubbed of personal
data first, the provider's errors are cleaned of keys, and the platform (not this file) counts the usage."""

from typing import Any

from ziira.modules.intel.domain import ai_rules
from ziira.modules.intel.domain.llm import LlmError, LlmMessage
from ziira.sdk import SITE_ASSISTANT_LLM, SiteAssistantFailed, SiteAssistantLlm, SiteReply, ai_active_secrets, provides


@provides(SITE_ASSISTANT_LLM)
class IntelSiteAssistantLlm(SiteAssistantLlm):
    def complete(self, runtime: Any, system: str, user: str, max_tokens: int) -> SiteReply:
        secrets = ai_active_secrets()
        try:
            reply = runtime.build().complete(
                [LlmMessage("user", ai_rules.scrub_personal(user))], [], system, max_tokens
            )
        except LlmError as error:
            raise SiteAssistantFailed(ai_rules.hide_secrets(str(error), secrets)) from None
        except Exception as error:  # noqa: BLE001 - a provider's failure is never shown as a stack trace
            raise SiteAssistantFailed(ai_rules.hide_secrets(type(error).__name__, secrets)) from None
        if reply.stop_reason == "refusal":
            raise SiteAssistantFailed("The provider declined to answer")
        return SiteReply(
            reply.text,
            reply.usage.input_tokens,
            reply.usage.output_tokens,
            reply.model or runtime.model,
            reply.stop_reason,
        )
