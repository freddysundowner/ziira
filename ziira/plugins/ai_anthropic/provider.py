"""Anthropic's Messages API as an AI provider for the assistant (`intel.llm`).

Request shapes follow Anthropic's public documentation (checked 2026-10-16: Messages API, Models API). **They have not
been run against the real service from this code base**; what could not be confirmed is marked `# UNVERIFIED` below and
listed in `docs/ai.md`. One call is one POST to `{base_url}/v1/messages`; the shared retry, error and list-models
behaviour is in `HttpLlmProvider`.
"""

import logging
from collections.abc import Sequence
from typing import Any

from ziira.modules.intel.public import (
    HttpLlmProvider,
    LiveModel,
    LlmError,
    LlmMessage,
    LlmReply,
    LlmUsage,
    ToolCall,
    ToolSpec,
)

API_VERSION = "2023-06-01"


class AnthropicMessages(HttpLlmProvider):
    """Talks to the Messages API."""

    name = "anthropic"
    label = "Anthropic"
    log = logging.getLogger("ziira.ai.anthropic")

    def completion_url(self) -> str:
        return f"{self.base_url}/v1/messages"

    def models_url(self) -> str:
        return f"{self.base_url}/v1/models?limit=1000"

    def headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    def parse_models(self, data: Any) -> tuple[list[LiveModel], str | None]:
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise LlmError("The AI provider's model list was not in the expected shape")
        found = [LiveModel(str(m["id"]), str(m.get("display_name") or "")) for m in data["data"]
                 if isinstance(m, dict) and isinstance(m.get("id"), str)]
        # UNVERIFIED: paging with `after_id` = last_id when has_more; one page of 1000 covers every current model.
        return found, None

    # ----------------------------------------------------------------------- request
    def build_request(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                      max_tokens: int) -> dict[str, Any]:
        """The JSON body of the POST."""
        body: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                "messages": [self._message(m) for m in messages]}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in tools]
        return body

    @staticmethod
    def _message(message: LlmMessage) -> dict[str, Any]:
        if message.tool_results:
            blocks: list[dict[str, Any]] = []
            for r in message.tool_results:
                block: dict[str, Any] = {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content}
                if r.is_error:
                    block["is_error"] = True
                blocks.append(block)
            if message.text:
                blocks.append({"type": "text", "text": message.text})
            return {"role": "user", "content": blocks}
        if message.tool_calls:
            blocks = [{"type": "text", "text": message.text}] if message.text else []
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                       for c in message.tool_calls]
            return {"role": "assistant", "content": blocks}
        return {"role": message.role, "content": message.text}

    # ----------------------------------------------------------------------- response
    def parse_response(self, data: Any) -> LlmReply:
        """A `LlmReply` from the response JSON; LlmError if it is not shaped like a message."""
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise LlmError("The AI provider's reply was not in the expected shape")
        text: list[str] = []
        calls: list[ToolCall] = []
        for block in data["content"]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text.append(block["text"])
            elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                arguments = block.get("input")
                calls.append(ToolCall(str(block.get("id", "")), block["name"],
                                      arguments if isinstance(arguments, dict) else {}))
        usage: dict[str, Any] = data["usage"] if isinstance(data.get("usage"), dict) else {}
        tokens_in = sum(int(usage.get(k) or 0) for k in
                        ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        return LlmReply(text="".join(text), tool_calls=tuple(calls),
                        usage=LlmUsage(tokens_in, int(usage.get("output_tokens") or 0)),
                        stop_reason=data.get("stop_reason") if isinstance(data.get("stop_reason"), str) else None,
                        model=data.get("model") if isinstance(data.get("model"), str) else None)
