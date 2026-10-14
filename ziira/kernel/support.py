"""Support access: platform staff working in a business's data, only with the business's consent.

- A business user with `support.grant` creates a **grant**: why, read-only or full, for how long (at most 7 days).
  They can revoke it at any moment; that ends every support session under it at once.
- Platform staff (operators, see operators.py) are not users of the business. With an active grant an operator opens a
  **support session**; its token is checked against the grant on every request, so expiry and revocation apply to a
  session that is already open.
- A session never has more than the grant allows: `read` = only GET requests and only view permissions; `full` = every
  permission except the ones below. Neither can change passwords, second factors, roles, API keys, other sessions
  or support grants, or sign anyone out.
- Everything a session does is written to the business's own audit log (channel `support`, with the operator named) and
  to the platform's `master.support_access_log`.
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ziira.kernel import audit
from ziira.kernel.context import Assignment, RequestContext, get_context, set_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import Forbidden, NotFound, Unauthorized, ValidationFailed

log = logging.getLogger("ziira.support")

LEVELS = ("read", "full")
MAX_GRANT_HOURS = 24 * 7
DEFAULT_GRANT_HOURS = 24
SESSION_MINUTES = 60                  # one support session; the operator opens another while the grant lasts
PERMISSION = "support.grant"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Never held in a support session, whatever the grant says: they would let staff keep access or hide their tracks.
FORBIDDEN_PERMISSIONS = frozenset({"users.manage", "roles.manage", "api_keys.manage", "support.grant",
                                   "privacy.manage", "units.manage"})
# Read access is the view permissions, except people's pay.
READ_EXCLUDED = frozenset({"payroll.view"})
# Changes no support session may make, even a full one (a read-only session cannot make any change at all).
_FORBIDDEN_CHANGES = re.compile(
    r"^/api/v1/(auth/(password|mfa|sessions|sign-out|refresh)|users/[^/]+/(password|roles|mfa|status)|roles|"
    r"api-keys|support|settings/security|users$)")


def _now() -> datetime:
    return datetime.now(UTC)


def enforce(ctx: RequestContext, method: str, path: str) -> None:
    """Refuse a request a support session may not make (read-only grant; the changes nobody on support may make)."""
    if ctx.support_session_id is None:
        return
    if method.upper() not in SAFE_METHODS:
        if ctx.support_level != "full":
            raise Forbidden("This support access is read-only")
        if _FORBIDDEN_CHANGES.match(path):
            raise Forbidden("Support access cannot change passwords, two-step verification, roles, API keys, "
                            "sign-ins or support access")


def support_assignment(s: Session, level: str) -> Assignment:
    """What a support session may do: the view permissions (read) or everything but the forbidden ones (full)."""
    codes = set(s.execute(text("select code from kernel.permission")).scalars())
    if level == "read":
        allowed = {c for c in codes if c.endswith(".view") and c not in READ_EXCLUDED}
    else:
        allowed = codes - FORBIDDEN_PERMISSIONS
    return Assignment(role_id=None, role_name="Support", scope="tenant", company_id=None, branch_id=None,
                      permissions=frozenset(allowed))


# --------------------------------------------------------------------------- grants (the business's side)
_GRANT_COLUMNS = ("g.id, g.created_at, g.created_by, u.full_name as created_by_name, g.reason, g.level, g.note, "
                  "g.expires_at, g.revoked_at")


def _status(row: Any) -> str:
    if row.revoked_at is not None:
        return "revoked"
    return "expired" if row.expires_at <= _now() else "active"


def create_grant(s: Session, *, reason: str, level: str, hours: int = DEFAULT_GRANT_HOURS,
                 note: str | None = None) -> dict[str, Any]:
    """Let platform staff in. Returns the grant."""
    ctx = get_context()
    ctx.require(PERMISSION)
    if level not in LEVELS:
        raise ValidationFailed(f"Level must be one of: {', '.join(LEVELS)}")
    if not 1 <= hours <= MAX_GRANT_HOURS:
        raise ValidationFailed(f"Support access lasts between 1 hour and {MAX_GRANT_HOURS} hours")
    if not reason.strip():
        raise ValidationFailed("Say why support needs access")
    expires = _now() + timedelta(hours=hours)
    grant_id: UUID = s.execute(text(
        "insert into kernel.support_grant (tenant_id, created_by, reason, level, note, expires_at) "
        "values (kernel.current_tenant(), :u, :r, :l, :n, :e) returning id"),
        {"u": str(ctx.user_id) if ctx.user_id else None, "r": reason.strip(), "l": level,
         "n": (note or "").strip() or None, "e": expires}).scalar_one()
    audit.record(s, "support_grant_created", "kernel.support_grant", grant_id,
                 {"reason": reason.strip(), "level": level, "expires_at": expires})
    return get_grant(s, grant_id)


def get_grant(s: Session, grant_id: UUID) -> dict[str, Any]:
    row = s.execute(text(f"select {_GRANT_COLUMNS} from kernel.support_grant g "
                         "left join kernel.app_user u on u.id = g.created_by where g.id = :i"),
                    {"i": str(grant_id)}).first()
    if row is None:
        raise NotFound("Support access not found")
    return _grant_out(s, row)


def _grant_out(s: Session, row: Any) -> dict[str, Any]:
    sessions = [dict(r._mapping) for r in s.execute(text(
        "select ss.id, ss.operator_name, ss.started_at, ss.expires_at, ss.ended_at, "
        "  (select count(*) from kernel.audit_log a where a.entity_id = ss.id and a.action = 'support_request' "
        "   and a.tenant_id = kernel.current_tenant()) as requests "
        "from kernel.support_session ss where ss.grant_id = :g order by ss.started_at desc"), {"g": str(row.id)})]
    return {"id": row.id, "created_at": row.created_at, "created_by": row.created_by,
            "created_by_name": row.created_by_name, "reason": row.reason, "level": row.level, "note": row.note,
            "expires_at": row.expires_at, "revoked_at": row.revoked_at, "status": _status(row), "sessions": sessions}


def list_grants(s: Session, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Grants, newest first, with the sessions opened under each."""
    get_context().require(PERMISSION)
    rows = s.execute(text(f"select {_GRANT_COLUMNS} from kernel.support_grant g "
                          "left join kernel.app_user u on u.id = g.created_by "
                          "order by g.created_at desc limit :l offset :o"), {"l": limit, "o": offset}).all()
    return [_grant_out(s, r) for r in rows]


def revoke_grant(s: Session, grant_id: UUID) -> dict[str, Any]:
    """Take access back now: the grant stops working and every session under it ends with the next request."""
    ctx = get_context()
    ctx.require(PERMISSION)
    row = s.execute(text("select id, revoked_at from kernel.support_grant where id = :i for update"),
                    {"i": str(grant_id)}).first()
    if row is None:
        raise NotFound("Support access not found")
    if row.revoked_at is None:
        s.execute(text("update kernel.support_grant set revoked_at = now(), revoked_by = :u where id = :i"),
                  {"u": str(ctx.user_id) if ctx.user_id else None, "i": str(grant_id)})
        ended = s.execute(text(
            "update kernel.support_session set ended_at = now() where grant_id = :g and ended_at is null "
            "returning id, operator_id, operator_name"), {"g": str(grant_id)}).all()
        audit.record(s, "support_grant_revoked", "kernel.support_grant", grant_id, {"sessions_ended": len(ended)})
        for e in ended:
            log_event("revoked", ctx.tenant_id, operator_id=e.operator_id, operator_name=e.operator_name,
                      grant_id=grant_id, support_session_id=e.id)
    return get_grant(s, grant_id)


def access_log(s: Session, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """What platform staff did in this business, from its own audit log (so the business never depends on us)."""
    get_context().require(PERMISSION)
    rows = s.execute(text(
        "select id, occurred_at, action, entity_type, entity_id, changes from kernel.audit_log "
        "where channel = 'support' and tenant_id = kernel.current_tenant() order by id desc limit :l offset :o"),
        {"l": limit, "o": offset})
    out = []
    for r in rows:
        changes = dict(r.changes or {})
        out.append({"id": r.id, "occurred_at": r.occurred_at, "action": r.action, "entity_type": r.entity_type,
                    "entity_id": r.entity_id, "operator": changes.pop("support_operator", None),
                    "operator_id": changes.pop("support_operator_id", None), "detail": changes})
    return out


def active_support_session(s: Session) -> dict[str, Any] | None:
    """The newest support session still open in this business, if any."""
    row = s.execute(text(
        "select ss.operator_name as operator, ss.level, least(ss.expires_at, g.expires_at) as until "
        "from kernel.support_session ss join kernel.support_grant g on g.id = ss.grant_id "
        "where ss.ended_at is null and g.revoked_at is null and ss.expires_at > now() and g.expires_at > now() "
        "order by ss.started_at desc limit 1")).first()
    return dict(row._mapping) if row else None


# --------------------------------------------------------------------------- the staff side's view of a session
def load_session_context(tenant_id: UUID, session_id: UUID, operator_id: UUID) -> RequestContext:
    """The context of a support session, checked now: the session is open, its grant is not revoked or expired and
    the operator is still active (else Unauthorized)."""
    ended = Unauthorized("Support access has ended")
    with tenant_session(tenant_id) as s:
        row = s.execute(text(
            "select ss.operator_id, ss.operator_name, ss.level, ss.grant_id, ss.ended_at, ss.expires_at, "
            "g.expires_at as grant_expires, g.revoked_at from kernel.support_session ss "
            "join kernel.support_grant g on g.id = ss.grant_id where ss.id = :i"), {"i": str(session_id)}).first()
        if row is None or row.operator_id != operator_id:
            raise Unauthorized("Invalid token")
        now = _now()
        until = min(row.expires_at, row.grant_expires)
        if row.ended_at is not None or row.revoked_at is not None or until <= now:
            raise ended
        assignment = support_assignment(s, row.level)
    with master_session() as m:
        status = m.execute(text("select status from master.operator where id = :i"), {"i": str(operator_id)}).scalar()
    if status != "active":
        raise ended
    return RequestContext(tenant_id=tenant_id, channel="support", session_id=None, assignments=(assignment,),
                          support_operator_id=operator_id, support_operator_name=row.operator_name,
                          support_grant_id=row.grant_id, support_session_id=session_id, support_level=row.level,
                          support_until=until)


# --------------------------------------------------------------------------- the platform's log
def log_event(event: str, tenant_id: UUID, *, operator_id: UUID, operator_name: str, grant_id: UUID | None = None,
              support_session_id: UUID | None = None, method: str | None = None, route: str | None = None,
              status: int | None = None, detail: dict[str, Any] | None = None) -> None:
    """Add one line to the platform's support access log (master database; the application never edits or deletes)."""
    with master_session() as m:
        m.execute(text(
            "insert into master.support_access_log (event, operator_id, operator_name, tenant_id, grant_id, "
            "support_session_id, method, route, status, detail) values (:e, :o, :n, :t, :g, :s, :m, :r, :st, "
            "cast(:d as jsonb))"),
            {"e": event, "o": str(operator_id), "n": operator_name, "t": str(tenant_id),
             "g": str(grant_id) if grant_id else None, "s": str(support_session_id) if support_session_id else None,
             "m": method, "r": route, "st": status, "d": json.dumps(detail, default=str) if detail else None})


def log_request(ctx: RequestContext, method: str, route: str, status: int) -> None:
    """Record one request made in a support session: in the platform's log and in the business's own audit log."""
    assert ctx.support_operator_id is not None and ctx.support_session_id is not None
    log_event("refused" if status in (401, 403, 429) else "request", ctx.tenant_id,
              operator_id=ctx.support_operator_id, operator_name=ctx.support_operator_name or "",
              grant_id=ctx.support_grant_id, support_session_id=ctx.support_session_id, method=method, route=route,
              status=status)
    set_context(ctx)
    with tenant_session(ctx.tenant_id) as s:
        audit.record(s, "support_request", "kernel.support_session", ctx.support_session_id,
                     {"method": method, "route": route, "status": status})
