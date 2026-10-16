"""Sockets the Paystack plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.billing_paystack.gateway import PaystackGateway
from ziira.sdk import provides

provides("kernel.payment_gateway")(PaystackGateway)
