"""Self-service subscription payments: the gateway settings, what is offered, an attempt from start to credit, the
signed notifications of each provider, confirm-before-credit, recovery of lost notifications, concurrency and secrets.

No test reaches a real service: every provider call goes through an `httpx.MockTransport` (see `Provider` below).
Numbers are worked out by hand in the comments."""

import hashlib
import hmac
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D  # noqa: N817
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from tests.conftest import make_tenant, sign_in
from tests.platform_helpers import API, make_plan, staff
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import TooManyRequests, ValidationFailed
from ziira.kernel.platform import billing, gateways, payments, settings, subscriptions
from ziira.plugins.billing_paystack import gateway as paystack_gateway
from ziira.plugins.billing_stripe import gateway as stripe_gateway
from ziira.plugins.billing_sunpay.gateway import SunPayGateway, normalise_phone
from ziira.plugins.messaging.providers import FakeEmail

SUN_KEY, SUN_SECRET = "sp_live_KEY_123", "sunpay-webhook-secret"
STRIPE_KEY, STRIPE_SECRET = "sk_test_STRIPEKEY", "whsec_stripe"
PAYSTACK_KEY = "sk_test_PAYSTACKKEY"


class Provider:
    """A scripted provider: records every request and answers from `routes` ({(METHOD, path): handler})."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
        for (method, path), answer in self.routes.items():
            if request.method == method and request.url.path.startswith(path):
                return answer(request)
        return httpx.Response(404, json={"message": "not found"})

    def sent(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.startswith(path)]


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Provider:
    p = Provider()
    monkeypatch.setattr(gateways, "http_client_factory", lambda: httpx.Client(transport=httpx.MockTransport(p.handler)))
    return p


@pytest.fixture(scope="module")
def world(client, registry):  # type: ignore[no-untyped-def]
    settings.set_value("billing.tax_lines", [], "test")
    settings.set_value("billing.payment_instructions", "Pay by bank transfer to account 0001", "test")
    make_plan("pay-basic", units=["products"], prices={("KES", "month"): "3500.00", ("KES", "year"): "35000.00",
                                                       ("USD", "month"): "30.00", ("JPY", "month"): "4500"})
    make_plan("pay-usd", units=["products"], prices={("USD", "month"): "30.00"})
    boss = staff(client, "superadmin")
    for name, secrets, config in (
        ("sunpay", {"api_key": SUN_KEY, "webhook_secret": SUN_SECRET}, {}),
        ("stripe", {"secret_key": STRIPE_KEY, "webhook_secret": STRIPE_SECRET}, {}),
        ("paystack", {"secret_key": PAYSTACK_KEY}, {}),
    ):
        payments.save_gateway(name, enabled=True, config=config, secrets=secrets, clear_secrets=None,
                              default_for=None, by="test")
    yield {"boss": boss, "billing": staff(client, "billing"), "viewer": staff(client, "readonly")}
    for name in ("sunpay", "stripe", "paystack"):
        with master_session() as m:
            m.execute(text("update master.payment_gateway set enabled = false where name = :n"), {"n": name})


def business(client, name: str, *, currency: str = "KES", amount: str = "3500.00", suspended: bool = False,
             country: str | None = None) -> dict[str, Any]:
    """A business with an owner, a subscription and one issued renewal invoice of `amount` `currency`."""
    t = make_tenant(name)
    code = name.lower().replace(" ", "-")
    subscriptions.start(t["tenant_id"], "pay-basic", currency="KES", mode="active")
    if country:
        with tenant_session(t["tenant_id"], admin=True) as s:
            s.execute(text("update kernel.company set country = :c"), {"c": country})
    now = datetime.now(UTC)
    invoice = billing.create_invoice(
        tenant_id=t["tenant_id"], currency=currency, kind="renewal", issue=True,
        lines=[{"description": "Pay Basic (month)", "unit_amount": amount}],
        period_start=now, period_end=now + timedelta(days=30))
    if suspended:
        subscriptions.suspend(t["tenant_id"], "unpaid for the test")
    owner = sign_in(client, code, f"owner@{code}.test", device_id=f"d-{code}").headers
    return {**t, "code": code, "invoice": invoice, "owner": owner}


def pay_sunpay(client, b: dict[str, Any], phone: str = "0712 345 678") -> httpx.Response:
    return client.post(f"{API}/billing/payments", headers=b["owner"],
                       json={"invoice_id": str(b["invoice"]["id"]), "provider": "sunpay", "payer": {"phone": phone}})


def sunpay_routes(p: Provider, states: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """STK push answers with transactionId tx-N; the status endpoint reads `states[txn]` (pending by default)."""
    states = {} if states is None else states
    counter = iter(range(1, 1000))

    def push(request: httpx.Request) -> httpx.Response:
        n = next(counter)
        states.setdefault(f"tx-{n}", {"status": "pending"})
        return httpx.Response(200, json={"success": True, "message": "Prompt sent", "transactionId": f"tx-{n}",
                                         "checkoutRequestId": f"ws_CO_{n}"})

    def status(request: httpx.Request) -> httpx.Response:
        txn = request.url.path.rsplit("/", 1)[-1]
        if txn not in states:
            return httpx.Response(404, json={"message": "no such payment"})
        return httpx.Response(200, json={"id": txn, **states[txn]})

    p.routes[("POST", "/api/v1/payments/stk-push")] = push
    p.routes[("GET", "/api/v1/payments/")] = status
    return states


def sun_webhook(event: str, txn: str, invoice_number: str = "", secret: str = SUN_SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps({"event": event, "timestamp": "2030-01-01T00:00:00Z",
                       "data": {"transactionId": txn, "externalRef": invoice_number, "status": "completed",
                                "mpesaRef": "QWE123", "amount": "3500", "resultCode": 0}}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Webhook-Signature": sig, "Content-Type": "application/json"}


def post_sun(client, body: bytes, headers: dict[str, str]) -> httpx.Response:
    return client.post(f"{API}/billing/webhooks/sunpay", content=body, headers=headers)


def invoice_of(b: dict[str, Any]) -> dict[str, Any]:
    return billing.get_invoice(b["invoice"]["id"])


def _forget_last_check(attempt_id: str) -> None:
    """Pretend the last look at the provider was a while ago (the poll and "check again" are throttled)."""
    with master_session() as m:
        m.execute(text("update master.payment_attempt set last_checked_at = now() - interval '1 minute' "
                       "where id = :i"), {"i": attempt_id})


def attempts_of(b: dict[str, Any]) -> list[dict[str, Any]]:
    return payments.list_attempts(invoice_id=b["invoice"]["id"])


# --------------------------------------------------------------------------- SunPay: pure rules
@pytest.mark.parametrize("typed", ["0712345678", "0712 345 678", "+254712345678", "254712345678", "712345678",
                                   "0112345678", "07-12-345-678"])
def test_phone_numbers_are_normalised_to_the_provider_form(typed: str) -> None:
    expected = "254112345678" if typed == "0112345678" else "254712345678"
    assert normalise_phone(typed) == expected


@pytest.mark.parametrize("typed", ["", "12345", "0812345678", "+44 7911 123456", "abcdefghij", "07123456789"])
def test_invalid_phone_numbers_are_refused(typed: str) -> None:
    with pytest.raises(ValidationFailed):
        normalise_phone(typed)


def test_the_provider_declares_itself_as_data() -> None:
    g = SunPayGateway()
    assert (g.currencies, g.countries, g.flow, g.payment_method) == (("KES",), ("KE",), "prompt", "mobile_money")
    assert [f.name for f in g.config_fields if f.secret] == ["api_key", "webhook_secret"]
    assert g.payer_fields[0].help == "The number that will receive the M-Pesa prompt"
    assert g.config_fields[0].default == "https://sunpay.co.ke"


# --------------------------------------------------------------------------- what is offered
def test_a_kes_invoice_offers_mpesa_and_a_usd_invoice_does_not(client, world) -> None:  # type: ignore[no-untyped-def]
    kes = business(client, "Pay Offer Kes")
    r = client.get(f"{API}/billing/pay/options", headers=kes["owner"], params={"invoice_id": str(kes["invoice"]["id"])})
    assert r.status_code == 200, r.text
    labels = {o["provider"]: o for o in r.json()["options"]}
    assert set(labels) == {"sunpay", "stripe", "paystack"}                      # all three serve KES (Stripe: any)
    assert labels["sunpay"]["flow"] == "prompt" and labels["stripe"]["flow"] == "redirect"
    assert labels["sunpay"]["payer_fields"][0]["name"] == "phone"
    usd = business(client, "Pay Offer Usd", currency="USD", amount="30.00")
    r = client.get(f"{API}/billing/pay/options", headers=usd["owner"], params={"invoice_id": str(usd["invoice"]["id"])})
    assert {o["provider"] for o in r.json()["options"]} == {"stripe", "paystack"}    # Paystack serves USD, SunPay not
    assert "M-Pesa payments are in KES: ask us for a KES price" not in r.json()["hints"]       # others qualify: no hint


def test_when_nothing_qualifies_the_hint_and_manual_instructions_show(client, world) -> None:  # type: ignore[no-untyped-def]
    for name in ("stripe", "paystack"):
        payments.save_gateway(name, enabled=False, config=None, secrets=None, clear_secrets=None, default_for=None,
                              by="test")
    try:
        b = business(client, "Pay Offer Eur", currency="EUR", amount="30.00", country="KE")
        out = client.get(f"{API}/billing/pay/options", headers=b["owner"],
                         params={"invoice_id": str(b["invoice"]["id"])}).json()
        assert out["options"] == []
        assert out["hints"] == ["M-Pesa payments are in KES: ask us for a KES price"]
        assert out["payment_instructions"] == "Pay by bank transfer to account 0001"
        # and a payment is refused with that plain message
        r = client.post(f"{API}/billing/payments", headers=b["owner"],
                        json={"invoice_id": str(b["invoice"]["id"]), "provider": "sunpay", "payer": {"phone": "0712345678"}})
        assert r.status_code == 422 and "ask us for a KES price" in r.json()["message"]
    finally:
        for name in ("stripe", "paystack"):
            payments.save_gateway(name, enabled=True, config=None, secrets=None, clear_secrets=None, default_for=None,
                                  by="test")


def test_country_and_defaults_decide_what_is_offered_and_in_what_order(client, world) -> None:  # type: ignore[no-untyped-def]
    other = business(client, "Pay Country Other", country="GB")              # a KES invoice, but not in the M-Pesa country
    out = client.get(f"{API}/billing/pay/options", headers=other["owner"],
                     params={"invoice_id": str(other["invoice"]["id"])}).json()
    assert {o["provider"] for o in out["options"]} == {"stripe", "paystack"}
    home = business(client, "Pay Country Home", country="KE")
    payments.save_gateway("sunpay", enabled=None, config=None, secrets=None, clear_secrets=None, default_for=["ke"],
                          by="test")
    try:
        out = client.get(f"{API}/billing/pay/options", headers=home["owner"],
                         params={"invoice_id": str(home["invoice"]["id"])}).json()
        assert [o["provider"] for o in out["options"]][0] == "sunpay" and out["options"][0]["preferred"] is True
    finally:
        payments.save_gateway("sunpay", enabled=None, config=None, secrets=None, clear_secrets=None, default_for=[],
                              by="test")


# --------------------------------------------------------------------------- starting a payment
def test_the_stk_push_request_has_the_documented_shape(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    sunpay_routes(provider)
    b = business(client, "Pay Shape")
    r = pay_sunpay(client, b)
    assert r.status_code == 201, r.text
    [req] = provider.sent("POST", "/api/v1/payments/stk-push")
    assert str(req.url) == "https://sunpay.co.ke/api/v1/payments/stk-push"
    assert req.headers["authorization"] == f"Bearer {SUN_KEY}"
    # 3500.00 is sent as the number 3500, the phone in 254 form, the invoice number as externalRef
    assert json.loads(req.content) == {"phoneNumber": "254712345678", "amount": 3500,
                                       "externalRef": b["invoice"]["number"]}
    body = r.json()
    assert (body["status"], body["flow"], body["amount"], body["currency"], body["payer_phone_last4"]) == \
        ("pending", "prompt", "3500.00", "KES", "5678")
    assert "254712345678" not in r.text and "callbackUrl" not in req.content.decode()


def test_the_provider_address_is_a_setting(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    sunpay_routes(provider)
    payments.save_gateway("sunpay", enabled=None, config={"base_url": "https://pay.example.test/"}, secrets=None,
                          clear_secrets=None, default_for=None, by="test")
    try:
        pay_sunpay(client, business(client, "Pay Base Url"))
        assert provider.requests[0].url.host == "pay.example.test"
        with pytest.raises(ValidationFailed):
            payments.save_gateway("sunpay", enabled=None, config={"base_url": "http://evil.example"}, secrets=None,
                                  clear_secrets=None, default_for=None, by="test")
    finally:
        payments.save_gateway("sunpay", enabled=None, config={"base_url": ""}, secrets=None, clear_secrets=None,
                              default_for=None, by="test")


def test_a_second_click_returns_the_first_attempt_and_pushes_once(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    sunpay_routes(provider)
    b = business(client, "Pay Double")
    first, second = pay_sunpay(client, b), pay_sunpay(client, b)
    assert first.json()["id"] == second.json()["id"]
    assert len(provider.sent("POST", "/api/v1/payments/stk-push")) == 1 and len(attempts_of(b)) == 1


def test_an_invalid_number_is_refused_before_anything_is_sent(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    sunpay_routes(provider)
    r = pay_sunpay(client, business(client, "Pay Bad Phone"), phone="12345")
    assert r.status_code == 422 and provider.requests == []


def test_at_most_five_attempts_an_hour_per_business(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    sunpay_routes(provider)
    b = business(client, "Pay Rate Limit")
    for _ in range(5):
        attempt = pay_sunpay(client, b).json()
        payments._fail(UUID(attempt["id"]), "cancelled", "failed")            # close it so a new one may begin
    r = pay_sunpay(client, b)
    assert r.status_code == 429 and len(provider.sent("POST", "/api/v1/payments/stk-push")) == 5


def test_a_refusal_by_the_provider_is_shown_plainly_and_can_be_retried(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    provider.routes[("POST", "/api/v1/payments/stk-push")] = lambda r: httpx.Response(400, json={"message": "Bad phone"})
    b = business(client, "Pay Refused")
    r = pay_sunpay(client, b)
    assert r.status_code == 422 and r.json()["message"] == "Bad phone"
    assert attempts_of(b)[0]["status"] == "failed"
    provider.routes[("POST", "/api/v1/payments/stk-push")] = lambda r: httpx.Response(503, text="down")
    r = pay_sunpay(client, b)
    assert r.status_code == 503                                                   # retryable: try again later
    sunpay_routes(provider)
    assert pay_sunpay(client, b).status_code == 201                               # nothing blocks a fresh attempt


# --------------------------------------------------------------------------- notifications: signature and confirm-before-credit
def started(client, provider, name: str, **kw: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    states = sunpay_routes(provider)
    b = business(client, name, **kw)
    attempt = pay_sunpay(client, b).json()
    return b, states, attempt["id"]


def test_a_bad_missing_or_tampered_signature_is_refused_and_credits_nothing(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, _ = started(client, provider, "Pay Sig")
    txn = next(iter(states))
    states[txn] = {"status": "completed", "amount": "3500", "mpesaRef": "QWE123"}
    body, headers = sun_webhook("payment.completed", txn, b["invoice"]["number"])
    assert post_sun(client, body, {**headers, "X-Webhook-Signature": "0" * 64}).status_code == 401
    assert post_sun(client, body, {"Content-Type": "application/json"}).status_code == 401
    assert post_sun(client, body.replace(b"3500", b"1"), headers).status_code == 401          # tampered body
    wrong = sun_webhook("payment.completed", txn, secret="not-the-secret")
    assert post_sun(client, *wrong).status_code == 401
    assert invoice_of(b)["status"] == "issued" and invoice_of(b)["amount_paid"] == D("0")


def test_a_genuine_notification_credits_after_the_provider_confirms(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Success", suspended=True)
    assert subscriptions.get(b["tenant_id"])["status"] == "suspended"
    txn = next(iter(states))
    states[txn] = {"status": "completed", "amount": "3500", "mpesaRef": "TJK9XYZ"}
    before = len(FakeEmail.sent)
    body, headers = sun_webhook("payment.completed", txn, b["invoice"]["number"])
    r = post_sun(client, body, headers)
    assert r.status_code == 200 and r.json() == {"handled": 1}
    inv = invoice_of(b)
    assert (inv["status"], inv["amount_paid"]) == ("paid", D("3500.00"))
    [pay] = billing.list_payments(b["invoice"]["id"])
    assert (pay["method"], pay["reference"], pay["provider"], pay["amount"]) == \
        ("mobile_money", "TJK9XYZ", "sunpay", D("3500.00"))
    assert subscriptions.get(b["tenant_id"])["status"] == "active"                       # access is back at once
    got = client.get(f"{API}/billing/payments/{attempt_id}", headers=b["owner"]).json()
    assert (got["status"], got["payment_reference"], got["open"]) == ("completed", "TJK9XYZ", False)
    receipts = [m for m in FakeEmail.sent[before:] if "Receipt" in (m.subject or "") and m.recipient == f"owner@{b['code']}.test"]
    assert len(receipts) == 1 and "TJK9XYZ" in receipts[0].body and "/billing" in receipts[0].body
    page = client.get(f"{API}/billing/invoices/{b['invoice']['id']}/html", headers=b["owner"])
    assert "paid" in page.text.lower() and "3500.00" in page.text
    # a repeat of the same notification changes nothing, and neither does an unknown transaction
    assert post_sun(client, body, headers).json() == {"handled": 0}
    assert len(billing.list_payments(b["invoice"]["id"])) == 1
    unknown = sun_webhook("payment.completed", "tx-unknown")
    assert post_sun(client, *unknown).status_code == 200
    assert post_sun(client, *sun_webhook("withdrawal.completed", txn)).json() == {"handled": 0}


def test_a_notification_alone_never_credits(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Liar")
    txn = next(iter(states))
    states[txn] = {"status": "pending"}                           # the webhook claims completed; the provider says no
    assert post_sun(client, *sun_webhook("payment.completed", txn, b["invoice"]["number"])).status_code == 200
    assert invoice_of(b)["status"] == "issued" and billing.list_payments(b["invoice"]["id"]) == []
    assert payments.get_attempt(UUID(attempt_id))["status"] == "pending"
    states[txn] = {"status": "failed"}
    assert post_sun(client, *sun_webhook("payment.failed", txn, b["invoice"]["number"])).status_code == 200
    failed = payments.get_attempt(UUID(attempt_id))
    assert failed["status"] == "failed" and "cancelled" in failed["result_desc"]
    assert invoice_of(b)["status"] == "issued"


def test_a_wrong_amount_is_a_mismatch_flagged_to_operators_and_not_credited(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Mismatch")
    txn = next(iter(states))
    states[txn] = {"status": "completed", "amount": "100", "mpesaRef": "SHORT1"}          # 100 paid, 3500 expected
    operator = world["boss"]["email"]
    before = len(FakeEmail.sent)
    post_sun(client, *sun_webhook("payment.completed", txn, b["invoice"]["number"]))
    attempt = payments.get_attempt(UUID(attempt_id))
    assert attempt["status"] == "mismatch" and "amount reported 100 but 3500.00 was expected" in attempt["result_desc"]
    assert invoice_of(b)["status"] == "issued" and billing.list_payments(b["invoice"]["id"]) == []
    assert any(m.recipient == operator and "needs a look" in (m.subject or "") for m in FakeEmail.sent[before:])
    kinds = [e["kind"] for e in payments.timeline(UUID(attempt_id))]
    assert "mismatch" in kinds and "credited" not in kinds
    # an operator can settle it by hand, with a reason, and it is in the timeline
    done = payments.mark_paid_manually(UUID(attempt_id), "customer sent the rest by bank", by="Ops")
    assert done["status"] == "completed" and "marked_paid" in [e["kind"] for e in payments.timeline(UUID(attempt_id))]


def test_a_payment_for_a_voided_invoice_is_flagged_not_credited(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Void")
    txn = next(iter(states))
    billing.void_invoice(b["invoice"]["id"], "voided during the test")
    states[txn] = {"status": "completed", "amount": "3500", "mpesaRef": "LATE1"}
    post_sun(client, *sun_webhook("payment.completed", txn))
    attempt = payments.get_attempt(UUID(attempt_id))
    assert attempt["status"] == "mismatch" and "no longer open" in attempt["result_desc"]


# --------------------------------------------------------------------------- recovery and concurrency
def test_the_recovery_pass_credits_a_lost_notification(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Recover", suspended=True)
    txn = next(iter(states))
    states[txn] = {"status": "completed", "amount": "3500", "mpesaRef": "LOST1"}           # no webhook ever arrives
    counts = payments.recover_pending()
    assert counts["credited"] >= 1
    assert invoice_of(b)["status"] == "paid" and subscriptions.get(b["tenant_id"])["status"] == "active"
    assert payments.recover_pending()["credited"] == 0                                    # nothing more to do


def test_old_attempts_expire_and_attempts_that_never_reached_the_provider_fail(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Expire")
    with master_session() as m:
        m.execute(text("update master.payment_attempt set created_at = now() - interval '25 hours', "
                       "last_checked_at = null where id = :i"), {"i": attempt_id})
    assert payments.recover_pending()["expired"] >= 1
    assert payments.get_attempt(UUID(attempt_id))["status"] == "expired"
    other = business(client, "Pay Never")
    with master_session() as m:
        row = m.execute(text("insert into master.payment_attempt (reference, invoice_id, tenant_id, provider, amount, "
                             "currency, created_at) values ('zp-never', :i, :t, 'sunpay', 10, 'KES', now() - interval "
                             "'10 minutes') returning id"),
                        {"i": str(other["invoice"]["id"]), "t": str(other["tenant_id"])}).one()
    assert payments.recover_pending()["failed"] >= 1
    assert payments.get_attempt(row.id)["status"] == "failed"


def test_two_notifications_and_the_poller_at_once_credit_exactly_once(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Race")
    txn = next(iter(states))
    states[txn] = {"status": "completed", "amount": "3500", "mpesaRef": "RACE1"}
    body, headers = sun_webhook("payment.completed", txn, b["invoice"]["number"])
    results: list[object] = []
    errors: list[BaseException] = []

    def hook() -> None:
        try:
            results.append(payments.handle_webhook("sunpay", headers, body))
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    def poll() -> None:
        try:
            results.append(payments.recover_pending())
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=f) for f in (hook, hook, poll)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(billing.list_payments(b["invoice"]["id"])) == 1 and invoice_of(b)["amount_paid"] == D("3500.00")
    assert payments.get_attempt(UUID(attempt_id))["status"] == "completed"


# --------------------------------------------------------------------------- the owner's view and permissions
def test_only_the_owners_billing_permission_can_pay_and_businesses_are_separate(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    sunpay_routes(provider)
    a, other = business(client, "Pay Perm A"), business(client, "Pay Perm B")
    # a user with no role cannot see options, pay, or read an attempt
    roles = {r["name"]: r for r in client.get(f"{API}/roles", headers=a["owner"]).json()}
    for who, role in (("outsider", None), ("manager", "Branch Manager")):
        email = f"{who}@{a['code']}.test"
        u = client.post(f"{API}/users", headers=a["owner"],
                        json={"full_name": who, "email": email, "password": f"{who}-pass-1"}).json()
        if role:
            client.post(f"{API}/users/{u['id']}/roles", headers=a["owner"],
                        json={"role_id": roles[role]["id"], "scope": "tenant"})
        h = sign_in(client, a["code"], email, f"{who}-pass-1").headers
        assert client.get(f"{API}/billing/pay/options", headers=h, params={"invoice_id": str(a["invoice"]["id"])}).status_code == 403
        assert client.post(f"{API}/billing/payments", headers=h, json={"invoice_id": str(a["invoice"]["id"]),
                           "provider": "sunpay", "payer": {"phone": "0712345678"}}).status_code == 403
    assert client.post(f"{API}/billing/payments", json={}).status_code == 401
    mine = pay_sunpay(client, a).json()
    # another business can neither read the attempt nor pay or look at this business's invoice
    assert client.get(f"{API}/billing/payments/{mine['id']}", headers=other["owner"]).status_code == 404
    assert client.post(f"{API}/billing/payments/{mine['id']}/check", headers=other["owner"]).status_code == 404
    assert pay_sunpay(client, {**other, "invoice": a["invoice"]}).status_code == 404
    assert client.get(f"{API}/billing/payments", headers=other["owner"]).json() == []
    assert [x["id"] for x in client.get(f"{API}/billing/payments", headers=a["owner"]).json()] == [mine["id"]]


def test_the_status_poll_asks_the_provider_and_check_again_works(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Poll")
    txn = next(iter(states))
    first = client.get(f"{API}/billing/payments/{attempt_id}", headers=b["owner"]).json()
    assert first["status"] == "pending" and first["open"] is True
    states[txn] = {"status": "completed", "amount": "3500", "mpesaRef": "POLL1"}
    _forget_last_check(attempt_id)
    done = client.post(f"{API}/billing/payments/{attempt_id}/check", headers=b["owner"]).json()
    assert done["status"] == "completed" and invoice_of(b)["status"] == "paid"


# --------------------------------------------------------------------------- choosing a plan oneself
def test_a_suspended_owner_chooses_a_plan_and_pays_it(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    states = sunpay_routes(provider)
    t = make_tenant("Pay Subscribe")
    subscriptions.start(t["tenant_id"], "pay-basic", currency="KES", mode="trial")
    subscriptions.suspend(t["tenant_id"], "the trial ended for the test")
    me = sign_in(client, "pay-subscribe", "owner@pay-subscribe.test", device_id="d-sub").headers
    # the owner can still reach billing while suspended
    assert client.get(f"{API}/billing/plan", headers=me).json()["status"] == "suspended"
    r = client.post(f"{API}/billing/subscribe", headers=me, json={"plan_code": "pay-basic", "interval": "year",
                                                                  "currency": "KES"})
    assert r.status_code == 201, r.text
    invoice = r.json()["invoice"]
    assert (invoice["status"], invoice["total"], invoice["currency"]) == ("issued", "35000.00", "KES")
    again = client.post(f"{API}/billing/subscribe", headers=me, json={"plan_code": "pay-basic", "interval": "month",
                                                                      "currency": "KES"}).json()["invoice"]
    assert again["total"] == "3500.00"                                                 # the first, unpaid, one was replaced
    assert billing.get_invoice(UUID(invoice["id"]))["status"] == "void"
    paid = client.post(f"{API}/billing/payments", headers=me, json={
        "invoice_id": again["id"], "provider": "sunpay", "payer": {"phone": "0712345678"}}).json()
    states[payments.get_attempt(UUID(paid["id"]))["provider_transaction_id"]] = {
        "status": "completed", "amount": "3500", "mpesaRef": "SUBS1"}
    _forget_last_check(paid["id"])
    done = client.post(f"{API}/billing/payments/{paid['id']}/check", headers=me).json()
    assert done["status"] == "completed"
    sub = subscriptions.get(t["tenant_id"])
    assert (sub["status"], sub["interval"], sub["unit_amount"]) == ("active", "month", D("3500.00"))


# --------------------------------------------------------------------------- Stripe
def stripe_routes(p: Provider, session: dict[str, Any]) -> None:
    def create(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.test/c/pay/cs_test_1"})

    p.routes[("POST", "/v1/checkout/sessions")] = create
    p.routes[("GET", "/v1/checkout/sessions/cs_test_1")] = lambda r: httpx.Response(200, json=session)


def stripe_event(kind: str, obj: dict[str, Any], *, secret: str = STRIPE_SECRET, at: float | None = None,
                 event_id: str | None = None) -> tuple[bytes, dict[str, str]]:
    body = json.dumps({"id": event_id or f"evt_{uuid4().hex[:8]}", "type": kind, "data": {"object": obj}}).encode()
    stamp = str(int(at if at is not None else time.time()))
    sig = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, {"Stripe-Signature": f"t={stamp},v1={sig},v0=ignored", "Content-Type": "application/json"}


def test_stripe_creates_a_hosted_checkout_session_and_credits_after_retrieving_it(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, "Pay Stripe", currency="USD", amount="30.00", suspended=True)
    stripe_routes(provider, {"id": "cs_test_1", "status": "complete", "payment_status": "paid", "currency": "usd",
                             "amount_total": 3000, "client_reference_id": "x", "payment_intent": "pi_1",
                             "metadata": {"invoice_number": b["invoice"]["number"]}})
    r = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(b["invoice"]["id"]), "provider": "stripe", "payer": {}})
    assert r.status_code == 201, r.text
    attempt = r.json()
    assert attempt["redirect_url"] == "https://checkout.stripe.test/c/pay/cs_test_1" and attempt["flow"] == "redirect"
    [req] = provider.sent("POST", "/v1/checkout/sessions")
    form = dict(httpx.QueryParams(req.content.decode()))
    ref = payments.get_attempt(UUID(attempt["id"]))["reference"]
    assert req.headers["authorization"] == f"Bearer {STRIPE_KEY}" and req.headers["idempotency-key"] == ref
    # 30.00 USD is 3000 in the smallest unit; the currency is lower case; the references tie it to us
    assert form["mode"] == "payment" and form["line_items[0][price_data][unit_amount]"] == "3000"
    assert form["line_items[0][price_data][currency]"] == "usd" and form["client_reference_id"] == ref
    assert form["metadata[invoice_number]"] == b["invoice"]["number"]
    assert form["success_url"].endswith(f"/billing?attempt={attempt['id']}&payment=success")
    assert form["cancel_url"].endswith(f"/billing?attempt={attempt['id']}&payment=cancelled")
    assert "card" not in req.content.decode().lower().replace("checkout", "")                 # no card data of ours
    # the session as Stripe reports it carries our reference
    provider.routes[("GET", "/v1/checkout/sessions/cs_test_1")] = lambda rq: httpx.Response(200, json={
        "id": "cs_test_1", "status": "complete", "payment_status": "paid", "currency": "usd", "amount_total": 3000,
        "client_reference_id": ref, "payment_intent": "pi_1", "metadata": {"invoice_number": b["invoice"]["number"]}})
    body, headers = stripe_event("checkout.session.completed", {"id": "cs_test_1", "client_reference_id": ref})
    assert client.post(f"{API}/billing/webhooks/stripe", content=body, headers=headers).json() == {"handled": 1}
    assert invoice_of(b)["status"] == "paid" and subscriptions.get(b["tenant_id"])["status"] == "active"
    [pay] = billing.list_payments(b["invoice"]["id"])
    assert (pay["method"], pay["reference"], pay["provider"]) == ("card", "pi_1", "stripe")


def test_stripe_signatures_are_checked_with_the_timestamp_tolerance(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, "Pay Stripe Sig", currency="USD", amount="30.00")
    stripe_routes(provider, {"id": "cs_test_1", "status": "open"})
    client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(b["invoice"]["id"]), "provider": "stripe", "payer": {}})
    obj = {"id": "cs_test_1"}
    url = f"{API}/billing/webhooks/stripe"
    body, headers = stripe_event("checkout.session.completed", obj)
    assert client.post(url, content=body.replace(b"cs_test_1", b"cs_test_2"), headers=headers).status_code == 401
    assert client.post(url, content=body, headers={"Stripe-Signature": "t=1,v1=00"}).status_code == 401
    assert client.post(url, content=body, headers={}).status_code == 401
    bad = stripe_event("checkout.session.completed", obj, secret="whsec_other")
    assert client.post(url, content=bad[0], headers=bad[1]).status_code == 401
    old = stripe_event("checkout.session.completed", obj, at=time.time() - 400)           # 400 s > 300 s tolerance
    assert client.post(url, content=old[0], headers=old[1]).status_code == 401
    edge = stripe_event("checkout.session.completed", obj, at=time.time() - 200)
    assert client.post(url, content=edge[0], headers=edge[1]).status_code == 200
    ignored = stripe_event("customer.created", {"id": "cus_1"})
    assert client.post(url, content=ignored[0], headers=ignored[1]).json() == {"handled": 0}
    assert invoice_of(b)["status"] == "issued"                                              # the session is still open


def test_stripe_amount_mismatch_and_unit_rules(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    assert stripe_gateway.to_minor(D("30.00"), "USD") == 3000
    assert stripe_gateway.to_minor(D("4500"), "JPY") == 4500                                 # zero-decimal, from data
    assert stripe_gateway.to_minor(D("1.500"), "KWD") == 1500                                # three-decimal
    assert stripe_gateway.from_minor(4500, "jpy") == D("4500")
    b = business(client, "Pay Stripe Wrong", currency="USD", amount="30.00")
    stripe_routes(provider, {})
    attempt = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(b["invoice"]["id"]), "provider": "stripe", "payer": {}}).json()
    ref = payments.get_attempt(UUID(attempt["id"]))["reference"]
    provider.routes[("GET", "/v1/checkout/sessions/cs_test_1")] = lambda rq: httpx.Response(200, json={
        "id": "cs_test_1", "status": "complete", "payment_status": "paid", "currency": "usd", "amount_total": 300,
        "client_reference_id": ref, "payment_intent": "pi_2", "metadata": {"invoice_number": b["invoice"]["number"]}})
    body, headers = stripe_event("checkout.session.completed", {"id": "cs_test_1"})
    client.post(f"{API}/billing/webhooks/stripe", content=body, headers=headers)
    assert payments.get_attempt(UUID(attempt["id"]))["status"] == "mismatch" and invoice_of(b)["status"] == "issued"


def test_a_stripe_session_that_expired_fails_the_attempt(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, "Pay Stripe Expired", currency="USD", amount="30.00")
    stripe_routes(provider, {"id": "cs_test_1", "status": "expired"})
    attempt = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(b["invoice"]["id"]), "provider": "stripe", "payer": {}}).json()
    body, headers = stripe_event("checkout.session.expired", {"id": "cs_test_1"})
    client.post(f"{API}/billing/webhooks/stripe", content=body, headers=headers)
    assert payments.get_attempt(UUID(attempt["id"]))["status"] == "failed"


# --------------------------------------------------------------------------- Paystack
def paystack_event(obj: dict[str, Any], *, key: str = PAYSTACK_KEY, kind: str = "charge.success") -> tuple[bytes, dict[str, str]]:
    body = json.dumps({"event": kind, "data": obj}).encode()
    return body, {"x-paystack-signature": hmac.new(key.encode(), body, hashlib.sha512).hexdigest(),
                  "Content-Type": "application/json"}


def test_paystack_initialises_redirects_and_credits_after_verifying(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, "Pay Paystack", currency="USD", amount="30.00", suspended=True)

    def init(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": True, "data": {
            "authorization_url": "https://checkout.paystack.test/abc", "access_code": "abc",
            "reference": json.loads(request.content)["reference"]}})

    provider.routes[("POST", "/transaction/initialize")] = init
    r = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(b["invoice"]["id"]), "provider": "paystack", "payer": {"email": "pay@owner.test"}})
    assert r.status_code == 201, r.text
    attempt = r.json()
    assert attempt["redirect_url"] == "https://checkout.paystack.test/abc"
    ref = payments.get_attempt(UUID(attempt["id"]))["reference"]
    [req] = provider.sent("POST", "/transaction/initialize")
    sent = json.loads(req.content)
    # 30.00 USD is 3000 cents, sent as a string; reference is ours; the callback returns to Plan & billing
    assert (sent["email"], sent["amount"], sent["currency"], sent["reference"]) == ("pay@owner.test", "3000", "USD", ref)
    assert sent["callback_url"].endswith(f"/billing?attempt={attempt['id']}&payment=success")
    assert json.loads(sent["metadata"])["invoice_number"] == b["invoice"]["number"]
    assert req.headers["authorization"] == f"Bearer {PAYSTACK_KEY}"
    provider.routes[("GET", "/transaction/verify/")] = lambda rq: httpx.Response(200, json={"status": True, "data": {
        "status": "success", "amount": 3000, "currency": "USD", "reference": ref,
        "metadata": json.dumps({"invoice_number": b["invoice"]["number"]})}})
    body, headers = paystack_event({"reference": ref, "amount": 3000})
    url = f"{API}/billing/webhooks/paystack"
    assert client.post(url, content=body, headers={**headers, "x-paystack-signature": "00"}).status_code == 401
    assert client.post(url, content=body.replace(b"3000", b"1"), headers=headers).status_code == 401
    assert client.post(url, content=body, headers=headers).json() == {"handled": 1}
    assert invoice_of(b)["status"] == "paid" and subscriptions.get(b["tenant_id"])["status"] == "active"
    assert client.post(url, content=body, headers=headers).json() == {"handled": 0}               # a replay is ignored
    [pay] = billing.list_payments(b["invoice"]["id"])
    assert (pay["provider"], pay["reference"], pay["amount"]) == ("paystack", ref, D("30.00"))


def test_paystack_verify_disagreeing_with_the_notification_does_not_credit(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b = business(client, "Pay Paystack Wrong", currency="USD", amount="30.00")
    provider.routes[("POST", "/transaction/initialize")] = lambda rq: httpx.Response(200, json={"data": {
        "authorization_url": "https://checkout.paystack.test/x", "reference": "r"}})
    attempt = client.post(f"{API}/billing/payments", headers=b["owner"], json={
        "invoice_id": str(b["invoice"]["id"]), "provider": "paystack", "payer": {"email": "p@o.test"}}).json()
    ref = payments.get_attempt(UUID(attempt["id"]))["reference"]
    body, headers = paystack_event({"reference": ref})
    for verify, expected in (
        ({"status": "abandoned", "amount": 3000, "currency": "USD", "reference": ref}, "pending"),
        ({"status": "success", "amount": 3000, "currency": "NGN", "reference": ref}, "mismatch"),
    ):
        provider.routes[("GET", "/transaction/verify/")] = lambda rq, v=verify: httpx.Response(200, json={"data": v})
        client.post(f"{API}/billing/webhooks/paystack", content=body, headers=headers)
        assert payments.get_attempt(UUID(attempt["id"]))["status"] == expected
        if expected == "pending":
            with master_session() as m:
                m.execute(text("alter table master.payment_attempt_event disable trigger payment_attempt_event_immutable"))
                m.execute(text("delete from master.payment_attempt_event where attempt_id = :i and event_key is not null"),
                          {"i": attempt["id"]})
                m.execute(text("alter table master.payment_attempt_event enable trigger payment_attempt_event_immutable"))
    assert invoice_of(b)["status"] == "issued"
    assert D(100) == paystack_gateway.SUBUNIT


# --------------------------------------------------------------------------- the Super Admin
def test_gateway_settings_are_operator_only_and_secrets_are_write_only(client, world, caplog) -> None:  # type: ignore[no-untyped-def]
    boss, billing_op, viewer = world["boss"]["headers"], world["billing"]["headers"], world["viewer"]["headers"]
    caplog.set_level(logging.DEBUG)
    listed = client.get(f"{API}/operator/payment-gateways", headers=viewer)
    assert listed.status_code == 200
    assert {g["name"] for g in listed.json()} >= {"sunpay", "stripe", "paystack"}
    sun = next(g for g in listed.json() if g["name"] == "sunpay")
    secret_fields = {f["name"]: f for f in sun["fields"] if f["secret"]}
    assert all(f["value"] is None and f["is_set"] for f in secret_fields.values())
    assert sun["webhook_url"].endswith("/api/v1/billing/webhooks/sunpay") and sun["webhook_problem"] is None
    for needle in (SUN_KEY, SUN_SECRET, STRIPE_KEY, STRIPE_SECRET, PAYSTACK_KEY):
        assert needle not in listed.text
    # who may change them
    body = {"secrets": {"api_key": "sp_NEW_ROTATED_KEY"}}
    assert client.put(f"{API}/operator/payment-gateways/sunpay", headers=viewer, json=body).status_code == 403
    assert client.put(f"{API}/operator/payment-gateways/sunpay", headers={}, json=body).status_code in (401, 403)
    assert client.put(f"{API}/operator/payment-gateways/sunpay", headers=billing_op, json=body).status_code == 200
    changed = client.get(f"{API}/operator/payment-gateways", headers=boss).text
    assert "sp_NEW_ROTATED_KEY" not in changed
    with master_session() as m:
        stored = m.execute(text("select secrets_encrypted from master.payment_gateway where name = 'sunpay'")).scalar_one()
        trail = [r.detail for r in m.execute(text(
            "select detail from master.operator_action_log where action = 'payment_gateway.save'"))]
    assert "sp_NEW_ROTATED_KEY" not in stored and trail and "sp_NEW_ROTATED_KEY" not in json.dumps(trail, default=str)
    assert {"gateway": "sunpay", "fields": ["api_key"], "enabled": True} in trail
    assert "sp_NEW_ROTATED_KEY" not in caplog.text and SUN_SECRET not in caplog.text
    # a tenant's token is not an operator's
    owner = sign_in(client, "pay-offer-kes", "owner@pay-offer-kes.test", device_id="d-x").headers
    assert client.get(f"{API}/operator/payment-gateways", headers=owner).status_code in (401, 403)
    client.put(f"{API}/operator/payment-gateways/sunpay", headers=billing_op, json={"secrets": {"api_key": SUN_KEY}})
    # unknown fields and switching on without settings are refused
    assert client.put(f"{API}/operator/payment-gateways/sunpay", headers=boss,
                      json={"config": {"nope": "x"}}).status_code == 422
    assert client.put(f"{API}/operator/payment-gateways/sunpay", headers=boss,
                      json={"secrets": {"base_url": "x"}}).status_code == 422


def test_test_connection_reads_the_status_of_a_made_up_payment(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    boss = world["boss"]["headers"]
    provider.routes[("GET", "/api/v1/payments/")] = lambda r: httpx.Response(404, json={"message": "no such payment"})
    assert client.post(f"{API}/operator/payment-gateways/sunpay/test", headers=boss).json() == {
        "ok": True, "message": "SunPay accepted the API key"}
    provider.routes[("GET", "/api/v1/payments/")] = lambda r: httpx.Response(401, json={"message": "bad key"})
    out = client.post(f"{API}/operator/payment-gateways/sunpay/test", headers=boss).json()
    assert out["ok"] is False and "rejected" in out["message"]
    provider.routes[("GET", "/api/v1/payments/")] = lambda r: httpx.Response(500)
    assert client.post(f"{API}/operator/payment-gateways/sunpay/test", headers=boss).json()["ok"] is False


def test_operators_see_attempts_and_can_recheck_and_mark_paid(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay Operator View")
    boss, viewer = world["boss"]["headers"], world["viewer"]["headers"]
    rows = client.get(f"{API}/operator/payment-attempts", headers=viewer, params={"status": "pending"}).json()
    assert attempt_id in [r["id"] for r in rows] and "payer_phone_hash" not in json.dumps(rows)
    done_rows = client.get(f"{API}/operator/payment-attempts", headers=viewer, params={"status": "completed"})
    assert attempt_id not in [r["id"] for r in done_rows.json()]
    detail = client.get(f"{API}/operator/payment-attempts/{attempt_id}", headers=viewer).json()
    assert [e["kind"] for e in detail["timeline"]][:2] == ["created", "started"]
    assert detail["tenant_code"] == b["code"] and detail["provider_transaction_id"] == "tx-1"
    assert client.post(f"{API}/operator/payment-attempts/{attempt_id}/recheck", headers=viewer).status_code == 403
    assert client.post(f"{API}/operator/payment-attempts/{attempt_id}/mark-paid", headers=boss,
                       json={"reason": "x"}).status_code == 422
    re = client.post(f"{API}/operator/payment-attempts/{attempt_id}/recheck", headers=boss)
    assert re.status_code == 200 and re.json()["status"] == "pending"
    paid = client.post(f"{API}/operator/payment-attempts/{attempt_id}/mark-paid", headers=boss,
                       json={"reason": "Safaricom statement shows it"})
    assert paid.status_code == 200 and paid.json()["status"] == "completed"
    assert invoice_of(b)["status"] == "paid"
    on_invoice = client.get(f"{API}/operator/invoices/{b['invoice']['id']}/payment-attempts", headers=viewer).json()
    assert [a["id"] for a in on_invoice] == [attempt_id]


def test_the_webhook_address_is_withheld_when_the_public_address_is_not_https(monkeypatch: pytest.MonkeyPatch) -> None:
    from ziira.kernel.config import get_settings

    monkeypatch.setattr(get_settings(), "public_base_url", "http://api.example.com")
    url, problem = payments.webhook_url("sunpay")
    assert url is None and "https" in str(problem)
    monkeypatch.setattr(get_settings(), "public_base_url", "http://localhost:8000")
    assert payments.webhook_url("sunpay")[0] == "http://localhost:8000/api/v1/billing/webhooks/sunpay"
    monkeypatch.setattr(get_settings(), "public_base_url", "https://api.example.com/")
    assert payments.webhook_url("stripe")[0] == "https://api.example.com/api/v1/billing/webhooks/stripe"


def test_the_phone_number_is_never_stored_whole(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    b, states, attempt_id = started(client, provider, "Pay No Phone")
    with master_session() as m:
        row = m.execute(text("select * from master.payment_attempt where id = :i"), {"i": attempt_id}).one()
    assert row.payer_phone_last4 == "5678" and row.payer_phone_hash == payments.phone_hash("254712345678")
    assert "254712345678" not in json.dumps({k: str(v) for k, v in row._mapping.items()})
    assert payments.phone_hash("+254 712 345 678") == row.payer_phone_hash


def test_the_timeline_cannot_be_rewritten(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import DBAPIError

    _, _, attempt_id = started(client, provider, "Pay Timeline")
    with pytest.raises(DBAPIError), master_session() as m:
        m.execute(text("update master.payment_attempt_event set kind = 'x' where attempt_id = :i"), {"i": attempt_id})
    with pytest.raises(DBAPIError), master_session() as m:
        m.execute(text("delete from master.payment_attempt_event where attempt_id = :i"), {"i": attempt_id})


def test_too_many_requests_error_type() -> None:
    assert issubclass(TooManyRequests, Exception) and gateways.get_gateway("nope") is None


def test_payer_details_are_found_exported_and_erased_through_the_privacy_provider(client, world, provider) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.personal_data import Subject
    from ziira.kernel.privacy_providers import PaymentPayerData

    b, _, attempt_id = started(client, provider, "Pay Privacy")
    other = business(client, "Pay Privacy Other")
    sunpay_routes(provider)
    pay_sunpay(client, other)                                                      # the same number, another business
    subject = Subject(raw="254712345678", phone="254712345678")
    with tenant_session(b["tenant_id"], admin=True) as s:
        data = PaymentPayerData()
        [record] = data.find(s, b["company_id"], subject)                           # only this business's attempt
        assert str(record.record_id) == attempt_id
        assert data.export(s, record)["payer_phone_last4"] == "5678"
        outcome = data.anonymise(s, record, "erasure request")
    assert outcome.status == "anonymised"
    with tenant_session(b["tenant_id"], admin=True) as s:
        assert PaymentPayerData().find(s, b["company_id"], subject) == []
