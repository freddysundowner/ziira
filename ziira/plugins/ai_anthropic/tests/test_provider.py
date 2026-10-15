"""The Anthropic provider against a pretend API: headers, body shape, a tool-use round trip, retries and refusals.

These check our side of the conversation only; the shapes come from the public documentation and have not been run
against the real service (see docs/ai.md).
"""

import json
from typing import Any

import httpx
import pytest

from ziira.modules.intel.public import LlmError, LlmMessage, ToolCall, ToolResult, ToolSpec
from ziira.plugins.ai_anthropic.provider import AnthropicMessages

KEY = "sk-ant-test-0123456789abcdef"
TOOL = ToolSpec("pos_sales_summary", "Sales between two dates",
                {"type": "object", "properties": {"date_from": {"type": "string"}}, "required": ["date_from"]})
OK = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "stop_reason": "end_turn",
      "content": [{"type": "text", "text": "Sales were 116.00."}],
      "usage": {"input_tokens": 100, "output_tokens": 12}}


class Pretend:
    """Plays back replies and keeps the requests."""

    def __init__(self, *replies: httpx.Response | Exception) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []
        self.pauses: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(item, Exception):
            raise item
        return item

    def provider(self, **kw: Any) -> AnthropicMessages:
        class P(AnthropicMessages):
            client_factory = staticmethod(lambda timeout: httpx.Client(transport=httpx.MockTransport(self.handler)))
            sleep = staticmethod(self.pauses.append)

        return P(api_key=KEY, model="claude-sonnet-5-5", base_url="https://api.example.test/", **kw)


def reply(status: int, body: Any = None, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {}, headers=headers)


def ask(provider: AnthropicMessages, **kw: Any):  # type: ignore[no-untyped-def]
    return provider.complete([LlmMessage("user", "How were sales?")], kw.get("tools", []), "Be brief.", 300)


def test_the_request_has_the_documented_headers_and_body() -> None:
    net = Pretend(reply(200, OK))
    result = ask(net.provider(), tools=[TOOL])
    sent = net.requests[0]
    assert sent.method == "POST" and str(sent.url) == "https://api.example.test/v1/messages"
    assert sent.headers["x-api-key"] == KEY and sent.headers["anthropic-version"] == "2023-06-01"
    assert sent.headers["content-type"] == "application/json"
    assert json.loads(sent.content) == {
        "model": "claude-sonnet-5-5", "max_tokens": 300, "system": "Be brief.",
        "messages": [{"role": "user", "content": "How were sales?"}],
        "tools": [{"name": "pos_sales_summary", "description": "Sales between two dates",
                   "input_schema": TOOL.parameters}]}
    assert result.text == "Sales were 116.00." and result.usage.input_tokens == 100 and result.usage.output_tokens == 12
    assert result.stop_reason == "end_turn" and result.model == "claude-sonnet-5-5"


def test_no_system_or_tools_means_neither_is_sent() -> None:
    net = Pretend(reply(200, OK))
    net.provider().complete([LlmMessage("user", "Hi")], [], "", 50)
    assert set(json.loads(net.requests[0].content)) == {"model", "max_tokens", "messages"}


def test_a_tool_use_round_trip() -> None:
    asking = {**OK, "stop_reason": "tool_use", "content": [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "toolu_1", "name": "pos_sales_summary", "input": {"date_from": "2026-10-01"}}]}
    net = Pretend(reply(200, asking), reply(200, OK))
    provider = net.provider()
    first = ask(provider, tools=[TOOL])
    assert first.tool_calls == (ToolCall("toolu_1", "pos_sales_summary", {"date_from": "2026-10-01"}),)
    assert first.text == "Let me look." and first.stop_reason == "tool_use"
    history = [LlmMessage("user", "How were sales?"),
               LlmMessage("assistant", first.text, tool_calls=first.tool_calls),
               LlmMessage("user", tool_results=(ToolResult("toolu_1", '{"rows": []}'),
                                                ToolResult("toolu_2", "Not possible", True)))]
    provider.complete(history, [TOOL], "Be brief.", 300)
    messages = json.loads(net.requests[1].content)["messages"]
    assert messages[1] == {"role": "assistant", "content": [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "toolu_1", "name": "pos_sales_summary", "input": {"date_from": "2026-10-01"}}]}
    assert messages[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"rows": []}'},
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "Not possible", "is_error": True}]}


def test_an_assistant_turn_with_only_tool_calls_has_no_empty_text_block() -> None:
    net = Pretend(reply(200, OK))
    net.provider().complete([LlmMessage("user", "q"), LlmMessage("assistant", "", tool_calls=(ToolCall("t", "x", {}),)),
                             LlmMessage("user", tool_results=(ToolResult("t", "r"),))], [TOOL], "", 50)
    assert json.loads(net.requests[0].content)["messages"][1]["content"] == [
        {"type": "tool_use", "id": "t", "name": "x", "input": {}}]


def test_cached_input_tokens_count_against_the_budget_and_other_blocks_are_ignored() -> None:
    body = {**OK, "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "Hi"}],
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 20,
                      "output_tokens": 3}}
    result = ask(Pretend(reply(200, body)).provider())
    assert result.text == "Hi" and (result.usage.input_tokens, result.usage.output_tokens) == (35, 3)


def test_a_rate_limit_is_retried_after_the_pause_the_provider_asked_for() -> None:
    net = Pretend(reply(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}},
                        **{"retry-after": "3"}), reply(200, OK))
    assert ask(net.provider()).text == "Sales were 116.00."
    assert len(net.requests) == 2 and net.pauses == [3.0]


def test_an_outage_is_retried_with_growing_pauses_then_reported_as_retryable() -> None:
    net = Pretend(reply(529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}))
    with pytest.raises(LlmError) as caught:
        ask(net.provider(max_retries=2))
    assert caught.value.retryable and caught.value.status == 529 and len(net.requests) == 3
    assert len(net.pauses) == 2 and net.pauses[0] < net.pauses[1] + 1.0
    assert "overloaded_error" in str(caught.value)


def test_a_network_failure_is_retried() -> None:
    net = Pretend(httpx.ConnectTimeout("no route"), reply(200, OK))
    assert ask(net.provider()).text and len(net.requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_a_refusal_fails_at_once_and_never_shows_the_key(status: int) -> None:
    net = Pretend(reply(status, {"type": "error", "error": {"type": "invalid_request_error",
                                                              "message": f"bad key {KEY} given"}}))
    with pytest.raises(LlmError) as caught:
        ask(net.provider())
    assert not caught.value.retryable and len(net.requests) == 1 and net.pauses == []
    assert KEY not in str(caught.value) and caught.value.status == status


@pytest.mark.parametrize("body", [{"no": "content"}, {"content": "text"}, [], "oops"])
def test_a_reply_not_shaped_like_a_message_is_an_error(body: Any) -> None:
    with pytest.raises(LlmError):
        ask(Pretend(reply(200, body)).provider())


def test_a_reply_that_is_not_json_is_an_error() -> None:
    with pytest.raises(LlmError):
        ask(Pretend(httpx.Response(200, content=b"<html>")).provider())


def test_it_is_configured_only_with_a_key_and_names_its_model() -> None:
    assert not AnthropicMessages(api_key="").configured()
    provider = AnthropicMessages(api_key=KEY, model="m-1")
    assert provider.configured() and provider.model_id() == "m-1" and provider.name == "anthropic"
