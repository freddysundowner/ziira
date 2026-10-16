"""The Gemini provider against a pretend API: URL, key header, body (system prompt, tools, function results), parsing of
text, function calls, thought signatures and usage, and the model list. Shapes are from the public documentation and
not run against the real service (docs/ai.md)."""

import json

import pytest

from tests.ai_provider_helpers import TOOL, Pretend, ask, reply
from ziira.modules.intel.public import LlmError, LlmMessage, ToolResult
from ziira.plugins.ai_gemini.provider import GeminiGenerateContent, gemini_schema

KEY = "AIzaSyTestKey0123456789abcdefghijk"
OK = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Sales were 116.00."}]}, "finishReason": "STOP"}],
      "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 12, "thoughtsTokenCount": 30,
                        "totalTokenCount": 142}, "modelVersion": "gemini-test"}


def make(net: Pretend, **kw):  # type: ignore[no-untyped-def]
    return net.provider(GeminiGenerateContent, KEY, model="gemini-test", **kw)


def test_the_request_has_the_documented_url_key_header_and_body() -> None:
    net = Pretend(reply(200, OK))
    result = ask(make(net), [TOOL])
    sent = net.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.example.test/v1beta/models/gemini-test:generateContent"
    assert sent.headers["x-goog-api-key"] == KEY and "key=" not in str(sent.url)
    body = json.loads(sent.content)
    assert body["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "How were sales?"}]}]
    assert body["generationConfig"] == {"maxOutputTokens": 300}
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "pos_sales_summary" and "additionalProperties" not in declaration["parameters"]
    assert declaration["parameters"]["properties"]["limit"] == {"type": "integer", "minimum": 1, "maximum": 30}
    assert result.text == "Sales were 116.00." and result.stop_reason == "end_turn"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (100, 42)       # thinking is billed as output


def test_no_system_or_tools_means_neither_is_sent() -> None:
    net = Pretend(reply(200, OK))
    make(net).complete([LlmMessage("user", "Hi")], [], "", 50)
    assert set(json.loads(net.requests[0].content)) == {"contents", "generationConfig"}


def test_the_schema_keeps_only_what_gemini_accepts() -> None:
    cut = gemini_schema({"type": "object", "additionalProperties": False, "$schema": "x",
                         "properties": {"a": {"type": "array", "items": {"type": "string", "pattern": "x"},
                                              "uniqueItems": True}}, "required": ["a"]})
    assert cut == {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "string"}}},
                   "required": ["a"]}


def test_a_function_call_round_trip_keeps_the_signature_and_names_the_answer() -> None:
    asking = {"candidates": [{"content": {"role": "model", "parts": [
        {"text": "Looking."},
        {"functionCall": {"id": "fc1", "name": "pos_sales_summary", "args": {"date_from": "2026-10-01"}},
         "thoughtSignature": "SIG=="}, {"thought": True, "text": "hidden thinking"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2}}
    net = Pretend(reply(200, asking), reply(200, OK))
    provider = make(net)
    first = ask(provider, [TOOL])
    assert first.stop_reason == "tool_use" and first.text == "Looking."
    call = first.tool_calls[0]
    assert call.name == "pos_sales_summary" and call.arguments == {"date_from": "2026-10-01"}
    history = [LlmMessage("user", "q"), LlmMessage("assistant", first.text, tool_calls=first.tool_calls),
               LlmMessage("user", tool_results=(ToolResult(call.id, '{"total": "116.00"}'),))]
    provider.complete(history, [TOOL], "", 100)
    contents = json.loads(net.requests[1].content)["contents"]
    assert contents[1] == {"role": "model", "parts": [
        {"text": "Looking."},
        {"functionCall": {"name": "pos_sales_summary", "args": {"date_from": "2026-10-01"}, "id": "fc1"},
         "thoughtSignature": "SIG=="}]}
    assert contents[2] == {"role": "user", "parts": [
        {"functionResponse": {"name": "pos_sales_summary", "response": {"total": "116.00"}, "id": "fc1"}}]}


def test_a_call_without_an_id_gets_one_that_is_not_sent_back_and_an_error_result_says_so() -> None:
    asking = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "x", "args": {}}}]}}]}
    net = Pretend(reply(200, asking), reply(200, OK))
    provider = make(net)
    first = ask(provider)
    call = first.tool_calls[0]
    provider.complete([LlmMessage("user", "q"), LlmMessage("assistant", "", tool_calls=first.tool_calls),
                       LlmMessage("user", tool_results=(ToolResult(call.id, "Not possible", True),))], [], "", 50)
    parts = json.loads(net.requests[1].content)["contents"]
    assert parts[1]["parts"] == [{"functionCall": {"name": "x", "args": {}}}]
    assert parts[2]["parts"] == [{"functionResponse": {"name": "x", "response": {"error": "Not possible"}}}]


@pytest.mark.parametrize(("body", "stop"), [
    ({"candidates": [{"content": {"parts": [{"text": "cut"}]}, "finishReason": "MAX_TOKENS"}]}, "max_tokens"),
    ({"candidates": [{"finishReason": "SAFETY"}]}, "refusal"),
    ({"promptFeedback": {"blockReason": "SAFETY"}}, "refusal")])
def test_stops_and_blocks_are_mapped(body: dict, stop: str) -> None:  # type: ignore[type-arg]
    assert ask(make(Pretend(reply(200, body)))).stop_reason == stop


@pytest.mark.parametrize("body", [{"no": "candidates"}, [], "oops"])
def test_a_reply_not_shaped_like_a_response_is_an_error(body: object) -> None:
    with pytest.raises(LlmError):
        ask(make(Pretend(reply(200, body))))


def test_a_rate_limit_is_retried_after_the_pause_asked_for_and_a_wrong_key_fails_at_once() -> None:
    net = Pretend(reply(429, {"error": {"code": 429, "message": "slow", "status": "RESOURCE_EXHAUSTED"}},
                        **{"retry-after": "4"}), reply(200, OK))
    assert ask(make(net)).text and net.pauses == [4.0]
    net = Pretend(reply(403, {"error": {"code": 403, "message": f"API key {KEY} is invalid", "status": "PERMISSION_DENIED"}}))
    with pytest.raises(LlmError) as caught:
        ask(make(net))
    assert not caught.value.retryable and KEY not in str(caught.value) and caught.value.status == 403
    assert "PERMISSION_DENIED" in str(caught.value)


def test_the_model_list_follows_pages_and_keeps_models_that_can_generate() -> None:
    page1 = {"models": [{"name": "models/gemini-a", "displayName": "A", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/embed-x", "supportedGenerationMethods": ["embedContent"]}],
             "nextPageToken": "T2"}
    page2 = {"models": [{"name": "models/gemini-b", "displayName": "B",
                         "supportedGenerationMethods": ["generateContent", "countTokens"]}]}
    net = Pretend(reply(200, page1), reply(200, page2))
    found = make(net).list_models()
    assert [m.id for m in found] == ["gemini-a", "gemini-b"]
    assert "pageToken=T2" in str(net.requests[1].url) and net.requests[1].headers["x-goog-api-key"] == KEY


def test_it_declares_its_models_as_data() -> None:
    catalog = GeminiGenerateContent.catalog()
    assert catalog is not None and catalog.title == "Google Gemini" and "tool_calling" in catalog.capabilities
    assert catalog.default_model("ask") in {m.id for m in catalog.models}
