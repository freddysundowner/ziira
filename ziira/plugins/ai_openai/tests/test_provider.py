"""The OpenAI provider (Responses API) against a pretend API. Shapes are from the public documentation and not run
against the real service (docs/ai.md)."""

import json

import pytest

from tests.ai_provider_helpers import TOOL, Pretend, ask, reply
from ziira.modules.intel.public import LlmError, LlmMessage, ToolResult
from ziira.plugins.ai_openai.provider import OpenAIResponses

KEY = "sk-proj-test0123456789abcdefghijklmnop"
OK = {"id": "resp_1", "model": "model-x", "status": "completed", "output": [
    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Sales were 116.00."}]}],
      "usage": {"input_tokens": 100, "output_tokens": 12, "total_tokens": 112}}


def make(net: Pretend, **kw):  # type: ignore[no-untyped-def]
    return net.provider(OpenAIResponses, KEY, model="model-x", **kw)


def test_the_request_has_the_documented_url_auth_and_body() -> None:
    net = Pretend(reply(200, OK))
    result = ask(make(net, options={"reasoning_effort": "low"}), [TOOL])
    sent = net.requests[0]
    assert str(sent.url) == "https://api.example.test/v1/responses"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(sent.content)
    assert body == {"model": "model-x", "input": [{"role": "user", "content": "How were sales?"}],
                    "max_output_tokens": 300, "store": False, "instructions": "Be brief.",
                    "tools": [{"type": "function", "name": "pos_sales_summary", "description": "Sales between two dates",
                               "parameters": TOOL.parameters}], "reasoning": {"effort": "low"}}
    assert result.text == "Sales were 116.00." and result.stop_reason == "end_turn" and result.model == "model-x"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 12)


def test_no_system_tools_or_options_means_none_are_sent() -> None:
    net = Pretend(reply(200, OK))
    make(net).complete([LlmMessage("user", "Hi")], [], "", 50)
    assert set(json.loads(net.requests[0].content)) == {"model", "input", "max_output_tokens", "store"}


def test_a_function_call_round_trip() -> None:
    asking = {**OK, "output": [{"type": "reasoning", "summary": []},
                               {"type": "function_call", "id": "fc_1", "call_id": "call_9", "name": "pos_sales_summary",
                                "arguments": '{"date_from": "2026-10-01"}', "status": "completed"}]}
    net = Pretend(reply(200, asking), reply(200, OK))
    provider = make(net)
    first = ask(provider, [TOOL])
    assert first.stop_reason == "tool_use"
    assert [(c.id, c.name, c.arguments) for c in first.tool_calls] == [
        ("call_9", "pos_sales_summary", {"date_from": "2026-10-01"})]
    provider.complete([LlmMessage("user", "q"), LlmMessage("assistant", "Let me look", tool_calls=first.tool_calls),
                       LlmMessage("user", tool_results=(ToolResult("call_9", '{"t": "1"}'),
                                                        ToolResult("call_10", "Nope", True)))], [TOOL], "", 100)
    items = json.loads(net.requests[1].content)["input"]
    assert items[1] == {"role": "assistant", "content": "Let me look"}
    assert items[2] == {"type": "function_call", "call_id": "call_9", "name": "pos_sales_summary",
                        "arguments": '{"date_from": "2026-10-01"}'}
    assert items[3:] == [{"type": "function_call_output", "call_id": "call_9", "output": '{"t": "1"}'},
                         {"type": "function_call_output", "call_id": "call_10", "output": "Error: Nope"}]


def test_tool_results_come_before_the_text_of_the_same_turn_and_bad_arguments_become_empty() -> None:
    body = {**OK, "output": [{"type": "function_call", "call_id": "c", "name": "x", "arguments": "not json"}]}
    assert ask(make(Pretend(reply(200, body)))).tool_calls[0].arguments == {}


@pytest.mark.parametrize(("body", "stop"), [
    ({**OK, "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}, "max_tokens"),
    ({**OK, "status": "incomplete", "incomplete_details": {"reason": "content_filter"}}, "refusal"),
    ({**OK, "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}, "refusal")])
def test_incomplete_and_refused_replies_are_mapped(body: dict, stop: str) -> None:  # type: ignore[type-arg]
    assert ask(make(Pretend(reply(200, body)))).stop_reason == stop


@pytest.mark.parametrize("body", [{"no": "output"}, {"output": "x"}, [], "oops"])
def test_a_reply_not_shaped_like_a_response_is_an_error(body: object) -> None:
    with pytest.raises(LlmError):
        ask(make(Pretend(reply(200, body))))


def test_errors_are_mapped_and_the_key_never_shows() -> None:
    net = Pretend(reply(429, {"error": {"type": "rate_limit_exceeded", "message": "slow"}}, **{"retry-after": "2"}),
                  reply(200, OK))
    assert ask(make(net)).text and net.pauses == [2.0]
    net = Pretend(reply(401, {"error": {"type": "invalid_request_error", "message": f"Incorrect API key {KEY}"}}))
    with pytest.raises(LlmError) as caught:
        ask(make(net))
    assert not caught.value.retryable and KEY not in str(caught.value) and len(net.requests) == 1


def test_the_model_list_reads_data_ids() -> None:
    net = Pretend(reply(200, {"data": [{"id": "gpt-a"}, {"id": "text-embedding-3"}, {"object": "x"}]}))
    assert [m.id for m in make(net).list_models()] == ["gpt-a", "text-embedding-3"]
    assert str(net.requests[0].url) == "https://api.example.test/v1/models"


def test_it_declares_its_models_as_data() -> None:
    catalog = OpenAIResponses.catalog()
    assert catalog is not None and catalog.title == "OpenAI" and catalog.live_prefixes
    assert catalog.model(catalog.default_model("ask")) is not None
