"""Reading a signed delivery (shared by the real provider and the development one).

Lead Intel's go-live checklist (https://leadsintel.net/developers.html): `X-LeadIntel-Timestamp` in milliseconds
within five
minutes of now; `X-LeadIntel-Signature` the lower-case hex HMAC-SHA256, keyed with our secret, of `{timestamp}.{raw
body}`,
compared in constant time over the exact bytes; `X-LeadIntel-Event-Id` for de-duplication. The body is Meta's change
value.
"""

import hashlib
import hmac
import json
import time
from typing import Any

from ziira.sdk import ChatDelivery, ChatMessageIn, ValidationFailed

MAX_SKEW_MS = 5 * 60 * 1000
MAX_BODY = 65536
MEDIA_TYPES = ("image", "audio", "video", "document", "sticker", "voice")


def signature_of(secret: str, timestamp: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()


def check_signature(
    secret: str, timestamp: str | None, signature: str | None, raw: bytes, now_ms: int | None = None
) -> None:
    """Raise ValidationFailed unless the timestamp is recent and the signature is right for exactly these bytes."""
    if not secret or not timestamp or not signature or not timestamp.isdigit() or len(raw) > MAX_BODY:
        raise ValidationFailed("Not accepted")
    current = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(current - int(timestamp)) > MAX_SKEW_MS:
        raise ValidationFailed("Not accepted")
    if not hmac.compare_digest(signature_of(secret, timestamp, raw), signature.strip().lower()):
        raise ValidationFailed("Not accepted")


def _message(item: dict[str, Any]) -> ChatMessageIn | None:
    message_id = str(item.get("id") or "")
    sender = "".join(c for c in str(item.get("from") or "") if c.isdigit())
    if not message_id or not sender:
        return None
    kind = str(item.get("type") or "")
    if kind == "text":
        body = item.get("text")
        return ChatMessageIn(message_id, sender, "text", str((body or {}).get("body") or "")[:4000])
    if kind == "interactive":
        inter = item.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return ChatMessageIn(
            message_id, sender, "button", str(reply.get("title") or "")[:200], str(reply.get("id") or "")[:200] or None
        )
    if kind == "button":
        tap = item.get("button") or {}
        return ChatMessageIn(
            message_id, sender, "button", str(tap.get("text") or "")[:200], str(tap.get("payload") or "")[:200] or None
        )
    return ChatMessageIn(message_id, sender, "media" if kind in MEDIA_TYPES else "other")


def read_delivery(headers: dict[str, str], body: bytes, secret: str, expected_number_id: str | None) -> ChatDelivery:
    """Check the signature, then read the body. A genuine body we cannot read, or one for another number, has no
    messages."""
    check_signature(secret, headers.get("x-leadintel-timestamp"), headers.get("x-leadintel-signature"), body)
    event_id = (headers.get("x-leadintel-event-id") or "").strip()
    if not event_id or len(event_id) > 200:
        raise ValidationFailed("Not accepted")
    try:
        payload = json.loads(body)
    except ValueError:
        return ChatDelivery(event_id)
    if not isinstance(payload, dict):
        return ChatDelivery(event_id)
    raw_meta = payload.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    number_id = str(meta.get("phone_number_id") or "") or None
    if expected_number_id and number_id and number_id != expected_number_id:
        return ChatDelivery(event_id, number_id)
    messages = tuple(
        m for item in (payload.get("messages") or []) if isinstance(item, dict) and (m := _message(item)) is not None
    )
    return ChatDelivery(event_id, number_id, messages)
