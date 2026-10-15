"""Authentication: sign in, refresh, sign out, API keys, and building the request context.

- Sign in with an email or phone and a password. The login directory (kernel/directory.py) says which business's
  database to check; a workspace code is optional (needed only when the same login is in several businesses).
- An access token lasts minutes; it names the session, which is checked on every request,
  so signing out or disabling a user takes effect immediately.
- A refresh token is bound to the device that signed in and is replaced on every use.
- API keys are for server-to-server integrations; their scopes are permission codes.

Token formats (the tenant is embedded so the row can be found under row-level security):
    refresh token  zr_<tenant hex>_<secret>
    API key        zk_<tenant hex>_<secret>
"""

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit, directory, mfa, support, throttle
from ziira.kernel.config import get_settings
from ziira.kernel.context import Assignment, RequestContext, get_context, set_context
from ziira.kernel.db import master_session, tenant_engine, tenant_session
from ziira.kernel.errors import ChallengeExpired, ChooseBusiness, MfaRequired, NotFound, Unauthorized, ValidationFailed
from ziira.kernel.security import hash_secret, new_secret, read_token, sign_token, verify_password

CHANNELS = ("web", "pos", "api")


@dataclass(frozen=True)
class Tokens:
    """What a successful sign-in or refresh returns."""

    access_token: str
    refresh_token: str
    expires_in: int          # seconds until the access token expires
    session_id: UUID
    user_id: UUID
    tenant_id: UUID


def _now() -> datetime:
    return datetime.now(UTC)


def _split_secret(value: str, prefix: str) -> tuple[UUID, str]:
    """Split `<prefix>_<tenant hex>_<secret>` into tenant and secret, or raise Unauthorized."""
    try:
        head, tenant_hex, _ = value.split("_", 2)
        if head != prefix:
            raise ValueError
        return UUID(hex=tenant_hex), value
    except ValueError:
        raise Unauthorized("Malformed credential") from None


def _require_active_tenant(tenant_id: UUID) -> None:
    """Unauthorized (not 'not found') if the tenant in a credential does not exist or is not active."""
    try:
        tenant_engine(tenant_id)
    except NotFound:
        raise Unauthorized("Credentials are not valid") from None


def client_ip(request: Request) -> str | None:
    """The caller's address for the audit log, or None if it is not a valid IP.

    Behind a trusted proxy (ZIIRA_TRUST_FORWARDED_FOR) the proxy's own entry, the last one in
    X-Forwarded-For, is used; earlier entries can be forged by the client.
    """
    candidate = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if get_settings().trust_forwarded_for and forwarded:
        candidate = forwarded.split(",")[-1].strip()
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None


def tenant_by_code(code: str) -> UUID | None:
    """Find an active tenant by its workspace code in the master database."""
    with master_session() as s:
        row = s.execute(text("select id from master.tenant where code = :c and status = 'active'"),
                        {"c": code.strip().lower()}).first()
    return row[0] if row else None


# --------------------------------------------------------------------------- sign in / out
def _try_tenant(tenant_id: UUID, login: str, password: str, channel: str, device_id: str, device_name: str | None,
                ip_address: str | None, *, open_session: bool) -> Tokens | bool:
    """Check the password inside one business's database. With `open_session` a good password opens a session and
    returns its tokens; otherwise it only says yes (True) or no (False). A refusal is audited in that business."""
    with tenant_session(tenant_id) as s:
        user = s.execute(text(
            "select id, password_hash, status from kernel.app_user "
            "where lower(email) = lower(:l) or phone = :l"), {"l": login.strip()}).first()
        if verify_password(password, user.password_hash if user else None) and user and user.status == "active":
            if open_session:
                if mfa.is_enabled(s, user.id):
                    raise MfaRequired("Enter the code from your authenticator app", {"challenge": _challenge(
                        tenant_id, user.id, channel, device_id, device_name)})
                return _open_session(s, tenant_id, user.id, channel, device_id, device_name, ip_address)
            return True
        set_context(RequestContext(tenant_id=tenant_id, channel=channel, device_id=device_id, ip_address=ip_address))
        audit.record(s, "login_failed", "kernel.app_user", user.id if user else None,
                     {"login": login.strip(), "device_id": device_id})
    return False


def sign_in(workspace: str | None, login: str, password: str, *, device_id: str, device_name: str | None = None,
            channel: str = "web", ip_address: str | None = None) -> Tokens:
    """Check the password and open a session on this device. Raises Unauthorized (wrong login or password),
    TooManyRequests (too many wrong tries: wait), MfaRequired (the password was right; send the code with the
    challenge to `complete_mfa`) or ChooseBusiness.
    """
    counters = throttle.sign_in_counters(login, ip_address)
    throttle.guard(counters)
    try:
        tokens = _sign_in(workspace, login, password, device_id=device_id, device_name=device_name, channel=channel,
                          ip_address=ip_address)
    except (MfaRequired, ChooseBusiness):
        throttle.succeeded(counters[:2])          # the password was right
        raise
    except Unauthorized:
        throttle.failed(counters)
        raise
    throttle.succeeded(counters[:2])
    return tokens


def _sign_in(workspace: str | None, login: str, password: str, *, device_id: str, device_name: str | None = None,
             channel: str = "web", ip_address: str | None = None) -> Tokens:
    """The sign-in itself (see `sign_in`).

    With a workspace code the business is known. Without one, the login directory lists the businesses that have a
    user with this login; the password is checked in each, and if it is right in exactly one the person is signed in
    there. If it is right in several (the same person works for more than one business), `ChooseBusiness` lists them
    and the client asks again with the chosen workspace code. Nothing is revealed about businesses the password does
    not open.
    """
    if channel not in CHANNELS:
        raise ValidationFailed(f"Channel must be one of: {', '.join(CHANNELS)}")
    if not device_id.strip():
        raise ValidationFailed("device_id is required")
    refused = "Wrong login or password"
    if workspace is not None and workspace.strip():
        tenant_id = tenant_by_code(workspace)
        if tenant_id is None:
            verify_password(password, None)     # same effort as a real check
            raise Unauthorized(refused)
        result = _try_tenant(tenant_id, login, password, channel, device_id, device_name, ip_address, open_session=True)
        if isinstance(result, Tokens):
            return result
        raise Unauthorized(refused)

    candidates = directory.tenants_for(login)
    if not candidates:
        verify_password(password, None)         # unknown login: same effort, same answer
        raise Unauthorized(refused)
    if len(candidates) == 1:
        result = _try_tenant(candidates[0], login, password, channel, device_id, device_name, ip_address,
                             open_session=True)
        if isinstance(result, Tokens):
            return result
        raise Unauthorized(refused)
    matching = [t for t in candidates if _try_tenant(t, login, password, channel, device_id, device_name, ip_address,
                                                      open_session=False) is True]
    if not matching:
        raise Unauthorized(refused)
    if len(matching) == 1:
        result = _try_tenant(matching[0], login, password, channel, device_id, device_name, ip_address,
                             open_session=True)
        if isinstance(result, Tokens):
            return result
        raise Unauthorized(refused)
    with master_session() as m:
        named = [{"workspace": r.code, "name": r.name} for r in m.execute(
            text("select code, name from master.tenant where id = any(:ids) order by name"),
            {"ids": [str(t) for t in matching]})]
    raise ChooseBusiness("This login works for more than one business: say which one",
                         {"businesses": named})


MFA_CHALLENGE_MINUTES = 5


def _challenge(tenant_id: UUID, user_id: UUID, channel: str, device_id: str, device_name: str | None) -> str:
    """A short-lived signed note that the password was right, to be sent back with the second-factor code."""
    return sign_token({"k": "mfa", "t": str(tenant_id), "u": str(user_id), "c": channel, "d": device_id,
                       "n": device_name}, MFA_CHALLENGE_MINUTES)


def complete_mfa(challenge: str, code: str, *, ip_address: str | None = None) -> Tokens:
    """Second step of a sign-in with a second factor: the challenge from the password step and a code (an authenticator
    code, or a backup code). Wrong codes count against the same limits as passwords."""
    try:
        payload = read_token(challenge)
    except Unauthorized as error:
        raise ChallengeExpired("This sign-in took too long or is not valid: enter your password again") from error
    if payload.get("k") != "mfa":
        raise ChallengeExpired("That is not a sign-in challenge: enter your password again")
    tenant_id, user_id = UUID(payload["t"]), UUID(payload["u"])
    counters = throttle.action_counters("mfa", str(user_id), ip_address, per_subject=5, per_ip=30)
    throttle.guard(counters)
    _require_active_tenant(tenant_id)
    with tenant_session(tenant_id) as s:
        # Audit entries (a backup code being used, a failed attempt) need to know who and where from.
        set_context(RequestContext(tenant_id=tenant_id, user_id=user_id, channel=payload["c"], device_id=payload["d"],
                                   ip_address=ip_address))
        active = s.execute(text("select status from kernel.app_user where id = :u"), {"u": str(user_id)}).scalar()
        if active == "active" and mfa.verify(s, user_id, code):
            throttle.succeeded(counters[:1])
            return _open_session(s, tenant_id, user_id, payload["c"], payload["d"], payload.get("n"), ip_address)
        audit.record(s, "mfa_failed", "kernel.app_user", user_id, {"device_id": payload["d"]})
    throttle.failed(counters)
    raise Unauthorized("That code is not right")


def open_session_for(tenant_id: UUID, user_id: UUID, *, device_id: str, device_name: str | None = None,
                     channel: str = "web", ip_address: str | None = None) -> Tokens:
    """Open a session for a user who has just proved who they are in some other way (the owner who verified their email
    when registering). Not for passwords: use `sign_in`."""
    if channel not in CHANNELS:
        raise ValidationFailed(f"Channel must be one of: {', '.join(CHANNELS)}")
    with tenant_session(tenant_id) as s:
        return _open_session(s, tenant_id, user_id, channel, device_id, device_name, ip_address)


def _open_session(s: Session, tenant_id: UUID, user_id: UUID, channel: str, device_id: str,
                  device_name: str | None, ip_address: str | None = None) -> Tokens:
    settings = get_settings()
    refresh = f"zr_{tenant_id.hex}_{new_secret()}"
    session_id: UUID = s.execute(text(
        "insert into kernel.user_session (tenant_id, user_id, channel, device_id, device_name, refresh_hash, "
        "expires_at) values (:t, :u, :c, :d, :n, :h, :e) returning id"),
        {"t": str(tenant_id), "u": str(user_id), "c": channel, "d": device_id, "n": device_name,
         "h": hash_secret(refresh), "e": _now() + timedelta(days=settings.refresh_token_days)}).scalar_one()
    s.execute(text("update kernel.app_user set last_login_at = now() where id = :u"), {"u": str(user_id)})
    set_context(RequestContext(tenant_id=tenant_id, user_id=user_id, channel=channel, session_id=session_id,
                               device_id=device_id, ip_address=ip_address))
    audit.record(s, "login", "kernel.app_user", user_id, {"device_id": device_id, "session_id": session_id})
    return _tokens(tenant_id, user_id, session_id, refresh, setup_required=mfa.must_set_up(s, user_id))


def _tokens(tenant_id: UUID, user_id: UUID, session_id: UUID, refresh: str, *, setup_required: bool = False) -> Tokens:
    minutes = get_settings().access_token_minutes
    claims: dict[str, object] = {"t": str(tenant_id), "u": str(user_id), "s": str(session_id)}
    if setup_required:
        claims["m"] = 1          # a second factor is compulsory and not set up: only the setup calls work
    access = sign_token(claims, minutes)
    return Tokens(access_token=access, refresh_token=refresh, expires_in=minutes * 60,
                  session_id=session_id, user_id=user_id, tenant_id=tenant_id)


def refresh(refresh_token: str, device_id: str) -> Tokens:
    """Swap a refresh token for new tokens. The old refresh token stops working.

    Refused if the token was issued to another device, the session was signed out,
    has expired, or has been idle too long.
    """
    tenant_id, _ = _split_secret(refresh_token, "zr")
    idle = timedelta(hours=get_settings().session_idle_hours)
    _require_active_tenant(tenant_id)
    with tenant_session(tenant_id) as s:
        row = s.execute(text(
            "select s.id, s.user_id, s.device_id, s.expires_at, s.last_used_at, s.revoked_at, u.status "
            "from kernel.user_session s join kernel.app_user u on u.id = s.user_id "
            "where s.refresh_hash = :h for update of s"), {"h": hash_secret(refresh_token)}).first()
        if row is None or row.revoked_at is not None or row.status != "active":
            raise Unauthorized("Session is no longer valid; sign in again")
        if row.device_id != device_id:
            raise Unauthorized("This refresh token belongs to another device")
        if row.expires_at < _now() or row.last_used_at + idle < _now():
            raise Unauthorized("Session expired; sign in again")
        new_refresh = f"zr_{tenant_id.hex}_{new_secret()}"
        s.execute(text("update kernel.user_session set refresh_hash = :h, last_used_at = now() where id = :i"),
                  {"h": hash_secret(new_refresh), "i": str(row.id)})
        setup_required = mfa.must_set_up(s, row.user_id)
    return _tokens(tenant_id, row.user_id, row.id, new_refresh, setup_required=setup_required)


def sign_out(s: Session, session_id: UUID) -> None:
    """End a session (this device, or remote sign-out of another of the user's devices)."""
    s.execute(text("update kernel.user_session set revoked_at = now() where id = :i and revoked_at is null"),
              {"i": str(session_id)})


def sign_out_user(s: Session, user_id: UUID) -> None:
    """End every session of a user (used when a user is disabled)."""
    s.execute(text("update kernel.user_session set revoked_at = now() "
                   "where user_id = :u and revoked_at is null"), {"u": str(user_id)})


# --------------------------------------------------------------------------- API keys
def create_api_key(s: Session, tenant_id: UUID, name: str, scopes: list[str],
                   expires_at: datetime | None = None) -> tuple[UUID, str]:
    """Create an API key. Returns its id and the key itself, which is shown only once.

    The caller checks that the scopes exist and that the actor may give them.
    """
    key = f"zk_{tenant_id.hex}_{new_secret()}"
    creator = get_context().user_id
    key_id: UUID = s.execute(text(
        "insert into kernel.api_key (tenant_id, created_by, name, key_hash, scopes, expires_at) "
        "values (:t, :u, :n, :h, :sc, :e) returning id"),
        {"t": str(tenant_id), "u": str(creator) if creator else None, "n": name, "h": hash_secret(key), "sc": scopes,
         "e": expires_at}).scalar_one()
    return key_id, key


# --------------------------------------------------------------------------- request context
def load_assignments(s: Session, user_id: UUID) -> tuple[Assignment, ...]:
    """The user's roles with their permissions and scopes."""
    rows = s.execute(text(
        "select ur.role_id, r.name, ur.scope, ur.company_id, ur.branch_id, "
        "       coalesce(array_agg(rp.permission_code) filter (where rp.permission_code is not null), '{}') "
        "         as permissions "
        "from kernel.user_role ur join kernel.role r on r.id = ur.role_id "
        "left join kernel.role_permission rp on rp.role_id = ur.role_id "
        "where ur.user_id = :u group by ur.id, ur.role_id, r.name, ur.scope, ur.company_id, ur.branch_id"),
        {"u": str(user_id)})
    return tuple(Assignment(role_id=r.role_id, role_name=r.name, scope=r.scope, company_id=r.company_id,
                            branch_id=r.branch_id, permissions=frozenset(r.permissions)) for r in rows)


def context_from_access_token(token: str) -> RequestContext:
    """Verify an access token and its session, and load the user's roles."""
    payload = read_token(token)
    kind = payload.get("k")
    if kind == "support":
        return _support_context(payload)
    if kind is not None:
        raise Unauthorized("Invalid token")          # operator tokens and sign-in challenges are not access tokens
    try:
        tenant_id, user_id, session_id = UUID(payload["t"]), UUID(payload["u"]), UUID(payload["s"])
    except (KeyError, ValueError, TypeError, AttributeError):
        raise Unauthorized("Invalid token") from None
    _require_active_tenant(tenant_id)
    with tenant_session(tenant_id) as s:
        row = s.execute(text(
            "select s.channel, s.device_id, s.revoked_at, s.expires_at, u.status from kernel.user_session s "
            "join kernel.app_user u on u.id = s.user_id where s.id = :i and s.user_id = :u"),
            {"i": str(session_id), "u": str(user_id)}).first()
        if row is None or row.revoked_at is not None or row.expires_at < _now() or row.status != "active":
            raise Unauthorized("Session is no longer valid; sign in again")
        assignments = load_assignments(s, user_id)
    return RequestContext(tenant_id=tenant_id, user_id=user_id, channel=row.channel, session_id=session_id,
                          assignments=assignments, device_id=row.device_id,
                          mfa_setup_required=bool(payload.get("m")))


def _support_context(payload: dict[str, object]) -> RequestContext:
    """The context of a platform staff member's support session. Everything is checked on every request: the session,
    the business's grant (revoked? expired?) and the operator."""
    try:
        tenant_id, session_id, operator_id = UUID(str(payload["t"])), UUID(str(payload["sp"])), UUID(str(payload["o"]))
    except (KeyError, ValueError, TypeError):
        raise Unauthorized("Invalid token") from None
    _require_active_tenant(tenant_id)
    return support.load_session_context(tenant_id, session_id, operator_id)


def context_from_api_key(key: str) -> RequestContext:
    """Verify an API key; its scopes become a tenant-wide set of permissions."""
    tenant_id, _ = _split_secret(key, "zk")
    _require_active_tenant(tenant_id)
    with tenant_session(tenant_id) as s:
        row = s.execute(text(
            "select id, scopes, expires_at, revoked_at from kernel.api_key where key_hash = :h"),
            {"h": hash_secret(key)}).first()
    if row is None or row.revoked_at is not None or (row.expires_at and row.expires_at < _now()):
        raise Unauthorized("API key is not valid")
    grant = Assignment(role_id=None, role_name=f"api_key:{row.id}", scope="tenant", company_id=None,
                       branch_id=None, permissions=frozenset(row.scopes))
    return RequestContext(tenant_id=tenant_id, channel="api", assignments=(grant,))
