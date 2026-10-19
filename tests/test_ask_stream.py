# ruff: noqa: F811 - the fixtures of the AI layer tests are reused by importing them
"""Ask Ziira as a chat (Server-Sent Events): the order of events, nothing unchecked is released, refusals arrive as
`error` events, the asker's branches are respected, tools run at the same time, the conversation is remembered, and no
database transaction is open while the model works. Only the fake provider is used (see tests/test_ai_layer.py)."""

import json
import threading
import time
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import text

from tests.stock_helpers import system
from tests.test_ai_layer import (  # noqa: F401 - fixtures and helpers of the AI layer tests
    INTEL,
    enable,
    fresh,
    no_transaction_open,
    shop,
    window,
)
from ziira.kernel import extensions
from ziira.kernel.context import RequestContext
from ziira.kernel.extensions import implementations_of
from ziira.modules.intel.domain.chat_text import split_chunks
from ziira.modules.intel.domain.llm import AskTool, LlmError, LlmReply
from ziira.modules.intel.fake_llm import FakeLlm
from ziira.modules.intel.services import ask, ask_stream
from ziira.modules.pos.ask_tools import SALES_PERMISSIONS

STREAM = f"{INTEL}/ask/stream"


def events_of(response) -> list[tuple[str, dict[str, Any]]]:  # type: ignore[no-untyped-def]
    """The events of a response body, in order: (name, data)."""
    out = []
    for block in response.text.split("\n\n"):
        if not block.strip():
            continue
        name, data = block.split("\n", 1)
        assert name.startswith("event: ") and data.startswith("data: "), block
        out.append((name[7:], json.loads(data[6:])))
    return out


def streaming(client, who: str, shop, question: str = "How were sales?", **kw: Any):  # type: ignore[no-untyped-def]
    r = client.post(STREAM, headers=shop[who], json={"question": question, **kw})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return events_of(r)


def names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [n for n, _ in events]


def said(events: list[tuple[str, dict[str, Any]]]) -> str:
    return "".join(d["text"] for n, d in events if n == "text")


# --------------------------------------------------------------------------- the pieces
def test_an_answer_is_cut_into_sentences_that_join_back_exactly() -> None:
    answer = "Sales were KES 1,250.00 today. That is up 3.5% on last week!\nTop items:\n1. Cement\n2. Paint"
    chunks = split_chunks(answer)
    assert "".join(chunks) == answer
    assert chunks[0] == "Sales were KES 1,250.00 today. " and "1,250.00" in chunks[0]
    assert len(chunks) >= 5 and split_chunks("") == []


def test_every_ask_tool_says_in_plain_words_what_it_is_doing() -> None:
    import ziira.modules.intel.hooks  # noqa: F401 - defines the extension points

    tools = list(implementations_of(ask.INTEL_ASK_TOOL))
    assert tools
    for tool in tools:
        for label in (tool.plain_label, tool.plain_label_sw):
            assert label and len(label) < 60, tool.name
            assert not any(ch.isdigit() for ch in label), tool.name


# --------------------------------------------------------------------------- the events
def test_the_chat_tells_what_it_is_doing_then_the_answer_sentence_by_sentence_then_the_evidence(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()),
                           FakeLlm.say("Head office made 1 sale. It was worth 116.00 in total.")])
    events = streaming(client, "manager", shop)
    order = names(events)
    assert order[0] == "status" and order[-1] == "done" and order[-2] == "sources"
    statuses = [d["text"] for n, d in events if n == "status"]
    assert statuses == ["Reading your question", "Looking at your sales", "Putting the answer together"]
    assert order.count("text") == 2 and said(events) == "Head office made 1 sale. It was worth 116.00 in total."
    assert order.index("text") > max(i for i, n in enumerate(order) if n == "status")
    sources = events[-2][1]["sources"]
    assert sources[0]["tool"] == "pos_sales_summary" and sources[0]["rows"][0]["sales_total"] == "116.00"
    done = events[-1][1]
    assert done["flagged"] is False and done["withheld"] is False and done["session_id"] and done["message_id"]
    stored = client.get(f"{INTEL}/ask/sessions/{done['session_id']}", headers=shop["manager"]).json()["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["content"] == "Head office made 1 sale. It was worth 116.00 in total."


def test_status_words_follow_the_language(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("Mauzo yalikuwa 116.00.")])
    events = streaming(client, "manager", shop, language="sw")
    assert [d["text"] for n, d in events if n == "status"] == [
        "Nasoma swali lako", "Naangalia mauzo yako", "Naandaa jibu"]


def test_a_sentence_with_a_figure_that_is_not_in_the_data_is_never_released(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()),
                           FakeLlm.say("Head office made 1 sale. Profit was 999,999.00 this week. "
                                       "The total was 116.00.")])
    events = streaming(client, "manager", shop)
    shown = said(events)
    assert "999" not in shown and "Head office made 1 sale." in shown and "The total was 116.00." in shown
    assert "could not be verified" in shown
    done = events[-1][1]
    assert done["flagged"] is True and done["withheld"] is True
    stored = client.get(f"{INTEL}/ask/sessions/{done['session_id']}", headers=shop["manager"]).json()["messages"][1]
    assert "999" not in stored["content"] and stored["flagged"] is True


def test_the_plain_endpoint_still_keeps_the_whole_answer_with_the_note(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("Profit was 999,999.00.")])
    body = client.post(f"{INTEL}/ask", headers=shop["manager"], json={"question": "Profit?"}).json()
    assert body["answer"].startswith("Profit was 999,999.00.") and body["flagged"] is True


# --------------------------------------------------------------------------- refusals
def test_refusals_arrive_as_one_error_event_in_plain_words(client, shop) -> None:  # type: ignore[no-untyped-def]
    events = streaming(client, "manager", shop)                              # the assistant is off
    assert names(events) == ["error"] and events[0][1]["reason"] == "not_enabled"
    assert "switched off" in events[0][1]["message"] and "ai_" not in events[0][1]["message"]
    sw = streaming(client, "manager", shop, language="sw")
    assert sw[0][1]["message"].startswith("Msaidizi")
    enable(client, shop, monthly_token_limit=0)
    assert streaming(client, "manager", shop)[0][1]["reason"] == "budget"
    enable(client, shop, ask=False)
    assert streaming(client, "manager", shop)[0][1]["reason"] == "purpose_off"
    assert FakeLlm.calls == []


def test_no_consent_is_an_error_event(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import company_settings

    client.put(f"{INTEL}/ai/settings", headers=shop["owner"], json={"company_id": str(shop["company_id"]),
                                                                    "enabled": False})
    with system(shop) as s:                                  # the setting alone, with no consent record, is not enough
        company_settings.update_settings(s, shop["company_id"], {"ai_enabled": True})
    events = streaming(client, "manager", shop)
    assert names(events) == ["error"] and events[0][1]["reason"] == "no_consent"


def test_a_provider_failure_is_an_error_event_and_nothing_is_stored(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.append(LlmError("The AI provider answered 500 (boom)", retryable=True, status=500))
    events = streaming(client, "manager", shop)
    assert names(events) == ["status", "error"] and events[-1][1]["reason"] == "provider_failed"
    assert "boom" not in events[-1][1]["message"]
    assert client.get(f"{INTEL}/ask/sessions", headers=shop["manager"]).json() == []


def test_someone_who_may_not_ask_gets_403_before_any_stream_starts(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    assert client.post(STREAM, headers=shop["cashier"], json={"question": "How were sales?"}).status_code == 403
    assert client.post(STREAM, headers=shop["manager"], json={"question": "   "}).status_code in (200, 422)
    blank = client.post(STREAM, headers=shop["manager"], json={"question": "   "})
    if blank.status_code == 200:
        assert names(events_of(blank)) == ["error"]
    assert client.post(STREAM, json={"question": "x"}).status_code == 401


# --------------------------------------------------------------------------- scope, history, speed
def test_a_branch_manager_gets_only_their_branchs_numbers_in_the_stream(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("No sales at your branch.")])
    events = streaming(client, "jujamgr", shop, "How did Head office do?")
    sources = events[-2][1]["sources"]
    assert all(r["branch"] != "Head office" for r in sources[0]["rows"])
    assert "116.00" not in json.dumps(events)


def test_a_follow_up_carries_the_conversation_so_far(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("It was worth 116.00."),
                           FakeLlm.say("Nothing new, still 116.00.")])
    first = streaming(client, "manager", shop, "What did we sell today?")
    sid = first[-1][1]["session_id"]
    FakeLlm.calls.clear()
    second = streaming(client, "manager", shop, "And last week?", session_id=sid)
    sent = FakeLlm.calls[0]["messages"]
    assert [m.role for m in sent] == ["user", "assistant", "user"]
    assert sent[0].text == "What did we sell today?" and sent[1].text == "It was worth 116.00."
    assert sent[2].text == "And last week?"
    assert second[-1][1]["session_id"] == sid and said(second) == "Nothing new, still 116.00."
    assert second[-1][1]["flagged"] is False                       # 116.00 came from the earlier, checked answer
    assert len(client.get(f"{INTEL}/ask/sessions/{sid}", headers=shop["manager"]).json()["messages"]) == 4
    other = client.post(STREAM, headers=shop["fm2"], json={"question": "x?", "session_id": sid})
    assert names(events_of(other)) == ["error"]                    # not their conversation


class SlowTool(AskTool):
    name = "test_slow_tool"
    description = "Waits, for the tests"
    parameters = {"type": "object", "properties": {"n": {"type": "integer"}}}
    permissions = SALES_PERMISSIONS
    plain_label = "Counting slowly"
    plain_label_sw = "Nahesabu polepole"
    runs: list[int] = []
    threads: set[int] = set()

    def run(self, session, context, params):  # type: ignore[no-untyped-def]
        type(self).threads.add(threading.get_ident())
        type(self).runs.append(int(params.get("n", 0)))
        time.sleep(0.4)
        return {"rows": [{"n": int(params.get("n", 0))}]}


@pytest.fixture
def slow_tool(shop):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401

    point = extensions._points[ask.INTEL_ASK_TOOL]
    extensions._add_implementation(point, "intel", SlowTool)
    SlowTool.runs, SlowTool.threads = [], set()
    yield SlowTool
    point.implementations.remove(("intel", SlowTool))


def test_different_tools_in_one_round_run_at_the_same_time_and_identical_ones_run_once(client, shop, slow_tool) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    FakeLlm.script.extend([
        FakeLlm.tool("test_slow_tool", {"n": 1}, ("test_slow_tool", {"n": 2}), ("test_slow_tool", {"n": 3}),
                     ("test_slow_tool", {"n": 3})),
        FakeLlm.tool("test_slow_tool", {"n": 1}),                  # an earlier round's call is not run again
        FakeLlm.say("Done.")])
    started = time.monotonic()
    events = streaming(client, "manager", shop)
    elapsed = time.monotonic() - started
    assert sorted(slow_tool.runs) == [1, 2, 3], slow_tool.runs
    assert len(slow_tool.threads) == 3 and elapsed < 1.1          # three waits of 0.4s at once, not one after another
    assert said(events) == "Done."
    tools = client.get(f"{INTEL}/ask/sessions/{events[-1][1]['session_id']}",
                       headers=shop["manager"]).json()["messages"][1]["tools_used"]
    assert [t.get("cached", False) for t in tools] == [False, False, False, True, True]
    assert [s["params"]["n"] for s in events[-2][1]["sources"]] == [1, 2, 3]


def test_no_database_transaction_is_open_while_the_model_works_in_the_stream(client, shop) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    seen: list[bool] = []

    def check(call: dict[str, Any]) -> LlmReply:
        seen.append(no_transaction_open(shop))
        return FakeLlm.tool("inventory_low_stock", {}) if len(seen) < 2 else FakeLlm.say("Nothing is low.")

    FakeLlm.script.extend([check, check])
    assert said(streaming(client, "manager", shop)) == "Nothing is low."
    assert seen == [True, True]


def test_the_first_status_arrives_before_the_model_is_asked(shop, client) -> None:  # type: ignore[no-untyped-def]
    enable(client, shop)
    with system(shop) as s:
        user = s.execute(text("select id from kernel.app_user where email = 'owner@example.test' or true "
                              "order by created_at limit 1")).scalar_one()
    context = RequestContext(tenant_id=shop["tenant_id"], user_id=user, channel="web", all_permissions=True)
    FakeLlm.delay = 0.5
    try:
        FakeLlm.script.extend([FakeLlm.tool("pos_sales_summary", window()), FakeLlm.say("It was 116.00.")])
        started = time.monotonic()
        events = ask_stream.stream(replace(context), "How were sales?", company_id=shop["company_id"],
                                   session_id=None, language="en", pause=0)
        first = next(events)
        first_at = time.monotonic() - started
        rest = list(events)
    finally:
        FakeLlm.delay = 0.0
    assert first["event"] == "status" and first_at < 0.3, first_at
    assert [e["event"] for e in rest][-1] == "done"
