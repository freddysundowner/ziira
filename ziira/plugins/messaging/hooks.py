"""Sockets the messaging plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.messaging.providers import (
    AfricasTalkingSms,
    BlessedTextsSms,
    FakeEmail,
    FakeSms,
    SmtpEmail,
)
from ziira.sdk import provides

for provider in (SmtpEmail, BlessedTextsSms, AfricasTalkingSms, FakeEmail, FakeSms):
    provides("kernel.notification_channel")(provider)
