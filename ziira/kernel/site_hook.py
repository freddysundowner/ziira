"""Telling the static site to rebuild after a publish.

`ZIIRA_SITE_BUILD_HOOK_URL` is called with a POST whose body names the publish; `ZIIRA_SITE_BUILD_HOOK_SECRET` signs it
exactly like business webhooks do: `Ziira-Signature: v1=<hex HMAC-SHA256 over "{timestamp}.{body}">` with the
`Ziira-Timestamp` (unix seconds) and a `Ziira-Event-Id` that stays the same on every retry. The address may carry a
token (many build services put one in the path), so it is never logged or stored: the record keeps only the host name,
the status code and a short reason. A failed try is retried by `ziira worker` with growing waits; a manual retry is a
button in the Super Admin.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session
from ziira.kernel.errors import NotFound

log = logging.getLogger("ziira.site_hook")

BACKOFF_SECONDS = (30, 120, 480, 1800, 7200)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
CLAIM_SECONDS = 300
TIMEOUT_SECONDS = 10.0
transport: httpx.BaseTransport | None = None        # tests put a fake here


class _HideAddress(logging.Filter):
    """httpx logs every request's full address at INFO. The rebuild address may hold a token, so it is replaced."""

    def filter(self, record: logging.LogRecord) -> bool:
        url = get_settings().site_build_hook_url.strip()
        message = record.getMessage()
        if url and url in message:
            record.msg, record.args = message.replace(url, "[site rebuild address]"), None
        return True


logging.getLogger("httpx").addFilter(_HideAddress())


def configured() -> bool:
    return bool(get_settings().site_build_hook_url.strip())


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"v1={mac}"


def _body(row: Any) -> bytes:
    return json.dumps({"event": "site.published", "publish_id": row.id, "version_hash": row.version_hash,
                       "published_at": row.published_at.astimezone(UTC).isoformat()}, separators=(",", ":")).encode()


def _post(row: Any) -> tuple[str, str]:
    """(ok | retry | fail | skip, what to record). Never returns or logs the address."""
    settings = get_settings()
    url = settings.site_build_hook_url.strip()
    if not url:
        return "skip", "no rebuild address is configured"
    parts = urlsplit(url)
    host = parts.hostname or "?"
    local = host in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (settings.env != "production" and local and parts.scheme == "http"):
        return "fail", f"{host}: the rebuild address must use https"
    body, stamp = _body(row), str(int(time.time()))
    headers = {"Content-Type": "application/json", "Ziira-Timestamp": stamp, "Ziira-Event-Id": f"site-publish-{row.id}",
               "User-Agent": "Ziira-Site-Publisher/1"}
    if settings.site_build_hook_secret:
        headers["Ziira-Signature"] = sign(settings.site_build_hook_secret, stamp, body)
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(url, content=body, headers=headers)
    except httpx.HTTPError as error:
        return "retry", f"{host}: could not be reached ({type(error).__name__})"
    if 200 <= response.status_code < 300:
        return "ok", f"{host}: answered {response.status_code}"
    retryable = response.status_code in (408, 425, 429) or response.status_code >= 500
    return ("retry" if retryable else "fail"), f"{host}: answered {response.status_code}"


def attempt(publish_id: int) -> dict[str, Any]:
    """Make one try for a publish that is waiting, and record how it went. Safe to call from two workers: the try is
    claimed first, so only one makes it."""
    with master_session() as m:
        row = m.execute(text(
            "update master.site_publish set hook_next_at = now() + make_interval(secs => :c) "
            "where id = :i and hook_status = 'pending' and (hook_next_at is null or hook_next_at <= now()) "
            "returning id, version_hash, published_at, hook_attempts"), {"c": CLAIM_SECONDS, "i": publish_id}).first()
    if row is None:
        return status(publish_id)
    outcome, result = _post(row)
    attempts = row.hook_attempts + 1
    wait: int | None = None
    if outcome == "retry" and attempts < MAX_ATTEMPTS:
        new_status, wait = "pending", BACKOFF_SECONDS[attempts - 1]
    else:
        new_status = {"ok": "ok", "skip": "skipped"}.get(outcome, "failed")
    with master_session() as m:
        m.execute(text(
            "update master.site_publish set hook_status = :s, hook_attempts = :a, hook_result = :r, "
            "hook_next_at = case when cast(:w as int) is null then null else now() + make_interval(secs => :w) end "
            "where id = :i"), {"s": new_status, "a": attempts, "r": result[:300], "w": wait, "i": publish_id})
    log.info("Site rebuild hook for publish %s: %s", publish_id, new_status)
    return status(publish_id)


def status(publish_id: int) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text("select id, hook_status, hook_attempts, hook_next_at, hook_result "
                             "from master.site_publish where id = :i"), {"i": publish_id}).first()
    if row is None:
        raise NotFound("No such publish")
    return dict(row._mapping)


def retry(publish_id: int) -> dict[str, Any]:
    """The operator's 'try again now': resets the count and makes one try at once."""
    with master_session() as m:
        found = m.execute(text(
            "update master.site_publish set hook_status = 'pending', hook_attempts = 0, hook_next_at = now(), "
            "hook_result = null where id = :i returning id"), {"i": publish_id}).first()
    if found is None:
        raise NotFound("No such publish")
    return attempt(publish_id)


def run_pending() -> int:
    """Try every waiting publish that is due (the worker calls this). Returns how many tries were made."""
    with master_session() as m:
        due = [r.id for r in m.execute(text("select id from master.site_publish where hook_status = 'pending' and "
                                            "(hook_next_at is null or hook_next_at <= now()) order by id"))]
    for publish_id in due:
        attempt(publish_id)
    return len(due)

