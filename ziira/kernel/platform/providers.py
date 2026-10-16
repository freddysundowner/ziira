"""Billing providers: how a subscriber can pay the vendor (docs/platform-admin.md, "Payment providers").

This is the platform-side socket for a payment gateway. **No real gateway is implemented**: live gateways are parked. A
provider turns an invoice into a way to pay (`checkout_link`), may charge a saved method (`charge`), and tells the
platform about payments it received (`parse_webhook`), which the platform records like a manually entered payment.

Two providers exist now:

- `manual`: the vendor receives money outside the system (bank transfer, cash, mobile money) and records it in the Super
  Admin. It has no checkout link; the subscriber sees the vendor's payment instructions.
- `fake`: for tests and demos only; it "charges" successfully, gives a link on a made-up address and reads a simple JSON
  webhook. It refuses to run in production.

A real gateway plugin subclasses `BillingProvider` and calls `register(MyProvider)` when its package is imported.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from ziira.kernel.config import get_settings
from ziira.kernel.errors import NotFound, ValidationFailed


@dataclass(frozen=True)
class ProviderPayment:
    """A payment a provider reports: which invoice, how much, and the provider's own reference."""

    invoice_number: str
    amount: Decimal
    reference: str
    paid_on: date | None = None


class BillingProvider(ABC):
    """The contract of a billing provider."""

    name: str
    label: str

    @abstractmethod
    def checkout_link(self, invoice: dict[str, Any], return_url: str) -> str | None:
        """A web address where the subscriber can pay this invoice, or None when payment happens elsewhere."""

    @abstractmethod
    def charge(self, invoice: dict[str, Any], payment_method: dict[str, Any]) -> ProviderPayment:
        """Take payment for an invoice from a saved method. Raises ValidationFailed when it is refused."""

    @abstractmethod
    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[ProviderPayment]:
        """Check and read a notification from the provider (raise ValidationFailed when it is not genuine)."""


_providers: dict[str, type[BillingProvider]] = {}


def register(provider: type[BillingProvider]) -> type[BillingProvider]:
    """Make a provider available (usable as a class decorator)."""
    _providers[provider.name] = provider
    return provider


def get(name: str) -> BillingProvider:
    if name not in _providers:
        raise NotFound(f"No billing provider '{name}'. Available: {', '.join(sorted(_providers))}")
    return _providers[name]()


def names() -> list[str]:
    return sorted(_providers)


@register
class ManualProvider(BillingProvider):
    name = "manual"
    label = "Pay the vendor directly (bank transfer, cash, mobile money)"

    def checkout_link(self, invoice: dict[str, Any], return_url: str) -> str | None:
        return None

    def charge(self, invoice: dict[str, Any], payment_method: dict[str, Any]) -> ProviderPayment:
        raise ValidationFailed("Manual billing takes no automatic charges: the vendor records the payment")

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[ProviderPayment]:
        raise ValidationFailed("Manual billing has no webhook")


@register
class FakeProvider(BillingProvider):
    """Tests and demos only. `parse_webhook` reads {"payments": [{"invoice": "INV-000001", "amount": "10.00",
    "reference": "x"}]} when the header `x-fake-signature` is `ok`."""

    name = "fake"
    label = "Fake provider (tests)"

    def _guard(self) -> None:
        if get_settings().env == "production":
            raise ValidationFailed("The fake billing provider is not available in production")

    def checkout_link(self, invoice: dict[str, Any], return_url: str) -> str | None:
        self._guard()
        return f"https://pay.example.test/checkout/{invoice['id']}?return={return_url}"

    def charge(self, invoice: dict[str, Any], payment_method: dict[str, Any]) -> ProviderPayment:
        self._guard()
        if payment_method.get("decline"):
            raise ValidationFailed("The card was declined")
        return ProviderPayment(
            invoice["number"], Decimal(invoice["total"]) - Decimal(invoice["amount_paid"]), f"fake-{invoice['number']}"
        )

    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[ProviderPayment]:
        self._guard()
        if headers.get("x-fake-signature") != "ok":
            raise ValidationFailed("The notification is not genuine")
        data = json.loads(body)
        return [
            ProviderPayment(p["invoice"], Decimal(str(p["amount"])), str(p["reference"]))
            for p in data.get("payments", [])
        ]
