"""Small helpers shared by the POS services."""

from sqlalchemy import text

from ziira.sdk import Session


def unit_enabled(session: Session, unit: str) -> bool:
    """True when the unit is enabled for this business (CRM, Finance and Payments may be missing)."""
    known: dict[str, bool] = session.info.setdefault("pos_units_enabled", {})      # one answer per transaction
    if unit not in known:
        known[unit] = session.execute(text(
            "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
            "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None
    return known[unit]
