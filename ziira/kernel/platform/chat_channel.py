"""The platform's own chat channel: a way for the public to talk to the platform's assistant by message (the "bot").

This is the platform-level twin of the payment gateways (`gateways.py`): a provider plugin implements the
`kernel.platform_chat_channel` extension point (`PlatformChatProvider`), is found at platform level (its manifest says
`platform_scope = true`) and is set up by the platform owner in the Super Admin, never switched on by a business. It has
nothing to do with the per-business notification channels (docs/channels.md).

The kernel owns everything that is the same for every provider (settings and encrypted secrets, the public inbound
address, de-duplication, limits, the conversation, hand-offs, the audit trail: `chat_bot.py`, `chat_inbound.py`). The
provider owns only what is its own: how to connect a number, how to read a signed delivery, how a reply is sent.

Nothing here names a service, a country or a currency.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from ziira.kernel.errors import ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations_of, provider_named
from ziira.kernel.platform.gateways import ConnectionTest, SettingField

log = logging.getLogger("ziira.chat")
PLATFORM_CHAT_CHANNEL = "kernel.platform_chat_channel"
HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
BUTTON_TITLE_MAX = 20
BUTTONS_MAX = 3
TEXT_MAX = 4000
BUTTON_BODY_MAX = 1024


class ChatError(Exception):
    """The provider refused a call or could not be reached. `message` is plain words, safe to show to the platform
    owner:
    it never holds a key, a secret or a full phone number. `code` is a short machine word (`key_rejected`,
    `number_in_use`, `rate_limited`, `unavailable` ...). `retryable`: an outage or a rate limit (try again later)."""

    def __init__(self, message: str, *, code: str = "refused", retryable: bool = False, retry_after: int | None = None):
        super().__init__(message)
        self.message, self.code, self.retryable, self.retry_after = message, code, retryable, retry_after


@dataclass(frozen=True)
class ChatButton:
    id: str
    title: str


@dataclass(frozen=True)
class ChatReply:
    """What the bot says: plain text, optionally with up to three reply buttons."""

    text: str
    buttons: tuple[ChatButton, ...] = ()


@dataclass(frozen=True)
class ChatMessageIn:
    """One message a person sent, in the provider-neutral shape. `kind`: text | button | media | other."""

    id: str
    sender: str  # the sender's number as digits, no plus sign
    kind: str
    text: str = ""
    button_id: str | None = None


@dataclass(frozen=True)
class ChatDelivery:
    """One verified delivery: its id (for de-duplication), the number it was for and the messages in it."""

    event_id: str
    receiver_id: str | None = None
    messages: tuple[ChatMessageIn, ...] = ()
    reply_timeout_ms: int | None = None


@dataclass(frozen=True)
class ChatConnectRequest:
    """What the owner typed to connect a number. `mode`: `new` (a number not yet on the provider) or `existing` (a
    number
    that is already there and is claimed with a code)."""

    mode: str
    country_code: str  # digits
    phone_number: str  # digits, no country code
    business_name: str
    display_name: str
    webhook_url: str
    webhook_secret: str
    profile: dict[str, str] = field(default_factory=dict)
    tenant_ref: str = ""
    connection_ref: str = ""


@dataclass(frozen=True)
class ChatConnectState:
    """Where connecting stands. `status`: pending | awaiting_code | connected | failed | cancelled."""

    status: str
    request_ref: str | None = None
    message: str = ""
    code: str = ""
    phone_number_id: str | None = None
    display_phone: str | None = None


@dataclass(frozen=True)
class ChatConnectionInfo:
    """A connection as the provider reports it. `active` is true only when messages can flow."""

    active: bool
    status: str
    phone_number_id: str | None = None
    display_phone: str | None = None
    tenant_ref: str = ""
    connection_ref: str = ""


@dataclass(frozen=True)
class ChatContext:
    """What a provider needs for one call: its settings, its secrets and an HTTP client (a mock in tests)."""

    config: dict[str, str]
    secrets: dict[str, str]
    http: httpx.Client
    connection: dict[str, str] = field(default_factory=dict)  # the stored references (tenant, connection, number id)
    webhook_url: str | None = None


class PlatformChatProvider(ABC):
    """The contract of a platform chat provider (`@provides("kernel.platform_chat_channel")`)."""

    name: str
    title: str
    description: str = ""
    development_only: bool = False
    config_fields: tuple[SettingField, ...] = ()
    supports_profile: bool = True
    supports_existing_number: bool = True

    # ---- the key
    @abstractmethod
    def test_key(self, ctx: ChatContext) -> ConnectionTest:
        """The lightest authenticated read that shows whether the key is accepted. Changes nothing."""

    # ---- connecting
    @abstractmethod
    def start_connect(self, ctx: ChatContext, request: ChatConnectRequest) -> ChatConnectState:
        """Ask the provider to connect a number (new, or claim an existing one). Raises ChatError."""

    @abstractmethod
    def poll_connect(self, ctx: ChatContext, request_ref: str) -> ChatConnectState:
        """Where connecting stands. Raises ChatError."""

    @abstractmethod
    def cancel_connect(self, ctx: ChatContext, request_ref: str) -> None:
        """Cancel a request that is still waiting. Raises ChatError."""

    @abstractmethod
    def verify_code(self, ctx: ChatContext, request_ref: str, code: str) -> ChatConnectState:
        """Give the code sent to a number being claimed. Raises ChatError."""

    @abstractmethod
    def find_connection(self, ctx: ChatContext, country_code: str, phone_number: str) -> ChatConnectionInfo | None:
        """Look up a number that may already be connected (to recover its references). None when there is none."""

    @abstractmethod
    def connection_info(self, ctx: ChatContext) -> ChatConnectionInfo:
        """The stored connection as the provider sees it now. Raises ChatError."""

    @abstractmethod
    def disconnect(self, ctx: ChatContext) -> None:
        """Remove the connection at the provider. Raises ChatError."""

    @abstractmethod
    def update_webhook(self, ctx: ChatContext, url: str, secret: str) -> None:
        """Point the provider at a new inbound address and signing secret. Raises ChatError."""

    @abstractmethod
    def update_profile(self, ctx: ChatContext, profile: dict[str, str]) -> None:
        """Change the public profile of the number (about, description, website). Raises ChatError."""

    # ---- talking
    @abstractmethod
    def read_delivery(self, ctx: ChatContext, headers: dict[str, str], body: bytes, secret: str) -> ChatDelivery:
        """Check the signature on the RAW body (constant time) and read it. Raises ValidationFailed when it is not
        genuine (one message for every reason); returns no messages for things it does not care about."""

    @abstractmethod
    def reply_body(self, reply: ChatReply) -> dict[str, object]:
        """The reply as the provider wants it in the answer to a delivery."""

    @abstractmethod
    def send(self, ctx: ChatContext, to: str, reply: ChatReply, idempotency_key: str) -> None:
        """Send a message later (outside a delivery's answer). The same key never sends twice. Raises ChatError."""

    # ---- development only (the fake provider; the real ones leave these alone)
    def simulate_delivery(
        self, secret: str, sender: str, message: str, button_id: str | None, receiver_id: str | None
    ) -> tuple[dict[str, str], bytes]:
        """A signed delivery as the provider would post it: (headers, raw body). Used by the development screen."""
        raise ChatError("This provider cannot simulate deliveries", code="refused")

    def captured_sends(self) -> list[dict[str, str]]:
        """Messages the development provider was asked to send (newest last)."""
        return []


define_extension_point(
    PLATFORM_CHAT_CHANNEL, PlatformChatProvider, "A way for the public to chat with the platform's bot"
)

HttpFactory = Callable[[], httpx.Client]


def _default_http() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False)


# Tests replace this with a client over httpx.MockTransport: no test ever reaches a real service.
http_client_factory: HttpFactory = _default_http


def new_http_client() -> httpx.Client:
    return http_client_factory()


def fake_mode() -> bool:
    """Development only (`ZIIRA_CHAT_FAKE=1`, ignored in production): the fake provider stands in for the real one."""
    from ziira.kernel.config import get_settings

    s = get_settings()
    return bool(s.chat_fake) and s.env != "production"


def installed() -> list[type[PlatformChatProvider]]:
    """The providers the installed plugins offer. With the fake mode on only the fake one; otherwise never the fake."""
    found = [p for p in implementations_of(PLATFORM_CHAT_CHANNEL) if issubclass(p, PlatformChatProvider)]
    fake = fake_mode()
    return sorted((p for p in found if p.development_only == fake), key=lambda p: p.name)


def get_provider(name: str) -> PlatformChatProvider | None:
    found = provider_named(PLATFORM_CHAT_CHANNEL, name)
    if found is None or not issubclass(found, PlatformChatProvider):
        return None
    provider = found()
    if provider.development_only != fake_mode():
        return None
    return provider


def the_provider() -> PlatformChatProvider:
    """The one provider in use (there is one at a time). Raises ValidationFailed with plain words when there is none."""
    options = installed()
    if not options:
        raise ValidationFailed("No chat channel plugin is installed on this platform")
    return options[0]()


def call[T](work: Callable[[], T]) -> T:
    """Run a provider call, turning anything unexpected into a ChatError (never leaking a key in a traceback)."""
    try:
        return work()
    except ChatError:
        raise
    except httpx.TimeoutException:
        raise ChatError("The chat service did not answer in time", code="unavailable", retryable=True) from None
    except httpx.HTTPError:
        raise ChatError("The chat service could not be reached", code="unavailable", retryable=True) from None
