"""Idempotency keys: a request that is retried (a flaky connection, an offline device uploading again) must not be
done twice.

A client sends an `Idempotency-Key` header. The first request with that key runs and its response is stored; any later
request with the same key and the same content gets the stored response back without running again. The same key with
different content is refused (a client bug). The key is held under a lock while the first request runs, so two copies
arriving together do not both run.

Everything happens inside the request's own transaction: if the operation fails, nothing is stored and a retry runs it.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel.context import get_context
from ziira.kernel.errors import ValidationFailed

MAX_KEY_LENGTH = 200
KEEP_DAYS = 7


def check_key(key: str) -> str:
    """A key is 1-200 printable characters."""
    if not key or len(key) > MAX_KEY_LENGTH or not key.isprintable():
        raise ValidationFailed(f"The Idempotency-Key must be 1-{MAX_KEY_LENGTH} printable characters")
    return key


def request_hash(request: Any) -> str:
    """A fingerprint of what the client asked for."""
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


def run_once(session: Session, key: str | None, request: Any, operation: Callable[[], Any]) -> tuple[Any, bool]:
    """Run `operation` once per key. Returns (response, replayed).

    `request` is anything JSON-like that identifies what was asked; `operation` returns a JSON-able response (convert
    models with `fastapi.encoders.jsonable_encoder`). Without a key the operation simply runs.
    """
    if key is None:
        return operation(), False
    check_key(key)
    tenant = str(get_context().tenant_id)
    digest = request_hash(request)
    session.execute(text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"idempotency:{tenant}:{key}"})
    row = session.execute(text(
        "select request_hash, response from kernel.idempotency_key where tenant_id = kernel.current_tenant() "
        "and key = :k"), {"k": key}).first()
    if row is not None:
        if row.request_hash != digest:
            raise ValidationFailed("This Idempotency-Key was already used for a different request")
        return row.response, True
    response = operation()
    session.execute(text(
        "insert into kernel.idempotency_key (tenant_id, key, request_hash, response) "
        "values (kernel.current_tenant(), :k, :h, cast(:r as jsonb))"),
        {"k": key, "h": digest, "r": json.dumps(response, default=str)})
    return response, False


def purge_old_keys(session: Session) -> int:
    """Forget keys older than a week (a client retrying after that is not a retry any more)."""
    return len(session.execute(text(
        "delete from kernel.idempotency_key where created_at < now() - make_interval(days => :d) returning key"),
        {"d": KEEP_DAYS}).all())
