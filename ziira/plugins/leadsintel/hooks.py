"""Sockets the Lead Intel plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.leadsintel.providers import LeadIntelWhatsApp
from ziira.sdk import provides

provides("kernel.notification_channel")(LeadIntelWhatsApp)
