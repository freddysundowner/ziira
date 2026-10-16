"""Payment gateways: how a business pays the vendor's invoices by itself (docs/subscription-payments.md).

A gateway is a plugin that implements the `kernel.payment_gateway` extension point (`PaymentGateway` below). It turns
an invoice into a payment attempt, says what became of it, and reads the provider's notifications. This module and the
service that uses it (`payments.py`) know no provider, currency or country: each gateway declares its own title,
currencies, countries, payer fields, settings and secrets as data, and the platform owner switches it on in the Super
Admin. Gateways are found at platform level (no business is involved), so a business never "enables" one.

Two shapes of payment exist:

- `prompt`: the provider asks the payer on their phone (a mobile-money prompt); the app shows a live status.
- `redirect`: the payer is sent to the provider's page; the app shows the result when they come back.

Either way the platform never credits an invoice because of what a browser or a notification *says*: it asks the
provider (`check`) and credits only when the provider confirms the status, the amount, the currency and the invoice.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from ziira.kernel.extensions import define_extension_point, implementations_of, provider_named

log = logging.getLogger("ziira.gateways")
PAYMENT_GATEWAY = "kernel.payment_gateway"
HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class GatewayError(Exception):
    """The provider could not be reached or refused a request. `retryable`: a network failure or a 5xx (try again
    later); False for a 4xx (the request itself was refused: trying again will not help). The message is safe to
    show to a person: it never holds a key, a secret or a full phone number."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class SettingField:
    """One thing the platform owner enters for a gateway. A `secret` is write-only: stored encrypted, never shown."""

    name: str
    label: str
    secret: bool = False
    required: bool = True
    default: str = ""
    help: str = ""


@dataclass(frozen=True)
class PayerField:
    """One thing the payer is asked for before paying (`phone`, `email`). `kind` tells the screen which input to use."""

    name: str
    label: str
    kind: str = "text"
    help: str = ""
    required: bool = True


@dataclass(frozen=True)
class GatewayContext:
    """What a gateway needs for one call: its settings, its secrets and an HTTP client (a mock in tests)."""

    config: dict[str, str]
    secrets: dict[str, str]
    http: httpx.Client
    webhook_url: str | None = None


@dataclass(frozen=True)
class AttemptInfo:
    """The attempt a gateway is asked about (never the payer's full details beyond what it needs)."""

    reference: str          # our reference for the attempt: unique, safe to send to the provider
    invoice_number: str
    amount: Decimal
    currency: str
    description: str
    payer: dict[str, str] = field(default_factory=dict)
    provider_transaction_id: str | None = None
    checkout_request_id: str | None = None
    return_url: str | None = None
    cancel_url: str | None = None


@dataclass(frozen=True)
class StartResult:
    """What the provider gave back for a new attempt."""

    provider_transaction_id: str | None = None
    checkout_request_id: str | None = None
    redirect_url: str | None = None
    message: str = ""


@dataclass(frozen=True)
class PaymentState:
    """The provider's own account of an attempt. `status`: pending, completed or failed. `invoice_number` is what the
    provider reports as the invoice reference (None when it does not say)."""

    status: str
    amount: Decimal | None = None
    currency: str | None = None
    invoice_number: str | None = None
    reference: str | None = None
    reason: str = ""
    code: str | None = None
    provider_transaction_id: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """One verified notification. `kind`: completed, failed or ignored. It says only which attempt to look at: the
    platform then asks the provider (`check`) before it believes anything."""

    kind: str
    event_key: str
    provider_transaction_id: str | None = None
    attempt_reference: str | None = None


@dataclass(frozen=True)
class ConnectionTest:
    ok: bool
    message: str


class PaymentGateway(ABC):
    """The contract of a payment gateway plugin (`@provides("kernel.payment_gateway")`)."""

    name: str                                   # short code, e.g. "acme"
    title: str                                  # what the Super Admin calls it
    pay_label: str                              # the button/choice a business sees, e.g. "Pay with Mobile money"
    description: str = ""
    flow: str = "redirect"                      # "prompt" or "redirect"
    methods: tuple[str, ...] = ()               # e.g. ("mobile_money",) or ("card",)
    payment_method: str = "card"                # recorded as the payment's method on the invoice
    currencies: tuple[str, ...] = ()            # empty: any currency
    countries: tuple[str, ...] = ()             # empty: any country
    currency_hint: str = ""                     # plain words shown when the country fits but the currency does not
    config_fields: tuple[SettingField, ...] = ()
    payer_fields: tuple[PayerField, ...] = ()
    development_only: bool = False
    # How long a prompt/redirect stays worth polling before the platform expires the attempt.
    retry_after_seconds: int = 180              # an open attempt older than this may be replaced by a new click

    def validate_config(self, config: dict[str, str]) -> dict[str, str]:
        """Check the (non-secret) settings the owner entered and return them cleaned (raise ValidationFailed)."""
        return config

    def normalise_payer(self, payer: dict[str, str]) -> dict[str, str]:
        """Check what the payer typed and return it in the provider's form (raise ValidationFailed)."""
        return payer

    @abstractmethod
    def start(self, ctx: GatewayContext, attempt: AttemptInfo) -> StartResult:
        """Ask the provider to take the payment. Raises GatewayError."""

    @abstractmethod
    def check(self, ctx: GatewayContext, attempt: AttemptInfo) -> PaymentState:
        """The provider's current account of the attempt. Raises GatewayError."""

    @abstractmethod
    def verify_webhook(self, ctx: GatewayContext, headers: dict[str, str], body: bytes) -> list[WebhookEvent]:
        """Check the signature of a notification on the RAW body and read it. Raises ValidationFailed when it is not
        genuine; returns no events for kinds it does not care about."""

    @abstractmethod
    def test_connection(self, ctx: GatewayContext) -> ConnectionTest:
        """The lightest safe call that shows whether the keys are accepted. Never moves money."""


define_extension_point(PAYMENT_GATEWAY, PaymentGateway, "A way for a business to pay the vendor's invoices")

HttpFactory = Callable[[], httpx.Client]


def _default_http() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False)


# Tests replace this with a client over httpx.MockTransport: no test ever reaches a real service.
http_client_factory: HttpFactory = _default_http


def new_http_client() -> httpx.Client:
    return http_client_factory()


def installed() -> list[type[PaymentGateway]]:
    """Every gateway the installed plugins offer (the fakes only outside production)."""
    from ziira.kernel.config import get_settings

    production = get_settings().env == "production"
    found: list[type[PaymentGateway]] = [
        g for g in implementations_of(PAYMENT_GATEWAY) if issubclass(g, PaymentGateway)
    ]
    return sorted((g for g in found if not (g.development_only and production)), key=lambda g: g.name)


def get_gateway(name: str) -> PaymentGateway | None:
    found = provider_named(PAYMENT_GATEWAY, name)
    if found is None:
        return None
    gateway: PaymentGateway = found()
    from ziira.kernel.config import get_settings

    if gateway.development_only and get_settings().env == "production":
        return None
    return gateway


def call(gateway_name: str, work: Callable[[], Any]) -> Any:
    """Run a gateway call, turning anything unexpected into a GatewayError (never leaking a key in a traceback)."""
    try:
        return work()
    except GatewayError:
        raise
    except httpx.TimeoutException:
        raise GatewayError("The payment service did not answer in time", retryable=True) from None
    except httpx.HTTPError:
        raise GatewayError("The payment service could not be reached", retryable=True) from None


def classify_response(response: httpx.Response, *, what: str = "The payment service") -> None:
    """Raise a GatewayError for an HTTP error status: 5xx and 429 are retryable, other 4xx are not. The provider's own
    short message is kept when it sends one (never the request, so no key can leak)."""
    code = response.status_code
    if code < 400:
        return
    if code in (401, 403):
        raise GatewayError(f"{what} did not accept our access key", retryable=False)
    detail = ""
    try:
        body = response.json()
        error = body.get("error", body) if isinstance(body, dict) else {}
        for source in (error, body):
            if isinstance(source, dict):
                value = source.get("message") or source.get("error")
                if isinstance(value, str) and value.strip():
                    detail = value.strip()[:200]
                    break
    except ValueError:
        detail = ""
    retryable = code >= 500 or code == 429
    raise GatewayError(detail or f"{what} refused the request (HTTP {code})", retryable=retryable)
