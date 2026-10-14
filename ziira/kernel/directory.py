"""The login directory: which businesses a login (an email or a phone number) belongs to.

Every business has its own database, so before a password can be checked the platform has to know which database(s) to
look in. The master database keeps a keyed hash of each user's email and phone with the tenant it belongs to; signing in
looks the typed login up here and then checks the password inside those businesses' own databases.

It is a pointer, not a source of truth: an entry that has gone stale (an email changed, a user disabled) only makes
sign-in look in a database where the check then fails. Entries are added when a user is created; `ziira index-logins`
rebuilds them from the businesses' own records.
"""

import hashlib
import hmac
import logging
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.config import get_settings
from ziira.kernel.db import master_session

log = logging.getLogger("ziira.directory")


def normalise(login: str) -> str:
    """The form a login is looked up in: trimmed and lower-case (an email's case never matters)."""
    return login.strip().lower()


def hash_login(login: str) -> str:
    """A keyed hash of the login (the platform's secret key), so the directory holds no raw emails or numbers."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, b"login:" + normalise(login).encode(), hashlib.sha256).hexdigest()


def register(tenant_id: UUID, *logins: str | None) -> None:
    """Record that these logins belong to a business. Never raises: a failure is logged and `index-logins` repairs
    it."""
    found = {hash_login(x) for x in logins if x and x.strip()}
    if not found:
        return
    try:
        with master_session() as s:
            for value in found:
                s.execute(text("insert into master.login_directory (tenant_id, identifier_hash) "
                               "values (:t, :h) on conflict do nothing"), {"t": str(tenant_id), "h": value})
    except Exception:
        log.exception("Could not register logins for tenant %s", tenant_id)


def rebuild(tenant_ids: list[UUID] | None = None) -> int:
    """Re-read every business's users and register their logins (for businesses made before the directory existed, or
    after a failure). Returns how many logins were registered."""
    from ziira.kernel.context import system_context
    from ziira.kernel.db import tenant_session

    with master_session() as s:
        known = [r[0] for r in s.execute(text("select id from master.tenant where status = 'active'"))]
    count = 0
    for tenant_id in tenant_ids or known:
        system_context(tenant_id)
        with tenant_session(tenant_id) as s:
            rows = s.execute(text("select email, phone from kernel.app_user where status <> 'disabled'")).all()
        for email, phone in rows:
            register(tenant_id, email, phone)
            count += (1 if email else 0) + (1 if phone else 0)
    return count


def tenants_for(login: str) -> list[UUID]:
    """The active businesses that have a user with this login."""
    with master_session() as s:
        rows = s.execute(text(
            "select d.tenant_id from master.login_directory d join master.tenant t on t.id = d.tenant_id "
            "where d.identifier_hash = :h and t.status = 'active' order by t.code"), {"h": hash_login(login)})
        return [r[0] for r in rows]
