"""Sockets the platform chat plugin plugs into (declared under [extends] in manifest.toml)."""

from ziira.plugins.leadsintel_platform.fake import FakeChatProvider
from ziira.plugins.leadsintel_platform.provider import LeadIntelPlatformChat
from ziira.sdk import provides

provides("kernel.platform_chat_channel")(LeadIntelPlatformChat)
provides("kernel.platform_chat_channel")(FakeChatProvider)
