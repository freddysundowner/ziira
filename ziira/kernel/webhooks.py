"""Outgoing webhooks: tell a business's own web address when something happens (docs/webhooks.md).

A business registers HTTPS endpoints and picks event types from the catalogue (the events units mark as public in their
manifests, with the payload fields each may expose). When such an event is published, the outbox hands it to `fan_out`,
which writes one delivery per subscribed endpoint and queues a background job; the job posts the signed body, so no
request ever waits on a customer's server.

- Signature: `Ziira-Signature: v1=<hex HMAC-SHA256 over "{timestamp}.{body}">` with the endpoint's secret (shown once),
  `Ziira-Timestamp` (unix seconds) and `Ziira-Event-Id` (the same on every retry and redelivery of one delivery).
- Retries: exponential backoff (30 s, 2 min, 8 min, ...) up to `webhook_max_attempts` tries within
  `webhook_retry_hours`.
  A 410 answer disables the endpoint and puts an item in the exceptions inbox.
- SSRF: an address must be https, name a public host and resolve only to public addresses; it is resolved again, and
  the connection is made to the address that was checked, at every delivery. `http://localhost` works only in
  development.
- Privacy: only the fields the manifest lists leave the system; a delivery keeps its body for `webhook_body_days`, then
  only its hash and first bytes.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, exceptions_inbox
from ziira.kernel.config import get_settings
from ziira.kernel.context import get_context
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.events import Event, subscribe_after
from ziira.kernel.jobs import enqueue, job, periodic
from ziira.kernel.manifest import Manifest, PublicEvent
from ziira.kernel.security import decrypt, encrypt, new_secret

log = logging.getLogger("ziira.webhooks")
PING = "webhook.ping"
MAX_ENDPOINTS = 20
MAX_BODY_BYTES = 512_000
PREVIEW_BYTES = 200
SECRET_PREFIX = "whsec_"
SIGNATURE_VERSION = "v1"
_SECRET_KEYS = ("secret", "password", "token", "passcode", "ciphertext", "hash")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".lan", ".home.arpa")

_catalogue: dict[str, tuple[str, PublicEvent]] = {}  # event type -> (unit, description and fields)
_registered: set[str] = set()
_resolver: Callable[[str], list[str]] | None = None  # tests replace DNS
_transport: httpx.BaseTransport | None = None  # tests replace the network


def use_resolver(resolver: Callable[[str], list[str]] | None) -> None:
    """Replace the DNS lookup (tests); None restores the real one."""
    global _resolver
    _resolver = resolver


def use_transport(transport: httpx.BaseTransport | None) -> None:
    """Replace the HTTP transport (tests); None restores the real one."""
    global _transport
    _transport = transport


# --------------------------------------------------------------------------- the catalogue
def register_public_events(units: dict[str, Manifest]) -> None:
    """Remember the public events of the discovered units and subscribe to them (called when units are loaded)."""
    for m in units.values():
        for event_type, spec in m.public_events.items():
            _catalogue[event_type] = (m.name, spec)
            if event_type not in _registered:
                _registered.add(event_type)
                subscribe_after(event_type)(fan_out)


def catalogue() -> list[dict[str, Any]]:
    """The events a webhook may subscribe to, with the fields of their payload."""
    return [
        {"type": t, "unit": unit, "description": spec.description, "fields": list(spec.fields)}
        for t, (unit, spec) in sorted(_catalogue.items())
    ]


# --------------------------------------------------------------------------- addresses
class UnsafeAddress(ValidationFailed):
    """The address is not one a webhook may call."""


def _is_public(ip: str) -> bool:
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _lookup(host: str) -> list[str]:
    if _resolver is not None:
        return _resolver(host)
    try:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except (OSError, ValueError):  # not found, or a name that cannot be looked up at all
        return []


def check_address(url: str) -> tuple[str, int, list[str]]:
    """Refuse an address a webhook must not call; return its host, port and the addresses it resolves to.

    Called when an endpoint is saved and again at every delivery (DNS can change)."""
    if len(url) > 2000:
        raise UnsafeAddress("That address is too long")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise UnsafeAddress("That does not look like a web address") from None
    host = (parts.hostname or "").lower()
    development_local = get_settings().env == "development" and host in LOCAL_HOSTS
    if parts.scheme != "https" and not (parts.scheme == "http" and development_local):
        raise UnsafeAddress("The address must start with https://")
    if not host or parts.username or parts.password:
        raise UnsafeAddress("The address needs a host name and must not contain a user name or password")
    if not development_local and (host in LOCAL_HOSTS or host.endswith(LOCAL_SUFFIXES)):
        raise UnsafeAddress("That address names this machine or a private network, which a webhook may not call")
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        ips = _lookup(host)
    if not ips:
        raise UnsafeAddress("That host name could not be found")
    if not development_local and not all(_is_public(ip) for ip in ips):
        raise UnsafeAddress("That address points inside a private or local network, which a webhook may not call")
    return host, port or (443 if parts.scheme == "https" else 80), ips


# --------------------------------------------------------------------------- signing and bodies
def sign(secret: str, timestamp: int | str, body: str) -> str:
    """The `Ziira-Signature` value for a delivery: `v1=` and the hex HMAC-SHA256 of `{timestamp}.{body}`."""
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not any(w in str(k).lower() for w in _SECRET_KEYS)}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def build_body(event_id: UUID, event: Event, created_at: datetime, tenant_id: UUID) -> str:
    """The JSON body of a delivery: the envelope and only the fields the event's manifest entry exposes."""
    fields = _catalogue[event.type][1].fields if event.type in _catalogue else ()
    data = _scrub({k: v for k, v in event.payload.items() if k in fields})
    envelope: dict[str, Any] = {
        "id": str(event_id),
        "type": event.type,
        "created_at": created_at.isoformat(),
        "business_id": str(tenant_id),
        "aggregate": {"type": event.aggregate_type, "id": str(event.aggregate_id)},
        "data": data,
    }
    body = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
    if len(body.encode()) > MAX_BODY_BYTES:
        envelope["data"] = {"too_large": True}
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str)
    return body


def backoff_seconds(attempts_made: int) -> int:
    """Wait before the next try: 30 s, 2 min, 8 min, 32 min, ... at most 12 hours."""
    return int(min(30 * 4 ** max(attempts_made - 1, 0), 43_200))


# --------------------------------------------------------------------------- endpoints
COLUMNS = (
    "id, created_at, name, url, event_types, secret_hint, status, disabled_reason, consecutive_failures, "
    "last_success_at, last_failure_at"
)


def _check_events(event_types: list[str]) -> list[str]:
    cleaned = sorted(set(event_types))
    if not cleaned:
        raise ValidationFailed("Choose at least one event")
    unknown = [t for t in cleaned if t not in _catalogue]
    if unknown:
        raise ValidationFailed(f"Not an event a webhook can carry: {', '.join(unknown)}")
    return cleaned


def create_endpoint(s: Session, *, name: str, url: str, event_types: list[str]) -> tuple[UUID, str]:
    """Register an endpoint. Returns its id and its signing secret, which is shown only now."""
    if not name.strip():
        raise ValidationFailed("Give the endpoint a name")
    check_address(url)
    events = _check_events(event_types)
    if s.execute(text("select count(*) from kernel.webhook_endpoint")).scalar_one() >= MAX_ENDPOINTS:
        raise Conflict(f"A business can have at most {MAX_ENDPOINTS} webhook endpoints")
    secret = SECRET_PREFIX + new_secret()
    user = get_context().user_id
    endpoint_id: UUID = s.execute(
        text(
            "insert into kernel.webhook_endpoint (tenant_id, created_by, name, url, event_types, secret_ciphertext, "
            "secret_hint) values (kernel.current_tenant(), :u, :n, :url, :ev, :c, :h) returning id"
        ),
        {
            "u": str(user) if user else None,
            "n": name.strip(),
            "url": url.strip(),
            "ev": events,
            "c": encrypt(secret).encode(),
            "h": secret[-4:],
        },
    ).scalar_one()
    audit.record(s, "create", "kernel.webhook_endpoint", endpoint_id, {"name": name.strip(), "events": events})
    return endpoint_id, secret


def _endpoint(s: Session, endpoint_id: UUID) -> Any:
    row = s.execute(
        text(f"select {COLUMNS} from kernel.webhook_endpoint where id = :i"), {"i": str(endpoint_id)}
    ).first()
    if row is None:
        raise NotFound("Webhook endpoint not found")
    return row


def list_endpoints(s: Session) -> list[Any]:
    return list(s.execute(text(f"select {COLUMNS} from kernel.webhook_endpoint order by created_at")))


def get_endpoint(s: Session, endpoint_id: UUID) -> Any:
    return _endpoint(s, endpoint_id)


def update_endpoint(
    s: Session,
    endpoint_id: UUID,
    *,
    name: str | None = None,
    url: str | None = None,
    event_types: list[str] | None = None,
    status: str | None = None,
) -> Any:
    """Change an endpoint. `status` active/paused; making a disabled one active again also clears its failure count."""
    row = _endpoint(s, endpoint_id)
    changes: dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise ValidationFailed("Give the endpoint a name")
        changes["name"] = name.strip()
    if url is not None:
        check_address(url)
        changes["url"] = url.strip()
    if event_types is not None:
        changes["event_types"] = _check_events(event_types)
    if status is not None:
        if status not in ("active", "paused"):
            raise ValidationFailed("Status is 'active' or 'paused'")
        if status == "active" and "url" not in changes:
            check_address(row.url)
        changes["status"] = status
        if status == "active":
            changes.update(disabled_reason=None, consecutive_failures=0)
    if changes:
        user = get_context().user_id
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        s.execute(
            text(f"update kernel.webhook_endpoint set {sets}, updated_at = now(), updated_by = :_u where id = :_i"),
            {**changes, "_u": str(user) if user else None, "_i": str(endpoint_id)},
        )
        audit.record(
            s,
            "update",
            "kernel.webhook_endpoint",
            endpoint_id,
            {k: v for k, v in changes.items() if k != "disabled_reason"},
        )
    return _endpoint(s, endpoint_id)


def rotate_secret(s: Session, endpoint_id: UUID) -> str:
    """Give the endpoint a new signing secret (shown once); the old one stops working at once."""
    _endpoint(s, endpoint_id)
    secret = SECRET_PREFIX + new_secret()
    s.execute(
        text(
            "update kernel.webhook_endpoint set secret_ciphertext = :c, secret_hint = :h, updated_at = now() "
            "where id = :i"
        ),
        {"c": encrypt(secret).encode(), "h": secret[-4:], "i": str(endpoint_id)},
    )
    audit.record(s, "rotate_secret", "kernel.webhook_endpoint", endpoint_id)
    return secret


def delete_endpoint(s: Session, endpoint_id: UUID) -> None:
    row = _endpoint(s, endpoint_id)
    s.execute(text("delete from kernel.webhook_endpoint where id = :i"), {"i": str(endpoint_id)})
    audit.record(s, "delete", "kernel.webhook_endpoint", endpoint_id, {"name": row.name})


def _secret(s: Session, endpoint_id: UUID) -> str:
    cipher = s.execute(
        text("select secret_ciphertext from kernel.webhook_endpoint where id = :i"), {"i": str(endpoint_id)}
    ).scalar_one()
    return decrypt(bytes(cipher).decode())


# --------------------------------------------------------------------------- deliveries
DELIVERY_COLUMNS = (
    "id, created_at, endpoint_id, event_id, event_type, aggregate_type, aggregate_id, status, "
    "attempts, "
    "max_attempts, last_attempt_at, next_attempt_at, delivered_at, last_status_code, "
    "last_duration_ms, last_error, is_test, body_bytes, body_sha256, body_preview, "
    "(body is not null) as has_body"
)


def _new_delivery(s: Session, endpoint_id: UUID, event: Event, *, is_test: bool = False) -> UUID:
    settings = get_settings()
    ctx = get_context()
    event_id = uuid.uuid4()
    body = build_body(event_id, event, datetime.now(UTC), ctx.tenant_id)
    raw = body.encode()
    delivery_id: UUID = s.execute(
        text(
            "insert into kernel.webhook_delivery (tenant_id, endpoint_id, event_id, event_type, aggregate_type, "
            "aggregate_id, body, body_sha256, body_preview, body_bytes, max_attempts, expires_at, next_attempt_at, "
            "is_test) values (kernel.current_tenant(), :e, :ev, :t, :at, :ai, :b, :sha, :pv, :n, :m, "
            "now() + make_interval(hours => :h), now(), :test) returning id"
        ),
        {
            "e": str(endpoint_id),
            "ev": str(event_id),
            "t": event.type,
            "at": event.aggregate_type,
            "ai": str(event.aggregate_id),
            "b": body,
            "sha": hashlib.sha256(raw).hexdigest(),
            "pv": raw[:PREVIEW_BYTES].decode(errors="ignore"),
            "n": len(raw),
            "m": settings.webhook_max_attempts,
            "h": settings.webhook_retry_hours,
            "test": is_test,
        },
    ).scalar_one()
    enqueue(s, "webhooks.deliver", {"delivery_id": str(delivery_id)}, dedupe_key=f"webhook:{delivery_id}:first")
    return delivery_id


def fan_out(s: Session, event: Event) -> None:
    """After-commit handler of every public event: one delivery for each active endpoint subscribed to it."""
    ids = (
        s.execute(
            text("select id from kernel.webhook_endpoint where status = 'active' and :t = any(event_types)"),
            {"t": event.type},
        )
        .scalars()
        .all()
    )
    for endpoint_id in ids:
        _new_delivery(s, endpoint_id, event)


def send_ping(s: Session, endpoint_id: UUID) -> UUID:
    """Queue a test delivery (event type `webhook.ping`) so the business can check its receiver."""
    row = _endpoint(s, endpoint_id)
    if row.status == "disabled":
        raise Conflict("This endpoint is disabled; fix the receiver and enable it again first")
    audit.record(s, "ping", "kernel.webhook_endpoint", endpoint_id)
    return _new_delivery(
        s,
        endpoint_id,
        Event(PING, "kernel.webhook_endpoint", endpoint_id, {"message": "This is a test from Ziira"}),
        is_test=True,
    )


def redeliver(s: Session, delivery_id: UUID) -> None:
    """Send a delivery again (same event id, so a receiver can recognise it). Needs the body to still be kept."""
    row = s.execute(
        text(
            "select d.endpoint_id, d.status, (d.body is null) as expired, e.status as endpoint_status "
            "from kernel.webhook_delivery d join kernel.webhook_endpoint e on e.id = d.endpoint_id "
            "where d.id = :i for update of d"
        ),
        {"i": str(delivery_id)},
    ).first()
    if row is None:
        raise NotFound("Delivery not found")
    if row.status == "pending":
        raise Conflict("This delivery is still being sent")
    if row.expired:
        raise Conflict(
            f"This delivery is older than {get_settings().webhook_body_days} days; its content is no longer kept"
        )
    if row.endpoint_status != "active":
        raise Conflict("The endpoint is not active")
    settings = get_settings()
    s.execute(
        text(
            "update kernel.webhook_delivery set status = 'pending', attempts = 0, last_error = null, "
            "next_attempt_at = now(), expires_at = now() + make_interval(hours => :h) where id = :i"
        ),
        {"i": str(delivery_id), "h": settings.webhook_retry_hours},
    )
    enqueue(
        s,
        "webhooks.deliver",
        {"delivery_id": str(delivery_id)},
        dedupe_key=f"webhook:{delivery_id}:{uuid.uuid4().hex[:8]}",
    )
    audit.record(s, "redeliver", "kernel.webhook_delivery", delivery_id)


def list_deliveries(s: Session, endpoint_id: UUID, *, status: str | None, limit: int, offset: int) -> list[Any]:
    _endpoint(s, endpoint_id)
    return list(
        s.execute(
            text(
                f"select {DELIVERY_COLUMNS} from kernel.webhook_delivery where endpoint_id = :e "
                "and (cast(:st as text) is null or status = :st) order by created_at desc limit :l offset :o"
            ),
            {"e": str(endpoint_id), "st": status, "l": limit, "o": offset},
        )
    )


def get_delivery(s: Session, delivery_id: UUID) -> tuple[Any, list[Any]]:
    row = s.execute(
        text(f"select {DELIVERY_COLUMNS} from kernel.webhook_delivery where id = :i"), {"i": str(delivery_id)}
    ).first()
    if row is None:
        raise NotFound("Delivery not found")
    attempts = list(
        s.execute(
            text(
                "select attempted_at, ok, status_code, duration_ms, error from kernel.webhook_attempt "
                "where delivery_id = :i order by attempted_at"
            ),
            {"i": str(delivery_id)},
        )
    )
    return row, attempts


# --------------------------------------------------------------------------- sending
def _post(url: str, headers: dict[str, str], body: str) -> tuple[int | None, int, str | None]:
    """One POST. Returns (status code or None, milliseconds, a short error for the log). Never raises."""
    started = time.monotonic()

    def took() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        host, port, ips = check_address(url)
    except UnsafeAddress as exc:
        return None, took(), f"Address not allowed: {exc.message}"
    parts = urlsplit(url)
    ip = ips[0]
    literal = f"[{ip}]" if ":" in ip else ip
    target = f"{parts.scheme}://{literal}:{port}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")
    transport = _transport or httpx.HTTPTransport()
    try:
        with httpx.Client(
            transport=transport, follow_redirects=False, timeout=get_settings().webhook_timeout_seconds
        ) as client:
            request = client.build_request(
                "POST",
                target,
                content=body.encode(),
                headers={**headers, "Host": f"{host}:{port}" if parts.port else host},
                extensions={"sni_hostname": host},
            )
            response = client.send(request, stream=True)
            code = response.status_code
            response.close()
    except httpx.TimeoutException:
        return None, took(), "The receiver did not answer in time"
    except httpx.ConnectError:
        return None, took(), "Could not connect to the receiver"
    except httpx.HTTPError as exc:
        return None, took(), f"Request failed ({type(exc).__name__})"
    return code, took(), None


@job("webhooks.deliver")
def deliver(s: Session, payload: dict[str, Any]) -> None:
    """Background job: one try at one delivery; schedules the next try itself so the log keeps every attempt."""
    delivery_id = UUID(str(payload["delivery_id"]))
    d = s.execute(
        text(
            "select d.id, d.endpoint_id, d.event_id, d.event_type, d.body, d.attempts, d.max_attempts, d.status, "
            "d.expires_at < now() as expired, e.url, e.status as endpoint_status "
            "from kernel.webhook_delivery d join kernel.webhook_endpoint e on e.id = d.endpoint_id "
            "where d.id = :i for update of d"
        ),
        {"i": str(delivery_id)},
    ).first()
    if d is None or d.status != "pending":
        return
    if d.endpoint_status != "active":
        _finish(s, d.id, "cancelled", error=f"The endpoint is {d.endpoint_status}")
        return
    if d.body is None:
        _finish(s, d.id, "failed", error="The content is no longer kept")
        return
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Ziira-Webhooks/1",
        "Ziira-Event-Id": str(d.event_id),
        "Ziira-Timestamp": str(timestamp),
        "Ziira-Signature": sign(_secret(s, d.endpoint_id), timestamp, d.body),
    }
    code, ms, error = _post(d.url, headers, d.body)
    ok = code is not None and 200 <= code < 300
    attempts = d.attempts + 1
    if code is not None and not ok:
        error = f"The receiver answered {code}"
    s.execute(
        text(
            "insert into kernel.webhook_attempt (tenant_id, delivery_id, ok, status_code, duration_ms, error) "
            "values (kernel.current_tenant(), :d, :ok, :c, :ms, :e)"
        ),
        {"d": str(d.id), "ok": ok, "c": code, "ms": ms, "e": error},
    )
    s.execute(
        text(
            "update kernel.webhook_delivery set attempts = :a, last_attempt_at = now(), last_status_code = :c, "
            "last_duration_ms = :ms, last_error = :e where id = :i"
        ),
        {"a": attempts, "c": code, "ms": ms, "e": error, "i": str(d.id)},
    )
    if ok:
        s.execute(
            text(
                "update kernel.webhook_delivery set status = 'delivered', delivered_at = now(), "
                "next_attempt_at = null where id = :i"
            ),
            {"i": str(d.id)},
        )
        s.execute(
            text("update kernel.webhook_endpoint set consecutive_failures = 0, last_success_at = now() where id = :e"),
            {"e": str(d.endpoint_id)},
        )
        return
    s.execute(
        text("update kernel.webhook_endpoint set last_failure_at = now() where id = :e"), {"e": str(d.endpoint_id)}
    )
    if code == 410:
        _disable(s, d.endpoint_id, "The receiver answered 410 Gone, which means it no longer wants these")
        _finish(s, d.id, "failed", keep_error=True)
    elif attempts >= d.max_attempts or d.expired:
        _finish(s, d.id, "failed", keep_error=True)
        _give_up(s, d.endpoint_id)
    else:
        wait = backoff_seconds(attempts)
        s.execute(
            text(
                "update kernel.webhook_delivery set next_attempt_at = now() + make_interval(secs => :w) where id = :i"
            ),
            {"w": wait, "i": str(d.id)},
        )
        enqueue(
            s,
            "webhooks.deliver",
            {"delivery_id": str(d.id)},
            delay_seconds=wait,
            dedupe_key=f"webhook:{d.id}:{uuid.uuid4().hex[:8]}",
        )


def _finish(s: Session, delivery_id: UUID, status: str, *, error: str | None = None, keep_error: bool = False) -> None:
    s.execute(
        text(
            "update kernel.webhook_delivery set status = :st, next_attempt_at = null, "
            "last_error = case when :keep then last_error else :e end where id = :i"
        ),
        {"st": status, "e": error, "keep": keep_error, "i": str(delivery_id)},
    )


def _disable(s: Session, endpoint_id: UUID, reason: str) -> None:
    s.execute(
        text(
            "update kernel.webhook_endpoint set status = 'disabled', disabled_reason = :r, updated_at = now() "
            "where id = :i"
        ),
        {"r": reason, "i": str(endpoint_id)},
    )
    s.execute(
        text(
            "update kernel.webhook_delivery set status = 'cancelled', next_attempt_at = null, "
            "last_error = 'The endpoint was disabled' where endpoint_id = :i and status = 'pending'"
        ),
        {"i": str(endpoint_id)},
    )
    name = s.execute(
        text("select name from kernel.webhook_endpoint where id = :i"), {"i": str(endpoint_id)}
    ).scalar_one()
    exceptions_inbox.flag(
        s,
        unit="kernel",
        kind="webhook_disabled",
        severity="high",
        ref_type="webhook_endpoint",
        ref_id=endpoint_id,
        message=f"Webhook '{name}' was switched off: {reason}. Fix the receiver, then enable it again in Settings.",
        dedupe_key=f"webhook-disabled:{endpoint_id}:{uuid.uuid4().hex[:8]}",
    )
    audit.record(s, "disable", "kernel.webhook_endpoint", endpoint_id, {"reason": reason})


def _give_up(s: Session, endpoint_id: UUID) -> None:
    """A delivery used all its tries: count it against the endpoint and tell a person (once a day per endpoint)."""
    s.execute(
        text("update kernel.webhook_endpoint set consecutive_failures = consecutive_failures + 1 where id = :i"),
        {"i": str(endpoint_id)},
    )
    name = s.execute(
        text("select name from kernel.webhook_endpoint where id = :i"), {"i": str(endpoint_id)}
    ).scalar_one()
    day = datetime.now(UTC).date().isoformat()
    exceptions_inbox.flag(
        s,
        unit="kernel",
        kind="webhook_failing",
        severity="medium",
        ref_type="webhook_endpoint",
        ref_id=endpoint_id,
        message=f"Webhook '{name}' could not be delivered after several tries. Check the delivery log in Settings.",
        dedupe_key=f"webhook-failing:{endpoint_id}:{day}",
    )


@periodic("kernel.webhook_purge", every_seconds=3600)
def purge(s: Session) -> None:
    """Keep each delivery's body for `webhook_body_days` (it is the only place event data is copied to), then only its
    hash and first bytes; forget the log after `webhook_log_days`."""
    settings = get_settings()
    s.execute(
        text(
            "update kernel.webhook_delivery set body = null where body is not null and status <> 'pending' "
            "and created_at < now() - make_interval(days => :d)"
        ),
        {"d": settings.webhook_body_days},
    )
    s.execute(
        text("delete from kernel.webhook_delivery where created_at < now() - make_interval(days => :d)"),
        {"d": settings.webhook_log_days},
    )
