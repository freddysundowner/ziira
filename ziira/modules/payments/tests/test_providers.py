"""The Daraja provider with Safaricom replaced by a mock: request shapes, passwords, errors and retries."""

import base64
import json
from decimal import Decimal as D  # noqa: N817

import httpx
import pytest

from ziira.modules.payments.providers import DarajaProvider, FakeProvider
from ziira.modules.payments.public import StkQuery, StkRequest

CREDS = {"consumer_key": "ck", "consumer_secret": "cs", "passkey": "PASSKEY"}


class Safaricom:
    """A pretend Safaricom: records what it was sent and answers as told."""

    def __init__(self, token_status: int = 200, push: tuple[int, dict] | None = None, query: tuple[int, dict] | None = None):  # type: ignore[type-arg]
        self.requests: list[httpx.Request] = []
        self.token_status = token_status
        self.push = push or (200, {"MerchantRequestID": "m1", "CheckoutRequestID": "ws_CO_1", "ResponseCode": "0",
                                   "ResponseDescription": "Success", "CustomerMessage": "Success. Request accepted"})
        self.query = query or (200, {"ResultCode": "0", "ResultDesc": "ok", "MerchantRequestID": "m1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/oauth/v1/generate":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"errorMessage": "Invalid credentials"})
            return httpx.Response(200, json={"access_token": "TOKEN-1", "expires_in": "3599"})
        if request.url.path == "/mpesa/stkpush/v1/processrequest":
            return httpx.Response(self.push[0], json=self.push[1])
        if request.url.path == "/mpesa/stkpushquery/v1/query":
            return httpx.Response(self.query[0], json=self.query[1])
        return httpx.Response(404)

    def provider(self) -> DarajaProvider:
        provider = DarajaProvider()
        provider.client_factory = lambda: httpx.Client(transport=httpx.MockTransport(self.handler))
        DarajaProvider._tokens.clear()
        return provider


def request(**kw) -> StkRequest:  # type: ignore[no-untyped-def]
    return StkRequest(**{"shortcode": "174379", "till_type": "paybill", "amount": D("116"), "msisdn": "254712345678",
                         "callback_url": "https://example.test/cb", "account_reference": "INV-1",
                         "description": "Payment", "credentials": CREDS, "environment": "sandbox", **kw})


def test_a_push_is_sent_as_daraja_expects() -> None:
    pretend = Safaricom()
    response = pretend.provider().stk_push(request())
    assert response.accepted and response.provider_request_id == "ws_CO_1"
    token_request, push = pretend.requests
    assert token_request.url.host == "sandbox.safaricom.co.ke"
    assert token_request.headers["authorization"] == "Basic " + base64.b64encode(b"ck:cs").decode()
    assert push.headers["authorization"] == "Bearer TOKEN-1"
    body = json.loads(push.content)
    assert body["BusinessShortCode"] == "174379" and body["Amount"] == 116 and body["PartyA"] == "254712345678"
    assert body["PhoneNumber"] == "254712345678" and body["CallBackURL"] == "https://example.test/cb"
    assert body["TransactionType"] == "CustomerPayBillOnline" and body["AccountReference"] == "INV-1"
    expected = base64.b64decode(body["Password"]).decode()
    assert expected == "174379PASSKEY" + body["Timestamp"] and len(body["Timestamp"]) == 14


def test_a_till_uses_buy_goods_and_production_uses_the_live_address() -> None:
    pretend = Safaricom()
    pretend.provider().stk_push(request(till_type="till", environment="production", party_b="600638"))
    assert pretend.requests[0].url.host == "api.safaricom.co.ke"
    body = json.loads(pretend.requests[1].content)
    assert body["TransactionType"] == "CustomerBuyGoodsOnline" and body["PartyB"] == "600638"


def test_the_token_is_reused() -> None:
    pretend = Safaricom()
    provider = pretend.provider()
    provider.stk_push(request())
    provider.stk_push(request())
    assert [r.url.path for r in pretend.requests].count("/oauth/v1/generate") == 1


def test_long_references_are_cut_to_what_daraja_accepts() -> None:
    pretend = Safaricom()
    pretend.provider().stk_push(request(account_reference="A-VERY-LONG-REFERENCE-123", description="Payment for goods"))
    body = json.loads(pretend.requests[1].content)
    assert len(body["AccountReference"]) <= 12 and len(body["TransactionDesc"]) <= 13


def test_refusals_are_permanent_and_outages_are_retried() -> None:
    refused = Safaricom(push=(400, {"errorCode": "400.002.02", "errorMessage": "Bad Request - Invalid PhoneNumber"}))
    r = refused.provider().stk_push(request())
    assert not r.accepted and r.permanent_failure and "Invalid PhoneNumber" in r.message
    declined = Safaricom(push=(200, {"ResponseCode": "1", "ResponseDescription": "Rejected"}))
    assert declined.provider().stk_push(request()).permanent_failure
    bad_credentials = Safaricom(token_status=401)
    r = bad_credentials.provider().stk_push(request())
    assert not r.accepted and r.permanent_failure and "credentials" in r.message
    for status in (500, 503, 429):
        with pytest.raises(httpx.HTTPStatusError):
            Safaricom(push=(status, {})).provider().stk_push(request())


def test_a_status_query() -> None:
    pretend = Safaricom()
    result = pretend.provider().query_stk(StkQuery("174379", "ws_CO_1", CREDS, "sandbox"))
    assert result.succeeded and result.checkout_request_id == "ws_CO_1"
    body = json.loads(pretend.requests[-1].content)
    assert body["CheckoutRequestID"] == "ws_CO_1" and "Password" in body
    failed = Safaricom(query=(200, {"ResultCode": "1032", "ResultDesc": "Request cancelled by user"}))
    r = failed.provider().query_stk(StkQuery("174379", "ws_CO_1", CREDS))
    assert r.cancelled and not r.succeeded
    processing = Safaricom(query=(500, {"errorCode": "500.001.1001", "errorMessage": "The transaction is being processed"}))
    with pytest.raises(httpx.HTTPStatusError):
        processing.provider().query_stk(StkQuery("174379", "ws_CO_1", CREDS))
    pending = Safaricom(query=(200, {"errorMessage": "The transaction is being processed"}))
    assert pending.provider().query_stk(StkQuery("174379", "ws_CO_1", CREDS)).result_code == -1


def test_an_unknown_environment_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="environment"):
        Safaricom().provider().stk_push(request(environment="mars"))


def test_the_fake_provider_follows_the_test_script() -> None:
    FakeProvider.sent.clear()
    FakeProvider.outcomes.clear()
    fake = FakeProvider()
    first = fake.stk_push(request())
    assert first.accepted and first.provider_request_id == FakeProvider.last_checkout_id()
    checkout = first.provider_request_id
    FakeProvider.refuse_next = "Nope"
    assert fake.stk_push(request()).permanent_failure and FakeProvider.refuse_next is None
    assert fake.query_stk(StkQuery("1", checkout)).result_code == -1
    FakeProvider.succeed(checkout, "RKQ1", D("116"), "254712345678")
    assert fake.query_stk(StkQuery("1", checkout)).succeeded
    FakeProvider.sent.clear()
    FakeProvider.outcomes.clear()
