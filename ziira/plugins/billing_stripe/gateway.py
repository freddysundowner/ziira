"""Card payments through Stripe Checkout (Stripe's hosted page: no card data touches Ziira).

Request and notification shapes follow Stripe's public documentation (docs.stripe.com/api/checkout/sessions and
docs.stripe.com/webhooks) and have NOT been run against the real service: each is marked `# UNVERIFIED` and listed in
docs/subscription-payments.md with a live-test checklist (use test-mode keys and test cards first).
"""

import hashlib
import hmac
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

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

DEFAULT_BASE_URL = "https://api.stripe.com"
TOLERANCE_SECONDS = 300
_DATA = json.loads((Path(__file__).parent / "currencies.json").read_text())


def decimals_of(currency: str) -> int:
    """Places in Stripe's smallest unit for the currency (from currencies.json)."""
    code = currency.upper()
    return 0 if code in _DATA["zero_decimal"] else 3 if code in _DATA["three_decimal"] else 2


def to_minor(amount: Decimal, currency: str) -> int:
    scaled = amount * (Decimal(10) ** decimals_of(currency))
    if scaled != scaled.to_integral_value():
        raise GatewayError(f"{amount} {currency} cannot be charged in {currency}'s smallest unit")
    return int(scaled)


def from_minor(minor: int, currency: str) -> Decimal:
    return Decimal(minor) / (Decimal(10) ** decimals_of(currency))


def now() -> float:
    """The clock the signature tolerance uses (tests replace it)."""
    return time.time()


class StripeGateway(PaymentGateway):
    name = "stripe"
    title = "Card (Stripe)"
    pay_label = "Pay by card"
    description = "The owner is sent to Stripe's secure page to pay by card, then returns to Plan & billing."
    flow = "redirect"
    methods = ("card",)
    payment_method = "card"
    retry_after_seconds = 1800
    config_fields = (
        SettingField("base_url", "Stripe API address", default=DEFAULT_BASE_URL),
        SettingField("secret_key", "Secret key", secret=True, help="Starts with sk_ (use sk_test_ while testing)."),
        SettingField("webhook_secret", "Webhook signing secret", secret=True,
                     help="Starts with whsec_, shown when you add the webhook address below in Stripe."),
    )
    payer_fields = (
        PayerField("email", "Email for the receipt", kind="email", required=False,
                   help="Stripe sends the card receipt here. Leave empty to use the owner's email."),
    )

    @staticmethod
    def _url(ctx: GatewayContext, path: str) -> str:
        return ctx.config.get("base_url", DEFAULT_BASE_URL).rstrip("/") + path

    @staticmethod
    def _headers(ctx: GatewayContext, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {ctx.secrets.get('secret_key', '')}", **extra}

    def validate_config(self, config: dict[str, str]) -> dict[str, str]:
        url = config.get("base_url", "").strip() or DEFAULT_BASE_URL
        if not (url.startswith("https://") or url.startswith("http://localhost")):
            raise ValidationFailed("The Stripe address must start with https://")
        return {**config, "base_url": url.rstrip("/")}

    def start(self, ctx: GatewayContext, attempt: AttemptInfo) -> StartResult:
        form = {                                                         # UNVERIFIED: form field names from the docs
            "mode": "payment",
            "client_reference_id": attempt.reference,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": attempt.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(to_minor(attempt.amount, attempt.currency)),
            "line_items[0][price_data][product_data][name]": attempt.description,
            "metadata[invoice_number]": attempt.invoice_number,
            "metadata[attempt_reference]": attempt.reference,
            "payment_intent_data[metadata][attempt_reference]": attempt.reference,
            "success_url": attempt.return_url or "",
            "cancel_url": attempt.cancel_url or "",
        }
        if attempt.payer.get("email"):
            form["customer_email"] = attempt.payer["email"]
        response = ctx.http.post(
            self._url(ctx, "/v1/checkout/sessions"), data=form,
            headers=self._headers(ctx, **{"Idempotency-Key": attempt.reference}),
        )
        classify_response(response, what="Stripe")
        data = response.json()
        if not isinstance(data, dict) or not data.get("id") or not data.get("url"):
            raise GatewayError("Stripe did not give a payment page")
        return StartResult(provider_transaction_id=str(data["id"]), redirect_url=str(data["url"]))

    def check(self, ctx: GatewayContext, attempt: AttemptInfo) -> PaymentState:
        if not attempt.provider_transaction_id:
            raise GatewayError("The payment has no Stripe session yet")
        response = ctx.http.get(                                         # UNVERIFIED: retrieve a session
            self._url(ctx, f"/v1/checkout/sessions/{attempt.provider_transaction_id}"), headers=self._headers(ctx)
        )
        classify_response(response, what="Stripe")
        session: dict[str, Any] = response.json()
        if not isinstance(session, dict):
            raise GatewayError("Stripe sent an answer we could not read", retryable=True)
        currency = str(session.get("currency") or "").upper() or None
        if session.get("status") == "expired":
            return PaymentState("failed", reason="The payment page expired before the card was charged")
        if session.get("status") == "complete" and session.get("payment_status") == "paid" and currency:
            ours = session.get("client_reference_id") == attempt.reference
            meta = session.get("metadata") or {}
            intent = session.get("payment_intent")
            return PaymentState(
                "completed",
                amount=from_minor(int(session.get("amount_total") or 0), currency),
                currency=currency,
                invoice_number=meta.get("invoice_number") if ours else "(a different payment)",
                reference=str(intent) if intent else None,
                provider_transaction_id=str(session.get("id")),
            )
        return PaymentState("pending")

    def verify_webhook(self, ctx: GatewayContext, headers: dict[str, str], body: bytes) -> list[WebhookEvent]:
        secret = ctx.secrets.get("webhook_secret", "")
        parts = [p.split("=", 1) for p in headers.get("stripe-signature", "").split(",") if "=" in p]
        stamps = [v for k, v in parts if k.strip() == "t"]
        signatures = [v.strip().lower() for k, v in parts if k.strip() == "v1"]      # ignore other schemes
        if not secret or not stamps or not signatures or not stamps[0].isdigit():
            raise ValidationFailed("The notification is not genuine")
        expected = hmac.new(secret.encode(), stamps[0].encode() + b"." + body, hashlib.sha256).hexdigest()
        if not any(len(s) == len(expected) and hmac.compare_digest(s.encode(), expected.encode()) for s in signatures):
            raise ValidationFailed("The notification is not genuine")
        if abs(now() - int(stamps[0])) > TOLERANCE_SECONDS:
            raise ValidationFailed("The notification is too old")
        try:
            event = json.loads(body)
            kind, key = str(event["type"]), str(event["id"])
            obj = event["data"]["object"]
        except (ValueError, KeyError, TypeError):
            raise ValidationFailed("The notification could not be read") from None
        outcome = {
            "checkout.session.completed": "completed",
            "checkout.session.async_payment_succeeded": "completed",
            "checkout.session.expired": "failed",
            "checkout.session.async_payment_failed": "failed",
            "payment_intent.payment_failed": "failed",
        }.get(kind, "ignored")
        if outcome == "ignored" or not isinstance(obj, dict):
            return [WebhookEvent("ignored", key)]
        if kind.startswith("checkout.session"):
            return [WebhookEvent(outcome, key, provider_transaction_id=str(obj.get("id") or "") or None,
                                 attempt_reference=obj.get("client_reference_id"))]
        meta = obj.get("metadata") or {}
        return [WebhookEvent(outcome, key, attempt_reference=meta.get("attempt_reference"))]

    def test_connection(self, ctx: GatewayContext) -> ConnectionTest:
        response = ctx.http.get(self._url(ctx, "/v1/balance"), headers=self._headers(ctx))   # UNVERIFIED: read scope
        if response.status_code in (401, 403):
            return ConnectionTest(False, "Stripe rejected the secret key")
        if response.status_code >= 500:
            return ConnectionTest(False, "Stripe is not answering properly right now")
        return ConnectionTest(True, "Stripe accepted the secret key")
