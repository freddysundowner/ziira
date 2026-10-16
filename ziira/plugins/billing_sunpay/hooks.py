"""Sockets the SunPay plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.billing_sunpay.gateway import SunPayGateway
from ziira.sdk import provides

provides("kernel.payment_gateway")(SunPayGateway)
