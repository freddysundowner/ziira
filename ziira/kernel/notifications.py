"""Messages to people outside the system (a customer reminded about an invoice, a supplier sent an order).

A unit asks for a message to be sent with `queue(...)`. The message is recorded in the caller's transaction (so it
exists only if the caller's change committed) and a background job sends it through the business's channel for that
medium - email or SMS - which a plugin provides through the "kernel.notification_channel" extension point.
Sending is never part of the caller's request: a slow or broken gateway cannot hold up a sale or lose a payment.

* People who asked not to be contacted are respected: a message to them is recorded as skipped, not sent.
* A message with no channel set up for the business is skipped and put in the exceptions inbox once.
* A failure that may pass (the gateway is down) is retried with growing delays; one that will not (a bad number, wrong
  credentials) fails at once and is flagged. Nothing is sent twice: a message that is sent stays sent.
* Channel credentials are kept encrypted per business (`kernel.integration_credential`, provider = the medium) with the
  name of the provider in the non-secret config, for example {"provider": "africastalking"}.
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, credentials, exceptions_inbox
from ziira.kernel.context import get_context
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations
from ziira.kernel.jobs import enqueue, job

log = logging.getLogger("ziira.notifications")
CHANNELS = ("email", "sms")
NOTIFICATION_CHANNEL = "kernel.notification_channel"
MAX_ATTEMPTS = 5
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^254[17]\d{8}$")
MAX_BODY = {"email": 20000, "sms": 1000}


@dataclass(frozen=True)
class Outgoing:
    """A message about to be handed to a channel."""

    notification_id: UUID
    company_id: UUID
    recipient: str
    subject: str | None
    body: str


@dataclass(frozen=True)
class SendResult:
    """What a channel said when asked to send."""

    accepted: bool
    provider_ref: str | None = None
    message: str = ""
    permanent_failure: bool = False          # True: do not try again (bad number, wrong credentials)


class NotificationChannel(ABC):
    """Contract of the "kernel.notification_channel" extension point: a way to send one medium."""

    channel: str = "email"                   # email | sms
    name: str = "provider"                   # chosen by the credential's config {"provider": name}

    @abstractmethod
    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        """Send the message. Raise for a failure that may pass (the gateway is unreachable); return a result with
        `permanent_failure` for one that will not."""


define_extension_point(NOTIFICATION_CHANNEL, NotificationChannel,
                       "A way to send a message: email or SMS through a gateway.")


def check_recipient(channel: str, recipient: str) -> str:
    """The recipient in the form the channel needs: a lower-case email, or a phone as 2547XXXXXXXX."""
    if channel not in CHANNELS:
        raise ValidationFailed(f"Channel must be one of: {', '.join(CHANNELS)}")
    value = recipient.strip()
    if channel == "email":
        value = value.lower()
        if len(value) > 200 or not EMAIL.match(value):
            raise ValidationFailed("That email address does not look right")
        return value
    digits = re.sub(r"[\s\-()+]", "", value)
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    if not PHONE.match(digits):
        raise ValidationFailed("A phone number looks like 0712345678 or +254712345678")
    return digits


def mask(recipient: str) -> str:
    """A recipient for screens and logs: most of it hidden."""
    if "@" in recipient:
        name, _, domain = recipient.partition("@")
        return f"{name[:1]}***@{domain}"
    return f"{recipient[:5]}****{recipient[-3:]}"


def is_opted_out(session: Session, company_id: UUID, channel: str, recipient: str) -> bool:
    return session.execute(text(
        "select 1 from kernel.notification_optout where company_id = :c and recipient = :r "
        "and (channel is null or channel = :ch)"), {"c": str(company_id), "r": recipient, "ch": channel}
    ).first() is not None


def queue(session: Session, *, company_id: UUID, channel: str, recipient: str, body: str,
          subject: str | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
          dedupe_key: str | None = None) -> UUID | None:
    """Record a message and have it sent in the background. Returns its id, or None when the same `dedupe_key` was
    already queued. A recipient who asked not to be contacted gets a record marked skipped, and nothing is sent."""
    to = check_recipient(channel, recipient)
    clean = body.strip()
    if not clean or len(clean) > MAX_BODY[channel]:
        raise ValidationFailed(f"A {channel} message has between 1 and {MAX_BODY[channel]} characters")
    if channel == "email" and not (subject and subject.strip()):
        raise ValidationFailed("An email needs a subject")
    ctx = get_context()
    skipped = is_opted_out(session, company_id, channel, to)
    row = session.execute(text(
        "insert into kernel.notification (tenant_id, created_by, company_id, channel, recipient, subject, body, "
        "status, error, ref_type, ref_id, dedupe_key) values (kernel.current_tenant(), :u, :co, :ch, :r, :s, :b, "
        ":st, :e, :rt, :ri, :k) on conflict do nothing returning id"),
        {"u": str(ctx.user_id) if ctx.user_id else None, "co": str(company_id), "ch": channel, "r": to,
         "s": (subject or "").strip()[:200] or None, "b": clean, "st": "skipped" if skipped else "queued",
         "e": "The recipient asked not to be contacted" if skipped else None, "rt": ref_type,
         "ri": str(ref_id) if ref_id else None, "k": dedupe_key}).first()
    if row is None:
        return None
    notification_id: UUID = row.id
    if not skipped:
        enqueue(session, "kernel.send_notification", {"id": str(notification_id)},
                dedupe_key=f"notify:{notification_id}")
    return notification_id


def _fail(session: Session, row: Any, status: str, message: str, *, flag: bool = True, severity: str = "low") -> None:
    session.execute(text("update kernel.notification set status = :s, error = :e where id = :i"),
                    {"s": status, "e": message[:500], "i": str(row.id)})
    if flag:
        exceptions_inbox.flag(session, unit="kernel", kind=f"notification_{status}", severity=severity,
                              company_id=row.company_id, ref_type="notification", ref_id=row.id,
                              dedupe_key=f"notification:{row.id}",
                              message=f"A {row.channel} message to {mask(row.recipient)} was not sent: {message}"[:500])


@job("kernel.send_notification")
def send_notification(session: Session, payload: dict[str, Any]) -> None:
    """Send a queued message through the business's channel for its medium."""
    row = session.execute(text(
        "select id, company_id, channel, recipient, subject, body, status, attempts from kernel.notification "
        "where id = :i for update"), {"i": payload["id"]}).first()
    if row is None or row.status != "queued":
        return                                                      # already sent, skipped or given up on
    found = session.execute(text(
        "select id, config from kernel.integration_credential where company_id = :c and provider = :ch "
        "and status = 'active' order by created_at desc limit 1"),
        {"c": str(row.company_id), "ch": row.channel}).first()
    if found is None:
        _fail(session, row, "skipped", f"No {row.channel} channel is set up for this business")
        return
    wanted = str((found.config or {}).get("provider") or "")
    channel = next((c for c in implementations(session, NOTIFICATION_CHANNEL)
                    if c.channel == row.channel and c.name == wanted), None)
    if channel is None:
        _fail(session, row, "skipped", f"The {row.channel} provider '{wanted}' is not installed")
        return
    message = Outgoing(row.id, row.company_id, row.recipient, row.subject, row.body)
    try:
        result = channel.send(message, credentials.read_secret(session, found.id), dict(found.config or {}))
    except Exception as exc:  # noqa: BLE001 - a transient failure is retried; the gateway may simply be down
        attempts = row.attempts + 1
        log.warning("Notification %s: attempt %s failed: %s", row.id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            session.execute(text("update kernel.notification set attempts = :a where id = :i"),
                            {"a": attempts, "i": str(row.id)})
            _fail(session, row, "failed", f"Gave up after {attempts} tries: {exc}", severity="medium")
            return
        session.execute(text("update kernel.notification set attempts = :a, error = :e where id = :i"),
                        {"a": attempts, "e": f"{type(exc).__name__}: {exc}"[:500], "i": str(row.id)})
        enqueue(session, "kernel.send_notification", payload, delay_seconds=60 * 2 ** attempts,
                dedupe_key=f"notify:{row.id}:{attempts}")
        return
    if result.accepted:
        session.execute(text(
            "update kernel.notification set status = 'sent', provider = :p, provider_ref = :r, sent_at = now(), "
            "attempts = attempts + 1, error = null where id = :i"),
            {"p": channel.name, "r": result.provider_ref, "i": str(row.id)})
        return
    session.execute(text("update kernel.notification set provider = :p, attempts = attempts + 1 where id = :i"),
                    {"p": channel.name, "i": str(row.id)})
    _fail(session, row, "failed", result.message or "The gateway refused the message",
          severity="medium" if not result.permanent_failure else "high")


# --------------------------------------------------------------------------- opt-outs and channels
def opt_out(session: Session, *, company_id: UUID, recipient: str, channel: str | None = None,
            reason: str | None = None) -> UUID:
    """Record that a person asked not to be contacted (on one channel, or on all of them)."""
    if channel is not None and channel not in CHANNELS:
        raise ValidationFailed(f"Channel must be one of: {', '.join(CHANNELS)}")
    to = check_recipient(channel or ("email" if "@" in recipient else "sms"), recipient)
    ctx = get_context()
    row = session.execute(text(
        "insert into kernel.notification_optout (tenant_id, created_by, company_id, recipient, channel, reason) "
        "values (kernel.current_tenant(), :u, :c, :r, :ch, :why) "
        "on conflict (tenant_id, company_id, recipient, channel) do update set reason = excluded.reason returning id"),
        {"u": str(ctx.user_id) if ctx.user_id else None, "c": str(company_id), "r": to, "ch": channel,
         "why": (reason or "").strip()[:300] or None}).one()
    audit.record(session, "opt_out", "kernel.notification_optout", row.id, {"channel": channel})
    return UUID(str(row.id))


def remove_opt_out(session: Session, optout_id: UUID) -> None:
    if session.execute(text("delete from kernel.notification_optout where id = :i returning id"),
                       {"i": str(optout_id)}).first() is None:
        raise NotFound("Not found")
    audit.record(session, "opt_in", "kernel.notification_optout", optout_id, None)
