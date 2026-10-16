"""Email the platform itself sends, before any business exists (the verification email of self-service registration).

A business sends its own messages through its own channels (kernel/notifications.py). The platform has no business, so
it uses one provider named in its settings (ZIIRA_PLATFORM_EMAIL_PROVIDER, with the secret and config as JSON), found
among the implementations the messaging plugin registers. With no provider set, development and tests use the fake one
(it only records what it was asked to send); production is refused at start-up if registration is open and nothing can
send mail.
"""

import json
import logging
from typing import Any
from uuid import uuid4

from ziira.kernel.channels import NOTIFICATION_CHANNEL
from ziira.kernel.config import get_settings
from ziira.kernel.errors import Unavailable
from ziira.kernel.extensions import provider_named
from ziira.kernel.notifications import Outgoing

log = logging.getLogger("ziira.platform_mail")


def _json(value: str) -> dict[str, Any]:
    return json.loads(value) if value.strip() else {}


def send(to: str, subject: str, body: str) -> None:
    """Send one email as the platform. Raises Unavailable if it cannot (nothing configured, or the provider refused)."""
    settings = get_settings()
    name = settings.platform_email_provider or ("fake" if settings.env != "production" else "")
    provider = provider_named(NOTIFICATION_CHANNEL, name) if name else None
    if provider is None or getattr(provider, "channel", None) != "email":
        log.error("No platform email provider '%s' is available", name)
        raise Unavailable("Email cannot be sent right now, so registration is unavailable. Please try again later.")
    try:
        result = provider().send(Outgoing(uuid4(), uuid4(), to, subject, body),
                                 _json(settings.platform_email_secret) or {"api_key": "development"},
                                 _json(settings.platform_email_config))
    except Exception:
        log.exception("The platform email provider failed")
        raise Unavailable("Email cannot be sent right now. Please try again later.") from None
    if not result.accepted:
        log.error("The platform email provider refused the message: %s", result.message)
        raise Unavailable("Email cannot be sent right now. Please try again later.")
