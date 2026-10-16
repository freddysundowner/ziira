"""Messages to people outside the system (a customer reminded about an invoice, a supplier sent an order).

A unit asks for a message to be sent with `queue(...)`. The message is recorded in the caller's transaction (so it
exists only if the caller's change committed) and a background job sends it through the business's channel for that
medium - email, SMS or a chat service - which a plugin provides through the "kernel.notification_channel" extension
point.
Sending is never part of the caller's request: a slow or broken gateway cannot hold up a sale or lose a payment.

* People who asked not to be contacted are respected: a message to them is recorded as skipped, not sent.
* A message with no channel set up for the business is skipped and put in the exceptions inbox once.
* A failure that may pass (the gateway is down) is retried with growing delays; one that will not (a bad number, wrong
  credentials) fails at once and is flagged. Nothing is sent twice: a message that is sent stays sent.
* Channel credentials are kept encrypted per business (`kernel.integration_credential`, provider = the medium) with the
  name of the provider in the non-secret config, for example {"provider": "africastalking"}.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, channels, company_settings, credentials, exceptions_inbox
from ziira.kernel.channels import NOTIFICATION_CHANNEL
from ziira.kernel.context import get_context
from ziira.kernel.errors import NotFound, ValidationFailed
from ziira.kernel.extensions import define_extension_point, implementations
from ziira.kernel.jobs import enqueue, job
from ziira.kernel.phone import normalise_phone

log = logging.getLogger("ziira.notifications")
CHANNEL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
MAX_ATTEMPTS = 5
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY = {"email": 20000, "sms": 1000}      # other channels: DEFAULT_BODY
DEFAULT_BODY = 4000


@dataclass(frozen=True)
class Outgoing:
    """A message about to be handed to a channel."""

    notification_id: UUID
    company_id: UUID
    recipient: str
    subject: str | None
    body: str
    # Conversational channels only. mode "text": free-form text; "buttons": the text with reply buttons (id,
    # title); "template": an
    # approved template with its parameters in order (the buttons, if any, are its quick replies). The kernel decides
    # the mode (free-form is allowed only within 24 hours of the person's last message); a channel just sends it.
    mode: str = "text"
    buttons: tuple[tuple[str, str], ...] = ()
    template_name: str = ""
    template_language: str = ""
    template_params: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateSpec:
    """A message template as submitted to a channel provider: the text has positional placeholders {{1}}, {{2}}..."""

    name: str
    language: str
    category: str
    body: str
    variables: tuple[str, ...]
    examples: tuple[str, ...]
    buttons: tuple[str, ...] = ()            # titles of quick-reply buttons


@dataclass(frozen=True)
class TemplateState:
    """Where a template stands with the provider."""

    status: str                              # submitted | approved | rejected
    provider_template_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class SendResult:
    """What a channel said when asked to send."""

    accepted: bool
    provider_ref: str | None = None
    message: str = ""
    permanent_failure: bool = False          # True: do not try again (bad number, wrong credentials)


class NotificationChannel(ABC):
    """Contract of the "kernel.notification_channel" extension point: a way to send one medium."""

    channel: str = "email"                   # the one channel this provider offers: "email", "sms", or its own name
    name: str = "provider"                   # chosen by the credential's config {"provider": name}
    channel_label: str = ""                  # how screens name the channel ("": the channel name, capitalised)
    supports_templates: bool = False         # the provider approves message templates (needed to start a conversation)
    supports_buttons: bool = False           # reply buttons (Outgoing.mode "buttons")
    supports_inbound: bool = False           # replies arrive (kernel.inbound): a person's address must be verified
    window_hours: int | None = None          # conversational: free-form only this many hours after their message
    development_only: bool = False           # never offered in production (the fakes)
    hidden: bool = False                     # tests switch a provider off with this

    @abstractmethod
    def send(self, message: Outgoing, secret: dict[str, Any], config: dict[str, Any]) -> SendResult:
        """Send the message. Raise for a failure that may pass (the gateway is unreachable); return a result with
        `permanent_failure` for one that will not."""

    def submit_template(self, spec: TemplateSpec, secret: dict[str, Any], config: dict[str, Any]) -> TemplateState:
        """Send a template to the provider for approval. Only for channels with `supports_templates`."""
        raise NotImplementedError(f"The {self.name} provider has no message templates")

    def template_state(self, spec: TemplateSpec, provider_template_id: str | None, secret: dict[str, Any],
                       config: dict[str, Any]) -> TemplateState:
        """Ask the provider where a submitted template stands."""
        raise NotImplementedError(f"The {self.name} provider has no message templates")


define_extension_point(NOTIFICATION_CHANNEL, NotificationChannel,
                       "A way to send a message on one channel (email, SMS, a chat service) through a gateway.")


def check_recipient(channel: str, recipient: str, country_code: str = "") -> str:
    """The recipient in the form the channel needs: a lower-case email, or a phone as international digits (national
    numbers are read with the company's calling code)."""
    if not CHANNEL_NAME.match(channel):
        raise ValidationFailed("That is not a channel name")
    value = recipient.strip()
    if channel == "email":
        value = value.lower()
        if len(value) > 200 or not EMAIL.match(value):
            raise ValidationFailed("That email address does not look right")
        return value
    phone = normalise_phone(value, country_code)
    if phone is None:
        raise ValidationFailed("A phone number is required")
    return phone


def calling_code(session: Session, company_id: UUID) -> str:
    return str(company_settings.get_setting(session, company_id, "phone_country_code"))


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


def asked_for_nothing(session: Session, company_id: UUID, recipient: str) -> bool:
    """True if this recipient asked not to be contacted on any channel (a STOP, or 'do not contact' without one)."""
    return session.execute(text(
        "select 1 from kernel.notification_optout where company_id = :c and recipient = :r and channel is null"),
        {"c": str(company_id), "r": recipient}).first() is not None


def payload_subject(fallbacks: Sequence[dict[str, str]]) -> str | None:
    return "A message from Ziira" if fallbacks and fallbacks[0]["channel"] == "email" else None


def queue(session: Session, *, company_id: UUID, channel: str, recipient: str, body: str,
          subject: str | None = None, ref_type: str | None = None, ref_id: UUID | None = None,
          dedupe_key: str | None = None, template: str | None = None, variables: dict[str, str] | None = None,
          language: str | None = None, buttons: Sequence[tuple[str, str]] = (),
          fallbacks: Sequence[dict[str, str]] = (), user_id: UUID | None = None, kind: str | None = None,
          deliver_at: datetime | None = None) -> UUID | None:
    """Record a message and have it sent in the background. Returns its id, or None when the same `dedupe_key` was
    already queued. A recipient who asked not to be contacted gets a record marked skipped, and nothing is sent.

    Conversational channels: `template` names the template (with its `variables`) to use when the window is closed, and
    `buttons` are (id, title) reply buttons. `fallbacks` are other ways to reach the person ({"channel", "recipient"})
    tried in order when this one cannot be used. `deliver_at` defers sending (quiet hours): never drops."""
    if channels.info(session, channel) is None and channel not in channels.BASIC:
        # The channel is not offered (its plugin is off, or it never existed). A message that has another way to reach
        # the person goes that way; one that has none is refused.
        if fallbacks:
            return queue(session, company_id=company_id, channel=fallbacks[0]["channel"],
                         recipient=fallbacks[0]["recipient"], body=body, subject=subject or payload_subject(fallbacks),
                         ref_type=ref_type, ref_id=ref_id, dedupe_key=dedupe_key, template=template,
                         variables=variables, language=language, buttons=buttons, fallbacks=list(fallbacks[1:]),
                         user_id=user_id, kind=kind, deliver_at=deliver_at)
        channels.check(session, channel)
    to = check_recipient(channel, recipient, calling_code(session, company_id))
    limit = MAX_BODY.get(channel, DEFAULT_BODY)
    clean = body.strip()
    if not clean or len(clean) > limit:
        raise ValidationFailed(f"A {channel} message has between 1 and {limit} characters")
    if channel == "email" and not (subject and subject.strip()):
        raise ValidationFailed("An email needs a subject")
    ctx = get_context()
    skipped = is_opted_out(session, company_id, channel, to)
    extra = {"variables": variables or {}, "buttons": [list(b) for b in buttons], "fallbacks": list(fallbacks),
             "fallback_subject": (subject or "").strip()[:200] or None}
    row = session.execute(text(
        "insert into kernel.notification (tenant_id, created_by, company_id, channel, recipient, subject, body, "
        "status, error, ref_type, ref_id, dedupe_key, template, payload, language, user_id, kind) "
        "values (kernel.current_tenant(), :u, :co, :ch, :r, :s, :b, :st, :e, :rt, :ri, :k, :tp, cast(:pl as jsonb), "
        ":lang, :uid, :kind) on conflict do nothing returning id"),
        {"u": str(ctx.user_id) if ctx.user_id else None, "co": str(company_id), "ch": channel, "r": to,
         "s": (subject or "").strip()[:200] or None, "b": clean, "st": "skipped" if skipped else "queued",
         "e": "The recipient asked not to be contacted" if skipped else None, "rt": ref_type,
         "ri": str(ref_id) if ref_id else None, "k": dedupe_key, "tp": template, "pl": json.dumps(extra),
         "lang": language, "uid": str(user_id) if user_id else None, "kind": kind}).first()
    if row is None:
        return None
    notification_id: UUID = row.id
    if skipped and fallbacks and not asked_for_nothing(session, company_id, to):
        # They refused this channel only: the next one is still allowed. (Someone who refused every channel is left
        # alone, whichever other address we hold for them.)
        _fallback(session, row.id, company_id, "The recipient asked not to be contacted on this channel", extra,
                  clean, template, language, ref_type, ref_id, dedupe_key, user_id, kind, deliver_at)
    if not skipped:
        delay = max(int((deliver_at - datetime.now(UTC)).total_seconds()), 0) if deliver_at else 0
        enqueue(session, "kernel.send_notification", {"id": str(notification_id)}, delay_seconds=delay,
                dedupe_key=f"notify:{notification_id}")
    return notification_id


def _fallback(session: Session, notification_id: UUID, company_id: UUID, reason: str, payload: dict[str, Any],
              body: str, template: str | None, language: str | None, ref_type: str | None, ref_id: UUID | None,
              dedupe_key: str | None, user_id: UUID | None, kind: str | None, deliver_at: datetime | None) -> bool:
    """Hand the message to the next way of reaching the person, if there is one. The first record says what happened
    (no exception is raised: the person is being reached)."""
    options = list(payload.get("fallbacks") or [])
    while options:
        nxt, options = options[0], options[1:]
        subject = payload.get("fallback_subject") or ("A message from Ziira" if nxt["channel"] == "email" else None)
        made = queue(session, company_id=company_id, channel=nxt["channel"], recipient=nxt["recipient"], body=body,
                     subject=subject, ref_type=ref_type, ref_id=ref_id, dedupe_key=f"fb:{notification_id}",
                     template=template, variables=payload.get("variables") or {}, language=language,
                     buttons=[tuple(b) for b in payload.get("buttons") or []], fallbacks=options, user_id=user_id,
                     kind=kind, deliver_at=deliver_at)
        if made is not None:
            session.execute(text("update kernel.notification set status = 'skipped', error = :e where id = :i"),
                            {"e": f"{reason}; sent by {nxt['channel']} instead"[:500], "i": str(notification_id)})
            return True
    return False


def _fail(session: Session, row: Any, status: str, message: str, *, flag: bool = True, severity: str = "low") -> None:
    session.execute(text("update kernel.notification set status = :s, error = :e where id = :i"),
                    {"s": status, "e": message[:500], "i": str(row.id)})
    if flag:
        exceptions_inbox.flag(session, unit="kernel", kind=f"notification_{status}", severity=severity,
                              company_id=row.company_id, ref_type="notification", ref_id=row.id,
                              dedupe_key=f"notification:{row.id}",
                              message=f"A {row.channel} message to {mask(row.recipient)} was not sent: {message}"[:500])


def _outgoing(session: Session, row: Any) -> Outgoing | str:
    """What to hand the channel, or the reason this message cannot be sent now. A conversational channel allows a
    free-form message only within its window after the person's last message; otherwise an approved template is
    needed."""
    base = Outgoing(row.id, row.company_id, row.recipient, row.subject, row.body)
    found_info = channels.info(session, row.channel)
    if found_info is None or not found_info.conversational:
        return base
    from ziira.kernel import messaging, templates

    payload = row.payload or {}
    buttons = tuple((str(b[0]), str(b[1])) for b in payload.get("buttons") or []) if found_info.supports_buttons else ()
    if messaging.window_open(session, row.company_id, row.channel, row.recipient):
        return replace(base, mode="buttons" if buttons else "text", buttons=buttons)
    hours = found_info.window_hours
    if not row.template or not found_info.supports_templates:
        return f"No template was given and the {hours}-hour window for a free-form message is closed"
    found = templates.approved(session, row.company_id, row.channel, row.template, row.language or "en")
    if found is None:
        return f"The {found_info.label} template '{row.template}' is not approved yet"
    values = payload.get("variables") or {}
    params = tuple(templates.clean_value(str(values.get(name, ""))) for name in found.variables)
    return replace(base, mode="template", buttons=buttons, template_name=found.provider_name,
                   template_language=found.language, template_params=params)


def _try_fallback(session: Session, row: Any, reason: str) -> bool:
    return _fallback(session, row.id, row.company_id, reason, row.payload or {}, row.body, row.template, row.language,
                     row.ref_type, row.ref_id, row.dedupe_key, row.user_id, row.kind, None)


@job("kernel.send_notification")
def send_notification(session: Session, payload: dict[str, Any]) -> None:
    """Send a queued message through the business's channel for its medium."""
    row = session.execute(text(
        "select id, company_id, channel, recipient, subject, body, status, attempts, template, payload, language, "
        "user_id, kind, ref_type, ref_id, dedupe_key from kernel.notification where id = :i for update"),
        {"i": payload["id"]}).first()
    if row is None or row.status != "queued":
        return                                                      # already sent, skipped or given up on
    found = session.execute(text(
        "select id, config from kernel.integration_credential where company_id = :c and provider = :ch "
        "and status = 'active' order by created_at desc limit 1"),
        {"c": str(row.company_id), "ch": row.channel}).first()
    if found is None:
        reason = f"No {row.channel} channel is set up for this business"
        if not _try_fallback(session, row, reason):
            _fail(session, row, "skipped", reason)
        return
    wanted = str((found.config or {}).get("provider") or "")
    channel = next((c for c in implementations(session, NOTIFICATION_CHANNEL)
                    if c.channel == row.channel and c.name == wanted), None)
    if channel is None:
        reason = f"The {row.channel} provider '{wanted}' is not installed"
        if not _try_fallback(session, row, reason):
            _fail(session, row, "skipped", reason)
        return
    message = _outgoing(session, row)
    if isinstance(message, str):
        if not _try_fallback(session, row, message):
            _fail(session, row, "skipped", message)
        return
    try:
        result = channel.send(message, credentials.read_secret(session, found.id), dict(found.config or {}))
    except Exception as exc:  # noqa: BLE001 - a transient failure is retried; the gateway may simply be down
        attempts = row.attempts + 1
        log.warning("Notification %s: attempt %s failed: %s", row.id, attempts, exc)
        if attempts >= MAX_ATTEMPTS:
            session.execute(text("update kernel.notification set attempts = :a where id = :i"),
                            {"a": attempts, "i": str(row.id)})
            reason = f"Gave up after {attempts} tries: {exc}"
            if not _try_fallback(session, row, reason):
                _fail(session, row, "failed", reason, severity="medium")
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
    reason = result.message or "The gateway refused the message"
    if not _try_fallback(session, row, reason):
        _fail(session, row, "failed", reason, severity="medium" if not result.permanent_failure else "high")


def record_delivery(session: Session, *, provider: str, provider_ref: str, status: str,
                    error: str | None = None) -> bool:
    """A provider reported what became of a message it accepted (delivered, read, failed). Only moves forward: a
    message that was read is not 'delivered' again. Returns True if a message of ours was updated."""
    if status not in ("sent", "delivered", "read", "failed"):
        return False
    row = session.execute(text(
        "select id, status, company_id, channel, recipient from kernel.notification where provider = :p "
        "and provider_ref = :r order by created_at desc, id limit 1 for update"),
        {"p": provider, "r": provider_ref}).first()
    moves = {"sent": ("queued",), "delivered": ("sent", "failed"), "read": ("sent", "delivered", "failed"),
             "failed": ("sent",)}
    if row is None or row.status not in moves[status]:
        return False
    session.execute(text("update kernel.notification set status = :s, error = :e where id = :i"),
                    {"s": status, "e": (error or "")[:500] or None, "i": str(row.id)})
    if status == "failed":
        exceptions_inbox.flag(session, unit="kernel", kind="notification_failed", severity="low",
                              company_id=row.company_id, ref_type="notification", ref_id=row.id,
                              dedupe_key=f"notification:{row.id}",
                              message=f"A {row.channel} message to {mask(row.recipient)} was not delivered: "
                                      f"{error or 'the provider reported a failure'}"[:500])
    return True



# --------------------------------------------------------------------------- opt-outs and channels
def opt_out(session: Session, *, company_id: UUID, recipient: str, channel: str | None = None,
            reason: str | None = None) -> UUID:
    """Record that a person asked not to be contacted (on one channel, or on all of them)."""
    if channel is not None:
        channels.check(session, channel)
    kind = channel or ("email" if "@" in recipient else "sms")
    to = check_recipient(kind, recipient, calling_code(session, company_id))
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
