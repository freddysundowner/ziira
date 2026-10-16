"""Google's Gemini API (`generateContent`) as an AI provider for the assistant (`intel.llm`).

Written from Google AI for Developers (checked 2026-10-16: models.generateContent, models.list, function calling).
**Not run against the real service from this code base.** What could not be confirmed is marked `# UNVERIFIED`:

- the exact `generateContent` request fields were read from the API reference's field list, not from a full example;
  Google's newer docs lead with an "Interactions API", which is not used here;
- `functionDeclarations[].parameters` accepts an OpenAPI-style subset: our JSON schemas are cut down to it;
- Gemini 3 models return a `thoughtSignature` with function calls that must be sent back unchanged. The neutral
  contract has no field for it, so it travels inside the tool call's id (`<id>~<signature>`) and is split off again;
- `usageMetadata.thoughtsTokenCount` is billed as output and counted as such.

One call is one POST to `{base_url}/v1beta/models/{model}:generateContent` with the key in `x-goog-api-key`.
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

SIGNATURE_SEPARATOR = "~"
GENERATED_PREFIX = "gen-"
SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable", "minimum",
               "maximum", "minItems", "maxItems", "minLength", "maxLength", "title"}
REFUSED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}


def gemini_schema(schema: Any) -> Any:
    """A JSON schema cut down to the keys Gemini's function declarations accept (everything else is dropped)."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                out[key] = {k: gemini_schema(v) for k, v in value.items()}
            elif key in SCHEMA_KEYS:
                out[key] = gemini_schema(value) if key == "items" else value
        return out
    return schema


class GeminiGenerateContent(HttpLlmProvider):
    name = "gemini"
    label = "Google Gemini"
    log = logging.getLogger("ziira.ai.gemini")

    def completion_url(self) -> str:
        return f"{self.base_url}/v1beta/models/{self.model}:generateContent"

    def models_url(self) -> str:
        return f"{self.base_url}/v1beta/models?pageSize=1000"

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "content-type": "application/json"}

    # ----------------------------------------------------------------------- request
    def build_request(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                      max_tokens: int) -> dict[str, Any]:
        names: dict[str, str] = {}                      # call id -> function name, for the answers that follow
        contents: list[dict[str, Any]] = []
        for m in messages:
            for call in m.tool_calls:
                names[call.id] = call.name
            contents.append(self._content(m, names))
        body: dict[str, Any] = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": t.name, "description": t.description, "parameters": gemini_schema(t.parameters)}
                for t in tools]}]
        return body

    @staticmethod
    def _content(message: LlmMessage, names: dict[str, str]) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        for r in message.tool_results:
            try:
                value: Any = json.loads(r.content)
            except ValueError:
                value = r.content
            response = value if isinstance(value, dict) else {"result": value}
            part: dict[str, Any] = {"name": names.get(r.call_id, "unknown"),
                                    "response": {"error": r.content} if r.is_error else response}
            call_id = r.call_id.split(SIGNATURE_SEPARATOR, 1)[0]
            if not call_id.startswith(GENERATED_PREFIX):
                part["id"] = call_id
            parts.append({"functionResponse": part})
        if message.text:
            parts.append({"text": message.text})
        for call in message.tool_calls:
            call_id, _, signature = call.id.partition(SIGNATURE_SEPARATOR)
            part = {"name": call.name, "args": call.arguments}
            if not call_id.startswith(GENERATED_PREFIX):
                part["id"] = call_id
            entry: dict[str, Any] = {"functionCall": part}
            if signature:
                entry["thoughtSignature"] = signature
            parts.append(entry)
        return {"role": "model" if message.role == "assistant" else "user", "parts": parts or [{"text": ""}]}

    # ----------------------------------------------------------------------- response
    def parse_response(self, data: Any) -> LlmReply:
        if not isinstance(data, dict):
            raise LlmError("The AI provider's reply was not in the expected shape")
        usage_raw: dict[str, Any] = data["usageMetadata"] if isinstance(data.get("usageMetadata"), dict) else {}
        written = int(usage_raw.get("candidatesTokenCount") or 0) + int(usage_raw.get("thoughtsTokenCount") or 0)
        usage = LlmUsage(int(usage_raw.get("promptTokenCount") or 0), written)
        model = data.get("modelVersion") if isinstance(data.get("modelVersion"), str) else None
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = data.get("promptFeedback")
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                return LlmReply(usage=usage, stop_reason="refusal", model=model)
            raise LlmError("The AI provider's reply was not in the expected shape")
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        content = candidate.get("content")
        parts: list[Any] = (content["parts"] if isinstance(content, dict) and isinstance(content.get("parts"), list)
                            else [])
        text: list[str] = []
        calls: list[ToolCall] = []
        for index, part in enumerate(parts):
            if not isinstance(part, dict) or part.get("thought") is True:
                continue
            call = part.get("functionCall")
            if isinstance(call, dict) and isinstance(call.get("name"), str):
                args = call.get("args")
                call_id = str(call.get("id") or f"{GENERATED_PREFIX}{index}")
                if isinstance(part.get("thoughtSignature"), str):
                    call_id += SIGNATURE_SEPARATOR + part["thoughtSignature"]
                calls.append(ToolCall(call_id, call["name"], args if isinstance(args, dict) else {}))
            elif isinstance(part.get("text"), str):
                text.append(part["text"])
        finish = candidate.get("finishReason")
        if calls:
            stop = "tool_use"
        elif finish in REFUSED:
            stop = "refusal"
        elif finish == "MAX_TOKENS":
            stop = "max_tokens"
        else:
            stop = "end_turn" if finish in (None, "STOP") else str(finish).lower()
        return LlmReply(text="".join(text), tool_calls=tuple(calls), usage=usage, stop_reason=stop, model=model)

    # ----------------------------------------------------------------------- the model list
    def parse_models(self, data: Any) -> tuple[list[LiveModel], str | None]:
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise LlmError("The AI provider's model list was not in the expected shape")
        found = [LiveModel(m["name"].removeprefix("models/"), str(m.get("displayName") or ""))
                 for m in data["models"]
                 if isinstance(m, dict) and isinstance(m.get("name"), str)
                 and "generateContent" in (m.get("supportedGenerationMethods") or ["generateContent"])]
        token = data.get("nextPageToken")
        return found, (f"{self.base_url}/v1beta/models?pageSize=1000&pageToken={token}" if token else None)
