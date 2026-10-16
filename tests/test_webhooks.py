"""Outgoing webhooks: signing (against an independent verifier), delivery, retries, 410, SSRF, log and redelivery,
permissions, isolation and privacy. The network and DNS are replaced by fakes; nothing leaves the machine."""

import hashlib
import hmac
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from ziira.kernel import jobs, outbox, webhooks
from ziira.kernel.config import get_settings
from ziira.kernel.context import system_context
from ziira.kernel.db import tenant_session
from ziira.kernel.events import Event
from ziira.kernel.registry import discover
from ziira.sdk.testing import FakeHttp, fake_http

WH = "/api/v1/webhooks"
PUBLIC_IP = "93.184.216.34"
URL = "https://hooks.example.test/in"


# --------------------------------------------------------------------------- the receiver, as in docs/webhooks.md
def load_documented_verifier():  # type: ignore[no-untyped-def]
    """The Python receiver snippet from the docs, so the documentation cannot drift from the signing code."""
    doc = (Path(__file__).resolve().parent.parent / "docs" / "webhooks.md").read_text()
    block = re.search(r"```python\n(# --- ziira webhook receiver.*?)```", doc, re.DOTALL)
    assert block, "docs/webhooks.md has no receiver snippet"
    namespace: dict[str, object] = {}
    exec(block.group(1), namespace)                                          # noqa: S102 - our own documentation
    return namespace["verify_ziira_webhook"]


def reference_verify(secret: str, headers: dict[str, str], body: bytes, now: float | None = None,
                     tolerance: int = 300) -> bool:
    """An independent implementation of the documented scheme: HMAC-SHA256 over '{timestamp}.{body}', 'v1=' hex."""
    stamp = headers["ziira-timestamp"]
    expected = "v1=" + hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    fresh = abs((now or time.time()) - int(stamp)) <= tolerance
    return fresh and hmac.compare_digest(expected, headers["ziira-signature"])


# --------------------------------------------------------------------------- setup
@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    t = make_tenant("Webhook Shop")
    registry.enable(t["tenant_id"], "crm")
    other = make_tenant("Webhook Other")
    registry.enable(other["tenant_id"], "crm")
    owner = sign_in(client, "webhook-shop", "owner@webhook-shop.test").headers
    cashier = client.post("/api/v1/users", headers=owner, json={
        "full_name": "Till", "email": "till@webhook-shop.test", "password": "till-pass-123"}).json()
    roles = {r["name"]: r["id"] for r in client.get("/api/v1/roles", headers=owner).json()}
    client.post(f"/api/v1/users/{cashier['id']}/roles", headers=owner, json={
        "role_id": roles["Branch Manager"], "scope": "company", "company_id": str(t["company_id"])})
    return {**t, "owner": owner, "manager": sign_in(client, "webhook-shop", "till@webhook-shop.test", "till-pass-123").headers,
            "other": other, "other_owner": sign_in(client, "webhook-other", "owner@webhook-other.test").headers}


@pytest.fixture(autouse=True)
def network():  # type: ignore[no-untyped-def]
    """Every test: DNS answers a public address and the transport is a fake that says 200 unless a test changes it."""
    fake = fake_http(200)
    webhooks.use_resolver(lambda host: [PUBLIC_IP])
    webhooks.use_transport(fake.transport())
    yield fake
    webhooks.use_resolver(None)
    webhooks.use_transport(None)


def use(fake: FakeHttp) -> FakeHttp:
    webhooks.use_transport(fake.transport())
    return fake


def make_endpoint(client, shop, events=("customer.created",), url=URL, **extra):  # type: ignore[no-untyped-def]
    r = client.post(f"{WH}/endpoints", headers=shop["owner"],
                    json={"name": "My shop system", "url": url, "event_types": list(events), **extra})
    assert r.status_code == 201, r.text
    return r.json()["endpoint"], r.json()["secret"]


def new_customer(client, shop, owner="owner", name="Wanjiku Hardware"):  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/crm/customers", headers=shop[owner], json={"company_id": str(shop["company_id"]),
                                                                        "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def drain(shop) -> None:  # type: ignore[no-untyped-def]
    """Deliver the outbox, then run the webhook jobs that are due, for this business."""
    outbox.process_tenant(shop["tenant_id"])
    jobs.run_due(shop["tenant_id"])


def make_due(shop) -> None:  # type: ignore[no-untyped-def]
    system_context(shop["tenant_id"])
    with tenant_session(shop["tenant_id"]) as s:
        s.execute(text("update kernel.job set run_at = now() where job_type = 'webhooks.deliver' and status = 'queued'"))


def deliveries(client, shop, endpoint, **params):  # type: ignore[no-untyped-def]
    r = client.get(f"{WH}/endpoints/{endpoint['id']}/deliveries", headers=shop["owner"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def clean(client, shop) -> None:  # type: ignore[no-untyped-def]
    for e in client.get(f"{WH}/endpoints", headers=shop["owner"]).json():
        client.delete(f"{WH}/endpoints/{e['id']}", headers=shop["owner"])


@pytest.fixture(autouse=True)
def tidy(client, shop):  # type: ignore[no-untyped-def]
    clean(client, shop)
    drain(shop)
    yield


# --------------------------------------------------------------------------- the catalogue and privacy of payloads
def test_the_catalogue_lists_public_events_and_only_their_fields(client, shop) -> None:  # type: ignore[no-untyped-def]
    events = {e["type"]: e for e in client.get(f"{WH}/events", headers=shop["owner"]).json()}
    assert {"sale.posted", "sale.returned", "invoice.issued", "goods.received", "payment.received",
            "stock.below_reorder", "finding.created", "customer.created", "product.created"} <= set(events)
    assert "cashier_id" not in events["sale.posted"]["fields"] and "till_session_id" not in events["sale.posted"]["fields"]
    assert events["customer.created"]["fields"] == ["company_id", "code"]            # not the customer's name
    assert "summary" not in events["finding.created"]["fields"]
    assert "stock.moved" not in events                                                # internal events stay internal


def test_the_body_holds_only_listed_fields_and_never_secrets() -> None:
    webhooks.register_public_events(discover())
    tenant, aggregate = uuid4(), uuid4()
    event = Event("sale.posted", "pos.sale", aggregate, {
        "company_id": "c", "number": "S-1", "cashier_id": "someone", "customer_id": "cu", "api_token": "tok",
        "lines": [{"product_id": "p", "quantity": "2", "secret": "no", "password_hash": "no"}], "extra": "no"})
    body = json.loads(webhooks.build_body(uuid4(), event, datetime.now(UTC), tenant))
    assert set(body) == {"id", "type", "created_at", "business_id", "aggregate", "data"}
    assert body["aggregate"] == {"type": "pos.sale", "id": str(aggregate)} and body["business_id"] == str(tenant)
    assert body["data"] == {"company_id": "c", "number": "S-1", "customer_id": "cu",
                            "lines": [{"product_id": "p", "quantity": "2"}]}


def test_a_customers_name_never_leaves_in_the_webhook(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    make_endpoint(client, shop)
    customer = new_customer(client, shop, name="Jane Wanjiku Secret-Name")
    drain(shop)
    sent = json.loads(network.requests[0].content)
    assert sent["type"] == "customer.created" and sent["aggregate"]["id"] == customer["id"]
    assert set(sent["data"]) == {"company_id", "code"} and "Secret-Name" not in network.requests[0].content.decode()


# --------------------------------------------------------------------------- signing
def test_deliveries_are_signed_and_verify_with_an_independent_receiver(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    endpoint, secret = make_endpoint(client, shop)
    assert secret.startswith("whsec_") and endpoint["secret_hint"] == secret[-4:]
    new_customer(client, shop)
    drain(shop)
    request = network.requests[0]
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert request.method == "POST" and headers["content-type"] == "application/json"
    assert headers["ziira-signature"].startswith("v1=") and headers["ziira-event-id"]
    assert reference_verify(secret, headers, request.content)
    assert load_documented_verifier()(secret, headers, request.content)                  # the documented snippet agrees
    assert not reference_verify("whsec_wrong", headers, request.content)                  # wrong secret
    assert not reference_verify(secret, headers, request.content + b" ")                  # altered body
    assert not reference_verify(secret, headers, request.content, now=time.time() + 3600)  # replayed later
    assert not load_documented_verifier()(secret, headers, request.content + b" ")
    # connections go to the address that was checked, with the host name kept in the Host header
    assert request.url.host == PUBLIC_IP and request.headers["host"] == "hooks.example.test"


def test_the_secret_is_shown_once_and_a_new_one_replaces_the_old(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    endpoint, secret = make_endpoint(client, shop)
    for r in (client.get(f"{WH}/endpoints", headers=shop["owner"]),
              client.get(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"])):
        assert secret not in r.text and "ciphertext" not in r.text
    new = client.post(f"{WH}/endpoints/{endpoint['id']}/secret", headers=shop["owner"]).json()["secret"]
    assert new != secret
    new_customer(client, shop)
    drain(shop)
    request = network.requests[-1]
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert reference_verify(new, headers, request.content) and not reference_verify(secret, headers, request.content)


# --------------------------------------------------------------------------- delivery, log, test ping, redelivery
def test_a_request_never_waits_for_the_customers_server(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    make_endpoint(client, shop)
    new_customer(client, shop)
    assert network.requests == []                          # nothing sent while the request ran, nor before the outbox ran
    outbox.process_tenant(shop["tenant_id"])
    assert network.requests == []                          # a job is queued; the worker sends it
    jobs.run_due(shop["tenant_id"])
    assert len(network.requests) == 1


def test_the_delivery_log_records_the_result_and_the_attempt(client, shop) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    assert d["status"] == "delivered" and d["attempts"] == 1 and d["last_status_code"] == 200 and d["has_body"]
    detail = client.get(f"{WH}/deliveries/{d['id']}", headers=shop["owner"]).json()
    assert detail["event_type"] == "customer.created" and len(detail["body_sha256"]) == 64
    assert detail["body_preview"].startswith("{") and len(detail["body_preview"]) <= webhooks.PREVIEW_BYTES
    assert [(a["ok"], a["status_code"]) for a in detail["attempt_log"]] == [(True, 200)]
    assert client.get(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"]).json()["last_success_at"]
    assert deliveries(client, shop, endpoint, status="failed") == []


def test_the_test_ping_is_queued_and_delivered_in_the_background(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    endpoint, secret = make_endpoint(client, shop)
    queued = client.post(f"{WH}/endpoints/{endpoint['id']}/ping", headers=shop["owner"])
    assert queued.status_code == 202 and network.requests == []
    drain(shop)
    sent = json.loads(network.requests[0].content)
    assert sent["type"] == "webhook.ping" and sent["data"] == {}
    [d] = deliveries(client, shop, endpoint)
    assert d["is_test"] and d["status"] == "delivered" and d["id"] == queued.json()["delivery_id"]


def test_redelivery_sends_the_same_event_id_again(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    again = client.post(f"{WH}/deliveries/{d['id']}/redeliver", headers=shop["owner"])
    assert again.status_code == 202
    assert client.post(f"{WH}/deliveries/{d['id']}/redeliver", headers=shop["owner"]).status_code == 409   # still pending
    drain(shop)
    assert len(network.requests) == 2
    assert network.requests[0].headers["ziira-event-id"] == network.requests[1].headers["ziira-event-id"] == d["event_id"]
    assert network.requests[0].content == network.requests[1].content
    [d2] = deliveries(client, shop, endpoint)
    assert d2["status"] == "delivered" and d2["attempts"] == 1
    detail = client.get(f"{WH}/deliveries/{d['id']}", headers=shop["owner"]).json()
    assert len(detail["attempt_log"]) == 2                                          # the log keeps both


def test_a_delivery_whose_content_is_no_longer_kept_cannot_be_sent_again(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    monkeypatch.setattr(get_settings(), "webhook_body_days", 0)
    system_context(shop["tenant_id"])
    assert jobs.run_periodic(shop["tenant_id"], only="kernel.webhook_purge", force=True) == 1
    [d] = deliveries(client, shop, endpoint)
    assert d["has_body"] is False and d["status"] == "delivered"
    detail = client.get(f"{WH}/deliveries/{d['id']}", headers=shop["owner"]).json()
    assert len(detail["body_sha256"]) == 64 and detail["body_preview"]                  # the hash and first bytes stay
    assert client.post(f"{WH}/deliveries/{d['id']}/redeliver", headers=shop["owner"]).status_code == 409


# --------------------------------------------------------------------------- retries, give-up, 410
def test_backoff_grows_and_is_capped() -> None:
    assert [webhooks.backoff_seconds(n) for n in range(1, 9)] == [30, 120, 480, 1920, 7680, 30720, 43200, 43200]


def test_a_failing_receiver_is_retried_with_growing_waits_until_it_answers(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    answers = iter([500, 503, 200])
    use(fake_http(lambda request: httpx.Response(next(answers))))
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    assert (d["status"], d["attempts"], d["last_status_code"]) == ("pending", 1, 500) and d["next_attempt_at"]
    drain(shop)                                                                       # not due yet: nothing happens
    assert deliveries(client, shop, endpoint)[0]["attempts"] == 1
    make_due(shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    assert (d["status"], d["attempts"], d["last_status_code"]) == ("pending", 2, 503)
    make_due(shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    assert (d["status"], d["attempts"], d["last_status_code"]) == ("delivered", 3, 200)
    log = client.get(f"{WH}/deliveries/{d['id']}", headers=shop["owner"]).json()["attempt_log"]
    assert [(a["ok"], a["status_code"]) for a in log] == [(False, 500), (False, 503), (True, 200)]
    ep = client.get(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"]).json()
    assert ep["consecutive_failures"] == 0 and ep["status"] == "active"


def test_a_delivery_gives_up_after_its_attempts_and_is_flagged(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "webhook_max_attempts", 2)
    use(fake_http(500))
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    make_due(shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    assert (d["status"], d["attempts"]) == ("failed", 2) and d["next_attempt_at"] is None
    ep = client.get(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"]).json()
    assert ep["status"] == "active" and ep["consecutive_failures"] == 1
    assert "webhook_failing" in kinds_in_inbox(shop)


def kinds_in_inbox(shop) -> set[str]:  # type: ignore[no-untyped-def]
    system_context(shop["tenant_id"])
    with tenant_session(shop["tenant_id"]) as s:
        return set(s.execute(text("select kind from kernel.exception_item")).scalars())


def test_a_receiver_that_answers_410_is_switched_off_and_flagged(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    use(fake_http(410))
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    new_customer(client, shop, name="Second")
    drain(shop)
    ep = client.get(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"]).json()
    assert ep["status"] == "disabled" and "410" in ep["disabled_reason"]
    assert "webhook_disabled" in kinds_in_inbox(shop)
    statuses = {d["status"] for d in deliveries(client, shop, endpoint)}
    assert statuses <= {"failed", "cancelled"}                                      # nothing left waiting to be retried
    new_customer(client, shop, name="Third")
    drain(shop)
    assert len(deliveries(client, shop, endpoint)) == 2                              # a disabled endpoint gets nothing new
    use(fake_http(200))
    back = client.patch(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"], json={"status": "active"}).json()
    assert back["status"] == "active" and back["disabled_reason"] is None and back["consecutive_failures"] == 0


def test_timeouts_and_redirects_are_failures_and_redirects_are_not_followed(client, shop) -> None:  # type: ignore[no-untyped-def]
    def timeout(request):  # type: ignore[no-untyped-def]
        raise httpx.ReadTimeout("slow", request=request)

    use(fake_http(timeout))
    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    assert "in time" in deliveries(client, shop, endpoint)[0]["last_error"]
    redirected = use(fake_http(lambda request: httpx.Response(301, headers={"location": "http://169.254.169.254/"})))
    make_due(shop)
    drain(shop)
    assert deliveries(client, shop, endpoint)[0]["last_status_code"] == 301
    assert len(redirected.requests) == 1                                              # the redirect was not followed


# --------------------------------------------------------------------------- addresses (SSRF)
@pytest.mark.parametrize("url", [
    "http://hooks.example.test/in", "ftp://hooks.example.test/in", "https://localhost/in", "https://127.0.0.1/in",
    "https://[::1]/in", "https://10.0.0.5/in", "https://192.168.1.10/in", "https://172.16.0.1/in",
    "https://169.254.169.254/latest/meta-data", "https://100.64.0.1/in", "https://0.0.0.0/in",
    "https://[::ffff:10.0.0.1]/in", "https://[fd00::1]/in", "https://user:pass@hooks.example.test/in",
    "https://", "not a url", "https://hooks.example.test:99999/in", "//hooks.example.test/in"])
def test_addresses_that_reach_inside_are_refused(client, shop, monkeypatch, url) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "env", "production")
    r = client.post(f"{WH}/endpoints", headers=shop["owner"],
                    json={"name": "x", "url": url, "event_types": ["customer.created"]})
    assert r.status_code == 422, (url, r.status_code, r.text)


def test_a_host_name_that_resolves_to_a_private_or_mixed_address_is_refused(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "env", "production")
    for answer in (["10.1.2.3"], [PUBLIC_IP, "10.1.2.3"], ["169.254.169.254"], []):
        webhooks.use_resolver(lambda host, a=answer: a)
        r = client.post(f"{WH}/endpoints", headers=shop["owner"],
                        json={"name": "x", "url": URL, "event_types": ["customer.created"]})
        assert r.status_code == 422, (answer, r.text)


def test_localhost_over_http_is_allowed_in_development_only(client, shop, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    local = {"name": "Local", "url": "http://localhost:9999/hook", "event_types": ["customer.created"]}
    assert client.post(f"{WH}/endpoints", headers=shop["owner"], json=local).status_code == 201
    assert client.post(f"{WH}/endpoints", headers=shop["owner"],
                       json={**local, "url": "http://example.com/hook"}).status_code == 422     # http elsewhere: never
    monkeypatch.setattr(get_settings(), "env", "production")
    assert client.post(f"{WH}/endpoints", headers=shop["owner"], json=local).status_code == 422


def test_the_address_is_looked_up_again_at_every_delivery(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)                                       # fine when it was saved ...
    webhooks.use_resolver(lambda host: ["10.0.0.9"])                                # ... and later points inside
    new_customer(client, shop)
    drain(shop)
    assert network.requests == []                                                    # nothing was sent
    [d] = deliveries(client, shop, endpoint)
    assert d["last_status_code"] is None and "not allowed" in d["last_error"]


# --------------------------------------------------------------------------- management, permissions, isolation
def test_pausing_stops_sending_and_resuming_starts_again(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)
    assert client.patch(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"], json={"status": "paused"}).status_code == 200
    new_customer(client, shop)
    drain(shop)
    assert network.requests == [] and deliveries(client, shop, endpoint) == []
    client.patch(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"], json={"status": "active"})
    new_customer(client, shop, name="After")
    drain(shop)
    assert len(network.requests) == 1


def test_only_subscribed_events_are_sent(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    make_endpoint(client, shop, events=["sale.posted"])
    new_customer(client, shop)
    drain(shop)
    assert network.requests == []


def test_an_endpoint_can_be_edited_and_deleted_and_inputs_are_checked(client, shop) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)
    ok = client.patch(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"],
                      json={"name": "Renamed", "event_types": ["customer.created", "product.created"]})
    assert ok.status_code == 200 and ok.json()["name"] == "Renamed" and len(ok.json()["event_types"]) == 2
    for bad in ({"event_types": ["stock.moved"]}, {"event_types": []}, {"url": "https://10.0.0.1/x"}, {"name": " "},
                {"status": "disabled"}, {"unknown": 1}):
        assert client.patch(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"], json=bad).status_code == 422, bad
    assert client.delete(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"]).status_code == 204
    assert client.get(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"]).status_code == 404


def test_at_most_twenty_endpoints(client, shop) -> None:  # type: ignore[no-untyped-def]
    for n in range(webhooks.MAX_ENDPOINTS):
        make_endpoint(client, shop, url=f"https://hooks.example.test/{n}")
    r = client.post(f"{WH}/endpoints", headers=shop["owner"],
                    json={"name": "one too many", "url": URL, "event_types": ["customer.created"]})
    assert r.status_code == 409


def test_only_people_with_webhooks_manage_may_use_webhooks(client, shop) -> None:  # type: ignore[no-untyped-def]
    endpoint, _ = make_endpoint(client, shop)
    body = {"name": "x", "url": URL, "event_types": ["customer.created"]}
    calls = [("get", f"{WH}/events", None), ("get", f"{WH}/endpoints", None), ("post", f"{WH}/endpoints", body),
             ("get", f"{WH}/endpoints/{endpoint['id']}", None), ("patch", f"{WH}/endpoints/{endpoint['id']}", {"name": "y"}),
             ("delete", f"{WH}/endpoints/{endpoint['id']}", None),
             ("post", f"{WH}/endpoints/{endpoint['id']}/secret", None), ("post", f"{WH}/endpoints/{endpoint['id']}/ping", None),
             ("get", f"{WH}/endpoints/{endpoint['id']}/deliveries", None),
             ("get", f"{WH}/deliveries/{uuid4()}", None), ("post", f"{WH}/deliveries/{uuid4()}/redeliver", None)]
    for method, url, payload in calls:
        assert client.request(method, url, json=payload).status_code == 401, (method, url)
        assert client.request(method, url, headers=shop["manager"], json=payload).status_code == 403, (method, url)


def test_one_business_cannot_see_or_trigger_anothers_webhooks(client, shop, network) -> None:  # type: ignore[no-untyped-def]
    mine, _ = make_endpoint(client, shop)
    other = shop["other"]
    r = client.post(f"{WH}/endpoints", headers=shop["other_owner"],
                    json={"name": "theirs", "url": URL, "event_types": ["customer.created"]})
    theirs = r.json()["endpoint"]
    assert client.get(f"{WH}/endpoints", headers=shop["other_owner"]).json() == [theirs]
    for method, url in (("get", f"{WH}/endpoints/{mine['id']}"), ("delete", f"{WH}/endpoints/{mine['id']}"),
                        ("post", f"{WH}/endpoints/{mine['id']}/ping"), ("post", f"{WH}/endpoints/{mine['id']}/secret"),
                        ("get", f"{WH}/endpoints/{mine['id']}/deliveries")):
        assert client.request(method, url, headers=shop["other_owner"]).status_code == 404, (method, url)
    new_customer(client, shop)
    drain(shop)
    outbox.process_tenant(other["tenant_id"])
    jobs.run_due(other["tenant_id"])
    assert len(network.requests) == 1                                                 # only my own endpoint was called
    assert client.get(f"{WH}/endpoints/{theirs['id']}/deliveries", headers=shop["other_owner"]).json() == []
    delivery = deliveries(client, shop, mine)[0]
    assert client.get(f"{WH}/deliveries/{delivery['id']}", headers=shop["other_owner"]).status_code == 404
    assert client.post(f"{WH}/deliveries/{delivery['id']}/redeliver", headers=shop["other_owner"]).status_code == 404
    client.delete(f"{WH}/endpoints/{theirs['id']}", headers=shop["other_owner"])


def test_every_change_is_audited_without_the_secret(client, shop) -> None:  # type: ignore[no-untyped-def]
    endpoint, secret = make_endpoint(client, shop)
    client.post(f"{WH}/endpoints/{endpoint['id']}/secret", headers=shop["owner"])
    client.delete(f"{WH}/endpoints/{endpoint['id']}", headers=shop["owner"])
    system_context(shop["tenant_id"])
    with tenant_session(shop["tenant_id"]) as s:
        rows = s.execute(text("select action, changes::text as changes from kernel.audit_log "
                              "where entity_type = 'kernel.webhook_endpoint' and entity_id = :i order by id"),
                         {"i": endpoint["id"]}).all()
    assert [r.action for r in rows] == ["create", "rotate_secret", "delete"]
    assert secret not in "".join(r.changes or "" for r in rows) and "whsec_" not in "".join(r.changes or "" for r in rows)


# --------------------------------------------------------------------------- personal data
def test_privacy_finds_exports_and_removes_content_that_mentions_a_person(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.personal_data import Subject
    from ziira.kernel.privacy_providers import WebhookDeliveryData

    endpoint, _ = make_endpoint(client, shop)
    new_customer(client, shop)
    drain(shop)
    [d] = deliveries(client, shop, endpoint)
    provider, subject = WebhookDeliveryData(), Subject(raw="jane@example.com", email="jane@example.com")
    system_context(shop["tenant_id"])
    with tenant_session(shop["tenant_id"]) as s:
        assert provider.find(s, shop["company_id"], subject) == []                     # ids and codes only: no person in it
        s.execute(text("update kernel.webhook_delivery set body = body || ' jane@example.com' where id = :i"), {"i": d["id"]})
        [record] = provider.find(s, shop["company_id"], subject)
        assert provider.export(s, record)["deliveries"][0]["event"] == "customer.created"
        assert provider.anonymise(s, record, "request").status == "anonymised"
        assert provider.find(s, shop["company_id"], subject) == []
        assert provider.retention(s, shop["company_id"])[0].code == "webhooks"
    assert deliveries(client, shop, endpoint)[0]["has_body"] is False
