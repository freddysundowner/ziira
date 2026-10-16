"""Sockets the Stripe plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.billing_stripe.gateway import StripeGateway
from ziira.sdk import provides

provides("kernel.payment_gateway")(StripeGateway)
