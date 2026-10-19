"""Small helpers shared by the bookings services."""

from datetime import UTC, datetime, tzinfo
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session, ValidationFailed, company_zone, current_context


def unit_enabled(session: Session, unit: str) -> bool:
    """True when the unit is enabled for this business (optional units may be missing)."""
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def zone(session: Session, company_id: UUID) -> tzinfo:
    """The company's time zone."""
    return company_zone(session, company_id)


def now() -> datetime:
    return datetime.now(UTC)


def user_id() -> UUID | None:
    return current_context().user_id


def require_aware(moment: datetime, what: str = "The time") -> datetime:
    """A moment with a time zone (the web app always sends one)."""
    if moment.tzinfo is None:
        raise ValidationFailed(f"{what} needs a time zone, for example 2026-10-20T09:00:00+03:00")
    return moment
