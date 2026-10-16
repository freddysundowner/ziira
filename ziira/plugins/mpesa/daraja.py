"""Safaricom Daraja (M-Pesa) as a payment provider, and a simulator of it for development and tests.

The Daraja formats follow Safaricom's published documentation as we know it. They have NOT been exercised against
Safaricom itself from here (that needs a developer account and shortcode): confirm them in Safaricom's sandbox before
going live. The HTTP layer is injectable, so everything but the network is tested.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from ziira.modules.payments.public import (
    C2BTransaction,
    FormField,
    PaymentProvider,
    StkQuery,
    StkRequest,
    StkResponse,
    StkResult,
)
from ziira.plugins.mpesa import formats

log = logging.getLogger("ziira.mpesa.daraja")

BASE_URLS = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
Client = Callable[[], httpx.Client]

CREDENTIAL_FIELDS = (
    FormField("consumer_key", "Consumer key", secret=True),
    FormField("consumer_secret", "Consumer secret", secret=True),
    FormField("passkey", "STK passkey", secret=True, help="The Lipa na M-Pesa Online passkey of this shortcode"),
)
CONFIG_FIELDS = (
    FormField("till_type", "Till type", required=False, kind="select", options=("till", "paybill"), default="paybill",
              help="'till' pays a buy-goods till, 'paybill' a paybill number"),
    FormField("party_b", "Till number to pay", required=False,
              help="Only when it differs from the shortcode (a store's head-office shortcode and its till)"),
)


def _default_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT)


class DarajaProvider(PaymentProvider):
    """STK push and STK status queries over Safaricom's Daraja API; reads its callbacks."""

    name = "daraja"
    title = "M-Pesa (Safaricom Daraja)"
    credential_fields = CREDENTIAL_FIELDS
    config_fields = CONFIG_FIELDS
    c2b_source = "daraja_c2b"
    stk_source = "daraja_stk"
    callback_reply: ClassVar[dict[str, Any]] = {"ResultCode": 0, "ResultDesc": "Accepted"}
    prompt_minimum = formats.MIN_AMOUNT
    prompt_maximum = formats.MAX_STK_AMOUNT
    prompt_whole_amounts = True
    # Replaced in tests with a client using httpx.MockTransport.
    client_factory: Client = staticmethod(_default_client)
    _tokens: dict[tuple[str, str], tuple[str, float]] = {}

    def normalize_phone(self, raw: str, calling_code: str | None) -> str:
        return formats.normalize_phone(raw)

    def parse_stk_callback(self, payload: dict[str, Any]) -> StkResult:
        return formats.parse_stk_callback(payload)

    def parse_c2b(self, payload: dict[str, Any]) -> C2BTransaction:
        return formats.parse_c2b(payload)

    def _base(self, environment: str) -> str:
        if environment not in BASE_URLS:
            raise ValueError(f"Unknown Daraja environment '{environment}'")
        return BASE_URLS[environment]

    def _token(self, client: httpx.Client, environment: str, credentials: dict[str, Any]) -> str:
        key = (environment, str(credentials.get("consumer_key")))
        cached = self._tokens.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        response = client.get(f"{self._base(environment)}/oauth/v1/generate",
                              params={"grant_type": "client_credentials"},
                              auth=(str(credentials["consumer_key"]), str(credentials["consumer_secret"])))
        response.raise_for_status()
        body = response.json()
        token = str(body["access_token"])
        self._tokens[key] = (token, time.monotonic() + max(int(body.get("expires_in", 3599)) - 60, 30))
        return token

    def stk_push(self, request: StkRequest) -> StkResponse:
        if request.amount != request.amount.to_integral_value():     # a prompt takes whole amounts: never round money
            return StkResponse(False, None, "A mobile-money prompt can only ask for a whole amount",
                               permanent_failure=True)
        timestamp = formats.daraja_timestamp()
        till_type = str(request.settings.get("till_type", "paybill"))
        payload = {
            "BusinessShortCode": request.shortcode,
            "Password": formats.stk_password(request.shortcode, str(request.credentials["passkey"]), timestamp),
            "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline" if till_type == "till" else "CustomerPayBillOnline",
            "Amount": int(request.amount),
            "PartyA": request.msisdn,
            "PartyB": request.settings.get("party_b") or request.shortcode,
            "PhoneNumber": request.msisdn,
            "CallBackURL": request.callback_url,
            "AccountReference": request.account_reference[:12],
            "TransactionDesc": request.description[:13] or "Payment",
        }
        with self.client_factory() as client:
            try:
                token = self._token(client, request.environment, request.credentials)
                response = client.post(f"{self._base(request.environment)}/mpesa/stkpush/v1/processrequest",
                                       json=payload, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPStatusError as exc:                      # a bad token request: credentials are wrong
                log.warning("Daraja refused our credentials: %s", exc.response.status_code)
                return StkResponse(False, None, "Safaricom refused the credentials", permanent_failure=True)
            body = _json(response)
            if response.status_code == 429 or (response.status_code >= 500 and not body.get("errorCode")):
                # an outage (no body we can read): the job is retried later
                raise httpx.HTTPStatusError("Daraja is unavailable", request=response.request, response=response)
            if response.status_code == 200 and str(body.get("ResponseCode")) == "0":
                return StkResponse(True, str(body["CheckoutRequestID"]), str(body.get("CustomerMessage") or ""))
            message = str(body.get("errorMessage") or body.get("ResponseDescription") or "The prompt was refused")
            return StkResponse(False, None, message, permanent_failure=True)

    def query_stk(self, query: StkQuery) -> StkResult:
        timestamp = formats.daraja_timestamp()
        payload = {"BusinessShortCode": query.shortcode,
                   "Password": formats.stk_password(query.shortcode, str(query.credentials["passkey"]), timestamp),
                   "Timestamp": timestamp, "CheckoutRequestID": query.provider_request_id}
        with self.client_factory() as client:
            token = self._token(client, query.environment, query.credentials)
            response = client.post(f"{self._base(query.environment)}/mpesa/stkpushquery/v1/query", json=payload,
                                   headers={"Authorization": f"Bearer {token}"})
            body = _json(response)
        if response.status_code == 429 or (response.status_code >= 500 and not body.get("errorCode")):
            raise httpx.HTTPStatusError("Daraja is unavailable", request=response.request, response=response)
        if "ResultCode" not in body:                         # "still processing" comes back as an error body (HTTP 500)
            return StkResult(query.provider_request_id, None, -1, str(body.get("errorMessage") or "Pending"),
                             outcome="pending")
        code = int(str(body["ResultCode"]))
        return StkResult(query.provider_request_id, body.get("MerchantRequestID"), code,
                         str(body.get("ResultDesc") or ""), outcome=formats.outcome_of(code))


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class SimulatedDarajaProvider(DarajaProvider):
    """For development and tests: speaks Daraja's callback formats, accepts every prompt, and reports whatever outcome a
    test has set. Never talks to Safaricom."""

    name = "fake"
    title = "M-Pesa simulator (development only)"
    development_only = True
    sent: ClassVar[list[StkRequest]] = []
    outcomes: ClassVar[dict[str, StkResult]] = {}
    refuse_next: ClassVar[str | None] = None
    issued: ClassVar[int] = 0                      # never reset, so request ids stay unique across tests

    @staticmethod
    def last_checkout_id() -> str:
        return f"ws_CO_{SimulatedDarajaProvider.issued:06d}"

    def stk_push(self, request: StkRequest) -> StkResponse:
        cls = SimulatedDarajaProvider
        if cls.refuse_next is not None:
            message, cls.refuse_next = cls.refuse_next, None
            return StkResponse(False, None, message, permanent_failure=True)
        cls.sent.append(request)
        cls.issued += 1
        return StkResponse(True, cls.last_checkout_id(), "Success. Request accepted for processing")

    def query_stk(self, query: StkQuery) -> StkResult:
        return SimulatedDarajaProvider.outcomes.get(query.provider_request_id) or StkResult(
            query.provider_request_id, None, -1, "The transaction is being processed", outcome="pending")

    @staticmethod
    def succeed(checkout_id: str, receipt: str, amount: Decimal, phone: str) -> StkResult:
        result = StkResult(checkout_id, "m-1", 0, "The service request is processed successfully.", receipt, amount,
                           phone, datetime.now(UTC), outcome="succeeded")
        SimulatedDarajaProvider.outcomes[checkout_id] = result
        return result

