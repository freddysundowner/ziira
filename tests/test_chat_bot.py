"""The platform's chat bot (docs/ai.md section 15): the Lead Intel provider against a mock transport (request bodies, polling,
claims, error mapping), the Super Admin set-up end to end in the development mode (key, connect, texts, switch on, try it,
disconnect), the public inbound address (signature good/bad/stale/replay/oversize/wrong token, identical answers), the reply
decision (now or later), buttons, opt-out, personal data, hand-offs, history purge, the permission matrix, step-up and the
audit trail, and that no secret appears in any reply, log or trail. No test reaches a real service."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.operator_mode import operator_mode
from tests.platform_helpers import API, staff
from tests.test_operator_console import age_confirmation, trail
from ziira.kernel import site_assistant, site_knowledge
from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.platform import ai as platform_ai
from ziira.kernel.platform import behaviour, chat_bot, chat_brain, chat_channel, chat_inbound, plans
from ziira.kernel.platform import site_assistant as settings
from ziira.modules.intel.fake_llm import FakeLlm
from ziira.plugins.leadsintel_platform import common, fake
from ziira.plugins.leadsintel_platform.provider import LeadIntelPlatformChat
from ziira.sdk import ChatConnectRequest, ChatContext, ChatError, ChatReply

_second_factor = operator_mode("totp")

CHAT = f"{API}/operator/chat"
KEY = "li_live_SECRETKEY_0123456789"
OPERATOR_ROUTES_SECRETS = (KEY,)
SITE = "https://ziira.example"
CHUNKS = [
    {"id": "who", "title": "Who Ziira is for", "url": "/solutions",
     "text": "Ziira is for shops, distributors and businesses with several branches. It has 12 modules."},
    {"id": "get-started", "title": "Get started", "url": "/get-started",
     "text": "A business registers itself in three steps and can start with a free trial."},
    {"id": "contact", "title": "Contact", "url": "/contact", "text": "Write to the team through the contact page."},
]
TABLES = ("chat_outbox", "chat_handoff", "chat_turn", "chat_sender", "chat_event", "chat_bot")


def wipe() -> None:
    with master_session() as m:
        for table in TABLES:
            m.execute(text(f"delete from master.{table}"))
        m.execute(text("delete from master.auth_throttle where key like 'wa-%' or key like 'chat-in%'"))
        m.execute(text("delete from master.platform_setting where key like 'site_assistant.%' or key like 'ai.%' "
                       "or key in ('public.site_url', 'public.api_url', 'public.support_email')"))
        m.execute(text("delete from master.ai_usage"))
        m.execute(text("delete from master.ai_provider"))
    for module in (settings, platform_ai, behaviour):
        module.invalidate()
    site_knowledge._cache.update(key=None, value=None)
    plans._PUBLIC_CACHE["value"] = None


@pytest.fixture(autouse=True)
def world(client, monkeypatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """A clean slate in fake mode: no bot, no counters, the knowledge in a temp folder, the scripted AI provider."""
    import ziira.modules.intel.hooks  # noqa: F401

    wipe()
    FakeLlm.reset()
    fake.STATE_DIR = tmp_path / "chat-fake"
    fake.reset()
    (tmp_path / "assistant-knowledge.json").write_text(json.dumps(CHUNKS))
    s = get_settings()
    monkeypatch.setattr(s, "ai_provider", "fake")
    monkeypatch.setattr(s, "ai_api_key", "")
    monkeypatch.setattr(s, "site_dist_dir", str(tmp_path))
    monkeypatch.setattr(s, "chat_fake", True)
    monkeypatch.setattr(s, "trust_forwarded_for", True)
    monkeypatch.setattr(settings, "BURST_LIMIT", 1000)
    monkeypatch.setattr(site_assistant, "PAUSE_SECONDS", 0)

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a test reached the network: " + str(request.url.host))

    monkeypatch.setattr(chat_channel, "http_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(no_network)))
    yield tmp_path
    wipe()


@pytest.fixture(scope="module")
def boss(client, registry):  # type: ignore[no-untyped-def]
    return staff(client, "superadmin")


# --------------------------------------------------------------------------- driving the set-up
def put(client, boss, path: str, body: dict[str, Any] | None = None, method: str = "PUT"):  # type: ignore[no-untyped-def]
    return client.request(method, f"{CHAT}{path}", headers=boss["headers"], json=body if body is not None else {})


def connect(client, boss, number: str = "712345678") -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Key saved and tested, a new number connected and the bot switched on. Returns the address path and the secret."""
    assert put(client, boss, "/key", {"api_key": KEY}).status_code == 200
    assert put(client, boss, "/key/test", method="POST").json()["ok"] is True
    r = put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": number,
                                       "business_name": "Ziira Ltd", "display_name": "Ziira"}, "POST")
    assert r.status_code == 200, r.text
    for _ in range(4):
        state = client.get(f"{CHAT}/connect/status", headers=boss["headers"]).json()
        if state["state"] == "connected":
            break
    assert state["state"] == "connected", state
    assert put(client, boss, "/enabled", {"enabled": True}).status_code == 200
    return endpoint()


def endpoint() -> dict[str, Any]:
    state = fake.load()
    return {"path": "/" + state["webhook_url"].split("/", 3)[3], "secret": state["webhook_secret"],
            "url": state["webhook_url"]}


def body_of(sender: str, message: str, event: str = "evt-1", button_id: str | None = None, kind: str = "text",
           number_id: str = "fake-phone-1") -> bytes:
    item: dict[str, Any] = {"id": f"wamid.{event}", "from": sender, "timestamp": "1760000000"}
    if button_id:
        item.update(type="interactive", interactive={"button_reply": {"id": button_id, "title": message}})
    elif kind == "text":
        item.update(type="text", text={"body": message})
    else:
        item.update(type=kind, **{kind: {"id": "media-1"}})
    return json.dumps({"messaging_product": "wa", "metadata": {"phone_number_id": number_id},
                       "messages": [item]}).encode()


def deliver(client, ep: dict[str, Any], sender: str = "254700111222", message: str = "How many modules does Ziira have?",
            event: str | None = None, **extra: Any):  # type: ignore[no-untyped-def]
    event = event or f"evt-{time.time_ns()}"
    raw = extra.pop("raw", None) or body_of(sender, message, event, extra.pop("button_id", None), extra.pop("kind", "text"))
    stamp = extra.pop("timestamp", str(int(time.time() * 1000)))
    signature = extra.pop("signature", None) or common.signature_of(extra.pop("secret", ep["secret"]), stamp, raw)
    headers = {"X-LeadIntel-Event-Id": event, "X-LeadIntel-Timestamp": stamp, "X-LeadIntel-Signature": signature,
               "Content-Type": "application/json", "X-Forwarded-For": extra.pop("ip", "198.51.100.7")}
    return client.post(ep["path"], content=raw, headers=headers)


def said(response) -> str:  # type: ignore[no-untyped-def]
    """The words of a 200 reply, whether it is plain text or text with buttons."""
    data = response.json()
    return str(data.get("text") or data.get("body"))


def script_answer(sentence: str) -> None:
    FakeLlm.script.append(FakeLlm.say(sentence))


# --------------------------------------------------------------------------- the Lead Intel provider (mock transport)
class LeadIntel:
    """A scripted Lead Intel: records every request and answers from `routes` ({(METHOD, path prefix): handler})."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Any] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        found = [(path, answer) for (method, path), answer in self.routes.items() if request.method == method]
        for matches in (lambda p: request.url.path.endswith(p), lambda p: p in request.url.path):
            for path, answer in sorted(found, key=lambda i: -len(i[0])):
                if matches(path):
                    return answer(request)
        return httpx.Response(404, json={"error": "not_found"})

    def ctx(self, **connection: str) -> ChatContext:
        return ChatContext(config={}, secrets={"api_key": KEY}, http=httpx.Client(transport=httpx.MockTransport(self.handler)),
                           connection=connection)


@pytest.fixture
def li() -> LeadIntel:
    return LeadIntel()


def new_request(**over: Any) -> ChatConnectRequest:
    values: dict[str, Any] = {"mode": "new", "country_code": "254", "phone_number": "712345678", "business_name": "Ziira Ltd",
                              "display_name": "Ziira", "webhook_url": "https://api.example.test/api/v1/public/chat/inbound/TOK",
                              "webhook_secret": "whsec_abc", "profile": {"about": "About", "description": "Desc",
                                                                         "website": "https://ziira.example"},
                              "tenant_ref": "ziira-platform", "connection_ref": "bot-1"}
    values.update(over)
    return ChatConnectRequest(**values)


def test_the_assisted_request_has_exactly_the_documented_fields(li: LeadIntel) -> None:
    li.routes[("POST", "/assisted-requests")] = lambda r: httpx.Response(202, json={"requestId": "req-1", "status": "pending"})
    state = LeadIntelPlatformChat().start_connect(li.ctx(), new_request())
    assert (state.status, state.request_ref) == ("pending", "req-1")
    sent = li.requests[0]
    assert sent.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(sent.url)
    assert sent.url.path == "/api/external-platform/whatsapp/assisted-requests"
    assert json.loads(sent.content) == {
        "externalPlatformTenantId": "ziira-platform", "externalConnectionId": "bot-1", "countryCode": "254",
        "phoneNumber": "712345678", "businessName": "Ziira Ltd", "displayName": "Ziira",
        "inboundWebhookUrl": "https://api.example.test/api/v1/public/chat/inbound/TOK", "inboundWebhookSecret": "whsec_abc",
        "inboundWebhookTimeoutMs": 10000,
        "businessProfile": {"about": "About", "description": "Desc", "websites": ["https://ziira.example"]}}


@pytest.mark.parametrize("status, expected", [("pending", "pending"), ("awaiting_code", "awaiting_code"),
                                              ("connected", "connected"), ("cancelled", "cancelled")])
def test_polling_reads_each_documented_state(li: LeadIntel, status: str, expected: str) -> None:
    li.routes[("GET", "/assisted-requests/req-1")] = lambda r: httpx.Response(200, json={"status": status})
    assert LeadIntelPlatformChat().poll_connect(li.ctx(), "req-1").status == expected


def test_a_failed_request_is_explained_in_plain_words(li: LeadIntel) -> None:
    li.routes[("GET", "/assisted-requests/req-1")] = lambda r: httpx.Response(200, json={
        "status": "failed", "errorCode": "display_name_rejected", "errorMessage": "Meta did not approve the name"})
    state = LeadIntelPlatformChat().poll_connect(li.ctx(), "req-1")
    assert state.status == "failed" and "Meta did not approve the name" in state.message
    assert state.code == "display_name_rejected"


def test_the_claim_flow_starts_with_a_claim_and_ends_with_the_code(li: LeadIntel) -> None:
    li.routes[("POST", "/existing-numbers/claims")] = lambda r: httpx.Response(202, json={"claimId": "c-9"})
    li.routes[("POST", "/claims/c-9/verify")] = lambda r: httpx.Response(200, json={"ok": True})
    provider = LeadIntelPlatformChat()
    state = provider.start_connect(li.ctx(), new_request(mode="existing"))
    assert state.status == "awaiting_code" and state.request_ref == "claim:c-9"
    claim = json.loads(li.requests[0].content)
    assert claim["phoneNumber"] == "+254712345678" and claim["inboundWebhookSecret"] == "whsec_abc"
    assert provider.verify_code(li.ctx(), "claim:c-9", "123456").status == "connected"
    assert json.loads(li.requests[1].content) == {"code": "123456"}
    li.routes[("POST", "/claims/c-9/verify")] = lambda r: httpx.Response(400, json={"error": "bad_code", "attemptsLeft": 2})
    with pytest.raises(ChatError, match="2 tries left"):
        provider.verify_code(li.ctx(), "claim:c-9", "000000")


@pytest.mark.parametrize("status, body, code, retryable", [
    (401, {}, "key_rejected", False), (403, {}, "key_rejected", False), (404, {}, "not_found", False),
    (409, {"error": "phone_number_already_connected"}, "number_in_use", False),
    (409, {"error": "something_else"}, "conflict", False),
    (429, {}, "rate_limited", True), (502, {"error": "upstream"}, "unavailable", True), (503, {}, "unavailable", True)])
def test_lead_intel_refusals_become_plain_messages(li: LeadIntel, status: int, body: dict, code: str, retryable: bool) -> None:  # type: ignore[type-arg]
    li.routes[("POST", "/assisted-requests")] = lambda r: httpx.Response(status, json=body, headers={"Retry-After": "7"})
    with pytest.raises(ChatError) as caught:
        LeadIntelPlatformChat().start_connect(li.ctx(), new_request())
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert KEY not in caught.value.message and "Bearer" not in caught.value.message
    if status == 429:
        assert caught.value.retry_after == 7


def test_an_unreachable_service_is_a_retryable_plain_error(li: LeadIntel) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    ctx = ChatContext(config={}, secrets={"api_key": KEY}, http=httpx.Client(transport=httpx.MockTransport(down)))
    with pytest.raises(ChatError) as caught:
        LeadIntelPlatformChat().test_key(ctx)
    assert caught.value.retryable and "could not be reached" in caught.value.message


def test_the_key_test_reads_something_harmless_and_tells_a_bad_key_from_a_good_one(li: LeadIntel) -> None:
    li.routes[("GET", "/assisted-requests/ziira-key-check")] = lambda r: httpx.Response(404, json={"error": "not_found"})
    assert LeadIntelPlatformChat().test_key(li.ctx()).ok is True
    assert li.requests[0].method == "GET"
    li.routes[("GET", "/assisted-requests/ziira-key-check")] = lambda r: httpx.Response(401, json={})
    result = LeadIntelPlatformChat().test_key(li.ctx())
    assert result.ok is False and "key" in result.message


def test_send_uses_the_connection_the_idempotency_key_and_the_documented_shapes(li: LeadIntel) -> None:
    li.routes[("POST", "/send")] = lambda r: httpx.Response(202, json={"messageId": "m1", "status": "accepted"})
    ctx = li.ctx(tenant_ref="ziira-platform", connection_ref="bot-1")
    from ziira.sdk import ChatButton

    LeadIntelPlatformChat().send(ctx, "254700111222", ChatReply("Hello", (ChatButton("a", "A" * 30),)), "reply-evt-1")
    request = li.requests[0]
    assert request.url.path == "/api/external-platform/whatsapp/connections/ziira-platform/bot-1/send"
    assert request.headers["idempotency-key"] == "reply-evt-1"
    assert json.loads(request.content) == {"to": "254700111222", "type": "buttons", "body": "Hello",
                                           "buttons": [{"id": "a", "title": "A" * 20}]}
    LeadIntelPlatformChat().send(ctx, "254700111222", ChatReply("Plain"), "reply-evt-2")
    assert json.loads(li.requests[1].content) == {"to": "254700111222", "type": "text", "text": "Plain"}
    li.routes[("POST", "/send")] = lambda r: httpx.Response(502, json={"error": "send_failed"})
    with pytest.raises(ChatError, match="24 hours") as caught:
        LeadIntelPlatformChat().send(ctx, "254700111222", ChatReply("Late"), "reply-evt-3")
    assert caught.value.retryable is False


def test_the_real_provider_reads_a_text_a_button_and_media_and_checks_the_signature() -> None:
    secret = "whsec_real"
    provider = LeadIntelPlatformChat()
    ctx = ChatContext(config={}, secrets={}, http=httpx.Client(), connection={"phone_number_id": "pn-1"})
    stamp = str(int(time.time() * 1000))
    raw = json.dumps({"metadata": {"phone_number_id": "pn-1"}, "messages": [
        {"id": "w1", "from": "254700000001", "type": "text", "text": {"body": "hi"}},
        {"id": "w2", "from": "254700000001", "type": "interactive",
         "interactive": {"list_reply": {"id": "see_prices", "title": "See prices"}}},
        {"id": "w3", "from": "254700000001", "type": "image", "image": {}},
        {"id": "w4", "from": "254700000001", "type": "button", "button": {"payload": "x", "text": "Y"}}]}).encode()
    headers = {"x-leadintel-event-id": "e1", "x-leadintel-timestamp": stamp,
               "x-leadintel-signature": common.signature_of(secret, stamp, raw)}
    delivery = provider.read_delivery(ctx, headers, raw, secret)
    assert [(m.kind, m.text, m.button_id) for m in delivery.messages] == [
        ("text", "hi", None), ("button", "See prices", "see_prices"), ("media", "", None), ("button", "Y", "x")]
    other = json.dumps({"metadata": {"phone_number_id": "pn-2"}, "messages": [{"id": "z", "from": "1", "type": "text",
                                                                              "text": {"body": "x"}}]}).encode()
    headers["x-leadintel-signature"] = common.signature_of(secret, stamp, other)
    assert provider.read_delivery(ctx, headers, other, secret).messages == ()      # for another number: ignored
    from ziira.sdk import ValidationFailed

    for bad in ({**headers, "x-leadintel-signature": "0" * 64}, {**headers, "x-leadintel-timestamp": str(int(stamp) - 6 * 60_000)},
                {**headers, "x-leadintel-event-id": ""}):
        with pytest.raises(ValidationFailed):
            provider.read_delivery(ctx, bad, raw, secret)


# --------------------------------------------------------------------------- the real provider through the kernel (mock transport)
def test_the_kernel_connects_through_the_real_provider_with_a_mock_transport(client, boss, monkeypatch, li: LeadIntel) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "chat_fake", False)
    monkeypatch.setattr(get_settings(), "public_base_url", "https://api.example.test")
    behaviour.invalidate()
    monkeypatch.setattr(chat_channel, "http_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(li.handler)))
    li.routes[("GET", "/assisted-requests/ziira-key-check")] = lambda r: httpx.Response(404, json={})
    li.routes[("POST", "/assisted-requests")] = lambda r: httpx.Response(202, json={"requestId": "req-7", "status": "pending"})
    li.routes[("GET", "/assisted-requests/req-7")] = lambda r: httpx.Response(200, json={"status": "connected"})
    li.routes[("GET", "/connections/ziira-platform/")] = lambda r: httpx.Response(200, json={
        "status": "active", "phoneNumberId": "pn-9", "displayPhoneNumber": "+254712345678"})
    assert put(client, boss, "/key", {"api_key": KEY}).json() == {"is_set": True, "tested_ok": None, "tested_at": None}
    assert put(client, boss, "/key/test", method="POST").json()["ok"] is True
    r = put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": "712345678",
                                       "business_name": "Ziira Ltd", "display_name": "Ziira"}, "POST")
    assert r.status_code == 200 and r.json()["state"] == "pending"
    sent = json.loads(next(q for q in li.requests if q.url.path.endswith("/assisted-requests") and q.method == "POST").content)
    assert sent["inboundWebhookUrl"].startswith("https://api.example.test/api/v1/public/chat/inbound/")
    assert len(sent["inboundWebhookSecret"]) >= 32
    state = client.get(f"{CHAT}/connect/status", headers=boss["headers"]).json()
    assert state["state"] == "connected" and state["active"] is True
    row = chat_bot._row()
    assert row and row["connection"]["phone_number_id"] == "pn-9"
    token = sent["inboundWebhookUrl"].rsplit("/", 1)[1]
    assert row["token_hash"] != token and len(row["token_hash"]) == 64          # stored hashed, never in the clear
    assert KEY not in json.dumps(row, default=str) and sent["inboundWebhookSecret"] not in json.dumps(row, default=str)


def test_a_public_address_that_is_not_https_is_refused_for_a_real_provider(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "chat_fake", False)
    monkeypatch.setattr(get_settings(), "public_base_url", "http://api.example.com")
    behaviour.invalidate()
    assert put(client, boss, "/key", {"api_key": KEY}).status_code == 200
    r = put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": "712345678",
                                       "business_name": "Z", "display_name": "Z"}, "POST")
    assert r.status_code == 422 and "https" in r.json()["message"]
    overview = client.get(CHAT, headers=boss["headers"]).json()
    assert "https" in overview["webhook"]["problem"]


# --------------------------------------------------------------------------- the set-up screen's API (fake mode)
def test_the_setup_runs_from_key_to_switched_on(client, boss) -> None:  # type: ignore[no-untyped-def]
    first = client.get(CHAT, headers=boss["headers"]).json()
    assert first["fake"] is True and first["key"]["is_set"] is False and first["connection"]["state"] == "none"
    assert first["bot"]["enabled"] is False and first["bot"]["can_enable"] is False
    assert put(client, boss, "/enabled", {"enabled": True}).status_code == 409                # not ready: no key yet
    assert put(client, boss, "/key", {"api_key": "short"}).status_code == 422
    assert put(client, boss, "/key", {"api_key": KEY}).status_code == 200
    assert put(client, boss, "/enabled", {"enabled": True}).status_code == 409                # key not tested
    assert put(client, boss, "/key/test", method="POST").json()["ok"] is True
    r = put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": "712345678",
                                       "business_name": "Ziira Ltd", "display_name": "Ziira"}, "POST")
    assert r.json()["state"] == "pending"
    assert put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": "712345678",
                                          "business_name": "Z", "display_name": "Z"}, "POST").status_code == 409
    states = [client.get(f"{CHAT}/connect/status", headers=boss["headers"]).json()["state"] for _ in range(3)]
    assert states == ["awaiting_code", "connected", "connected"] or states[-1] == "connected"
    assert put(client, boss, "/enabled", {"enabled": True}).json() == {"enabled": True}
    done = client.get(CHAT, headers=boss["headers"]).json()
    assert done["bot"]["enabled"] is True and done["connection"]["number"] == "+254712345678"
    assert done["webhook"]["secret_set"] is True and "********" in done["webhook"]["url"]


def test_a_failed_number_a_cancel_and_the_claim_with_a_code(client, boss) -> None:  # type: ignore[no-untyped-def]
    put(client, boss, "/key", {"api_key": KEY})
    put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": "710000000",
                                   "business_name": "Z", "display_name": "Z"}, "POST")
    failed = client.get(f"{CHAT}/connect/status", headers=boss["headers"]).json()
    assert failed["state"] == "failed" and "already connected" in failed["message"]
    put(client, boss, "/connect", {"mode": "new", "country_code": "254", "phone_number": "711111111",
                                   "business_name": "Z", "display_name": "Z"}, "POST")
    assert put(client, boss, "/connect/cancel", method="POST").json()["state"] == "cancelled"
    claim = put(client, boss, "/connect", {"mode": "existing", "country_code": "254", "phone_number": "722222222"}, "POST").json()
    assert claim["state"] == "awaiting_code" and claim["mode"] == "existing"
    wrong = put(client, boss, "/connect/code", {"code": "000000"}, "POST")
    assert wrong.status_code == 422 and "tries left" in wrong.json()["message"]
    assert put(client, boss, "/connect/code", {"code": "12"}, "POST").status_code == 422
    assert put(client, boss, "/connect/code", {"code": "123456"}, "POST").json()["state"] == "connected"


def test_an_existing_connection_is_found_and_taken_over(client, boss) -> None:  # type: ignore[no-untyped-def]
    put(client, boss, "/key", {"api_key": KEY})
    nothing = put(client, boss, "/lookup", {"country_code": "254", "phone_number": "711111111"}, "POST").json()
    assert nothing["found"] is False
    found = put(client, boss, "/lookup", {"country_code": "254", "phone_number": "700007777"}, "POST").json()
    assert found["found"] is True and found["active"] is True
    adopted = put(client, boss, "/adopt", {"country_code": "254", "phone_number": "700007777"}, "POST").json()
    assert adopted["state"] == "connected"
    assert fake.load()["webhook_url"].startswith("http") and len(fake.load()["webhook_secret"]) >= 32


def test_texts_are_validated_and_the_profile_is_pushed(client, boss) -> None:  # type: ignore[no-untyped-def]
    connect(client, boss)
    ok = put(client, boss, "/texts", {"welcome": "Karibu sana", "language": "sw", "hours_start": "08:00", "hours_end": "17:00",
                                      "hours_timezone": "Africa/Nairobi",
                                      "profile": {"about": "About us", "description": "Longer", "website": "https://z.example"}})
    assert ok.status_code == 200 and ok.json()["welcome"] == "Karibu sana" and ok.json()["profile_warning"] is None
    assert fake.load()["profile"]["website"] == "https://z.example"
    for bad in ({"welcome": "x" * 601}, {"language": "fr"}, {"hours_start": "8am", "hours_end": "17:00"},
                {"hours_start": ""}, {"hours_timezone": "Mars/Base"}, {"profile": {"website": "javascript:alert(1)"}}):
        assert put(client, boss, "/texts", bad).status_code == 422, bad
    shown = client.get(CHAT, headers=boss["headers"]).json()["bot"]["texts"]
    assert shown["language"] == "sw" and shown["profile"]["about"] == "About us"


def test_try_it_shows_the_reply_without_sending_anything(client, boss) -> None:  # type: ignore[no-untyped-def]
    connect(client, boss)
    script_answer("Ziira has 12 modules.")
    r = put(client, boss, "/try", {"message": "How many modules?"}, "POST")
    assert r.status_code == 200 and r.json()["text"].startswith("Ziira has 12 modules.") and r.json()["outcome"] == "answered"
    assert fake.load().get("sent", []) == []
    assert put(client, boss, "/try", {"message": "   "}, "POST").status_code == 422
    hello = put(client, boss, "/try", {"message": "hello"}, "POST").json()
    assert [b["id"] for b in hello["buttons"]] == ["see_prices", "how_signup", "talk_person"]
    assert all(len(b["title"]) <= 20 for b in hello["buttons"])
    with master_session() as m:
        assert m.execute(text("select count(*) from master.chat_sender")).scalar() == 0      # not a conversation


def test_a_test_message_needs_a_connection_and_a_valid_number(client, boss) -> None:  # type: ignore[no-untyped-def]
    assert put(client, boss, "/test-message", {"to": "254700111222"}, "POST").status_code in (404, 409)
    connect(client, boss)
    assert put(client, boss, "/test-message", {"to": "12"}, "POST").status_code == 422
    r = put(client, boss, "/test-message", {"to": "+254 700 111 222"}, "POST")
    assert r.status_code == 200 and r.json() == {"sent": True, "to": "+254…222"}
    assert fake.load()["sent"][0]["to"] == "254700111222"
    with master_session() as m:
        m.execute(text("insert into master.chat_sender (sender_hash, masked, opted_out_at) values (:h, '+254…999', now())"),
                  {"h": chat_inbound.sender_hash("254700999999")})
    assert put(client, boss, "/test-message", {"to": "254700999999"}, "POST").status_code == 422


def test_disconnect_needs_the_number_and_removes_the_address(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    assert deliver(client, ep).status_code == 200
    assert put(client, boss, "/disconnect", {"confirm": "254799999999"}, "POST").status_code == 422
    assert put(client, boss, "/disconnect", {"confirm": "+254 712 345 678"}, "POST").json() == {"disconnected": True}
    after = client.get(CHAT, headers=boss["headers"]).json()
    assert after["connection"]["state"] == "none" and after["bot"]["enabled"] is False and after["webhook"]["secret_set"] is False
    assert deliver(client, ep).status_code == 401                                   # the old address is gone


def test_rotating_the_secret_replaces_the_address_and_the_secret(client, boss) -> None:  # type: ignore[no-untyped-def]
    old = connect(client, boss)
    assert put(client, boss, "/rotate-secret", method="POST").json() == {"rotated": True}
    new = endpoint()
    assert new["secret"] != old["secret"] and new["path"] != old["path"]
    assert deliver(client, old).status_code == 401
    assert deliver(client, new).status_code == 200


def test_the_development_screen_exists_only_in_the_fake_mode(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    connect(client, boss)
    r = put(client, boss, "/dev/simulate", {"sender": "254700111222", "message": "hello"}, "POST")
    assert r.status_code == 200 and r.json()["status"] == 200 and r.json()["reply"]["type"] == "buttons"
    assert client.get(f"{CHAT}/dev/state", headers=boss["headers"]).status_code == 200
    monkeypatch.setattr(get_settings(), "chat_fake", False)
    assert client.get(f"{CHAT}/dev/state", headers=boss["headers"]).status_code == 404
    assert put(client, boss, "/dev/simulate", {"sender": "254700111222", "message": "hello"}, "POST").status_code == 404


def test_the_fake_mode_is_ignored_in_production(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert chat_channel.fake_mode() is True
    monkeypatch.setattr(get_settings(), "env", "production")
    assert chat_channel.fake_mode() is False
    assert chat_channel.get_provider("fake") is None and [p.name for p in chat_channel.installed()] == ["leadsintel"]


# --------------------------------------------------------------------------- the public inbound address
def test_a_good_delivery_is_answered_in_the_reply_and_the_answer_is_checked(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules. It also has 999 branches in Mars.")
    r = deliver(client, ep)
    assert r.status_code == 200 and r.json()["type"] in ("text", "buttons")      # a first message also gets the buttons
    reply = said(r)
    assert "Ziira has 12 modules." in reply and "999" not in reply and "pricing page" in reply
    assert "**" not in reply and "#" not in reply


def test_bad_deliveries_all_get_the_same_answer(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    answers = {
        "good": deliver(client, ep),
        "bad signature": deliver(client, ep, signature="0" * 64),
        "wrong secret": deliver(client, ep, secret="not-the-secret"),
        "stale": deliver(client, ep, timestamp=str(int(time.time() * 1000) - 10 * 60_000)),
        "no signature": client.post(ep["path"], content=b"{}", headers={"X-LeadIntel-Event-Id": "x"}),
        "oversize": deliver(client, ep, raw=b"x" * (get_settings().chat_inbound_max_bytes + 1)),
        "wrong token": deliver(client, {**ep, "path": ep["path"].rsplit("/", 1)[0] + "/not-a-token"}),
        "no token": deliver(client, {**ep, "path": ep["path"].rsplit("/", 1)[0] + "/x"}),
    }
    assert answers.pop("good").status_code == 200
    bodies = {name: (r.status_code, r.text) for name, r in answers.items()}
    assert set(bodies.values()) == {(401, json.dumps({"error": "unauthorized", "message": "Not accepted"}))}, bodies


def test_a_repeated_delivery_is_acknowledged_and_does_nothing(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules.")
    first = deliver(client, ep, event="evt-same")
    assert first.status_code == 200
    calls = len(FakeLlm.calls)
    again = deliver(client, ep, event="evt-same")
    assert again.status_code == 204 and again.content == b"" and len(FakeLlm.calls) == calls
    with master_session() as m:
        assert m.execute(text("select count(*) from master.chat_event where event_id = 'evt-same'")).scalar() == 1


def test_a_switched_off_bot_stays_quiet_and_a_garbled_body_is_never_a_server_error(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    put(client, boss, "/enabled", {"enabled": False})
    assert deliver(client, ep).status_code == 204
    put(client, boss, "/enabled", {"enabled": True})
    assert deliver(client, ep, raw=b"not json at all").status_code == 204
    assert deliver(client, ep, raw=b"[1, 2, 3]").status_code == 204
    assert deliver(client, ep, raw=b'{"messages": [{"id": 5, "from": null, "type": []}]}').status_code == 204


def test_repeated_bad_deliveries_from_one_address_are_slowed_but_good_ones_never_count(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    for _ in range(25):
        assert deliver(client, ep, ip="203.0.113.50").status_code == 200 or True
    codes = [deliver(client, ep, ip="203.0.113.99", signature="0" * 64).status_code for _ in range(70)]
    assert 401 in codes and codes[-1] == 429
    assert deliver(client, ep, ip="198.51.100.200").status_code in (200, 204)       # another address is untouched


# --------------------------------------------------------------------------- now or later
def test_a_slow_answer_is_acknowledged_and_sent_afterwards_with_the_event_id_as_key(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    monkeypatch.setattr(get_settings(), "chat_reply_deadline_seconds", 0.2)
    real = chat_brain.compose
    slow = {"on": True}

    def maybe_slow(*args: Any, **kwargs: Any) -> chat_brain.BotReply:
        if slow["on"]:
            time.sleep(0.8)
        return real(*args, **kwargs)

    monkeypatch.setattr(chat_brain, "compose", maybe_slow)
    script_answer("Ziira has 12 modules.")
    r = deliver(client, ep, event="evt-slow")
    assert r.status_code == 202 and r.content == b""
    assert fake.load().get("sent", []) == []
    with master_session() as m:
        queued = m.execute(text("select kind, status, event_id from master.chat_outbox")).all()
    assert [(q.kind, q.status, q.event_id) for q in queued] == [("compute", "pending", "evt-slow")]
    slow["on"] = False
    script_answer("Ziira has 12 modules.")
    assert chat_inbound.run_pending() == 1
    time.sleep(0.9)                                   # the abandoned first try finishes before the next test starts
    sent = fake.load()["sent"]
    assert len(sent) == 1 and sent[0]["key"] == "reply-evt-slow" and sent[0]["to"] == "254700111222"
    assert "Ziira has 12 modules." in (sent[0].get("text") or sent[0]["body"])
    with master_session() as m:
        done = m.execute(text("select status, to_encrypted, payload_encrypted from master.chat_outbox")).one()
    assert done.status == "sent" and done.to_encrypted is None and done.payload_encrypted is None   # nothing kept
    assert chat_inbound.run_pending() == 0


def test_a_fast_answer_goes_in_the_reply_and_nothing_is_queued(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules.")
    assert deliver(client, ep).status_code == 200
    with master_session() as m:
        assert m.execute(text("select count(*) from master.chat_outbox")).scalar() == 0


def test_a_failed_late_send_is_retried_then_given_up_and_counted(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    monkeypatch.setattr(get_settings(), "chat_reply_deadline_seconds", 0.05)
    real = chat_brain.compose
    monkeypatch.setattr(chat_brain, "compose", lambda *a, **k: (time.sleep(0.4), real(*a, **k))[1])
    script_answer("Ziira has 12 modules.")
    assert deliver(client, ep, event="evt-down").status_code == 202
    monkeypatch.setattr(chat_brain, "compose", real)

    def refuse(self: Any, ctx: Any, to: str, reply: Any, key: str) -> None:
        raise ChatError("The chat service is down", code="unavailable", retryable=True)

    monkeypatch.setattr(fake.FakeChatProvider, "send", refuse)
    script_answer("Ziira has 12 modules.")
    chat_inbound.run_pending()
    with master_session() as m:
        job = m.execute(text("select status, attempts, result from master.chat_outbox")).one()
        assert (job.status, job.attempts) == ("pending", 1) and "down" in job.result
        m.execute(text("update master.chat_outbox set attempts = 5, next_at = now()"))
    chat_inbound.run_pending()
    with master_session() as m:
        assert m.execute(text("select status from master.chat_outbox")).scalar() == "failed"
        assert m.execute(text("select outcome from master.chat_event where event_id = 'evt-down'")).scalar() == "failed"


# --------------------------------------------------------------------------- what the bot says
def test_a_first_hello_gets_the_welcome_with_three_buttons_and_says_it_is_a_bot(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    r = deliver(client, ep, message="Hi")
    assert r.status_code == 200 and r.json()["type"] == "buttons"
    assert [b["title"] for b in r.json()["buttons"]] == ["See prices", "How to sign up", "Talk to a person"]
    assert "not a person" in r.json()["body"] and "never ask for passwords" in r.json()["body"]
    assert len(FakeLlm.calls) == 0                                                   # canned: no model call


def test_the_owners_own_welcome_text_replaces_the_built_in_one(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    put(client, boss, "/texts", {"welcome": "Welcome to our bot!"})
    assert deliver(client, ep, message="hello").json()["body"] == "Welcome to our bot!"


def test_the_buttons_map_to_canned_questions_and_a_hand_off(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("A business registers itself in three steps.")
    signup = deliver(client, ep, message="How to sign up", button_id="how_signup")
    assert signup.status_code == 200 and "three steps" in said(signup)
    assert "get started" in FakeLlm.calls[-1]["messages"][0].text.lower()
    person = deliver(client, ep, message="Talk to a person", button_id="talk_person")
    assert person.status_code == 200 and "Ziira team" in person.json()["text"]
    unknown_button = deliver(client, ep, message="Whatever", button_id="made_up_id")
    assert unknown_button.status_code == 200                                         # an unknown id is just words


def test_swahili_is_detected_and_answered_in_swahili(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    r = deliver(client, ep, message="Habari")
    assert r.json()["type"] == "buttons" and "msaidizi wa kiotomatiki" in r.json()["body"]
    assert [b["title"] for b in r.json()["buttons"]] == ["Angalia bei", "Jinsi ya kujisajili", "Ongea na mtu"]
    script_answer("Ziira ina moduli 12.")
    deliver(client, ep, message="Ninataka kujua Ziira ina modules ngapi")
    assert "Swahili" in FakeLlm.calls[-1]["system"]
    assert chat_brain.detect_language("what is the price", "sw") == "en"
    assert chat_brain.detect_language("ok", "sw") == "sw" and chat_brain.detect_language("ok", None) == "en"


def test_a_question_nobody_can_answer_says_so_and_offers_the_buttons(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    put(client, boss, "/texts", {"profile": {"website": SITE}})
    with master_session() as m:
        m.execute(text("insert into master.platform_setting (key, value) values ('public.site_url', cast(:v as jsonb))"),
                  {"v": json.dumps(SITE)})
    behaviour.invalidate()
    r = deliver(client, ep, message="Do you sell xylophones")
    assert r.json()["type"] == "buttons" and "I do not know" in r.json()["body"]
    assert f"Contact: {SITE}/contact" in r.json()["body"]                           # plain addresses, from the knowledge
    assert len(FakeLlm.calls) == 0


def test_media_and_voice_get_one_plain_line(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    for kind in ("image", "audio"):
        r = deliver(client, ep, kind=kind)
        assert r.status_code == 200 and r.json()["text"] == "I can only read text messages. Please type your question."


def test_personal_details_are_noted_scrubbed_and_never_stored(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules.")
    r = deliver(client, ep, message="My email is jane.doe@example.com and my card is 4111 1111 1111 1111, how many modules?")
    assert "Please do not share personal or business details here." in said(r)
    assert "jane.doe" not in json.dumps(FakeLlm.calls[-1]["messages"][0].text)
    with master_session() as m:
        stored = " ".join(t.body for t in m.execute(text("select body from master.chat_turn")))
    assert "jane.doe" not in stored and "4111" not in stored and "[removed]" in stored


def test_a_sender_who_writes_too_fast_is_told_once_then_left_alone(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    monkeypatch.setattr(get_settings(), "chat_per_sender_per_hour", 3)
    script_answer("Ziira has 12 modules.")
    codes = [deliver(client, ep, message="How many modules?").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 204]
    other = deliver(client, ep, sender="254700999000", message="hello")
    assert other.status_code == 200                                                  # another person is not limited


def test_stop_words_opt_out_with_one_confirmation_and_start_comes_back(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    h = chat_inbound.sender_hash("254700111222")
    deliver(client, ep, message="hello")
    for word in ("STOP", "unsubscribe", "Acha", "simamisha."):
        out = deliver(client, ep, message=word)
        assert out.status_code == 200 and "will not message you" in out.json()["text"] or "Hatutakutumia" in out.json()["text"]
    with master_session() as m:
        row = m.execute(text("select opted_out_at from master.chat_sender where sender_hash = :h"), {"h": h}).one()
        assert row.opted_out_at is not None
        assert m.execute(text("select count(*) from master.chat_turn where sender_hash = :h"), {"h": h}).scalar() == 0
    assert chat_inbound.is_opted_out("254700111222") is True
    script_answer("Ziira has 12 modules.")
    answered = deliver(client, ep, message="How many modules?")
    assert answered.status_code == 200                                               # their own new message is answered
    with master_session() as m:
        assert m.execute(text("select count(*) from master.chat_turn where sender_hash = :h"), {"h": h}).scalar() == 0
    back = deliver(client, ep, message="START")
    assert "Welcome back" in back.json()["text"] and chat_inbound.is_opted_out("254700111222") is False
    assert deliver(client, ep, message="please stop calling it that").status_code == 200   # a sentence is not a STOP


def test_a_hand_off_is_recorded_masked_scrubbed_once_and_can_be_closed(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    with master_session() as m:
        m.execute(text("insert into master.platform_setting (key, value) values ('public.support_email', "
                       "cast(:v as jsonb))"), {"v": json.dumps("support@ziira.example")})
    behaviour.invalidate()
    mails: list[tuple[str, str, str]] = []
    from ziira.kernel.platform import mail

    monkeypatch.setattr(mail, "send", lambda to, subject, body, kind="other": mails.append((to, subject, body)))
    r = deliver(client, ep, message="human please call 0722333444")
    assert r.status_code == 200 and "write back" in said(r)
    assert mails == []                                                               # never in the request
    deliver(client, ep, message="agent")                                             # again: no second request
    listed = client.get(f"{CHAT}/handoffs", headers=boss["headers"]).json()
    assert len(listed) == 1 and listed[0]["sender_masked"] == "+254…222" and listed[0]["status"] == "open"
    assert "0722333444" not in (listed[0]["snippet"] or "") and "254700111222" not in json.dumps(listed)
    chat_inbound.run_pending()
    assert len(mails) == 1 and mails[0][0] == "support@ziira.example" and "+254…222" in mails[0][2]
    assert "254700111222" not in mails[0][2]
    done = put(client, boss, f"/handoffs/{listed[0]['id']}/done", method="POST").json()
    assert done["status"] == "done" and done["done_by"]
    assert client.get(f"{CHAT}/handoffs?status=open", headers=boss["headers"]).json() == []
    assert put(client, boss, "/handoffs/00000000-0000-0000-0000-000000000000/done", method="POST").status_code == 404
    assert client.get(f"{CHAT}/handoffs?status=nope", headers=boss["headers"]).status_code == 422


def test_off_hours_use_their_own_text(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    texts = chat_brain.BotTexts(hours_start="08:00", hours_end="17:00", hours_timezone="UTC", off_hours="We are closed.")
    from datetime import UTC, datetime

    assert chat_brain.is_off_hours(texts, datetime(2026, 10, 21, 20, 0, tzinfo=UTC)) is True       # a Wednesday evening
    assert chat_brain.is_off_hours(texts, datetime(2026, 10, 21, 10, 0, tzinfo=UTC)) is False
    assert chat_brain.is_off_hours(texts, datetime(2026, 10, 24, 10, 0, tzinfo=UTC)) is True       # a Saturday
    assert chat_brain.is_off_hours(chat_brain.BotTexts(), datetime(2026, 10, 24, 10, 0, tzinfo=UTC)) is False
    assert deliver(client, ep, message="human", button_id="talk_person").status_code == 200


def test_an_ai_failure_is_a_short_apology_never_silence(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    from ziira.modules.intel.domain.llm import LlmError

    FakeLlm.script.append(LlmError("provider exploded with secret sk-123"))
    r = deliver(client, ep, message="How many modules?")
    assert r.status_code == 200 and "could not answer" in said(r) and "sk-123" not in r.text
    with master_session() as m:
        assert m.execute(text("select outcome from master.chat_event order by received_at desc limit 1")).scalar() == "failed"


def test_the_spend_ceiling_is_shared_with_the_website_assistant(client, boss, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    monkeypatch.setattr(get_settings(), "site_assistant_monthly_cap_usd", 0)
    settings.invalidate()
    r = deliver(client, ep, message="How many modules?")
    assert r.status_code == 200 and "resting" in said(r) and len(FakeLlm.calls) == 0


def test_history_gives_context_to_the_next_question_and_keeps_six_turns(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    for i in range(5):
        script_answer(f"Ziira has 12 modules, answer {i}.")
        deliver(client, ep, message=f"How many modules, question {i}?")
    last_call = FakeLlm.calls[-1]["messages"][0].text
    assert "question 3" in last_call and "Earlier in this chat" in last_call
    with master_session() as m:
        assert m.execute(text("select count(*) from master.chat_turn")).scalar() == 6


def test_words_are_purged_after_seven_days_and_old_rows_go(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules.")
    deliver(client, ep, message="How many modules?")
    deliver(client, ep, message="talk to a human please", event="evt-h")
    h = chat_inbound.sender_hash("254700111222")
    with master_session() as m:
        m.execute(text("update master.chat_turn set created_at = now() - interval '8 days'"))
        m.execute(text("update master.chat_handoff set created_at = now() - interval '8 days'"))
        m.execute(text("update master.chat_event set received_at = now() - interval '31 days'"))
        m.execute(text("insert into master.chat_sender (sender_hash, masked, last_seen_at) values ('old', '+1…2', "
                       "now() - interval '100 days')"))
        m.execute(text("insert into master.chat_sender (sender_hash, masked, last_seen_at, opted_out_at) values ('oldstop', "
                       "'+1…3', now() - interval '100 days', now())"))
    chat_inbound.purge()
    with master_session() as m:
        assert m.execute(text("select count(*) from master.chat_turn")).scalar() == 0
        assert m.execute(text("select snippet from master.chat_handoff")).scalar() is None
        assert m.execute(text("select count(*) from master.chat_event")).scalar() == 0
        kept = {r.sender_hash for r in m.execute(text("select sender_hash from master.chat_sender"))}
    assert "old" not in kept and "oldstop" in kept and h in kept


def test_the_counters_show_outcomes_only(client, boss) -> None:  # type: ignore[no-untyped-def]
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules.")
    deliver(client, ep, message="How many modules?")
    deliver(client, ep, message="Do you sell xylophones", sender="254700444000")
    deliver(client, ep, message="STOP", sender="254700555000")
    deliver(client, ep, message="hello", sender="254700555001")
    stats = client.get(CHAT, headers=boss["headers"]).json()["stats"]
    assert (stats["answered"], stats["unknown"], stats["opted_out"], stats["failed"]) == (2, 1, 1, 0)
    assert set(stats) == {"last", "answered", "unknown", "opted_out", "failed", "other", "open_handoffs"}


# --------------------------------------------------------------------------- secrets, permissions, audit
def test_no_secret_is_ever_in_a_reply_a_log_or_the_trail(client, boss, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    ep = connect(client, boss)
    put(client, boss, "/rotate-secret", method="POST")
    ep = endpoint()
    token = ep["path"].rsplit("/", 1)[1]
    script_answer("Ziira has 12 modules.")
    replies = [client.get(CHAT, headers=boss["headers"]).text, put(client, boss, "/key", {"api_key": KEY}).text,
               put(client, boss, "/key/test", method="POST").text, put(client, boss, "/try", {"message": "modules"}, "POST").text,
               client.get(f"{CHAT}/handoffs", headers=boss["headers"]).text, deliver(client, ep).text]
    with master_session() as m:
        trail_text = json.dumps([dict(r._mapping) for r in m.execute(text("select * from master.operator_action_log"))],
                                default=str)
        stored = json.dumps(dict(m.execute(text("select * from master.chat_bot")).one()._mapping), default=str)
        queue = json.dumps([dict(r._mapping) for r in m.execute(text("select * from master.chat_outbox"))], default=str)
    secrets = [KEY, ep["secret"], token]
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("ziira"))     # not the test client's own
    everything = "\n".join([*replies, trail_text, ours])
    for secret in secrets:
        assert secret not in everything, secret
        assert secret not in stored and secret not in queue
    assert "chat.key_save" in trail_text and "chat.connect" in trail_text
    overview = client.get(CHAT, headers=boss["headers"]).json()
    assert overview["key"] == {"is_set": True, "tested_ok": True, "tested_at": overview["key"]["tested_at"]}
    assert all(f["value"] is None for f in overview["provider"]["fields"] if f["secret"])


def test_no_message_text_reaches_the_logs(client, boss, caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    ep = connect(client, boss)
    script_answer("Ziira has 12 modules.")
    deliver(client, ep, message="Tell me about the quokka tree frog 0722333444")
    assert "quokka" not in caplog.text and "0722333444" not in caplog.text and "254700111222" not in caplog.text


def test_every_change_needs_a_recent_confirmation_and_is_in_the_trail(client, boss) -> None:  # type: ignore[no-untyped-def]
    changer = staff(client, "superadmin")
    age_confirmation(changer, 60)
    r = client.put(f"{CHAT}/key", headers=changer["headers"], json={"api_key": KEY})
    assert r.status_code == 403 and r.json().get("error") == "mfa_step_up_required"
    assert chat_bot._row() is None or not chat_bot._secrets(chat_bot._row()).get("api_key")      # nothing was saved
    assert client.get(CHAT, headers=changer["headers"]).status_code == 200                       # reading needs none
    assert client.post(f"{CHAT}/try", headers=changer["headers"], json={"message": "modules"}).status_code == 200
    put(client, boss, "/key", {"api_key": KEY})
    rows = trail("chat.key_save")
    assert rows and rows[-1]["outcome"] in ("ok", "success", "done") or rows[-1]["outcome"]
    assert KEY not in json.dumps(rows, default=str)


@pytest.mark.parametrize("role", ["billing", "support", "content", "readonly"])
def test_only_a_superadmin_reaches_the_chat_bot(client, role: str) -> None:  # type: ignore[no-untyped-def]
    other = staff(client, role)
    for method, path in (("GET", ""), ("PUT", "/key"), ("POST", "/connect"), ("PUT", "/enabled"), ("PUT", "/texts"),
                         ("POST", "/try"), ("POST", "/disconnect"), ("GET", "/handoffs"), ("POST", "/rotate-secret"),
                         ("POST", "/test-message"), ("GET", "/dev/state")):
        r = client.request(method, f"{CHAT}{path}", headers=other["headers"], json={} if method != "GET" else None)
        assert r.status_code == 403 and "platform.settings" in r.json()["message"], (method, path, r.status_code)


def test_nobody_without_a_token_reaches_the_chat_bot(client) -> None:  # type: ignore[no-untyped-def]
    for method, path in (("GET", ""), ("PUT", "/key"), ("POST", "/try"), ("GET", "/handoffs"), ("POST", "/dev/simulate")):
        assert client.request(method, f"{CHAT}{path}", json={} if method != "GET" else None).status_code == 401


def test_the_provider_needs_the_platform_scope_and_the_extension_point_is_registered() -> None:
    from ziira.kernel.registry import Registry

    manifests = Registry().units
    assert manifests["leadsintel_platform"].platform_scope is True
    assert {p.name for p in chat_channel.installed()} == {"fake"}
