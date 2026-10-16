"""Email the platform itself sends, before any business exists (the verification email of self-service registration,
password resets, billing mail).

A business sends its own messages through its own channels (kernel/notifications.py). The platform has no business, so
it uses one provider that the owner sets up in the Super Admin (Platform > Email: `kernel/platform/mail.py`), found
among the implementations the messaging plugin registers. When the Super Admin has none, the environment settings
(ZIIRA_PLATFORM_EMAIL_PROVIDER, with the secret and config as JSON) are used; with neither, development and tests
use the fake provider (it only records what it was asked to send) and production cannot send, so registration
stays closed.
"""

from ziira.kernel.platform import mail


def send(to: str, subject: str, body: str, kind: str = "other") -> None:
    """Send one email as the platform. `kind` (registration, password_reset, billing, security) is for the mail log.
    Raises Unavailable if it cannot (nothing configured, or the provider refused)."""
    mail.send(to, subject, body, kind)
