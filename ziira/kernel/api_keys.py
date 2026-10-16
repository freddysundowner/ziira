"""API keys for server-to-server integrations (docs/public-api.md).

A key carries permission codes (what it may do), optionally limited to one company or branch, optionally read-only,
with an expiry and a per-minute request limit. It may call only the endpoints of the public API
(`public_api.PUBLIC_ENDPOINTS`). Every use is counted (last used, count, last address) and rate limited; an expired,
revoked or over-limit key is refused (401 or 429 with `Retry-After`).

The key itself is `zk_<tenant hex>_<secret>`, shown once; only its SHA-256 is stored.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, public_api
from ziira.kernel.auth import _require_active_tenant, _split_secret
from ziira.kernel.config import get_settings
from ziira.kernel.context import Assignment, RequestContext, get_context
from ziira.kernel.db import tenant_session
from ziira.kernel.errors import Forbidden, NotFound, TooManyRequests, Unauthorized, ValidationFailed
from ziira.kernel.security import hash_secret, new_secret
from ziira.kernel.users import check_can_give, check_permissions_exist

COLUMNS = (
    "id, name, scopes, read_only, company_id, branch_id, rate_limit_per_minute, created_at, expires_at, "
    "revoked_at, last_used_at, last_ip, use_count, rotated_from"
)
MAX_GRACE_HOURS = 24 * 30


def create_key(
    s: Session,
    tenant_id: UUID,
    *,
    name: str,
    scopes: list[str],
    expires_at: datetime | None = None,
    read_only: bool = False,
    company_id: UUID | None = None,
    branch_id: UUID | None = None,
    rate_limit_per_minute: int | None = None,
    rotated_from: UUID | None = None,
) -> tuple[UUID, str]:
    """Make a key. Returns its id and the key, which is shown only now. The actor must hold every scope given, over
    the company or branch the key is limited to."""
    if not name.strip():
        raise ValidationFailed("Give the key a name")
    if not scopes:
        raise ValidationFailed("Choose at least one permission for the key")
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise ValidationFailed("The expiry must be in the future")
    if rate_limit_per_minute is not None and not 1 <= rate_limit_per_minute <= 100_000:
        raise ValidationFailed("The rate limit is between 1 and 100000 requests a minute")
    if branch_id is not None and company_id is None:
        raise ValidationFailed("Name the company of the branch")
    if (
        company_id is not None
        and s.execute(text("select 1 from kernel.company where id = :c"), {"c": str(company_id)}).first() is None
    ):
        raise ValidationFailed("Company not found")
    if (
        branch_id is not None
        and s.execute(
            text("select 1 from kernel.branch where id = :b and company_id = :c"),
            {"b": str(branch_id), "c": str(company_id)},
        ).first()
        is None
    ):
        raise ValidationFailed("Branch not found in that company")
    check_permissions_exist(s, scopes)
    check_can_give(scopes, company_id, branch_id)
    key = f"zk_{tenant_id.hex}_{new_secret()}"
    creator = get_context().user_id
    key_id: UUID = s.execute(
        text(
            "insert into kernel.api_key (tenant_id, created_by, name, key_hash, scopes, expires_at, read_only, "
            "company_id, "
            "branch_id, rate_limit_per_minute, rotated_from) values (:t, :u, :n, :h, :sc, :e, :ro, :co, :b, :rl, :rf) "
            "returning id"
        ),
        {
            "t": str(tenant_id),
            "u": str(creator) if creator else None,
            "n": name.strip(),
            "h": hash_secret(key),
            "sc": sorted(set(scopes)),
            "e": expires_at,
            "ro": read_only,
            "co": str(company_id) if company_id else None,
            "b": str(branch_id) if branch_id else None,
            "rl": rate_limit_per_minute,
            "rf": str(rotated_from) if rotated_from else None,
        },
    ).scalar_one()
    audit.record(
        s,
        "create",
        "kernel.api_key",
        key_id,
        {
            "name": name.strip(),
            "scopes": sorted(set(scopes)),
            "read_only": read_only,
            "company_id": company_id,
            "branch_id": branch_id,
            "rate_limit_per_minute": rate_limit_per_minute,
            "expires_at": expires_at,
        },
    )
    return key_id, key


def list_keys(s: Session) -> list[object]:
    return list(s.execute(text(f"select {COLUMNS} from kernel.api_key order by created_at")))


def revoke(s: Session, key_id: UUID) -> None:
    if (
        s.execute(
            text("update kernel.api_key set revoked_at = now() where id = :i and revoked_at is null returning id"),
            {"i": str(key_id)},
        ).first()
        is None
    ):
        raise NotFound("API key not found")
    audit.record(s, "revoke", "kernel.api_key", key_id)


def rotate(s: Session, tenant_id: UUID, key_id: UUID, grace_hours: int = 24) -> tuple[UUID, str]:
    """Replace a key: a new one with the same name, permissions, limits and expiry, while the old one keeps working
    for `grace_hours` (0: stops now) so the integration can switch over without a gap."""
    if not 0 <= grace_hours <= MAX_GRACE_HOURS:
        raise ValidationFailed(f"The overlap is between 0 and {MAX_GRACE_HOURS} hours")
    old = s.execute(text(f"select {COLUMNS} from kernel.api_key where id = :i for update"), {"i": str(key_id)}).first()
    if old is None:
        raise NotFound("API key not found")
    if old.revoked_at is not None or (old.expires_at and old.expires_at <= datetime.now(UTC)):
        raise ValidationFailed("That key is no longer valid; make a new one instead")
    new_id, key = create_key(
        s,
        tenant_id,
        name=old.name,
        scopes=list(old.scopes),
        expires_at=old.expires_at,
        read_only=old.read_only,
        company_id=old.company_id,
        branch_id=old.branch_id,
        rate_limit_per_minute=old.rate_limit_per_minute,
        rotated_from=old.id,
    )
    s.execute(
        text(
            "update kernel.api_key set expires_at = case when :g = 0 then now() "
            "else least(coalesce(expires_at, 'infinity'), now() + make_interval(hours => :g)) end, "
            "revoked_at = case when :g = 0 then now() else revoked_at end where id = :i"
        ),
        {"g": grace_hours, "i": str(key_id)},
    )
    audit.record(s, "rotate", "kernel.api_key", key_id, {"replaced_by": new_id, "grace_hours": grace_hours})
    return new_id, key


def authenticate(key: str, ip_address: str | None) -> RequestContext:
    """Verify a key, count the use against its rate limit, and return the context it acts in."""
    tenant_id, _ = _split_secret(key, "zk")
    _require_active_tenant(tenant_id)
    window = 60
    with tenant_session(tenant_id) as s:
        row = s.execute(
            text(
                "update kernel.api_key set use_count = use_count + 1, last_used_at = now(), last_ip = :ip, "
                "window_count = case when window_started is null or window_started < now() - make_interval(secs => :w) "
                "                    then 1 else window_count + 1 end, "
                "window_started = case when window_started is null "
                "or window_started < now() - make_interval(secs => :w) "
                "                      then now() else window_started end "
                "where key_hash = :h and revoked_at is null and (expires_at is null or expires_at > now()) "
                "returning id, scopes, read_only, company_id, branch_id, window_count, "
                "coalesce(rate_limit_per_minute, :d) as limit, "
                "greatest(1, ceil(extract(epoch from window_started + make_interval(secs => :w) - now())))::int as wait"
            ),
            {"h": hash_secret(key), "ip": ip_address, "w": window, "d": get_settings().api_key_rate_limit_per_minute},
        ).first()
    if row is None:
        raise Unauthorized("API key is not valid")
    if row.window_count > row.limit:
        raise TooManyRequests(
            f"This key may make {row.limit} requests a minute. Try again shortly.", {"retry_after": row.wait}
        )
    scope = "branch" if row.branch_id else "company" if row.company_id else "tenant"
    grant = Assignment(
        role_id=None,
        role_name=f"api_key:{row.id}",
        scope=scope,
        company_id=row.company_id,
        branch_id=row.branch_id,
        permissions=frozenset(row.scopes),
    )
    return RequestContext(
        tenant_id=tenant_id, channel="api", assignments=(grant,), api_key_id=row.id, api_key_read_only=row.read_only
    )


def enforce(ctx: RequestContext, request: Request) -> None:
    """A key may read only if it is read-only, and may call only the public API."""
    if ctx.api_key_id is None:
        return
    if ctx.api_key_read_only and request.method not in ("GET", "HEAD"):
        raise Forbidden("This API key is read-only")
    if not public_api.is_public(request.method, request.url.path):
        raise Forbidden("This endpoint is not part of the public API, so API keys cannot use it (docs/public-api.md)")
