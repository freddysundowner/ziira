"""Sockets the Payments module offers and plugs into (declared in manifest.toml)."""

from ziira.modules.payments.providers import DarajaProvider, FakeProvider
from ziira.modules.payments.public import PROVIDER_EXTENSION, PaymentProvider
from ziira.sdk import define_extension_point, provides

define_extension_point(PROVIDER_EXTENSION, PaymentProvider,
                       "A way to ask customers for money (an STK push); Daraja and a fake one are built in.")

provides(PROVIDER_EXTENSION)(DarajaProvider)
provides(PROVIDER_EXTENSION)(FakeProvider)
