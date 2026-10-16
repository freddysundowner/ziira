"""The channels a business can use: derived from the messaging providers enabled for it, never from a fixed list.

Every provider (the `kernel.notification_channel` extension point) declares the one channel it offers (`channel`),
what it
can do (`supports_templates`, `supports_buttons`, `supports_inbound`, `window_hours`) and a plain `label` for screens. A
business has a channel when a provider for it belongs to a unit that is enabled for the business: switch the plugin off
and the channel is gone from every list, setting and screen; switch it on and it is back. Whatever was configured for a
channel that is gone is kept but not used: messages go by the next way of reaching the person.

Channels with `window_hours` are conversational: a free-form message may be sent only that many hours after the person
last wrote; outside it only an approved template may start a conversation. A channel with `supports_inbound` receives
replies, so the address of a person on it must be proved to be theirs before anything is done on their word.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ziira.kernel.config import get_settings
from ziira.kernel.errors import ValidationFailed
from ziira.kernel.extensions import implementations

NOTIFICATION_CHANNEL = "kernel.notification_channel"
LABELS = {"sms": "SMS", "email": "Email"}
BASIC = ("sms", "email")                    # channels without conversation rules, offered by the messaging plugin


@dataclass(frozen=True)
class ChannelInfo:
    """What the providers enabled for a business offer on one channel."""

    channel: str
    label: str
    providers: tuple[str, ...]
    supports_templates: bool = False
    supports_buttons: bool = False
    supports_inbound: bool = False
    window_hours: int | None = None

    @property
    def conversational(self) -> bool:
        """Free-form messages only inside a window; templates otherwise."""
        return self.window_hours is not None

    @property
    def address_kind(self) -> str:
        return "email" if self.channel == "email" else "phone"


def _shown(provider: Any) -> bool:
    """Development providers (the fakes) never appear in production, and a test can hide one."""
    if getattr(provider, "hidden", False):
        return False
    return not (getattr(provider, "development_only", False) and get_settings().env == "production")


def available(session: Session) -> list[ChannelInfo]:
    """The channels with an enabled provider for this business, rich ones first, then SMS, then email, then the rest."""
    found: dict[str, list[Any]] = {}
    for provider in implementations(session, NOTIFICATION_CHANNEL):
        if _shown(provider):
            found.setdefault(provider.channel, []).append(provider)
    infos = []
    for channel, providers in found.items():
        infos.append(ChannelInfo(
            channel=channel,
            label=next((p.channel_label for p in providers if p.channel_label), LABELS.get(channel, channel.title())),
            providers=tuple(sorted(p.name for p in providers)),
            supports_templates=any(p.supports_templates for p in providers),
            supports_buttons=any(p.supports_buttons for p in providers),
            supports_inbound=any(p.supports_inbound for p in providers),
            window_hours=next((p.window_hours for p in providers if p.window_hours is not None), None)))
    return sorted(infos, key=lambda i: (not i.conversational, i.channel not in BASIC, i.channel != "sms", i.channel))


def info(session: Session, channel: str) -> ChannelInfo | None:
    return next((i for i in available(session) if i.channel == channel), None)


def names(session: Session) -> list[str]:
    return [i.channel for i in available(session)]


def check(session: Session, channel: str, *, what: str = "Channel") -> str:
    """The channel if this business has it; otherwise a clear refusal naming the ones it has."""
    if info(session, channel) is not None:
        return channel
    have = ", ".join(names(session)) or "none"
    raise ValidationFailed(f"{what} '{channel}' is not available for this business (switch on the plugin that offers "
                           f"it). Available: {have}")
