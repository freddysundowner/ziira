"""Sockets the messaging plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.messaging.providers import (
    AfricasTalkingSms,
    BlessedTextsSms,
    BrevoEmail,
    FakeChat,
    FakeEmail,
    FakeSms,
    ResendEmail,
    SendGridEmail,
    SmtpEmail,
)
from ziira.sdk import provides

PROVIDERS = (SmtpEmail, BrevoEmail, ResendEmail, SendGridEmail, BlessedTextsSms, AfricasTalkingSms, FakeEmail, FakeSms,
             FakeChat)

for provider in PROVIDERS:
    provides("kernel.notification_channel")(provider)
