"""Anthropic's Messages API as an AI provider for the assistant (`intel.llm`).

**The request and response shapes below were written from Anthropic's public documentation and have not been run
against the real service** (see `docs/ai.md` and `scripts/live_check.py ai`). The parts most worth checking against the
live API: the `anthropic-version` header value, the model id, the `tool_use` / `tool_result` block shapes, and what
`stop_reason` and error bodies look like.

One call is one POST to `{base_url}/v1/messages`. A rate limit (429), an overload (529) or a server error (5xx) is
retried after a growing pause (the provider's `Retry-After` is respected up to a limit); other refusals (a wrong key, a
bad request) fail at once. Nothing but status, request id, tokens and time is logged: never a key, never a prompt.
"""

import logging
import random
import time
from collections.abc import Sequence
from typing import Any, ClassVar

import httpx

from ziira.modules.intel.public import (
    LlmError,
    LlmMessage,
    LlmProvider,
    LlmReply,
    LlmUsage,
    ToolCall,
    ToolSpec,
    hide_secrets,
)
from ziira.sdk import platform_settings

log = logging.getLogger("ziira.ai.anthropic")
API_VERSION = "2023-06-01"
MAX_PAUSE_SECONDS = 20.0


class AnthropicMessages(LlmProvider):
    """Talks to the Messages API. Settings come from the platform (`ZIIRA_AI_API_KEY`, `ZIIRA_AI_MODEL`,
    `ZIIRA_AI_BASE_URL`, `ZIIRA_AI_TIMEOUT_SECONDS`, `ZIIRA_AI_MAX_RETRIES`) unless given here (tests, the live check).
    `client_factory` lets tests and the live check replace the network."""

    name = "anthropic"
    label = "Anthropic"
    client_factory: ClassVar[Any] = None                       # tests: a function(timeout) returning an httpx.Client
    sleep: ClassVar[Any] = staticmethod(time.sleep)

    def __init__(self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None,
                 timeout: float | None = None, max_retries: int | None = None) -> None:
        cfg = platform_settings()
        self.api_key = cfg.ai_api_key if api_key is None else api_key
        self.model = model or cfg.ai_model
        self.base_url = (base_url or cfg.ai_base_url).rstrip("/")
        self.timeout = cfg.ai_timeout_seconds if timeout is None else timeout
        self.max_retries = cfg.ai_max_retries if max_retries is None else max_retries

    def configured(self) -> bool:
        return bool(self.api_key)

    def model_id(self) -> str:
        return self.model

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

    def headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    # ----------------------------------------------------------------------- response
    @staticmethod
    def parse_response(data: Any) -> LlmReply:
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

    def _failure(self, response: httpx.Response) -> LlmError:
        """What went wrong, in words safe to store (the provider's own message with any key removed)."""
        message = ""
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                message = f"{error.get('type', '')}: {error.get('message', '')}".strip(": ")
        except ValueError:
            pass
        retryable = response.status_code in (408, 409, 429, 529) or response.status_code >= 500
        detail = hide_secrets(message[:300], [self.api_key]) or "no details"
        return LlmError(f"The AI provider answered {response.status_code} ({detail})", retryable=retryable,
                        status=response.status_code)

    # ----------------------------------------------------------------------- the call
    def complete(self, messages: Sequence[LlmMessage], tools: Sequence[ToolSpec], system: str,
                 max_tokens: int) -> LlmReply:
        body = self.build_request(messages, tools, system, max_tokens)
        url = f"{self.base_url}/v1/messages"
        last: LlmError | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            pause: float | None = None
            try:
                with (self.client_factory(self.timeout) if self.client_factory
                      else httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5.0))) as client:
                    response = client.post(url, json=body, headers=self.headers())
            except httpx.HTTPError as error:
                last = LlmError(f"The AI provider could not be reached ({type(error).__name__})", retryable=True)
            else:
                log.info("anthropic status=%s request_id=%s ms=%s", response.status_code,
                         response.headers.get("request-id", "-"), int((time.monotonic() - started) * 1000))
                if response.status_code == 200:
                    try:
                        return self.parse_response(response.json())
                    except ValueError:
                        raise LlmError("The AI provider's reply was not valid JSON") from None
                last = self._failure(response)
                pause = self._retry_after(response)
            if not last.retryable or attempt >= self.max_retries:
                break
            self.sleep(pause if pause is not None else min(2.0 ** attempt + random.random() * 0.5, MAX_PAUSE_SECONDS))
        assert last is not None
        raise last

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        try:
            return min(max(float(response.headers.get("retry-after", "")), 0.0), MAX_PAUSE_SECONDS)
        except ValueError:
            return None
