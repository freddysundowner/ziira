"""OpenAI's Responses API as an AI provider for the assistant (`intel.llm`).

Written from OpenAI's API documentation (checked 2026-10-16: function calling guide, models page, pricing page). The
Responses API is used rather than Chat Completions because the models page points to it. **Not run against the real
service from this code base.** What could not be confirmed is marked `# UNVERIFIED`:

- the request fields `instructions`, `max_output_tokens`, `store` and `reasoning.effort`, and the response fields
  `status`, `incomplete_details.reason` and `usage.input_tokens` / `output_tokens` (the guide shows only part of them);
- `store: false` is sent so that nothing is kept for later turns: each call carries the whole conversation. Reasoning
  items of a reasoning model are therefore not sent back between tool rounds (the neutral contract has no place for
  them); the API may warn or reason a little less well in the second round of a tool conversation;
- `GET /v1/models` returns `{"data": [{"id": ...}]}` and lists models that cannot chat (embeddings, speech): the
  catalog's `live_prefixes` filter them.

One call is one POST to `{base_url}/v1/responses` with `Authorization: Bearer <key>`.
"""

import json
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


class OpenAIResponses(HttpLlmProvider):
    name = "openai"
    label = "OpenAI"
    log = logging.getLogger("ziira.ai.openai")

    def completion_url(self) -> str:
        return f"{self.base_url}/v1/responses"

    def models_url(self) -> str:
        return f"{self.base_url}/v1/models"

    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}

    # ----------------------------------------------------------------------- request
    def build_request(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                      max_tokens: int) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for m in messages:
            for r in m.tool_results:
                items.append({"type": "function_call_output", "call_id": r.call_id,
                              "output": f"Error: {r.content}" if r.is_error else r.content})
            if m.text:
                items.append({"role": m.role, "content": m.text})
            for c in m.tool_calls:
                items.append({"type": "function_call", "call_id": c.id, "name": c.name,
                              "arguments": json.dumps(c.arguments)})
        body: dict[str, Any] = {"model": self.model, "input": items, "max_output_tokens": max_tokens, "store": False}
        if system:
            body["instructions"] = system
        if tools:
            body["tools"] = [{"type": "function", "name": t.name, "description": t.description,
                              "parameters": t.parameters} for t in tools]
        effort = self.options.get("reasoning_effort")
        if effort:
            body["reasoning"] = {"effort": effort}
        return body

    # ----------------------------------------------------------------------- response
    def parse_response(self, data: Any) -> LlmReply:
        if not isinstance(data, dict) or not isinstance(data.get("output"), list):
            raise LlmError("The AI provider's reply was not in the expected shape")
        text: list[str] = []
        calls: list[ToolCall] = []
        refused = False
        for item in data["output"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call" and isinstance(item.get("name"), str):
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except ValueError:
                    args = {}
                calls.append(ToolCall(str(item.get("call_id") or item.get("id") or ""), item["name"],
                                      args if isinstance(args, dict) else {}))
            elif item.get("type") == "message":
                for block in item.get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                        text.append(block["text"])
                    elif block.get("type") == "refusal":
                        refused = True
        usage_raw: dict[str, Any] = data["usage"] if isinstance(data.get("usage"), dict) else {}
        usage = LlmUsage(int(usage_raw.get("input_tokens") or 0), int(usage_raw.get("output_tokens") or 0))
        details: dict[str, Any] = data["incomplete_details"] if isinstance(data.get("incomplete_details"), dict) else {}
        if calls:
            stop = "tool_use"
        elif refused or details.get("reason") == "content_filter":
            stop = "refusal"
        elif data.get("status") == "incomplete":
            stop = "max_tokens" if details.get("reason") == "max_output_tokens" else "incomplete"
        else:
            stop = "end_turn"
        return LlmReply(text="".join(text), tool_calls=tuple(calls), usage=usage, stop_reason=stop,
                        model=data.get("model") if isinstance(data.get("model"), str) else None)

    def parse_models(self, data: Any) -> tuple[list[LiveModel], str | None]:
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise LlmError("The AI provider's model list was not in the expected shape")
        found = [LiveModel(m["id"]) for m in data["data"] if isinstance(m, dict) and isinstance(m.get("id"), str)]
        return found, None
