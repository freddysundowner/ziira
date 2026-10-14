"""Small helpers shared by the people services."""

from sqlalchemy import text

from ziira.sdk import Session


def finance_enabled(session: Session) -> bool:
    """True when Finance is enabled for this business (payroll posts to its books)."""
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'finance' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None
