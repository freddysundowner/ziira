"""Short-lived signed download links.

A link is `<payload>.<signature>`: the payload (URL-safe base64 of compact JSON) names the business, the file, the form
wanted (original, web copy or thumbnail), when the link ends, which "generation" of the file's links it belongs to and
who or what it was made for; the signature is an HMAC with the platform's secret key. Nothing is stored for a link:

* it ends by itself (`exp`);
* it is revoked by raising the file's `link_epoch` (done when the file is deleted, made staff-only, or someone asks);
* whoever holds it can open exactly that one file form until then, and every opening is logged with its `purpose` and
  `label` (`kernel.attachment_access`).
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import UUID

from ziira.kernel.config import get_settings
from ziira.kernel.errors import NotFound

PURPOSES = ("staff", "public")
VARIANTS = ("original", "web", "thumb")
MAX_STAFF_SECONDS = 900
MAX_PUBLIC_SECONDS = 86_400


@dataclass(frozen=True)
class LinkClaims:
    tenant_id: UUID
    file_id: UUID
    variant: str
    expires: int
    epoch: int
    purpose: str
    label: str = ""
    user_id: UUID | None = None


def _signature(payload: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, b"file-link:" + payload.encode(), hashlib.sha256).hexdigest()[:43]


def make(claims: LinkClaims) -> str:
    """The token for these claims."""
    body = {"t": str(claims.tenant_id), "f": str(claims.file_id), "v": claims.variant, "e": claims.expires,
            "g": claims.epoch, "p": claims.purpose, "l": claims.label[:60]}
    if claims.user_id is not None:
        body["u"] = str(claims.user_id)
    payload = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{payload}.{_signature(payload)}"


def read(token: str, *, now: float | None = None) -> LinkClaims:
    """The claims of a token that is genuine and not yet ended, else NotFound (the same answer for every failure, so a
    caller cannot tell a bad signature from an ended link)."""
    payload, _, signature = (token or "").partition(".")
    if not payload or not signature or len(token) > 1000 or not hmac.compare_digest(_signature(payload), signature):
        raise NotFound("This link is not valid")
    try:
        body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        claims = LinkClaims(UUID(body["t"]), UUID(body["f"]), str(body["v"]), int(body["e"]), int(body["g"]),
                            str(body["p"]), str(body.get("l", "")), UUID(body["u"]) if body.get("u") else None)
    except (ValueError, KeyError, TypeError):
        raise NotFound("This link is not valid") from None
    if claims.variant not in VARIANTS or claims.purpose not in PURPOSES or claims.expires < (now or time.time()):
        raise NotFound("This link is not valid")
    return claims
