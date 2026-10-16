"""Platform staff ("operators"): who they are, how they sign in, and how they open a support session.

Operators are not users of any business. They exist only in the master database, the first one is created from the
command line (`ziira operator create`), and the rest by a superadmin in the Super Admin. How they sign in is a setting
(`ZIIRA_OPERATOR_MFA`, docs/security.md): "totp" is password, then a code from an authenticator app; "off" (the
default) is email and password alone, with shorter sessions, an idle limit, a stronger password rule, a re-entry of the
password before changes and a line in the operator trail for every sign-in. Their tokens are a different kind from a
business user's (`k = "op"`), so neither can be used where the other is expected.

Opening a support session needs an active grant from the business (see support.py). The session's token is an
ordinary business access token whose claims name the support session; the grant is checked again on every request.
"""

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import audit, mfa, notifications, passwords, platform_mail, support, throttle
from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import ChallengeExpired, Forbidden, NotFound, Unauthorized, Unavailable, ValidationFailed
from ziira.kernel.platform import permissions
from ziira.kernel.security import decrypt, encrypt, hash_password, read_token, sign_token, verify_password

log = logging.getLogger("ziira.operators")

OPERATOR_TOKEN_MINUTES = 30                 # a sign-in with a second factor (ZIIRA_OPERATOR_MFA=totp)
CHALLENGE_MINUTES = 5
MIN_PASSWORD_LENGTH = 12                    # operators hold more power than any business user: a longer minimum
TOUCH_SECONDS = 30                          # last_seen_at is written at most this often per sign-in


@dataclass(frozen=True)
class Operator:
    """A signed-in member of platform staff."""

    id: UUID
    name: str
    email: str
    session_id: UUID
    mfa_verified_at: datetime
    role: str = "superadmin"
    must_change_password: bool = False

    @property
    def permissions(self) -> frozenset[str]:
        return permissions.permissions_of(self.role)


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- managing operators (command line)
def check_password(password: str, email: str) -> None:
    """The operator password rule: at least 12 characters, not a common password, not the email."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(f"An operator password must be at least {MIN_PASSWORD_LENGTH} characters")
    passwords.check(password, login=email)


def temporary_password() -> str:
    """A random one-time password for a new or reset account (about 120 bits)."""
    return secrets.token_urlsafe(15)


def create_operator(name: str, email: str, password: str, role: str = "superadmin", *,
                    must_change_password: bool = False) -> tuple[UUID, str, str]:
    """Add a member of staff. Returns the id, the second-factor secret and its `otpauth://` address; both are shown
    once and the secret is stored encrypted. With ZIIRA_OPERATOR_MFA=off there is no second factor, so both are empty.
    The command line makes the first superadmin; superadmins make the rest in the Super Admin (with
    `must_change_password`, so the person chooses their own password at the first sign-in)."""
    clean = email.strip().lower()
    if not name.strip() or "@" not in clean:
        raise ValidationFailed("An operator needs a name and an email")
    if role not in permissions.ROLES:
        raise ValidationFailed(f"Role is one of: {', '.join(permissions.ROLES)}")
    check_password(password, clean)
    secret = "" if get_settings().operator_password_only() else mfa.new_secret()
    with master_session() as m:
        if m.execute(text("select 1 from master.operator where lower(email) = :e"), {"e": clean}).first():
            raise ValidationFailed("There is already an operator with this email")
        operator_id: UUID = m.execute(text(
            "insert into master.operator (name, email, password_hash, mfa_secret_enc, role, must_change_password) "
            "values (:n, :e, :h, :s, :r, :c) returning id"),
            {"n": name.strip(), "e": clean, "h": hash_password(password), "s": encrypt(secret) if secret else "",
             "r": role, "c": must_change_password}).scalar_one()
    return operator_id, secret, mfa.otpauth_uri(secret, clean) if secret else ""


def list_operators() -> list[dict[str, Any]]:
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text(
            "select id, name, email, status, role, created_at, last_sign_in_at from master.operator order by name"))]


def set_status(email: str, status: str) -> None:
    """Disable or re-enable an operator. Disabling ends their sign-ins at once, and their support sessions stop
    working with the next request."""
    if status not in ("active", "disabled"):
        raise ValidationFailed("Status must be active or disabled")
    with master_session() as m:
        if status == "disabled":
            _keep_one_superadmin(m, email.strip().lower())
        found = m.execute(text("update master.operator set status = :s where lower(email) = :e returning id"),
                          {"s": status, "e": email.strip().lower()}).first()
        if found is None:
            raise NotFound("No operator with this email")
        if status == "disabled":
            m.execute(text("update master.operator_session set revoked_at = now() "
                           "where operator_id = :o and revoked_at is null"), {"o": str(found.id)})


def _keep_one_superadmin(m: Any, email: str) -> None:
    """Refuse to disable or demote the last active superadmin: nobody could manage operators afterwards."""
    left = m.execute(text("select count(*) from master.operator where role = 'superadmin' and status = 'active' "
                          "and lower(email) <> :e"), {"e": email}).scalar_one()
    target = m.execute(text("select role, status from master.operator where lower(email) = :e"), {"e": email}).first()
    if target is not None and target.role == "superadmin" and target.status == "active" and left == 0:
        raise ValidationFailed("This is the last active superadmin: make another one first")


def set_role(email: str, role: str) -> None:
    """Change an operator's role (their sign-ins end, so the new role applies at once)."""
    if role not in permissions.ROLES:
        raise ValidationFailed(f"Role is one of: {', '.join(permissions.ROLES)}")
    with master_session() as m:
        if role != "superadmin":
            _keep_one_superadmin(m, email.strip().lower())
        found = m.execute(text("update master.operator set role = :r where lower(email) = :e returning id"),
                          {"r": role, "e": email.strip().lower()}).first()
        if found is None:
            raise NotFound("No operator with this email")
        m.execute(text("update master.operator_session set revoked_at = now() where operator_id = :o "
                       "and revoked_at is null"), {"o": str(found.id)})


def reset_mfa(email: str) -> tuple[str, str]:
    """A new second-factor secret for an operator who lost their device (also ends their sign-ins)."""
    secret = mfa.new_secret()
    with master_session() as m:
        found = m.execute(text(
            "update master.operator set mfa_secret_enc = :s, mfa_last_counter = 0 where lower(email) = :e "
            "returning id"),
            {"s": encrypt(secret), "e": email.strip().lower()}).first()
        if found is None:
            raise NotFound("No operator with this email")
        m.execute(text("update master.operator_session set revoked_at = now() where operator_id = :o "
                       "and revoked_at is null"), {"o": str(found.id)})
    return secret, mfa.otpauth_uri(secret, email.strip().lower())


def reset_password(email: str, *, password: str | None = None, actor: Operator | None = None) -> str:
    """Give an operator a new password and end their sign-ins. Without `password` it is a random temporary one that
    must be changed at the next sign-in (shown once to whoever asked); with one, it is the one chosen (command line)."""
    clean = email.strip().lower()
    chosen = password or temporary_password()
    check_password(chosen, clean)
    with master_session() as m:
        found = m.execute(text(
            "update master.operator set password_hash = :h, must_change_password = :c, password_changed_at = now() "
            "where lower(email) = :e returning id"),
            {"h": hash_password(chosen), "c": password is None, "e": clean}).first()
        if found is None:
            raise NotFound("No operator with this email")
        m.execute(text("update master.operator_session set revoked_at = now() where operator_id = :o "
                       "and revoked_at is null"), {"o": str(found.id)})
    audit_sign_in("auth.password_reset", actor.id if actor else None, actor.name if actor else "(command line)",
                  target=clean, ip_address=None)
    return chosen


def change_password(operator: Operator, current: str, new: str, *, ip_address: str | None) -> None:
    """The operator's own change: needs the current password (wrong tries are counted), applies the operator password
    rule, ends every other sign-in of theirs and lifts the "must change" flag."""
    counters = throttle.action_counters("operator-password", str(operator.id), ip_address, per_subject=5, per_ip=30)
    throttle.guard(counters)
    with master_session() as m:
        row = m.execute(text("select password_hash from master.operator where id = :i"),
                        {"i": str(operator.id)}).first()
    if row is None or not verify_password(current, row.password_hash):
        throttle.failed(counters)
        audit_sign_in("auth.password_change", operator.id, operator.name, outcome="refused",
                      detail={"why": "current password wrong"}, ip_address=ip_address)
        raise Unauthorized("Your current password is not right")
    throttle.succeeded(counters[:1])
    if new == current:
        raise ValidationFailed("Choose a password different from the current one")
    check_password(new, operator.email)
    with master_session() as m:
        m.execute(text("update master.operator set password_hash = :h, must_change_password = false, "
                       "password_changed_at = now() where id = :i"),
                  {"h": hash_password(new), "i": str(operator.id)})
        m.execute(text("update master.operator_session set revoked_at = now() where operator_id = :o "
                       "and id <> :s and revoked_at is null"), {"o": str(operator.id), "s": str(operator.session_id)})
    audit_sign_in("auth.password_change", operator.id, operator.name, ip_address=ip_address)


def sign_out_everywhere(operator: Operator, *, ip_address: str | None = None) -> None:
    """End every sign-in of this operator, this one included."""
    with master_session() as m:
        m.execute(text("update master.operator_session set revoked_at = now() where operator_id = :o "
                       "and revoked_at is null"), {"o": str(operator.id)})
    audit_sign_in("auth.sign_out_everywhere", operator.id, operator.name, ip_address=ip_address)


# --------------------------------------------------------------------------- the trail of sign-ins
def audit_sign_in(action: str, operator_id: UUID | None, name: str, *, outcome: str = "ok", target: str | None = None,
                  detail: dict[str, Any] | None = None, ip_address: str | None) -> None:
    """One line in the operator trail (append-only in the database) for a sign-in, a confirmation or a password
    change: who, from which address, whether it worked. Never the password or a code."""
    with master_session() as m:
        m.execute(text(
            "insert into master.operator_action_log (operator_id, operator_name, action, target, outcome, detail, "
            "ip_address) values (:o, :n, :a, :t, :out, cast(:d as jsonb), :ip)"),
            {"o": str(operator_id) if operator_id else None, "n": name, "a": action, "t": target, "out": outcome,
             "d": json.dumps(detail) if detail else None, "ip": ip_address})


def _attempted_login(email: str) -> str:
    """What to write for a sign-in by someone who is not an operator: the email if it looks like one (so staff can see
    who is being targeted), never anything else (a password typed into the wrong box)."""
    clean = email.strip().lower()
    return clean[:120] if "@" in clean and " " not in clean else "(not an email)"


def _seen_from(operator_id: UUID, ip_address: str | None) -> bool:
    """True if this operator has signed in successfully from this address before."""
    if ip_address is None:
        return True
    with master_session() as m:
        return m.execute(text(
            "select 1 from master.operator_action_log where operator_id = :o and action = 'auth.sign_in' "
            "and outcome = 'ok' and ip_address = :ip limit 1"), {"o": str(operator_id), "ip": ip_address}).first() \
            is not None


def tell_new_address(email: str, name: str, ip_address: str | None) -> None:
    """Email the operator that a sign-in came from an address not seen before (ZIIRA_OPERATOR_SIGNIN_EMAILS). A mail
    that cannot be sent is logged, never an error for the person signing in."""
    try:
        platform_mail.send(
            email, "New sign-in to the Ziira Super Admin",
            f"Hello {name},\n\nYour account signed in to the Ziira Super Admin from an address it has not used "
            f"before: {ip_address or 'unknown'}, at {_now():%Y-%m-%d %H:%M} UTC.\n\nIf this was you, nothing more "
            "is needed. If it was not, change your password now and ask another superadmin to reset it.")
    except Unavailable:
        log.warning("Could not send the new-address sign-in email", exc_info=True)


# --------------------------------------------------------------------------- signing in
@dataclass(frozen=True)
class SignInResult:
    """Either a challenge (a second factor is still needed) or a finished sign-in."""

    challenge: str | None = None
    access_token: str | None = None
    expires_in: int | None = None
    must_change_password: bool = False
    new_address: bool = False
    name: str = ""


def lifetime_minutes() -> int:
    """How long an operator sign-in lasts: a short half hour with a second factor, the (longer) session setting with
    a password alone, where the idle limit also applies."""
    settings = get_settings()
    return max(1, settings.operator_session_hours * 60) if settings.operator_password_only() else OPERATOR_TOKEN_MINUTES


def sign_in(email: str, password: str, *, ip_address: str | None) -> SignInResult:
    """Step one: the password. With a second factor the result is a short-lived challenge to send back with a code
    (there is no way in without it); with a password alone it is the signed-in session. The same message answers a
    wrong email, a wrong password and a disabled account. Wrong tries are counted and then locked, like business
    sign-ins, and every try is a line in the operator trail."""
    clean = email.strip().lower()
    counters = throttle.action_counters("operator", clean, ip_address, per_subject=5, per_ip=30)
    throttle.guard(counters)
    with master_session() as m:
        row = m.execute(text("select id, name, password_hash, status, mfa_secret_enc, must_change_password "
                             "from master.operator where lower(email) = :e"), {"e": clean}).first()
    if not verify_password(password, row.password_hash if row else None) or row is None or row.status != "active":
        throttle.failed(counters)
        why = "unknown login" if row is None else "disabled" if row.status != "active" else "wrong password"
        audit_sign_in("auth.sign_in", row.id if row else None, row.name if row else "(unknown)", outcome="refused",
                      target=None if row else _attempted_login(clean), detail={"why": why}, ip_address=ip_address)
        raise Unauthorized("Wrong email or password")
    throttle.succeeded(counters[:1])
    if not get_settings().operator_password_only():
        if not row.mfa_secret_enc:
            audit_sign_in("auth.sign_in", row.id, row.name, outcome="refused",
                          detail={"why": "no second factor set up"}, ip_address=ip_address)
            raise Unauthorized("A second factor is required but not set up for this account: ask a superadmin to run "
                               "`ziira operator reset-mfa`")
        return SignInResult(challenge=sign_token({"k": "opmfa", "o": str(row.id)}, CHALLENGE_MINUTES),
                            must_change_password=row.must_change_password)
    new_address = not _seen_from(row.id, ip_address)
    token, seconds = _open_session(row.id, ip_address)
    audit_sign_in("auth.sign_in", row.id, row.name, detail={"second_factor": "off", "new_address": new_address},
                  ip_address=ip_address)
    return SignInResult(access_token=token, expires_in=seconds, must_change_password=row.must_change_password,
                        new_address=new_address, name=row.name)


def _open_session(operator_id: UUID, ip_address: str | None) -> tuple[str, int]:
    """Record a finished sign-in and return its token and lifetime in seconds."""
    minutes = lifetime_minutes()
    with master_session() as m:
        m.execute(text("update master.operator set last_sign_in_at = now() where id = :i"), {"i": str(operator_id)})
        session_id: UUID = m.execute(text(
            "insert into master.operator_session (operator_id, expires_at, ip_address) values (:o, :e, :ip) "
            "returning id"), {"o": str(operator_id), "e": _now() + timedelta(minutes=minutes),
                              "ip": ip_address}).scalar_one()
    return sign_token({"k": "op", "o": str(operator_id), "os": str(session_id)}, minutes), minutes * 60


def verify_mfa(challenge: str, code: str, *, ip_address: str | None) -> tuple[str, int]:
    """Step two: the code from the authenticator app. Returns the operator token and its lifetime in seconds."""
    try:
        payload = read_token(challenge)
    except Unauthorized as error:
        raise ChallengeExpired("This sign-in took too long or is not valid: enter your password again") from error
    if payload.get("k") != "opmfa":
        raise ChallengeExpired("That is not a sign-in challenge: enter your password again")
    operator_id = UUID(payload["o"])
    counters = throttle.action_counters("operator-mfa", str(operator_id), ip_address, per_subject=5, per_ip=30)
    throttle.guard(counters)
    name = "(unknown)"
    with master_session() as m:
        row = m.execute(text("select name, mfa_secret_enc, mfa_last_counter, status from master.operator "
                             "where id = :i for update"), {"i": str(operator_id)}).first()
        name = row.name if row is not None else name
        counter = mfa.check_code(decrypt(row.mfa_secret_enc), code, row.mfa_last_counter) \
            if row is not None and row.status == "active" and row.mfa_secret_enc else None
        if counter is not None:
            m.execute(text("update master.operator set mfa_last_counter = :c where id = :i"),
                      {"c": counter, "i": str(operator_id)})
    if counter is None:
        throttle.failed(counters)
        audit_sign_in("auth.sign_in", operator_id, name, outcome="refused", detail={"why": "wrong code"},
                      ip_address=ip_address)
        raise Unauthorized("That code is not right")
    throttle.succeeded(counters[:1])
    token, seconds = _open_session(operator_id, ip_address)
    audit_sign_in("auth.sign_in", operator_id, name, detail={"second_factor": "totp"}, ip_address=ip_address)
    return token, seconds


def operator_from_token(token: str) -> Operator:
    """Check an operator token and that the operator and their sign-in are still good: not revoked, not past its end,
    and (with a password alone) not idle for longer than ZIIRA_OPERATOR_IDLE_MINUTES."""
    payload = read_token(token)
    if payload.get("k") != "op":
        raise Unauthorized("This is not an operator token")
    try:
        operator_id, session_id = UUID(payload["o"]), UUID(payload["os"])
    except (KeyError, ValueError, TypeError):
        raise Unauthorized("Invalid token") from None
    settings = get_settings()
    idle = timedelta(minutes=settings.operator_idle_minutes)
    with master_session() as m:
        row = m.execute(text(
            "select o.name, o.email, o.status, o.role, o.must_change_password, s.revoked_at, s.expires_at, "
            "s.mfa_verified_at, s.last_seen_at from master.operator o "
            "join master.operator_session s on s.operator_id = o.id where o.id = :o and s.id = :s"),
            {"o": str(operator_id), "s": str(session_id)}).first()
        if row is None or row.status != "active" or row.revoked_at is not None or row.expires_at <= _now():
            raise Unauthorized("Session is no longer valid; sign in again")
        if settings.operator_password_only():
            if _now() - row.last_seen_at > idle:
                m.execute(text("update master.operator_session set revoked_at = now() where id = :s"),
                          {"s": str(session_id)})
                m.commit()
                raise Unauthorized("You were signed out after a period of inactivity: sign in again")
            m.execute(text("update master.operator_session set last_seen_at = now() where id = :s "
                           "and last_seen_at < now() - make_interval(secs => :t)"),
                      {"s": str(session_id), "t": TOUCH_SECONDS})
    return Operator(id=operator_id, name=row.name, email=row.email, session_id=session_id,
                    mfa_verified_at=row.mfa_verified_at or datetime.fromtimestamp(0, UTC), role=row.role,
                    must_change_password=row.must_change_password)


def sign_out(operator: Operator, *, ip_address: str | None = None) -> None:
    with master_session() as m:
        m.execute(text("update master.operator_session set revoked_at = now() where id = :s"),
                  {"s": str(operator.session_id)})
    audit_sign_in("auth.sign_out", operator.id, operator.name, ip_address=ip_address)


# --------------------------------------------------------------------------- businesses and support sessions
def list_businesses() -> list[dict[str, str]]:
    """Code and name of every active business: never any data of theirs."""
    with master_session() as m:
        return [{"code": r.code, "name": r.name} for r in m.execute(text(
            "select code, name from master.tenant where status = 'active' order by name"))]


def open_support_session(operator: Operator, code: str, *, grant_id: UUID | None = None,
                         ip_address: str | None = None) -> dict[str, Any]:
    """Open a session in a business. Allowed only under an active grant of that business; the grant's creator is told by
    email, and the business sees a banner while it lasts. Returns the access token and what it allows."""
    from ziira.kernel.auth import tenant_by_code

    tenant_id = tenant_by_code(code)
    if tenant_id is None:
        raise NotFound("No such business")
    set_context(RequestContext(tenant_id=tenant_id, channel="support", ip_address=ip_address,
                               support_operator_id=operator.id, support_operator_name=operator.name))
    with tenant_session(tenant_id) as s:
        grant = s.execute(text(
            "select id, level, expires_at, created_by, reason from kernel.support_grant "
            "where revoked_at is null and expires_at > now() and (cast(:g as uuid) is null or id = :g) "
            "order by (level = 'full') desc, created_at desc limit 1"),
            {"g": str(grant_id) if grant_id else None}).first()
        if grant is None:
            support.log_event("refused", tenant_id, operator_id=operator.id, operator_name=operator.name,
                              detail={"why": "no active grant"})
            raise Forbidden("This business has not given support access, or it has ended")
        until = min(grant.expires_at, _now() + timedelta(minutes=support.SESSION_MINUTES))
        session_id: UUID = s.execute(text(
            "insert into kernel.support_session (tenant_id, grant_id, operator_id, operator_name, level, expires_at) "
            "values (kernel.current_tenant(), :g, :o, :n, :l, :e) returning id"),
            {"g": str(grant.id), "o": str(operator.id), "n": operator.name, "l": grant.level,
             "e": until}).scalar_one()
        audit.record(s, "support_session_started", "kernel.support_session", session_id,
                     {"grant_id": grant.id, "level": grant.level, "until": until})
        _tell_creator(s, grant, operator, until)
    support.log_event("start", tenant_id, operator_id=operator.id, operator_name=operator.name, grant_id=grant.id,
                      support_session_id=session_id, detail={"level": grant.level, "until": until.isoformat()})
    token = sign_token({"t": str(tenant_id), "k": "support", "sp": str(session_id), "o": str(operator.id)},
                       max(1, int((until - _now()).total_seconds() // 60) + 1))
    return {"access_token": token, "session_id": session_id, "tenant_id": tenant_id, "level": grant.level,
            "expires_at": until, "business": code}


def _tell_creator(s: Any, grant: Any, operator: Operator, until: datetime) -> None:
    """Queue an email to whoever gave the access, so they know it is being used."""
    person = s.execute(text("select email from kernel.app_user where id = :u"),
                       {"u": str(grant.created_by)}).first() if grant.created_by else None
    company = s.execute(text("select id from kernel.company order by created_at limit 1")).scalar()
    if person is None or not person.email or company is None:
        return
    try:
        notifications.queue(
            s, company_id=company, channel="email", recipient=person.email,
            subject="Ziira support has opened your business",
            body=(f"{operator.name} from Ziira support opened your business (access: "
                  f"{'read-only' if grant.level == 'read' else 'full'}) under the support access you gave for: "
                  f"{grant.reason}\n\nIt ends by {until:%Y-%m-%d %H:%M} UTC. You can see what was done, and end the "
                  "access at any time, under Settings, Support access."),
            ref_type="support_session", dedupe_key=f"support-start:{operator.id}:{until.isoformat()}")
    except ValidationFailed:
        log.warning("Could not queue the support access email", exc_info=True)


def list_sessions(operator: Operator, *, limit: int = 50) -> list[dict[str, Any]]:
    """This operator's support sessions, newest first, from the platform's access log."""
    with master_session() as m:
        rows = m.execute(text(
            "select l.support_session_id as id, l.tenant_id, t.code as business, l.occurred_at as started_at, "
            "  l.grant_id, l.detail->>'level' as level, (l.detail->>'until')::timestamptz as expires_at, "
            "  (select min(e.occurred_at) from master.support_access_log e where e.support_session_id = "
            "     l.support_session_id and e.event in ('end', 'revoked')) as ended_at, "
            "  (select count(*) from master.support_access_log r where r.support_session_id = l.support_session_id "
            "     and r.event in ('request', 'refused')) as requests "
            "from master.support_access_log l left join master.tenant t on t.id = l.tenant_id "
            "where l.event = 'start' and l.operator_id = :o order by l.occurred_at desc limit :n"),
            {"o": str(operator.id), "n": limit})
        return [dict(r._mapping) for r in rows]


def end_session(operator: Operator, session_id: UUID) -> None:
    """End one of this operator's own support sessions."""
    with master_session() as m:
        start = m.execute(text(
            "select tenant_id, grant_id from master.support_access_log where event = 'start' and "
            "support_session_id = :s and operator_id = :o"), {"s": str(session_id), "o": str(operator.id)}).first()
    if start is None:
        raise NotFound("No such support session")
    set_context(RequestContext(tenant_id=start.tenant_id, channel="support", support_operator_id=operator.id,
                               support_operator_name=operator.name))
    with tenant_session(start.tenant_id) as s:
        ended = s.execute(text("update kernel.support_session set ended_at = now() where id = :i and ended_at is null "
                               "returning id"), {"i": str(session_id)}).first()
        if ended:
            audit.record(s, "support_session_ended", "kernel.support_session", session_id, None)
    if ended:
        support.log_event("end", start.tenant_id, operator_id=operator.id, operator_name=operator.name,
                          grant_id=start.grant_id, support_session_id=session_id)
