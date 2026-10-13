"""Sockets the messaging plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.messaging.providers import (
    AfricasTalkingSms,
    FakeEmail,
    FakeSms,
    FakeWhatsApp,
    SmtpEmail,
    WhatsAppCloud,
)
from ziira.sdk import provides

for provider in (SmtpEmail, AfricasTalkingSms, WhatsAppCloud, FakeEmail, FakeSms, FakeWhatsApp):
    provides("kernel.notification_channel")(provider)
