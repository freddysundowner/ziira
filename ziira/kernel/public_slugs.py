"""Public booking addresses: a business picks a short name (`/book/<name>`) and this finds the business behind it.

The slug table lives in the master database (the business is not known yet when a visitor opens the page). It holds
only the slug and the ids. A slug belongs to one company; changing it frees the old one. Units use these through
`ziira.sdk` (`claim_booking_slug`, `release_booking_slug`, `resolve_booking_slug`, `rate_limit`).
"""

import re
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import throttle
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, ValidationFailed

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = {"api", "admin", "app", "book", "login", "static", "assets", "www", "help", "support", "ziira"}


def check_slug(slug: str) -> str:
    """The slug, or ValidationFailed (3 to 60 letters, digits and single dashes; a few words are kept back)."""
    clean = slug.strip().lower()
    if not 3 <= len(clean) <= 60 or not SLUG.match(clean):
        raise ValidationFailed("The booking address has 3 to 60 letters, digits or dashes (for example my-salon)")
    if clean in RESERVED:
        raise ValidationFailed("That booking address is not available")
    return clean


def claim(tenant_id: UUID, company_id: UUID, slug: str) -> str:
    """Give the company this address (replacing its old one). Conflict if another business has it."""
    clean = check_slug(slug)
    with master_session() as s:
        taken = s.execute(text("select tenant_id, company_id from master.booking_slug where slug = :s"),
                          {"s": clean}).first()
        if taken is not None and (taken.tenant_id != tenant_id or taken.company_id != company_id):
            raise Conflict("That booking address is already taken")
        s.execute(text("delete from master.booking_slug where tenant_id = :t and company_id = :c and slug <> :s"),
                  {"t": str(tenant_id), "c": str(company_id), "s": clean})
        s.execute(text("insert into master.booking_slug (slug, tenant_id, company_id) values (:s, :t, :c) "
                       "on conflict (slug) do nothing"), {"s": clean, "t": str(tenant_id), "c": str(company_id)})
    return clean


def release(tenant_id: UUID, company_id: UUID) -> None:
    """Free the company's address."""
    with master_session() as s:
        s.execute(text("delete from master.booking_slug where tenant_id = :t and company_id = :c"),
                  {"t": str(tenant_id), "c": str(company_id)})


def resolve(slug: str) -> tuple[UUID, UUID] | None:
    """(tenant id, company id) behind an address, or None."""
    clean = slug.strip().lower()
    if not SLUG.match(clean) or len(clean) > 60:
        return None
    with master_session() as s:
        row = s.execute(text("select b.tenant_id, b.company_id from master.booking_slug b "
                             "join master.tenant t on t.id = b.tenant_id where b.slug = :s and t.status = 'active'"),
                        {"s": clean}).first()
    return (row.tenant_id, row.company_id) if row is not None else None


def rate_limit(action: str, subject: str, ip_address: str | None, *, per_subject: int, per_ip: int) -> None:
    """Count one use of a public action against its subject and the caller's address and refuse (429) once a limit is
    reached inside the throttle window."""
    counters = throttle.action_counters(action, subject, ip_address, per_subject, per_ip)
    throttle.guard(counters)
    throttle.failed(counters)
