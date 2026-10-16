"""M-Pesa through SunPay: a prompt on the payer's phone (STK push), a live status, and signed notifications.

Every request shape and every claim about SunPay's behaviour below is written from its public documentation
(https://sunpay.co.ke/docs) and has NOT been run against the real service: each is marked `# UNVERIFIED` and listed
in docs/subscription-payments.md with a live-test checklist. The service's address is a setting (default
https://sunpay.co.ke); the docs page prints api.sunpay.co.ke, which the owner says is wrong.
"""

import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation
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

DEFAULT_BASE_URL = "https://sunpay.co.ke"
API = "/api/v1"
LOCAL = re.compile(r"^http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/|$)")


def normalise_phone(value: str) -> str:
    """07XXXXXXXX, 01XXXXXXXX, +254..., 254... or 7XXXXXXXX become 254XXXXXXXXX (SunPay is Kenya-only by nature)."""
    digits = re.sub(r"[\s().-]", "", value or "")
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        raise ValidationFailed("Enter the M-Pesa number with digits only, for example 0712 345 678")
    if digits.startswith("254"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if not re.fullmatch(r"[17]\d{8}", national):
        raise ValidationFailed("That does not look like an M-Pesa number: use 07.. or 01.. or +254..")
    return "254" + national


def _number(amount: Decimal) -> int | float:
    return int(amount) if amount == amount.to_integral_value() else float(amount)


class SunPayGateway(PaymentGateway):
    name = "sunpay"
    title = "M-Pesa (SunPay)"
    pay_label = "Pay with M-Pesa"
    description = "A prompt on the owner's phone; they enter their M-Pesa PIN. Charged in KES only."
    flow = "prompt"
    methods = ("mobile_money",)
    payment_method = "mobile_money"
    currencies = ("KES",)
    countries = ("KE",)
    currency_hint = "M-Pesa payments are in KES: ask us for a KES price"
    retry_after_seconds = 180
    config_fields = (
        SettingField("base_url", "SunPay address", default=DEFAULT_BASE_URL,
                     help="Where SunPay's API lives. Change it here if SunPay moves; no code change needed."),
        SettingField("api_key", "API key", secret=True, help="From SunPay: Settings, API Keys. Starts with sp_."),
        SettingField("webhook_secret", "Webhook secret", secret=True,
                     help="The secret SunPay shows when you register the webhook address below."),
    )
    payer_fields = (
        PayerField("phone", "M-Pesa number", kind="tel", help="The number that will receive the M-Pesa prompt"),
    )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _url(ctx: GatewayContext, path: str) -> str:
        return ctx.config.get("base_url", DEFAULT_BASE_URL).rstrip("/") + API + path

    @staticmethod
    def _headers(ctx: GatewayContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {ctx.secrets.get('api_key', '')}", "Accept": "application/json"}

    def validate_config(self, config: dict[str, str]) -> dict[str, str]:
        url = config.get("base_url", "").strip() or DEFAULT_BASE_URL
        if not (url.startswith("https://") or LOCAL.match(url)):
            raise ValidationFailed("The SunPay address must start with https://")
        return {**config, "base_url": url.rstrip("/")}

    def normalise_payer(self, payer: dict[str, str]) -> dict[str, str]:
        return {"phone": normalise_phone(payer.get("phone", ""))}

    # ------------------------------------------------------------------ the contract
    def start(self, ctx: GatewayContext, attempt: AttemptInfo) -> StartResult:
        body = {                                                          # UNVERIFIED: shape from the docs only
            "phoneNumber": attempt.payer["phone"],
            "amount": _number(attempt.amount),
            "externalRef": attempt.invoice_number,
        }
        response = ctx.http.post(self._url(ctx, "/payments/stk-push"), json=body, headers=self._headers(ctx))
        classify_response(response, what="SunPay")
        data = response.json()
        if not isinstance(data, dict) or data.get("success") is False or not data.get("transactionId"):
            message = data.get("message") if isinstance(data, dict) else None
            raise GatewayError(str(message or "SunPay did not accept the request")[:200])
        return StartResult(
            provider_transaction_id=str(data["transactionId"]),
            checkout_request_id=str(data["checkoutRequestId"]) if data.get("checkoutRequestId") else None,
            message=str(data.get("message") or "")[:200],
        )

    def check(self, ctx: GatewayContext, attempt: AttemptInfo) -> PaymentState:
        if not attempt.provider_transaction_id:
            raise GatewayError("The payment has no SunPay transaction yet")
        response = ctx.http.get(                                          # UNVERIFIED: status endpoint fields
            self._url(ctx, f"/payments/{attempt.provider_transaction_id}"), headers=self._headers(ctx)
        )
        classify_response(response, what="SunPay")
        data = response.json()
        if not isinstance(data, dict):
            raise GatewayError("SunPay sent an answer we could not read", retryable=True)
        status = str(data.get("status", "")).lower()
        try:
            amount = Decimal(str(data["amount"])) if data.get("amount") is not None else None
        except InvalidOperation:
            amount = None
        if status == "completed":
            return PaymentState("completed", amount=amount, currency="KES", reference=data.get("mpesaRef"),
                                provider_transaction_id=attempt.provider_transaction_id)
        if status == "failed":
            return PaymentState("failed", reason="The M-Pesa payment was cancelled or did not go through",
                                provider_transaction_id=attempt.provider_transaction_id)
        return PaymentState("pending", provider_transaction_id=attempt.provider_transaction_id)

    def verify_webhook(self, ctx: GatewayContext, headers: dict[str, str], body: bytes) -> list[WebhookEvent]:
        secret = ctx.secrets.get("webhook_secret", "")
        given = headers.get("x-webhook-signature", "").strip().lower()
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest() if secret else ""
        # Compare as bytes after a length check (compare_digest on different lengths is fine, but be explicit).
        if not secret or len(given) != len(expected) or not hmac.compare_digest(given.encode(), expected.encode()):
            raise ValidationFailed("The notification is not genuine")
        try:
            payload = json.loads(body)
        except ValueError:
            raise ValidationFailed("The notification could not be read") from None
        if not isinstance(payload, dict):
            raise ValidationFailed("The notification could not be read")
        event = str(payload.get("event", ""))
        raw = payload.get("data")
        data: dict[str, object] = raw if isinstance(raw, dict) else {}
        txn = str(data.get("transactionId") or "") or None
        kind = {"payment.completed": "completed", "payment.failed": "failed"}.get(event, "ignored")
        if kind == "ignored" or txn is None:
            return [WebhookEvent("ignored", f"{event}:{txn}")]
        return [WebhookEvent(kind, f"{event}:{txn}", provider_transaction_id=txn)]

    def test_connection(self, ctx: GatewayContext) -> ConnectionTest:
        # UNVERIFIED: a status lookup of an id that cannot exist. 404 means the key was accepted, 401/403 rejected.
        response = ctx.http.get(self._url(ctx, f"/payments/{uuid4()}"), headers=self._headers(ctx))
        if response.status_code in (401, 403):
            return ConnectionTest(False, "SunPay rejected the API key")
        if response.status_code >= 500:
            return ConnectionTest(False, "SunPay is not answering properly right now")
        return ConnectionTest(True, "SunPay accepted the API key")
