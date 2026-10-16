"""Forgotten passwords: an emailed one-use link to choose a new one.

- `request` never says whether the login exists (the reply is always the same) and is rate limited per login and per
  address. For every business that has the login, a link is emailed through the platform's email provider.
- The link holds a random secret; only its hash is stored, it works once and for a couple of hours.
- Using it sets the new password, signs the person out everywhere, and clears their sign-in lock. A second factor, if
  the person uses one, is NOT bypassed: the next sign-in still asks for the code (an administrator resets a lost
  device).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import audit, directory, platform_mail, throttle, users
from ziira.kernel.config import get_settings
from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import Unauthorized, Unavailable
from ziira.kernel.platform import behaviour
from ziira.kernel.security import hash_secret, new_secret

log = logging.getLogger("ziira.password_reset")


@dataclass(frozen=True)
class Requested:
    """What the caller learns: nothing about whether anyone was found. In development the link is returned so it can be
    used without reading a mailbox."""

    dev_token: str | None


def request(login: str, *, ip_address: str | None = None) -> Requested:
    """Email a reset link to each business user with this login. Always succeeds from the caller's point of view."""
    counters = throttle.action_counters("reset", directory.hash_login(login), ip_address, per_subject=3, per_ip=10)
    throttle.guard(counters)
    throttle.failed(counters)        # every request counts: the limit is on how often one can ask
    settings = get_settings()
    last_token: str | None = None
    for tenant_id in directory.tenants_for(login):
        with tenant_session(tenant_id) as s:
            user = s.execute(text(
                "select id, full_name, email, status from kernel.app_user "
                "where lower(email) = lower(:l) or phone = :l"),
                {"l": login.strip()}).first()
        if user is None or user.status != "active" or not user.email:
            continue
        token = f"zp_{new_secret()}"
        with master_session() as m:
            m.execute(text(
                "insert into master.password_reset (token_hash, tenant_id, user_id, expires_at, ip_address) "
                "values (:h, :t, :u, :e, :ip)"),
                {"h": hash_secret(token), "t": str(tenant_id), "u": str(user.id),
                 "e": datetime.now(UTC) + timedelta(hours=settings.password_reset_hours), "ip": ip_address})
        link = f"{behaviour.public_web_url()}/reset-password?token={token}"
        try:
            platform_mail.send(user.email, "Choose a new password",
                               f"Hello {user.full_name},\n\nSomeone asked to reset the password for your account. "
                               f"To choose a new one, open this link:\n\n{link}\n\nIt works once and for "
                               f"{settings.password_reset_hours} hours. If it was not you, ignore this message: "
                               "your password has not changed.\n", "password_reset")
        except Unavailable:
            log.error("A password reset email could not be sent")
            continue
        last_token = token
    return Requested(dev_token=last_token if settings.env != "production" else None)


def complete(token: str, new_password: str, *, ip_address: str | None = None) -> None:
    """Use the link: set the new password. Raises Unauthorized for a link that is wrong, used or expired."""
    counters = throttle.action_counters("reset-use", "any", ip_address, per_subject=1000, per_ip=20)
    throttle.guard(counters)
    with master_session() as m:
        row = m.execute(text(
            "update master.password_reset set used_at = now() where token_hash = :h and used_at is null "
            "and expires_at > now() returning tenant_id, user_id"), {"h": hash_secret(token)}).first()
    if row is None:
        throttle.failed(counters)
        raise Unauthorized("This link is not valid any more: ask for a new one")
    tenant_id: UUID = row.tenant_id
    with tenant_session(tenant_id) as s:
        set_context(RequestContext(tenant_id=tenant_id, user_id=row.user_id, channel="web", ip_address=ip_address))
        try:
            users.set_password(s, row.user_id, new_password)
        except Exception:
            with master_session() as m:        # the link was not used up by a password that was refused
                m.execute(text("update master.password_reset set used_at = null where token_hash = :h"),
                          {"h": hash_secret(token)})
            raise
        audit.record(s, "password_reset", "kernel.app_user", row.user_id, {"ip": ip_address})
        login = s.execute(text("select email from kernel.app_user where id = :u"), {"u": str(row.user_id)}).scalar()
    if login:
        throttle.succeeded(throttle.sign_in_counters(login, None)[:1])      # the person can sign in again at once
