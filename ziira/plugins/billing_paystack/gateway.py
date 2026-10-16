"""Card and bank payments through Paystack's hosted payment page.

Shapes follow Paystack's public documentation (paystack.com/docs/api/transaction and /docs/payments/webhooks) and have
NOT been run against the real service: each is marked `# UNVERIFIED` and listed in docs/subscription-payments.md with a
live-test checklist (use test keys first).
"""

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

from ziira.sdk import (
    AttemptInfo,
    ConnectionTest,
    GatewayContext,
    GatewayError,
    PayerField,
    PaymentGateway,
    PaymentState,
    SettingField,
    StartResult,
    ValidationFailed,
    WebhookEvent,
    classify_response,
)

DEFAULT_BASE_URL = "https://api.paystack.co"
SUBUNIT = Decimal(100)          # every currency Paystack serves here (NGN, GHS, ZAR, KES, USD) has 100 subunits
PENDING = {"ongoing", "pending", "processing", "queued", "abandoned"}


def _meta(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


class PaystackGateway(PaymentGateway):
    name = "paystack"
    title = "Card and bank (Paystack)"
    pay_label = "Pay with Paystack"
    description = "The owner is sent to Paystack's secure page to pay, then returns to Plan & billing."
    flow = "redirect"
    methods = ("card", "bank")
    payment_method = "card"
    currencies = ("NGN", "GHS", "ZAR", "KES", "USD")
    retry_after_seconds = 1800
    config_fields = (
        SettingField("base_url", "Paystack API address", default=DEFAULT_BASE_URL),
        SettingField("secret_key", "Secret key", secret=True,
                     help="Starts with sk_ (use sk_test_ while testing). Paystack signs notifications with it too."),
    )
    payer_fields = (
        PayerField("email", "Email for the receipt", kind="email", help="Paystack sends the receipt here."),
    )

    @staticmethod
    def _url(ctx: GatewayContext, path: str) -> str:
        return ctx.config.get("base_url", DEFAULT_BASE_URL).rstrip("/") + path

    @staticmethod
    def _headers(ctx: GatewayContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {ctx.secrets.get('secret_key', '')}"}

    def validate_config(self, config: dict[str, str]) -> dict[str, str]:
        url = config.get("base_url", "").strip() or DEFAULT_BASE_URL
        if not (url.startswith("https://") or url.startswith("http://localhost")):
            raise ValidationFailed("The Paystack address must start with https://")
        return {**config, "base_url": url.rstrip("/")}

    def normalise_payer(self, payer: dict[str, str]) -> dict[str, str]:
        email = payer.get("email", "").strip()
        if email and ("@" not in email or " " in email or len(email) > 254):
            raise ValidationFailed("Enter a valid email address")
        return {"email": email}

    def start(self, ctx: GatewayContext, attempt: AttemptInfo) -> StartResult:
        if not attempt.payer.get("email"):
            raise GatewayError("Paystack needs an email address for the receipt")
        minor = attempt.amount * SUBUNIT
        if minor != minor.to_integral_value():
            raise GatewayError("That amount cannot be charged in the smallest unit")
        body = {                                                         # UNVERIFIED: fields from the docs
            "email": attempt.payer["email"],
            "amount": str(int(minor)),
            "currency": attempt.currency,
            "reference": attempt.reference,
            "callback_url": attempt.return_url,
            "metadata": json.dumps({"invoice_number": attempt.invoice_number, "attempt_reference": attempt.reference}),
        }
        response = ctx.http.post(self._url(ctx, "/transaction/initialize"), json=body, headers=self._headers(ctx))
        classify_response(response, what="Paystack")
        data = response.json().get("data") if isinstance(response.json(), dict) else None
        if not isinstance(data, dict) or not data.get("authorization_url"):
            raise GatewayError("Paystack did not give a payment page")
        return StartResult(provider_transaction_id=str(data.get("reference") or attempt.reference),
                           redirect_url=str(data["authorization_url"]))

    def check(self, ctx: GatewayContext, attempt: AttemptInfo) -> PaymentState:
        response = ctx.http.get(                                         # UNVERIFIED: verify endpoint fields
            self._url(ctx, f"/transaction/verify/{attempt.reference}"), headers=self._headers(ctx)
        )
        classify_response(response, what="Paystack")
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise GatewayError("Paystack sent an answer we could not read", retryable=True)
        status = str(data.get("status", "")).lower()
        if status == "success":
            ours = data.get("reference") == attempt.reference
            return PaymentState(
                "completed",
                amount=Decimal(str(data.get("amount", 0))) / SUBUNIT,
                currency=str(data.get("currency") or "").upper() or None,
                invoice_number=_meta(data.get("metadata")).get("invoice_number") if ours else "(a different payment)",
                reference=str(data.get("reference")),
            )
        if status in PENDING:
            return PaymentState("pending")
        return PaymentState("failed", reason=str(data.get("gateway_response") or "The payment was not completed")[:200])

    def verify_webhook(self, ctx: GatewayContext, headers: dict[str, str], body: bytes) -> list[WebhookEvent]:
        secret = ctx.secrets.get("secret_key", "")
        given = headers.get("x-paystack-signature", "").strip().lower()
        expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest() if secret else ""
        if not secret or len(given) != len(expected) or not hmac.compare_digest(given.encode(), expected.encode()):
            raise ValidationFailed("The notification is not genuine")
        try:
            event = json.loads(body)
            name, data = str(event["event"]), event["data"]
        except (ValueError, KeyError, TypeError):
            raise ValidationFailed("The notification could not be read") from None
        reference = str(data.get("reference") or "") if isinstance(data, dict) else ""
        if name != "charge.success" or not reference:
            return [WebhookEvent("ignored", f"{name}:{reference}")]
        return [WebhookEvent("completed", f"{name}:{reference}", attempt_reference=reference)]

    def test_connection(self, ctx: GatewayContext) -> ConnectionTest:
        # UNVERIFIED: verifying a reference that cannot exist; 404 means the key was accepted.
        url = self._url(ctx, f"/transaction/verify/zp-test-{uuid4().hex}")
        response = ctx.http.get(url, headers=self._headers(ctx))
        if response.status_code in (401, 403):
            return ConnectionTest(False, "Paystack rejected the secret key")
        if response.status_code >= 500:
            return ConnectionTest(False, "Paystack is not answering properly right now")
        return ConnectionTest(True, "Paystack accepted the secret key")
