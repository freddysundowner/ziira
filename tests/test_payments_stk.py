"""Asking customers to pay by M-Pesa: the prompt, Safaricom's callback, status checks, and everything that can go wrong."""

from datetime import UTC, datetime
from decimal import Decimal as Dec
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.payments_helpers import PAY, due_now, fresh_ref, make_payments_shop, one, work
from tests.stock_helpers import system
from ziira.modules.payments.providers import FakeProvider


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_payments_shop(client, registry, "Stk Co")


@pytest.fixture(autouse=True)
def clean_provider():  # type: ignore[no-untyped-def]
    for store in (FakeProvider.sent, FakeProvider.outcomes):
        store.clear()
    FakeProvider.refuse_next = None
    yield


def push(client, shop, amount="116", phone="0712345678", headers=None, key=None, **kw):  # type: ignore[no-untyped-def]
    h = dict(headers or shop["owner"])
    if key:
        h["Idempotency-Key"] = key
    return client.post(f"{PAY}/intents", headers=h, json={
        "payment_account_id": shop["till"], "amount": amount, "phone": phone, **kw})


def sent_and_accepted(client, shop, **kw):  # type: ignore[no-untyped-def]
    r = push(client, shop, **kw)
    assert r.status_code == 201, r.text
    due_now(shop)
    work(shop)
    return r.json()


def callback_path() -> str:
    return urlparse(FakeProvider.sent[-1].callback_url).path


def success(checkout: str, amount="116", receipt: str | None = None, phone="254712345678", code=0):  # type: ignore[no-untyped-def]
    cb = {"MerchantRequestID": "m-1", "CheckoutRequestID": checkout, "ResultCode": code,
          "ResultDesc": "The service request is processed successfully." if code == 0 else "Request cancelled by user"}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": [
            {"Name": "Amount", "Value": float(amount)}, {"Name": "MpesaReceiptNumber", "Value": receipt or fresh_ref()},
            {"Name": "TransactionDate", "Value": int(datetime.now(UTC).astimezone().strftime("%Y%m%d%H%M%S"))},
            {"Name": "PhoneNumber", "Value": int(phone)}]}
    return {"Body": {"stkCallback": cb}}


def get(client, shop, intent_id):  # type: ignore[no-untyped-def]
    return client.get(f"{PAY}/intents/{intent_id}", headers=shop["owner"]).json()


# --------------------------------------------------------------------------- the happy path
def test_a_prompt_is_sent_by_the_worker_and_completed_by_the_callback(client, shop) -> None:  # type: ignore[no-untyped-def]
    intent = push(client, shop, amount="116", doc_type="sale", doc_id=str(uuid4()), account_reference="POS-1").json()
    assert intent["status"] == "pending" and intent["phone_masked"] == "2547****678" and "0712345678" not in str(intent)
    assert FakeProvider.sent == []                                  # nothing happens inside the cashier's request
    due_now(shop)
    work(shop)
    [request] = FakeProvider.sent
    assert request.msisdn == "254712345678" and request.amount == 116 and request.shortcode == "600638"
    assert request.till_type == "till" and request.account_reference == "POS-1"
    assert request.credentials["passkey"] == "pk-789" and request.environment == "sandbox"
    tenant_hex = shop["tenant_id"].hex
    assert f"/callbacks/stk/{tenant_hex}/{intent['id']}/" in request.callback_url

    receipt = fresh_ref()
    r = client.post(callback_path(), json=success(FakeProvider.last_checkout_id(), "116", receipt))
    assert r.status_code == 200 and r.json()["ResultCode"] == 0
    done = get(client, shop, intent["id"])
    assert done["status"] == "succeeded" and done["receipt"] == receipt and done["result_code"] == "0"
    txn = client.get(f"{PAY}/transactions", headers=shop["owner"], params={"payment_account_id": shop["till"]}).json()
    assert any(t["external_ref"] == receipt and t["source"] == "daraja_stk" and Dec(t["amount"]) == 116 for t in txn)
    assert one(shop, "select count(*) from kernel.event_outbox where event_type = 'stk.completed' and "
                     "aggregate_id = :i", i=intent["id"]) == 1


def test_a_callback_delivered_twice_does_nothing_the_second_time(client, shop) -> None:  # type: ignore[no-untyped-def]
    intent = sent_and_accepted(client, shop)
    path, receipt = callback_path(), fresh_ref()
    for _ in range(3):
        assert client.post(path, json=success(FakeProvider.last_checkout_id(), receipt=receipt)).status_code == 200
    assert one(shop, "select count(*) from payments.external_transaction where external_ref = :r", r=receipt) == 1
    assert get(client, shop, intent["id"])["status"] == "succeeded"


def test_the_customer_cancels_or_the_payment_fails(client, shop) -> None:  # type: ignore[no-untyped-def]
    cancelled = sent_and_accepted(client, shop)
    client.post(callback_path(), json=success(FakeProvider.last_checkout_id(), code=1032))
    assert get(client, shop, cancelled["id"])["status"] == "cancelled"
    failed = sent_and_accepted(client, shop)
    client.post(callback_path(), json=success(FakeProvider.last_checkout_id(), code=2001))
    assert get(client, shop, failed["id"])["status"] == "failed" and get(client, shop, failed["id"])["result_code"] == "2001"
    assert one(shop, "select count(*) from payments.external_transaction where source = 'daraja_stk' and "
                     "created_at > now() - interval '1 minute' and external_ref like 'FAIL%'") == 0


def test_callbacks_must_carry_the_right_signature(client, shop) -> None:  # type: ignore[no-untyped-def]
    intent = sent_and_accepted(client, shop)
    good = callback_path()
    checkout = FakeProvider.last_checkout_id()
    prefix, signature = good.rsplit("/", 1)
    assert client.post(f"{prefix}/{signature[:-1]}x", json=success(checkout)).status_code == 404
    assert client.post(f"{prefix}/{'0' * 40}", json=success(checkout)).status_code == 404
    other_tenant = good.replace(shop["tenant_id"].hex, uuid4().hex)
    assert client.post(other_tenant, json=success(checkout)).status_code == 404
    other_intent = good.replace(str(intent["id"]), str(uuid4()))
    assert client.post(other_intent, json=success(checkout)).status_code == 404
    assert client.post(f"{PAY}/callbacks/stk/nothex/{uuid4()}/sig", json=success(checkout)).status_code == 404
    assert get(client, shop, intent["id"])["status"] == "pending"                    # none of those did anything
    assert client.post(good, json={"junk": 1}).status_code == 422
    assert client.post(good, json=success("ws_CO_OTHER")).status_code == 404         # a different prompt's id


def test_the_amount_or_the_payer_differing_is_flagged(client, shop) -> None:  # type: ignore[no-untyped-def]
    sent_and_accepted(client, shop, amount="200", phone="0712345678")
    checkout = FakeProvider.last_checkout_id()
    receipt = fresh_ref()
    client.post(callback_path(), json=success(checkout, amount="150", receipt=receipt, phone="254722999888"))
    kinds = {i["kind"] for i in client.get("/api/v1/exceptions", headers=shop["owner"]).json() if receipt in i["message"]}
    assert kinds == {"stk_amount_differs", "stk_other_payer"}


# --------------------------------------------------------------------------- when things go wrong
def test_a_refused_prompt_fails_and_is_flagged_and_an_outage_is_retried(client, shop) -> None:  # type: ignore[no-untyped-def]
    FakeProvider.refuse_next = "Invalid PhoneNumber"
    refused = push(client, shop).json()
    due_now(shop)
    work(shop)
    assert get(client, shop, refused["id"])["status"] == "failed"
    items = client.get("/api/v1/exceptions", headers=shop["owner"], params={"kind": "stk_refused"}).json()
    assert any("Invalid PhoneNumber" in i["message"] for i in items)

    from ziira.modules.payments import providers

    real = providers.FakeProvider.stk_push
    calls: list[int] = []

    def flaky(self, request):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("Safaricom is down")
        return real(self, request)

    providers.FakeProvider.stk_push = flaky  # type: ignore[method-assign]
    try:
        retried = push(client, shop).json()
        due_now(shop)
        work(shop)
        attempts = one(shop, "select attempts from kernel.job where job_type = 'payments.send_stk' and "
                             "payload->>'intent_id' = :i", i=retried["id"])
        assert attempts == 1 and get(client, shop, retried["id"])["status"] == "pending"        # waiting to retry
        due_now(shop)
        work(shop)
        assert len(calls) == 2 and len(FakeProvider.sent) == 1
    finally:
        providers.FakeProvider.stk_push = real  # type: ignore[method-assign]


def test_without_a_callback_a_status_check_settles_the_prompt(client, shop) -> None:  # type: ignore[no-untyped-def]
    intent = sent_and_accepted(client, shop, amount="300")
    checkout = FakeProvider.last_checkout_id()
    assert one(shop, "select count(*) from kernel.job where job_type = 'payments.check_stk' and status = 'queued' "
                     "and payload->>'intent_id' = :i", i=intent["id"]) == 1
    due_now(shop)
    work(shop)                                                           # Safaricom says: still processing
    assert get(client, shop, intent["id"])["status"] == "pending"
    receipt = fresh_ref()
    FakeProvider.succeed(checkout, receipt, Dec("300"), "254712345678")
    due_now(shop)
    work(shop)
    done = get(client, shop, intent["id"])
    assert done["status"] == "succeeded" and done["receipt"] == receipt


def test_a_prompt_nobody_answers_times_out(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    intent = sent_and_accepted(client, shop)
    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("update payments.payment_intent set expires_at = now() - interval '10 minutes' where id = :i"),
                  {"i": intent["id"]})
    due_now(shop)
    work(shop)
    assert get(client, shop, intent["id"])["status"] == "timeout"
    assert client.post(callback_path(), json=success(FakeProvider.last_checkout_id())).status_code == 200
    assert get(client, shop, intent["id"])["status"] == "timeout"        # a late callback does not undo the timeout


def test_an_expired_prompt_is_never_sent(client, shop) -> None:  # type: ignore[no-untyped-def]
    from ziira.kernel.db import tenant_session

    intent = push(client, shop).json()
    with tenant_session(shop["tenant_id"], admin=True) as s:
        s.execute(text("update payments.payment_intent set expires_at = now() - interval '1 minute' where id = :i"),
                  {"i": intent["id"]})
    due_now(shop)
    work(shop)
    assert FakeProvider.sent == [] and get(client, shop, intent["id"])["status"] == "timeout"


# --------------------------------------------------------------------------- validation and permissions
def test_a_prompt_is_validated(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert push(client, shop, amount="0").status_code == 422
    assert push(client, shop, amount="150001").status_code == 422
    assert push(client, shop, amount="10.50").status_code == 422
    assert push(client, shop, amount="1e20").status_code == 422
    assert push(client, shop, phone="123").status_code == 422
    assert push(client, shop, phone="").status_code == 422
    r = client.post(f"{PAY}/intents", headers=shop["owner"], json={"payment_account_id": shop["bank"], "amount": "100",
                                                                   "phone": "0712345678"})
    assert r.status_code == 422 and "M-Pesa" in r.json()["message"]
    r = client.post(f"{PAY}/intents", headers=shop["owner"], json={"payment_account_id": str(uuid4()), "amount": "100",
                                                                   "phone": "0712345678"})
    assert r.status_code == 404
    client.patch(f"{PAY}/accounts/{shop['till']}", headers=shop["owner"], json={"is_active": False})
    assert push(client, shop).status_code == 422
    client.patch(f"{PAY}/accounts/{shop['till']}", headers=shop["owner"], json={"is_active": True})


def test_an_account_without_credentials_cannot_prompt(client, shop) -> None:  # type: ignore[no-untyped-def]
    other = client.post(f"{PAY}/accounts", headers=shop["owner"], json={
        "company_id": str(shop["company_id"]), "branch_id": str(shop["branch_id"]), "kind": "mpesa_paybill",
        "name": "No keys", "shortcode": "888880", "provider": "fake"}).json()
    r = client.post(f"{PAY}/intents", headers=shop["owner"], json={"payment_account_id": other["id"], "amount": "10",
                                                                   "phone": "0712345678"})
    assert r.status_code == 422 and "no M-Pesa credentials" in r.json()["message"]


def test_a_retried_request_prompts_the_customer_once(client, shop) -> None:  # type: ignore[no-untyped-def]
    key = "till-3-sale-4711"
    first, second = push(client, shop, key=key), push(client, shop, key=key)
    assert first.status_code == 201 == second.status_code and first.json() == second.json()
    due_now(shop)
    work(shop)
    assert len(FakeProvider.sent) == 1
    assert push(client, shop, key=key, amount="999").status_code == 422             # same key, a different request
    assert push(client, shop, key="bad\nkey").status_code == 422


def test_who_may_ask_customers_to_pay(client, shop) -> None:  # type: ignore[no-untyped-def]
    assert push(client, shop, headers=shop["cashier"]).status_code == 201           # a cashier at the till's branch
    assert push(client, shop, headers=shop["manager"]).status_code == 201
    assert push(client, shop, headers=shop["storekeeper"]).status_code == 403
    juja_cashier = shop["user"]("jujacashier", "Cashier", shop["juja"])
    assert push(client, shop, headers=juja_cashier).status_code == 403              # another branch's till
    assert client.get(f"{PAY}/intents", headers=juja_cashier).json() == []
    intent = push(client, shop).json()
    assert client.get(f"{PAY}/intents/{intent['id']}", headers=juja_cashier).status_code == 404
    assert client.get(f"{PAY}/intents/{uuid4()}", headers=shop["owner"]).status_code == 404


def test_intents_can_be_listed_by_status_and_document(client, shop) -> None:  # type: ignore[no-untyped-def]
    doc = uuid4()
    mine = push(client, shop, doc_type="sale", doc_id=str(doc)).json()
    by_doc = client.get(f"{PAY}/intents", headers=shop["owner"], params={"doc_id": str(doc)}).json()
    assert [i["id"] for i in by_doc] == [mine["id"]]
    pending = client.get(f"{PAY}/intents", headers=shop["owner"], params={"status": "pending"}).json()
    assert mine["id"] in {i["id"] for i in pending}
    assert client.get(f"{PAY}/intents", headers=shop["owner"], params={"limit": 0}).status_code == 422


def test_the_phone_number_is_never_stored_in_the_clear(client, shop) -> None:  # type: ignore[no-untyped-def]
    push(client, shop, phone="0733445566")
    with system(shop) as s:
        everything = s.execute(text("select string_agg(row_to_json(i)::text, ' ') from payments.payment_intent i"
                                    )).scalar_one()
        jobs = s.execute(text("select string_agg(payload::text, ' ') from kernel.job where "
                              "job_type = 'payments.send_stk'")).scalar_one()
        audit = s.execute(text("select string_agg(changes::text, ' ') from kernel.audit_log")).scalar_one()
    for blob in (everything, jobs, audit):
        assert "733445566" not in blob and "0733445566" not in blob           # masked, hashed or encrypted only
    assert UUID(shop["till"])
