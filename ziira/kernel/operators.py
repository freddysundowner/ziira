"""Platform staff ("operators"): who they are, how they sign in, and how they open a support session.

Operators are not users of any business. They exist only in the master database, are created only from the command
line (`ziira operator create`), and must use a second factor: sign-in is always password, then a code. Their tokens
are a different kind from a business user's (`k = "op"`), so neither can be used where the other is expected.

Opening a support session needs an active grant from the business (see support.py). The session's token is an
ordinary business access token whose claims name the support session; the grant is checked again on every request.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import audit, mfa, notifications, support, throttle
from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import ChallengeExpired, Forbidden, NotFound, Unauthorized, ValidationFailed
from ziira.kernel.security import decrypt, encrypt, hash_password, read_token, sign_token, verify_password

log = logging.getLogger("ziira.operators")

OPERATOR_TOKEN_MINUTES = 30
CHALLENGE_MINUTES = 5


@dataclass(frozen=True)
class Operator:
    """A signed-in member of platform staff."""

    id: UUID
    name: str
    email: str
    session_id: UUID


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- managing operators (command line)
def create_operator(name: str, email: str, password: str) -> tuple[UUID, str, str]:
    """Add a member of staff. Returns the id, the second-factor secret and its `otpauth://` address; both are shown
    once and the secret is stored encrypted."""
    clean = email.strip().lower()
    if not name.strip() or "@" not in clean:
        raise ValidationFailed("An operator needs a name and an email")
    secret = mfa.new_secret()
    with master_session() as m:
        if m.execute(text("select 1 from master.operator where lower(email) = :e"), {"e": clean}).first():
            raise ValidationFailed("There is already an operator with this email")
        operator_id: UUID = m.execute(text(
            "insert into master.operator (name, email, password_hash, mfa_secret_enc) values (:n, :e, :h, :s) "
            "returning id"), {"n": name.strip(), "e": clean, "h": hash_password(password),
                              "s": encrypt(secret)}).scalar_one()
    return operator_id, secret, mfa.otpauth_uri(secret, clean)


def list_operators() -> list[dict[str, Any]]:
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text(
            "select id, name, email, status, created_at, last_sign_in_at from master.operator order by name"))]


def set_status(email: str, status: str) -> None:
    """Disable or re-enable an operator. Disabling ends their sign-ins at once, and their support sessions stop
    working with the next request."""
    if status not in ("active", "disabled"):
        raise ValidationFailed("Status must be active or disabled")
    with master_session() as m:
        found = m.execute(text("update master.operator set status = :s where lower(email) = :e returning id"),
                          {"s": status, "e": email.strip().lower()}).first()
        if found is None:
            raise NotFound("No operator with this email")
        if status == "disabled":
            m.execute(text("update master.operator_session set revoked_at = now() "
                           "where operator_id = :o and revoked_at is null"), {"o": str(found.id)})


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


# --------------------------------------------------------------------------- signing in
def sign_in(email: str, password: str, *, ip_address: str | None) -> str:
    """Step one: the password. Returns a short-lived challenge to send back with a code (there is no way in without
    the second factor). Wrong tries are counted and then locked, like business sign-ins."""
    counters = throttle.action_counters("operator", email.strip().lower(), ip_address, per_subject=5, per_ip=30)
    throttle.guard(counters)
    with master_session() as m:
        row = m.execute(text("select id, password_hash, status from master.operator where lower(email) = :e"),
                        {"e": email.strip().lower()}).first()
    if not verify_password(password, row.password_hash if row else None) or row is None or row.status != "active":
        throttle.failed(counters)
        raise Unauthorized("Wrong email or password")
    throttle.succeeded(counters[:1])
    return sign_token({"k": "opmfa", "o": str(row.id)}, CHALLENGE_MINUTES)


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
    with master_session() as m:
        row = m.execute(text("select mfa_secret_enc, mfa_last_counter, status from master.operator where id = :i "
                             "for update"), {"i": str(operator_id)}).first()
        counter = mfa.check_code(decrypt(row.mfa_secret_enc), code, row.mfa_last_counter) \
            if row is not None and row.status == "active" else None
        if counter is None:
            failed = True
        else:
            failed = False
            m.execute(text("update master.operator set mfa_last_counter = :c, last_sign_in_at = now() where id = :i"),
                      {"c": counter, "i": str(operator_id)})
            session_id: UUID = m.execute(text(
                "insert into master.operator_session (operator_id, expires_at, ip_address) values (:o, :e, :ip) "
                "returning id"), {"o": str(operator_id), "e": _now() + timedelta(minutes=OPERATOR_TOKEN_MINUTES),
                                  "ip": ip_address}).scalar_one()
    if failed:
        throttle.failed(counters)
        raise Unauthorized("That code is not right")
    throttle.succeeded(counters[:1])
    return (sign_token({"k": "op", "o": str(operator_id), "os": str(session_id)}, OPERATOR_TOKEN_MINUTES),
            OPERATOR_TOKEN_MINUTES * 60)


def operator_from_token(token: str) -> Operator:
    """Check an operator token and that the operator and their sign-in are still good."""
    payload = read_token(token)
    if payload.get("k") != "op":
        raise Unauthorized("This is not an operator token")
    try:
        operator_id, session_id = UUID(payload["o"]), UUID(payload["os"])
    except (KeyError, ValueError, TypeError):
        raise Unauthorized("Invalid token") from None
    with master_session() as m:
        row = m.execute(text(
            "select o.name, o.email, o.status, s.revoked_at, s.expires_at from master.operator o "
            "join master.operator_session s on s.operator_id = o.id where o.id = :o and s.id = :s"),
            {"o": str(operator_id), "s": str(session_id)}).first()
    if row is None or row.status != "active" or row.revoked_at is not None or row.expires_at <= _now():
        raise Unauthorized("Session is no longer valid; sign in again")
    return Operator(id=operator_id, name=row.name, email=row.email, session_id=session_id)


def sign_out(operator: Operator) -> None:
    with master_session() as m:
        m.execute(text("update master.operator_session set revoked_at = now() where id = :s"),
                  {"s": str(operator.session_id)})


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
