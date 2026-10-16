"""WhatsApp and SMS through Lead Intel, against a pretend Lead Intel: connecting a number, sending (with the idempotency key,
the 24-hour rule, retries and fallbacks), the signed inbound webhook (good, forged, stale, repeated), delivery reports, and
replying to Intelligence's suggestions with the Approve / Reject / Why? buttons - end to end through the real Intelligence
engine. Nothing here talks to the real service."""

import hashlib
import hmac
import json
import logging
import time
from datetime import date
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from tests.payments_helpers import one
from tests.stock_helpers import make_stock_shop, system
from ziira.kernel import extensions, jobs, messaging
from ziira.modules.intel.public import (
    INTEL_ACTION,
    INTEL_CHECK,
    ActionContext,
    ActionProvider,
    ActionResult,
    Candidate,
    CheckContext,
    FindingInfo,
    IntelCheck,
    Proposal,
    Record,
)
from ziira.modules.intel.services import channel_questions, engine
from ziira.plugins.leadsintel import client as li_client
from ziira.plugins.leadsintel.services import setup
from ziira.sdk import read_credential

LI = "/api/v1/plugins/leadsintel"
HOOK = f"{LI}/webhook"
KEY = "li_platform_TESTKEY_0123456789"
BASE = "https://ziira.example"
OWNER_PHONE, ACCOUNTANT_PHONE, STRANGER = "254700100100", "254700100200", "254700999999"
DONE: list[str] = []                                           # what the fake action did


# --------------------------------------------------------------------------- a pretend Lead Intel
class LeadIntel:
    """Answers like the documented service. `script` queues one-off replies for a method and path ending."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.script: dict[tuple[str, str], list[httpx.Response]] = {}
        self.request_status = "pending"
        self.connection_status = "active"
        self.sent = 0
        self.claim_codes_left = 5

    def seen(self, method: str, ending: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(ending)]

    def bodies(self, ending: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.seen("POST", ending)]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api")
        queued = next((q for (m, end), q in self.script.items() if m == request.method and path.endswith(end) and q), None)
        if queued:
            return queued.pop(0)
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"error": "invalid_platform_key"})
        if path.endswith("/connections/lookup"):
            return httpx.Response(404, json={"error": "connection_not_found"})
        if path.endswith("/assisted-requests") and request.method == "POST":
            return httpx.Response(202, json={"requestId": "req-1", "status": "pending"})
        if "/assisted-requests/" in path and request.method == "GET":
            return httpx.Response(200, json={"requestId": "req-1", "status": self.request_status,
                                             "displayPhoneNumber": "+254 712 345678"})
        if "/assisted-requests/" in path and request.method == "DELETE":
            return httpx.Response(204)
        if path.endswith("/existing-numbers/lookup"):
            return httpx.Response(200, json={"connected": True, "claimable": True, "displayPhoneNumber": "+254 722 000999"})
        if path.endswith("/existing-numbers/claims"):
            return httpx.Response(202, json={"claimId": "claim-1", "status": "code_sent", "sentTo": "+254 *** 999",
                                             "expiresAt": "2026-10-15T12:10:00Z"})
        if path.endswith("/verify"):
            if json.loads(request.content)["code"] != "246810":
                self.claim_codes_left -= 1
                return httpx.Response(400, json={"error": "invalid_code", "attemptsLeft": self.claim_codes_left})
            return httpx.Response(200, json={"status": "connected", "phoneNumberId": "pn-1",
                                             "displayPhoneNumber": "+254 722 000999"})
        if path.endswith("/templates") and request.method == "POST":
            return httpx.Response(202, json={"id": "tpl-1", "status": "PENDING"})
        if path.endswith("/templates") and request.method == "GET":
            return httpx.Response(200, json={"id": "tpl-1", "status": "APPROVED"})
        if path.endswith("/send"):
            self.sent += 1
            return httpx.Response(202, json={"messageId": f"wamid.OUT{self.sent}", "status": "accepted"})
        if request.method == "GET" and "/connections/" in path:
            return httpx.Response(200, json={"status": self.connection_status, "phoneNumberId": "pn-1",
                                             "displayPhoneNumber": "+254 712 345678"})
        if request.method == "DELETE" and "/connections/" in path:
            return httpx.Response(204)
        return httpx.Response(404, json={"error": "not_found"})


@pytest.fixture(scope="module")
def li():  # type: ignore[no-untyped-def]
    server = LeadIntel()
    original, original_base = li_client.client_factory, setup.settings_public_base_url
    li_client.client_factory = lambda: httpx.Client(transport=httpx.MockTransport(server))
    setup.settings_public_base_url = lambda: BASE
    yield server
    li_client.client_factory, setup.settings_public_base_url = original, original_base


# --------------------------------------------------------------------------- the business: Intelligence and a fake action
PLAN: dict[str, Any] = {"candidates": []}


class AskCheck(IntelCheck):
    code = "test.reply"
    title = "A check the reply tests use"
    area = "stock"
    params: dict[str, Any] = {}

    def run(self, session, ctx: CheckContext) -> list[Candidate]:  # type: ignore[no-untyped-def]
        return [c(ctx.company_id) for c in PLAN["candidates"]]


class Draft(ActionProvider):
    type = "test.reply_draft"
    title = "Prepare a draft"
    description = "Makes a draft"
    check_codes = ("test.reply",)
    needs_permission = "exceptions.manage"
    auto_allowed = False
    params_schema = {"properties": {"quantity": {"type": "number", "title": "Quantity", "minimum": "1"}},
                     "required": ["quantity"]}

    def proposes(self, session, finding: FindingInfo) -> list[Proposal]:  # type: ignore[no-untyped-def]
        return [Proposal(params={"quantity": "5"}, description=f"Order 5 for: {finding.summary}",
                         facts={"Stock": "2 left", "Sold last month": "40"})]

    def execute(self, session, context: ActionContext, params: dict[str, Any]) -> ActionResult:  # type: ignore[no-untyped-def]
        DONE.append(f"{context.proposal_id}")
        return ActionResult(True, f"Draft made ({params['quantity']})")


def cand(fp: str) -> Any:
    def make(company_id):  # type: ignore[no-untyped-def]
        from decimal import Decimal

        return Candidate(fingerprint=fp, severity="high", summary=f"Problem {fp}", recommended_action="Look into it",
                         company_id=company_id, branch_id=None, amount=Decimal("100"),
                         records=(Record("test.thing", uuid4(), f"Thing {fp}"),))
    return make


@pytest.fixture(scope="module")
def shop(client, registry, li):  # type: ignore[no-untyped-def]
    import ziira.modules.intel.hooks  # noqa: F401 - defines the extension points

    points = extensions._points
    extensions._add_implementation(points[INTEL_CHECK], "intel", AskCheck)
    extensions._add_implementation(points[INTEL_ACTION], "intel", Draft)
    s = make_stock_shop(client, registry, "Li Co")
    for unit in ("intel", "messaging", "leadsintel"):
        registry.enable(s["tenant_id"], unit)
    s["accountant"] = s["user"]("acct", "Accountant", None)
    with system(s) as session:
        users = {r.email.split("@")[0]: r.id for r in session.execute(text("select id, email from kernel.app_user"))}
    s["users"] = users
    other = make_stock_shop(client, registry, "Li Other")
    registry.enable(other["tenant_id"], "leadsintel")
    s["other"] = other
    r = client.patch(f"/api/v1/companies/{s['company_id']}/settings", headers=s["owner"],
                     json={"intel_action_level": 3, "intel_alert_channel": "whatsapp"})
    assert r.status_code == 200, r.text
    client.put("/api/v1/notifications/channels/sms", headers=s["owner"], json={
        "company_id": str(s["company_id"]), "provider": "fake", "secret": {"k": "v"}})
    from ziira.plugins.messaging.providers import FakeChat

    FakeChat.hidden = True                      # only Lead Intel offers a chat channel in this business
    yield s
    FakeChat.hidden = False
    points[INTEL_CHECK].implementations.remove(("intel", AskCheck))
    points[INTEL_ACTION].implementations.remove(("intel", Draft))


def run_jobs(shop) -> None:  # type: ignore[no-untyped-def]
    for _ in range(5):
        with system(shop) as s:
            s.execute(text("update kernel.job set run_at = now() where status = 'queued' "
                           "and job_type = 'kernel.send_notification'"))
        if jobs.run_due(shop["tenant_id"]) == 0:
            break


def webhook_url(token: str) -> str:
    return f"{HOOK}/{token}"


class Hook:
    """The connection's inbound address and secret, with a way to post signed deliveries."""

    token = ""
    secret = ""


def post(client, payload: dict[str, Any] | bytes, *, token: str | None = None, event_id: str | None = None,
         ts: int | None = None, signature: str | None = None, secret: str | None = None, raw: bytes | None = None):  # type: ignore[no-untyped-def]
    body = raw if raw is not None else payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    stamp = str(int(time.time() * 1000) if ts is None else ts)
    sig = signature if signature is not None else hmac.new((secret or Hook.secret).encode(), stamp.encode() + b"." + body,
                                                          hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-LeadIntel-Event-Id": event_id or f"evt-{uuid4()}",
               "X-LeadIntel-Timestamp": stamp, "X-LeadIntel-Signature": sig}
    return client.post(webhook_url(token or Hook.token), content=body, headers=headers)


def text_in(sender: str, body: str, mid: str | None = None) -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "254 712 345678", "phone_number_id": "pn-1"},
            "messages": [{"id": mid or f"wamid.{uuid4()}", "from": sender, "timestamp": str(int(time.time())),
                          "type": "text", "text": {"body": body}}]}


def tap(sender: str, button_id: str, title: str = "Approve", mid: str | None = None) -> dict[str, Any]:
    payload = text_in(sender, "")
    payload["messages"][0].update({"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {
        "id": button_id, "title": title}}})
    del payload["messages"][0]["text"]
    payload["messages"][0]["id"] = mid or f"wamid.{uuid4()}"
    return payload


def inbound_count(shop) -> int:  # type: ignore[no-untyped-def]
    return int(one(shop, "select count(*) from plg_leadsintel.inbound_message"))


def notifications_count(shop) -> int:  # type: ignore[no-untyped-def]
    return int(one(shop, "select count(*) from kernel.notification"))


# --------------------------------------------------------------------------- connecting
def test_nothing_is_connected_at_first_and_only_a_manager_may_connect(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    state = client.get(f"{LI}/state", headers=shop["owner"], params={"company_id": co})
    assert state.status_code == 200 and state.json() == {"key_saved": False, "whatsapp": None, "warning": None,
                                                        "sent_to": None, "expires_at": None}
    assert client.put(f"{LI}/key", headers=shop["cashier"], json={"company_id": co, "platform_key": KEY}).status_code == 403
    assert client.get(f"{LI}/state", headers=shop["cashier"], params={"company_id": co}).status_code == 403
    assert client.post(f"{LI}/whatsapp/connect", headers=shop["owner"], json={
        "company_id": co, "country_code": "254", "phone_number": "712345678", "business_name": "A", "display_name": "A"}
                       ).status_code == 422                                                   # the key comes first


def test_the_key_is_checked_with_lead_intel_stored_encrypted_and_never_returned(client, shop, li, caplog) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    bad = client.put(f"{LI}/key", headers=shop["owner"], json={"company_id": co, "platform_key": "li_platform_WRONG_KEY"})
    assert bad.status_code == 422 and "does not accept" in bad.json()["message"] and "WRONG" not in bad.text
    assert client.get(f"{LI}/state", headers=shop["owner"], params={"company_id": co}).json()["key_saved"] is False
    with caplog.at_level(logging.DEBUG):
        good = client.put(f"{LI}/key", headers=shop["owner"], json={"company_id": co, "platform_key": KEY})
    assert good.status_code == 200 and good.json()["key_saved"] is True
    assert KEY not in good.text and KEY not in caplog.text
    probe = li.seen("POST", "/connections/lookup")[-1]
    assert probe.headers["authorization"] == f"Bearer {KEY}"
    stored = one(shop, "select secret_ciphertext from kernel.integration_credential where provider = 'whatsapp' "
                       "and status = 'active'")
    assert KEY.encode() not in bytes(stored)                                                 # encrypted at rest
    config = one(shop, "select config::text from kernel.integration_credential where provider = 'whatsapp' "
                       "and status = 'active'")
    assert KEY not in config and '"ready": false' in config
    assert client.post(f"{LI}/check", headers=shop["owner"], json={"company_id": co}).json()["ok"] is True
    li.script[("POST", "/connections/lookup")] = [httpx.Response(401, json={"error": "invalid_platform_key"})]
    revoked = client.post(f"{LI}/check", headers=shop["owner"], json={"company_id": co})
    assert revoked.json()["ok"] is False and "does not accept" in revoked.json()["message"] and KEY not in revoked.text
    li.script[("POST", "/connections/lookup")] = [httpx.Response(503, json={"error": "down"})]
    outage = client.post(f"{LI}/check", headers=shop["owner"], json={"company_id": co}).json()
    assert outage["ok"] is False and "could not be reached" in outage["message"]         # an outage is not a bad key
    assert client.post(f"{LI}/check", headers=shop["cashier"], json={"company_id": co}).status_code == 403


def test_connecting_a_new_number_follows_lead_intels_steps_to_active(client, shop, li, caplog) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    with caplog.at_level(logging.DEBUG):
        start = client.post(f"{LI}/whatsapp/connect", headers=shop["owner"], json={
            "company_id": co, "country_code": "+254", "phone_number": "0712 345 678", "business_name": "Li Co Ltd",
            "display_name": "Li Co", "about": "Hardware and more"})
    assert start.status_code == 202, start.text
    assert start.json()["whatsapp"]["status"] == "requested"
    [body] = li.bodies("/assisted-requests")
    assert body["externalPlatformTenantId"] == str(shop["tenant_id"]) and len(body["externalConnectionId"]) == 32
    assert body["countryCode"] == "254" and body["phoneNumber"] == "712345678"             # the leading 0 is not part of it
    assert body["businessName"] == "Li Co Ltd" and body["displayName"] == "Li Co"
    assert body["businessProfile"] == {"about": "Hardware and more"}
    url = body["inboundWebhookUrl"]
    assert url.startswith(f"{BASE}{HOOK}/") and url.split("/")[-1].startswith(shop["tenant_id"].hex + ".")
    Hook.token = url.split("/")[-1]
    with system(shop) as s:
        Hook.secret = read_credential(s, s.execute(text(
            "select id from kernel.integration_credential where provider = 'whatsapp' and status = 'active'")).scalar_one())[
            "webhook_secret"]
    assert body["inboundWebhookSecret"] == Hook.secret and len(Hook.secret) >= 32
    for secret in (KEY, Hook.secret, Hook.token):
        assert secret not in start.text and secret not in caplog.text
    # Only one connection at a time.
    assert client.post(f"{LI}/whatsapp/connect", headers=shop["owner"], json={
        "company_id": co, "country_code": "254", "phone_number": "712345679", "business_name": "A", "display_name": "A"}
                       ).status_code == 409
    # Lead Intel is still working, then wants a code, then connects, then the connection is active.
    assert client.post(f"{LI}/whatsapp/refresh", headers=shop["owner"], json={"company_id": co}).json()[
        "whatsapp"]["status"] == "requested"
    li.request_status = "awaiting_code"
    assert client.post(f"{LI}/whatsapp/refresh", headers=shop["owner"], json={"company_id": co}).json()[
        "whatsapp"]["status"] == "awaiting_code"
    li.request_status, li.connection_status = "connected", "pending"
    assert client.post(f"{LI}/whatsapp/refresh", headers=shop["owner"], json={"company_id": co}).json()[
        "whatsapp"]["status"] == "connected"                                                # not usable until active
    with system(shop) as s:
        assert "whatsapp" not in messaging.configured_channels(s, shop["company_id"])
    li.connection_status = "active"
    done = client.post(f"{LI}/whatsapp/refresh", headers=shop["owner"], json={"company_id": co}).json()
    assert done["whatsapp"]["status"] == "active" and done["whatsapp"]["display_phone"] == "+254 712 345678"
    with system(shop) as s:
        assert "whatsapp" in messaging.configured_channels(s, shop["company_id"])
    assert li.seen("GET", f"/connections/{shop['tenant_id']}/{body['externalConnectionId']}")


def test_a_failed_setup_shows_lead_intels_reason_and_can_be_started_again(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    assert client.post(f"{LI}/whatsapp/disconnect", headers=shop["owner"], json={"company_id": co}).status_code == 200
    with system(shop) as s:
        assert "whatsapp" not in messaging.configured_channels(s, shop["company_id"])
    assert any(r.method == "DELETE" and "/connections/" in r.url.path for r in li.requests)
    start = client.post(f"{LI}/whatsapp/connect", headers=shop["owner"], json={
        "company_id": co, "country_code": "254", "phone_number": "712345678", "business_name": "Li Co", "display_name": "Li Co"})
    assert start.status_code == 202
    li.script[("GET", "/assisted-requests/req-1")] = [httpx.Response(200, json={
        "requestId": "req-1", "status": "failed", "errorCode": "meta_permission_denied", "errorMessage": "Meta said no"})]
    failed = client.post(f"{LI}/whatsapp/refresh", headers=shop["owner"], json={"company_id": co}).json()
    assert failed["whatsapp"]["status"] == "failed" and failed["whatsapp"]["error_code"] == "meta_permission_denied"
    cancelled = client.post(f"{LI}/whatsapp/cancel", headers=shop["owner"], json={"company_id": co})
    assert cancelled.status_code == 422                                                      # nothing in progress to cancel


def test_a_number_already_on_lead_intel_is_claimed_with_the_code_it_receives(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    number = {"company_id": co, "country_code": "254", "phone_number": "722000999"}
    found = client.post(f"{LI}/whatsapp/existing", headers=shop["owner"], json=number)
    assert found.status_code == 200 and found.json() == {"connected": True, "claimable": True, "reason": None}
    assert li.bodies("/existing-numbers/lookup")[-1] == {"phoneNumber": "+254722000999"}
    started = client.post(f"{LI}/whatsapp/claim", headers=shop["owner"], json=number)
    assert started.status_code == 202 and started.json()["whatsapp"]["status"] == "code_sent"
    assert started.json()["sent_to"] == "+254 *** 999"
    claim = li.bodies("/existing-numbers/claims")[-1]
    assert claim["phoneNumber"] == "+254722000999" and claim["inboundWebhookUrl"].startswith(f"{BASE}{HOOK}/")
    Hook.token = claim["inboundWebhookUrl"].split("/")[-1]
    wrong = client.post(f"{LI}/whatsapp/claim/verify", headers=shop["owner"], json={"company_id": co, "code": "000000"})
    assert wrong.status_code == 422 and "not right" in wrong.json()["message"] and "4 tries left" in wrong.json()["message"]
    right = client.post(f"{LI}/whatsapp/claim/verify", headers=shop["owner"], json={"company_id": co, "code": "246810"})
    assert right.status_code == 200, right.text
    assert right.json()["whatsapp"]["status"] == "active"
    with system(shop) as s:
        assert "whatsapp" in messaging.configured_channels(s, shop["company_id"])


def test_a_lead_intel_outage_during_setup_keeps_the_last_known_state(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    co = str(shop["company_id"])
    li.script[("POST", "/whatsapp/existing-numbers/lookup")] = [httpx.Response(503, json={"error": "down"})]
    down = client.post(f"{LI}/whatsapp/existing", headers=shop["owner"], json={
        "company_id": co, "country_code": "254", "phone_number": "722000999"})
    assert down.status_code == 422 and "try again" in down.json()["message"].lower()
    assert client.get(f"{LI}/state", headers=shop["owner"], params={"company_id": co}).json()["whatsapp"]["status"] == "active"


def test_other_businesses_cannot_see_or_change_this_connection(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    other = shop["other"]
    mine = str(shop["company_id"])
    assert client.get(f"{LI}/state", headers=other["owner"], params={"company_id": mine}).status_code in (403, 422)
    assert client.get(f"{LI}/inbox", headers=other["owner"], params={"company_id": mine}).status_code in (403, 422)
    assert client.put(f"{LI}/key", headers=other["owner"], json={"company_id": mine, "platform_key": KEY}).status_code in (
        403, 422)
    theirs = client.get(f"{LI}/state", headers=other["owner"], params={"company_id": str(other["company_id"])})
    assert theirs.status_code == 200 and theirs.json()["key_saved"] is False


# --------------------------------------------------------------------------- sending
def queue_whatsapp(shop, body="Hello", to="0722000111", **kw):  # type: ignore[no-untyped-def]
    from ziira.sdk import send_notification

    with system(shop) as s:
        return send_notification(s, company_id=shop["company_id"], channel="whatsapp", recipient=to, body=body, **kw)


def open_window(shop, number="254722000111") -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        messaging.record_inbound_contact(s, shop["company_id"], "whatsapp", number)


def test_a_free_form_message_inside_the_window_is_one_post_with_a_stable_idempotency_key(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    open_window(shop)
    before = len(li.seen("POST", "/send"))
    made = queue_whatsapp(shop, "Your order is ready", dedupe_key="send-1")
    run_jobs(shop)
    [request] = li.seen("POST", "/send")[before:]
    assert f"/connections/{shop['tenant_id']}/" in request.url.path
    assert request.headers["idempotency-key"] == f"ziira-{made}-text"
    assert json.loads(request.content) == {"to": "254722000111", "type": "text", "text": "Your order is ready"}
    state = one(shop, "select status from kernel.notification where id = :i", i=str(made))
    ref = one(shop, "select provider_ref from kernel.notification where id = :i", i=str(made))
    assert state == "sent" and ref.startswith("wamid.OUT")                                  # accepted, not yet delivered


def test_a_timeout_is_retried_with_the_same_key_and_never_sends_twice(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    open_window(shop)
    li.script[("POST", "/send")] = [httpx.Response(503, json={"error": "unavailable"})]
    before = len(li.seen("POST", "/send"))
    made = queue_whatsapp(shop, "Second try", dedupe_key="send-2")
    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
    jobs.run_due(shop["tenant_id"])                                                          # one pass: the outage
    assert one(shop, "select status from kernel.notification where id = :i", i=str(made)) == "queued"   # waits to retry
    with system(shop) as s:
        s.execute(text("update kernel.job set run_at = now() where status = 'queued'"))
    jobs.run_due(shop["tenant_id"])
    tries = li.seen("POST", "/send")[before:]
    assert len(tries) == 2
    assert {t.headers["idempotency-key"] for t in tries} == {f"ziira-{made}-text"}           # Lead Intel dedupes on this
    assert one(shop, "select status from kernel.notification where id = :i", i=str(made)) == "sent"
    jobs.run_due(shop["tenant_id"])
    assert len(li.seen("POST", "/send")[before:]) == 2


def test_a_refused_key_or_connection_is_permanent_and_the_next_channel_is_used(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel import notifications
    from ziira.plugins.messaging.providers import FakeSms

    FakeSms.sent.clear()
    open_window(shop)
    li.script[("POST", "/send")] = [httpx.Response(409, json={"error": "connection_inactive"})]
    with system(shop) as s:
        made = notifications.queue(s, company_id=shop["company_id"], channel="whatsapp", recipient="0722000111",
                                   body="Fall back", dedupe_key="send-3",
                                   fallbacks=[{"channel": "sms", "recipient": "0722000111"}])
    run_jobs(shop)
    assert [m.body for m in FakeSms.sent] == ["Fall back"]
    assert "not active" in one(shop, "select error from kernel.notification where id = :i", i=str(made))
    assert one(shop, "select status from kernel.notification where id = :i", i=str(made)) == "skipped"


def test_templates_are_submitted_and_approved_through_lead_intel_and_then_used(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    co = {"company_id": str(shop["company_id"])}
    with system(shop) as s:
        s.execute(text("delete from kernel.contact_window"))
        s.execute(text("update kernel.message_template set status = 'draft', provider_template_id = null"))
    sub = client.post("/api/v1/notifications/templates/submit", headers=shop["owner"], json=co)
    assert sub.status_code == 200, sub.text
    assert sub.json()["counts"]["submitted"] == 12
    creates = [r for r in li.seen("POST", "/templates")]
    assert len(creates) == 12
    first = json.loads(next(r for r in creates if b"ziira_action_proposal" in r.content and b'"sw"' in r.content).content)
    assert first["category"] == "UTILITY" and first["language"] == "sw"
    assert first["components"][0]["text"] == "{{1}}: Ziira inapendekeza: {{2}} Linahitaji uamuzi wako."
    assert [b["text"] for b in first["components"][1]["buttons"]] == ["Idhinisha", "Kataa", "Kwa nini?"]
    synced = client.post("/api/v1/notifications/templates/sync", headers=shop["owner"], json=co)
    assert synced.json()["counts"]["approved"] == 12
    before = len(li.seen("POST", "/send"))
    from ziira.sdk import send_templated

    with system(shop) as s:
        made = send_templated(s, company_id=shop["company_id"], channel="whatsapp", recipient="0733555777",
                              template="payment_due", variables={"customer": "Juma", "invoice": "INV-9",
                                                                 "amount": "KES 50.00", "business": "Li Co",
                                                                 "due_date": "2026-10-30"}, dedupe_key="tpl-1")
    run_jobs(shop)
    [request] = li.seen("POST", "/send")[before:]
    assert request.headers["idempotency-key"] == f"ziira-{made}-template"
    assert json.loads(request.content) == {
        "to": "254733555777", "type": "template", "name": "ziira_payment_due", "language": "en", "components": [
            {"type": "body", "parameters": [{"type": "text", "text": t} for t in
                                            ("Juma", "INV-9", "KES 50.00", "Li Co", "2026-10-30")]}]}


# --------------------------------------------------------------------------- the inbound webhook
def test_a_forged_stale_or_unknown_delivery_is_refused_before_anything_is_read(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    before, sent_before = inbound_count(shop), notifications_count(shop)
    payload = text_in(STRANGER, "hello")
    now = int(time.time() * 1000)
    cases = [
        post(client, payload, signature="0" * 64),                                          # wrong signature
        post(client, payload, secret="not-the-secret"),                                     # signed by someone else
        post(client, payload, ts=now - 6 * 60_000),                                         # older than five minutes
        post(client, payload, ts=now + 6 * 60_000),                                         # from the future
        post(client, payload, token=f"{shop['tenant_id'].hex}.{'x' * 40}"),                  # this business, no such address
        post(client, payload, token="garbage"),
        post(client, payload, token=f"{shop['other']['tenant_id'].hex}.{Hook.token.split('.')[1]}"),   # another business
        post(client, payload, token=f"{uuid4().hex}.{'y' * 40}"),                            # a business that does not exist
        client.post(webhook_url(Hook.token), content=b"{}", headers={}),                     # no headers at all
    ]
    assert [c.status_code for c in cases] == [401] * len(cases)
    assert len({c.text for c in cases}) == 1                                                 # all answer alike: nothing to learn
    tampered = json.dumps(payload).encode()
    forged = post(client, payload, raw=tampered.replace(b"hello", b"HELLO"), signature=hmac.new(
        Hook.secret.encode(), str(now).encode() + b"." + tampered, hashlib.sha256).hexdigest(), ts=now)
    assert forged.status_code == 401                                                         # body changed after signing
    assert inbound_count(shop) == before and notifications_count(shop) == sent_before


def test_a_message_from_an_unknown_number_is_kept_but_gets_no_reply(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    before = notifications_count(shop)
    sent_before = len(li.seen("POST", "/send"))
    r = post(client, text_in(STRANGER, "Do you have cement?", mid="wamid.stranger1"))
    assert r.status_code == 202
    assert one(shop, "select outcome from plg_leadsintel.inbound_message where provider_message_id = 'wamid.stranger1'") == "unknown"
    assert notifications_count(shop) == before
    run_jobs(shop)
    assert len(li.seen("POST", "/send")) == sent_before                                      # not a word back
    inbox = client.get(f"{LI}/inbox", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).json()
    mine = next(m for m in inbox if m["body"] == "Do you have cement?")
    assert mine["sender"] == "25470****999" and mine["outcome"] == "unknown" and "254700999999" not in json.dumps(inbox)
    assert client.get(f"{LI}/inbox", headers=shop["cashier"], params={"company_id": str(shop["company_id"])}).status_code == 403


def test_a_repeat_delivery_does_nothing_twice(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    payload = text_in("254711000222", "STOP", mid="wamid.stop-repeat")
    first = post(client, payload, event_id="evt-repeat-1")
    again = post(client, payload, event_id="evt-repeat-1")                                    # Lead Intel retried the delivery
    renamed = post(client, payload, event_id="evt-repeat-2")                                  # same message under a new event id
    assert (first.status_code, again.status_code, renamed.status_code) == (202, 202, 202)
    assert one(shop, "select count(*) from plg_leadsintel.inbound_message where provider_message_id = 'wamid.stop-repeat'") == 1
    assert one(shop, "select count(*) from kernel.notification_optout where recipient = '254711000222'") == 1
    assert one(shop, "select outcome from plg_leadsintel.inbound_message where provider_message_id = 'wamid.stop-repeat'") == "stopped"
    assert one(shop, "select count(*) from plg_leadsintel.inbound_event where event_id = 'evt-repeat-1'") == 1


def test_a_failure_while_handling_is_a_500_so_lead_intel_delivers_again(client, shop, li, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ziira.plugins.leadsintel.services import webhook

    def boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("the router broke")

    monkeypatch.setattr(webhook, "route_inbound", boom)
    payload = text_in("254711000333", "hello", mid="wamid.retry1")
    failed = post(client, payload, event_id="evt-retry-1")
    assert failed.status_code == 500
    assert one(shop, "select count(*) from plg_leadsintel.inbound_event where event_id = 'evt-retry-1'") == 0   # not kept
    monkeypatch.undo()
    assert post(client, payload, event_id="evt-retry-1").status_code == 202                   # the retry works
    assert one(shop, "select count(*) from plg_leadsintel.inbound_message where provider_message_id = 'wamid.retry1'") == 1


def test_delivery_reports_move_our_messages_forward(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    open_window(shop, "254722000444")
    made = queue_whatsapp(shop, "Track me", to="0722000444", dedupe_key="track-1")
    run_jobs(shop)
    ref = one(shop, "select provider_ref from kernel.notification where id = :i", i=str(made))

    def report(status: str, **extra: Any):  # type: ignore[no-untyped-def]
        payload = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "pn-1"},
                   "statuses": [{"id": ref, "status": status, "recipient_id": "254722000444", **extra}]}
        return post(client, payload)

    def status() -> str:
        return str(one(shop, "select status from kernel.notification where id = :i", i=str(made)))

    assert report("delivered").status_code == 202 and status() == "delivered"
    assert report("read").status_code == 202 and status() == "read"
    assert report("delivered").status_code == 202 and status() == "read"                      # late report: not backwards
    assert report("failed", errors=[{"title": "late"}]).status_code == 202 and status() == "read"
    assert report("surprise").status_code == 202                                              # unknown status: ignored
    other = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "pn-OTHER"},
             "statuses": [{"id": ref, "status": "failed"}]}
    assert post(client, other).status_code == 202 and status() == "read"                      # another phone number: ignored


# --------------------------------------------------------------------------- replying to Intelligence
def verify_number(shop, user: str, phone: str, verified: bool = True) -> None:  # type: ignore[no-untyped-def]
    with system(shop) as s:
        s.execute(text("delete from kernel.user_phone where user_id = :u or phone = :p"),
                  {"u": str(shop["users"][user]), "p": phone})
        s.execute(text("insert into kernel.user_phone (tenant_id, user_id, phone, verified_at) values "
                       "(kernel.current_tenant(), :u, :p, case when :v then now() else null end)"),
                  {"u": str(shop["users"][user]), "p": phone, "v": verified})
        messaging.record_inbound_contact(s, shop["company_id"], "whatsapp", phone)


def make_proposal(shop, fp: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    PLAN["candidates"] = [cand(fp)]
    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=date(2026, 10, 14), only={"test.reply"})
    with system(shop) as s:
        row = s.execute(text(
            "select p.id, p.finding_id from intel.action_proposal p join intel.finding f on f.id = p.finding_id "
            "where f.summary = :s and p.action_type = 'test.reply_draft'"), {"s": f"Problem {fp}"}).one()
    return str(row.id), str(row.finding_id)


def proposal_state(shop, pid: str) -> str:  # type: ignore[no-untyped-def]
    return str(one(shop, "select status from intel.action_proposal where id = :i", i=pid))


def sent_texts(li, since: int) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return [json.loads(r.content) for r in li.seen("POST", "/send")[since:]]


def test_the_people_who_can_decide_are_sent_the_suggestion_with_buttons(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    verify_number(shop, "owner", OWNER_PHONE)
    verify_number(shop, "acct", ACCOUNTANT_PHONE)
    since = len(li.seen("POST", "/send"))
    pid, fid = make_proposal(shop, "r1")
    run_jobs(shop)
    messages = sent_texts(li, since)
    assert [m["to"] for m in messages] == [OWNER_PHONE]                                      # the accountant cannot decide this
    [m] = messages
    assert m["type"] == "buttons" and m["body"].startswith("Li Co Ltd: Ziira suggests: Order 5 for: Problem r1")
    assert m["buttons"] == [{"id": f"approve:{pid}", "title": "Approve"}, {"id": f"reject:{pid}", "title": "Reject"},
                            {"id": f"why:{pid}", "title": "Why?"}]
    run_jobs(shop)
    assert len(sent_texts(li, since)) == 1                                                   # once


def test_tapping_approve_does_it_as_that_person_and_records_the_channel(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    pid, fid = make_proposal(shop, "r2")
    DONE.clear()
    since = len(li.seen("POST", "/send"))
    r = post(client, tap(OWNER_PHONE, f"approve:{pid}", mid="wamid.tap-approve"))
    assert r.status_code == 202
    assert proposal_state(shop, pid) == "executed" and [pid] == DONE
    log = one(shop, "select concat(channel, '/', mode, '/', actor_user_id) from intel.action_log where proposal_id = :i",
              i=pid)
    assert log == f"chat/manual/{shop['users']['owner']}"
    audit = one(shop, "select concat(channel, '/', user_id) from kernel.audit_log where action = 'intel.action.executed' "
                      "and entity_id = :i", i=pid)
    assert audit == f"chat/{shop['users']['owner']}"
    event = one(shop, "select channel from intel.finding_event where finding_id = :f and event = 'action_taken'", f=fid)
    assert event == "chat"
    command = one(shop, "select changes::text from kernel.audit_log where action = 'channel.command' order by id desc limit 1")
    assert '"outcome": "handled"' in command and f"approve:{pid}" in command
    run_jobs(shop)
    texts = [m.get("text") or m.get("body") for m in sent_texts(li, since)]
    assert "Done: Draft made (5)" in texts                                                    # the answer comes back
    again = post(client, tap(OWNER_PHONE, f"approve:{pid}", mid="wamid.tap-approve-2"))        # tapped twice
    assert again.status_code == 202 and [pid] == DONE                                         # nothing is done a second time


def test_tapping_reject_and_why(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    pid, fid = make_proposal(shop, "r3")
    since = len(li.seen("POST", "/send"))
    post(client, tap(OWNER_PHONE, f"why:{pid}", "Why?", mid="wamid.tap-why"))
    run_jobs(shop)
    [why] = [m for m in sent_texts(li, since) if "Why:" in (m.get("text") or "")]
    assert why["to"] == OWNER_PHONE and "Order 5 for: Problem r3" in why["text"] and "Why: Problem r3" in why["text"]
    assert "- Stock: 2 left" in why["text"] and "- Sold last month: 40" in why["text"]
    assert proposal_state(shop, pid) == "proposed"                                           # asking changes nothing
    post(client, tap(OWNER_PHONE, f"reject:{pid}", "Reject", mid="wamid.tap-reject"))
    assert proposal_state(shop, pid) == "rejected"
    assert one(shop, "select decision_note from intel.action_proposal where id = :i", i=pid) == "Declined by reply in chat"
    assert one(shop, "select channel from intel.finding_event where finding_id = :f and event = 'action_rejected'", f=fid) == "chat"


def test_someone_without_the_permission_is_refused_and_nothing_happens(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    pid, fid = make_proposal(shop, "r4")
    DONE.clear()
    since = len(li.seen("POST", "/send"))
    post(client, tap(ACCOUNTANT_PHONE, f"approve:{pid}", mid="wamid.acct-approve"))
    assert proposal_state(shop, pid) == "proposed" and DONE == []
    run_jobs(shop)
    [reply] = [m for m in sent_texts(li, since) if m["to"] == ACCOUNTANT_PHONE]
    assert "exceptions.manage" in reply["text"]
    assert one(shop, "select outcome from plg_leadsintel.inbound_message where provider_message_id = 'wamid.acct-approve'") == "refused"
    # Rejecting needs the same right (or the right to manage findings, which an accountant does not hold either).
    post(client, tap(ACCOUNTANT_PHONE, f"reject:{pid}", mid="wamid.acct-reject"))
    assert proposal_state(shop, pid) == "proposed"


def test_an_unknown_unverified_or_disabled_number_cannot_approve(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    pid, fid = make_proposal(shop, "r5")
    DONE.clear()
    since, before = len(li.seen("POST", "/send")), notifications_count(shop)
    post(client, tap(STRANGER, f"approve:{pid}", mid="wamid.stranger-approve"))               # nobody
    verify_number(shop, "boss", "254700555111", verified=False)                                # typed in, never proved
    post(client, tap("254700555111", f"approve:{pid}", mid="wamid.unverified"))
    verify_number(shop, "manager", "254700555222")
    with system(shop) as s:
        s.execute(text("update kernel.app_user set status = 'disabled' where id = :u"), {"u": str(shop["users"]["manager"])})
    post(client, tap("254700555222", f"approve:{pid}", mid="wamid.disabled"))
    assert proposal_state(shop, pid) == "proposed" and DONE == []
    outcomes = {r.provider_message_id: r.outcome for r in system_rows(shop)}
    assert outcomes["wamid.stranger-approve"] == outcomes["wamid.unverified"] == outcomes["wamid.disabled"] == "unknown"
    assert notifications_count(shop) == before                                                # not even an error message
    run_jobs(shop)
    assert [m for m in sent_texts(li, since) if m["to"] in (STRANGER, "254700555111", "254700555222")] == []
    with system(shop) as s:
        s.execute(text("update kernel.app_user set status = 'active' where id = :u"), {"u": str(shop["users"]["manager"])})


def system_rows(shop):  # type: ignore[no-untyped-def]
    with system(shop) as s:
        return list(s.execute(text("select provider_message_id, outcome from plg_leadsintel.inbound_message")))


def test_two_people_cannot_share_a_verified_number(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception, match="user_phone_verified"), system(shop) as s:
        s.execute(text("insert into kernel.user_phone (tenant_id, user_id, phone, verified_at) values "
                       "(kernel.current_tenant(), :u, :p, now())"),
                  {"u": str(shop["users"]["cashier"]), "p": OWNER_PHONE})


def test_a_suggestion_that_closed_or_was_decided_cannot_be_approved_later(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    pid, fid = make_proposal(shop, "r6")
    PLAN["candidates"] = []                                                                  # the problem went away
    with system(shop) as s:
        engine.run_company(s, shop["company_id"], today=date(2026, 10, 15), only={"test.reply"})
    assert proposal_state(shop, pid) == "expired"
    since = len(li.seen("POST", "/send"))
    DONE.clear()
    post(client, tap(OWNER_PHONE, f"approve:{pid}", mid="wamid.late-approve"))
    run_jobs(shop)
    assert DONE == [] and proposal_state(shop, pid) == "expired"
    [reply] = [m for m in sent_texts(li, since) if m["to"] == OWNER_PHONE and "expired" in (m.get("text") or "")]
    assert reply["text"]
    pid2, _ = make_proposal(shop, "r7")
    post(client, tap(OWNER_PHONE, f"reject:{pid2}", mid="wamid.r7-reject"))
    since = len(li.seen("POST", "/send"))
    post(client, tap(OWNER_PHONE, f"approve:{pid2}", mid="wamid.r7-approve"))                 # changed their mind
    run_jobs(shop)
    assert proposal_state(shop, pid2) == "rejected"
    assert any("rejected" in (m.get("text") or "") for m in sent_texts(li, since))
    bogus = post(client, tap(OWNER_PHONE, "approve:not-a-uuid", mid="wamid.bogus"))
    assert bogus.status_code == 202
    assert one(shop, "select outcome from plg_leadsintel.inbound_message where provider_message_id = 'wamid.bogus'") == "help"
    unknown = post(client, tap(OWNER_PHONE, f"approve:{uuid4()}", mid="wamid.nosuch"))
    assert unknown.status_code == 202


def test_a_question_typed_to_ziira_is_queued_and_answered_in_the_background(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    since = len(li.seen("POST", "/send"))
    post(client, text_in(OWNER_PHONE, "How were sales this week?", mid="wamid.ask1"))
    run_jobs(shop)
    assert any("I will reply in a moment" in (m.get("text") or "") for m in sent_texts(li, since))
    assert one(shop, "select status from intel.channel_question where message_id = 'wamid.ask1'") == "pending"
    assert channel_questions.answer_pending(shop["tenant_id"]) == 0          # the assistant is off for this business
    status = one(shop, "select status from intel.channel_question where message_id = 'wamid.ask1'")
    assert status == "failed"
    since = len(li.seen("POST", "/send"))
    run_jobs(shop)
    [answer] = [m for m in sent_texts(li, since) if m["to"] == OWNER_PHONE]
    assert answer["text"]                                                                    # told why, not left waiting
    post(client, text_in(ACCOUNTANT_PHONE, "How were sales this week?", mid="wamid.ask2"))       # may ask (ai.ask)
    assert one(shop, "select count(*) from intel.channel_question where message_id = 'wamid.ask2'") == 1
    verify_number(shop, "cashier", "254700777888")
    since = len(li.seen("POST", "/send"))
    post(client, text_in("254700777888", "How were sales this week?", mid="wamid.ask3"))        # a cashier may not
    run_jobs(shop)
    assert one(shop, "select count(*) from intel.channel_question where message_id = 'wamid.ask3'") == 0
    assert any("not available to you" in (m.get("text") or "") for m in sent_texts(li, since))


def test_stop_from_a_staff_number_stops_whatsapp_to_it(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    verify_number(shop, "storekeeper", "254700888999")
    post(client, text_in("254700888999", "stop", mid="wamid.staff-stop"))
    with system(shop) as s:
        from ziira.kernel import notifications

        assert notifications.is_opted_out(s, shop["company_id"], "whatsapp", "254700888999")


# --------------------------------------------------------------------------- secrets
def test_no_secret_appears_in_notifications_jobs_audit_or_the_log(client, shop, li, caplog) -> None:  # type: ignore[no-untyped-def]
    secrets_ = (KEY, Hook.secret, Hook.token.split(".")[1])
    with caplog.at_level(logging.DEBUG):
        open_window(shop, "254722000555")
        queue_whatsapp(shop, "One more", to="0722000555", dedupe_key="secret-1")
        run_jobs(shop)
        post(client, text_in(STRANGER, "hi"))
        post(client, text_in(STRANGER, "hi"), signature="f" * 64)
        client.get(f"{LI}/state", headers=shop["owner"], params={"company_id": str(shop["company_id"])})
    # The platform's own log lines (the test client's HTTP log shows the address it called, which a real Lead Intel does too).
    server_log = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("ziira"))
    dumps = {
        "log": server_log,
        "notifications": one(shop, "select coalesce(string_agg(row_to_json(n)::text, ' '), '') from kernel.notification n"),
        "jobs": one(shop, "select coalesce(string_agg(row_to_json(j)::text, ' '), '') from kernel.job j"),
        "audit": one(shop, "select coalesce(string_agg(row_to_json(a)::text, ' '), '') from kernel.audit_log a"),
        "inbound": one(shop, "select coalesce(string_agg(row_to_json(m)::text, ' '), '') from plg_leadsintel.inbound_message m"),
        "exceptions": one(shop, "select coalesce(string_agg(row_to_json(e)::text, ' '), '') from kernel.exception_item e"),
        "channels": client.get("/api/v1/notifications/channels", headers=shop["owner"],
                               params={"company_id": str(shop["company_id"])}).text,
        "state": client.get(f"{LI}/state", headers=shop["owner"], params={"company_id": str(shop["company_id"])}).text,
    }
    for name, dump in dumps.items():
        for secret in secrets_:
            assert secret not in dump, f"a secret leaked into {name}"


# --------------------------------------------------------------------------- the plugin can be switched off and on
def available_names(client, shop) -> list[str]:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/notifications/channels/available", headers=shop["owner"],
                   params={"company_id": str(shop["company_id"])})
    assert r.status_code == 200, r.text
    return [c["channel"] for c in r.json()]


def test_switching_the_plugin_off_removes_whatsapp_everywhere_and_loses_nothing(client, shop, li, registry) -> None:  # type: ignore[no-untyped-def]
    from ziira.modules.intel.services import alerts
    from ziira.plugins.messaging.providers import FakeEmail, FakeSms

    co = str(shop["company_id"])
    assert client.put("/api/v1/notifications/channels/email", headers=shop["owner"], json={
        "company_id": co, "provider": "fake", "secret": {"k": "v"}}).status_code == 200
    assert "whatsapp" in available_names(client, shop)
    info = next(c for c in client.get("/api/v1/notifications/channels/available", headers=shop["owner"]).json()
                if c["channel"] == "whatsapp")
    assert info["label"] == "WhatsApp" and info["supports_buttons"] and info["supports_inbound"] and info["window_hours"] == 24
    FakeSms.sent.clear()
    FakeEmail.sent.clear()
    open_window(shop)
    from ziira.kernel import notifications

    with system(shop) as s:                                    # queued while the plugin is on...
        made = notifications.queue(s, company_id=shop["company_id"], channel="whatsapp", recipient="0722000111",
                                   body="Before it went off", dedupe_key="off-1",
                                   fallbacks=[{"channel": "sms", "recipient": "0722000111"}])
    registry.disable(shop["tenant_id"], "leadsintel")           # ...and the plugin goes off before it is sent
    try:
        assert "whatsapp" not in available_names(client, shop)
        assert client.get(f"/api/v1/companies/{co}/settings", headers=shop["owner"]).json()["intel_alert_channel"] == "whatsapp"
        r = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"reminder_channel": "whatsapp"})
        assert r.status_code == 422 and "not available" in r.json()["message"]       # choosing it now is refused
        r = client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"],
                         json={"intel_alert_channel": "whatsapp", "intel_alert_min_severity": "high"})
        assert r.status_code == 200 and r.json()["intel_alert_channel"] == "whatsapp"   # the kept value is not an error
        r = client.put("/api/v1/notifications/me/preferences", headers=shop["owner"],
                       json={"channels": {"approvals": "whatsapp"}})
        assert r.status_code == 422
        assert client.get(f"{LI}/state", headers=shop["owner"], params={"company_id": co}).status_code != 200
        assert post(client, text_in(STRANGER, "hello")).status_code == 401              # nothing is received either
        run_jobs(shop)
        assert [m.recipient for m in FakeSms.sent] == ["254722000111"]                  # not lost: the next way
        assert one(shop, "select status from kernel.notification where id = :i", i=str(made)) == "skipped"
        # Intelligence carries on: the alert setting still says whatsapp, so the alert goes by email, and suggestions are
        # made and wait in the app (no channel with reply buttons exists, and nothing breaks).
        PLAN["candidates"] = [cand("off1")]
        before = notifications_count(shop)
        announced = one(shop, "select count(*) from kernel.notification where body like '%Ziira suggests%'")
        with system(shop) as s:
            engine.run_company(s, shop["company_id"], today=date(2026, 10, 16), only={"test.reply"})
            assert alerts.send_alerts(s, shop["company_id"]) >= 1
        run_jobs(shop)
        assert any(m.recipient == "owner@li-co.test" for m in FakeEmail.sent)
        assert notifications_count(shop) > before
        assert one(shop, "select count(*) from intel.action_proposal p join intel.finding f on f.id = p.finding_id "
                         "where f.summary = 'Problem off1'") == 1
        assert one(shop, "select count(*) from kernel.notification where body like '%Ziira suggests%'") == announced
    finally:
        registry.enable(shop["tenant_id"], "leadsintel")
    assert "whatsapp" in available_names(client, shop)                                  # back, and working again
    assert client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"],
                        json={"reminder_channel": "whatsapp"}).status_code == 200
    client.patch(f"/api/v1/companies/{co}/settings", headers=shop["owner"], json={"reminder_channel": "off"})
    since = len(li.seen("POST", "/send"))
    open_window(shop, "254722000999")
    queue_whatsapp(shop, "Back again", to="0722000999", dedupe_key="off-2")
    run_jobs(shop)
    assert len(li.seen("POST", "/send")) == since + 1
    assert post(client, text_in(STRANGER, "hello again")).status_code == 202


def test_with_the_plugin_on_a_proposal_is_announced_only_to_people_who_verified_a_number(client, shop, li) -> None:  # type: ignore[no-untyped-def]
    verify_number(shop, "owner", OWNER_PHONE)
    since = len(li.seen("POST", "/send"))
    pid, _ = make_proposal(shop, "on1")
    run_jobs(shop)
    announced = [m for m in sent_texts(li, since) if m["type"] == "buttons"]
    assert [m["to"] for m in announced] == [OWNER_PHONE]
    assert announced[0]["buttons"][0]["id"] == f"approve:{pid}"
