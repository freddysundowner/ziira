"""Messages and delivery reports that Lead Intel posts to a business's inbound address.

Order of work, as Lead Intel's go-live checklist asks, and nothing is read from the body until step 3 passes:

1. The address token names the business (its tenant is in the token) and one connection; an unknown token is refused
   with
   the same answer as a bad signature, so nothing can be learned by probing.
2. `X-LeadIntel-Timestamp` (milliseconds) must be within five minutes of now.
3. `X-LeadIntel-Signature` must equal the lower-case hex HMAC-SHA256, keyed with the connection's webhook secret, of
   `{timestamp}.{raw body}`, compared in constant time over the exact bytes received.
4. `X-LeadIntel-Event-Id` is recorded; a repeat delivery is acknowledged and does nothing.
5. Only then is the body parsed: the Meta `value` object. `messages[]` are stored and handed to the platform's channel
   router (STOP words, replies from staff); `statuses[]` move our sent messages to delivered / read / failed. The
   `statuses` shape is NOT documented by Lead Intel: it is read as Meta's (id, status, recipient_id, errors).

All of it runs in one transaction: if anything fails, the event id is not kept and the answer is a 500, so Lead Intel
delivers it again.
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ziira.plugins.leadsintel import repository as repo
from ziira.sdk import (
    InboundMessage,
    NotFound,
    Session,
    Unauthorized,
    hash_secret,
    normalise_phone,
    read_credential,
    record_delivery,
    route_inbound,
    system_session,
)

log = logging.getLogger("ziira.leadsintel")
MAX_SKEW_MS = 5 * 60 * 1000
MAX_BODY = 1_000_000
MEDIA_TYPES = ("image", "audio", "video", "document", "sticker")


class Rejected(Unauthorized):
    """The delivery is not genuine. One message for every reason, so the reply teaches an attacker nothing."""

    def __init__(self) -> None:
        super().__init__("Not accepted")


def signature_of(secret: str, timestamp: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()


def check_signature(secret: str, timestamp: str | None, signature: str | None, raw: bytes,
                    now_ms: int | None = None) -> None:
    """Raise Rejected unless the timestamp is recent and the signature is right for exactly these bytes."""
    if not timestamp or not signature or not timestamp.isdigit() or len(raw) > MAX_BODY:
        raise Rejected()
    current = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(current - int(timestamp)) > MAX_SKEW_MS:
        raise Rejected()
    if not hmac.compare_digest(signature_of(secret, timestamp, raw), signature.strip().lower()):
        raise Rejected()


def _tenant_of(token: str) -> UUID:
    try:
        return UUID(hex=token.partition(".")[0])
    except ValueError:
        raise Rejected() from None


def receive(token: str, raw: bytes, headers: Mapping[str, str]) -> None:
    """Handle one delivery. Raises Rejected for anything not genuine (including an unknown business); any other
    exception means 'try again later'."""
    tenant_id = _tenant_of(token)
    try:
        with system_session(tenant_id) as session:
            _receive(session, token, raw, headers)
    except NotFound:
        raise Rejected() from None


def _receive(session: Session, token: str, raw: bytes, headers: Mapping[str, str]) -> None:
    connection = repo.connection_by_token(session, hash_secret(token))
    credential = repo.credential(session, connection.company_id, "whatsapp") if connection is not None else None
    if connection is None or credential is None or not _plugin_enabled(session):
        raise Rejected()
    secret = str(read_credential(session, credential.id).get("webhook_secret") or "")
    if not secret:
        raise Rejected()
    check_signature(secret, headers.get("x-leadintel-timestamp"), headers.get("x-leadintel-signature"), raw)
    event_id = (headers.get("x-leadintel-event-id") or "").strip()
    if not event_id or len(event_id) > 200:
        raise Rejected()
    if not repo.mark_event_seen(session, event_id):
        return                                              # a repeat of one already handled
    try:
        payload = json.loads(raw)
    except ValueError:
        return                                              # genuine but unreadable: nothing to do, do not retry
    if not isinstance(payload, dict):
        return
    raw_metadata = payload.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    expected = connection.phone_number_id
    if expected and metadata.get("phone_number_id") and metadata["phone_number_id"] != expected:
        log.warning("Lead Intel delivery for another phone number id ignored")
        return
    for status in payload.get("statuses") or []:            # UNVERIFIED shape (Meta's)
        if isinstance(status, dict):
            _status(session, status)
    for message in payload.get("messages") or []:
        if isinstance(message, dict):
            _message(session, connection, message)


def _plugin_enabled(session: Session) -> bool:
    from sqlalchemy import text

    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'leadsintel' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


def _status(session: Session, status: dict[str, Any]) -> None:
    ours = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}.get(str(status.get("status")))
    ref = status.get("id")
    if ours is None or not ref:
        return
    errors = status.get("errors")
    detail = None
    if ours == "failed":
        first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        detail = str(first.get("title") or first.get("message") or "The provider reported a failure")[:300]
    record_delivery(session, provider="leadsintel", provider_ref=str(ref), status=ours, error=detail)


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _message(session: Session, connection: Any, message: dict[str, Any]) -> None:
    message_id = str(message.get("id") or "")
    sender = normalise_phone(f"+{message.get('from')}", None) if message.get("from") else None
    if not message_id or sender is None:
        return
    kind_raw = str(message.get("type") or "")
    text_body: str | None = None
    button_id: str | None = None
    media: str | None = None
    kind = "other"
    if kind_raw == "text":
        kind, text_body = "text", str((message.get("text") or {}).get("body") or "")
    elif kind_raw == "interactive":
        inter = message.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        kind, button_id, text_body = "button", str(reply.get("id") or "") or None, str(reply.get("title") or "")
    elif kind_raw == "button":
        tap = message.get("button") or {}
        kind, button_id, text_body = "button", str(tap.get("payload") or "") or None, str(tap.get("text") or "")
    elif kind_raw in MEDIA_TYPES:
        item = message.get(kind_raw) or {}
        media = json.dumps({"type": kind_raw, "mime_type": item.get("mime_type"), "filename": item.get("filename"),
                            "download_url": item.get("downloadUrl"), "expires_at": item.get("expiresAt")})
        text_body = str(item.get("caption") or "") or None
    received = _timestamp(message.get("timestamp"))
    stored = repo.store_inbound(session, company_id=connection.company_id, connection_id=connection.id,
                                provider_message_id=message_id, sender=sender, kind=kind_raw or kind,
                                body=(text_body or None) and text_body[:4000], button_id=button_id, media=media,
                                received_at=received)
    if stored is None:
        return                                              # already stored: a repeat
    outcome = route_inbound(session, InboundMessage(
        company_id=connection.company_id, channel="whatsapp", sender=sender, kind=kind, text=text_body or "",
        button_id=button_id, received_at=received, message_id=message_id))
    repo.set_outcome(session, stored, outcome)
