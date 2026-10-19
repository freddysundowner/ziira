"""Recurring work of the Claims module."""

from sqlalchemy import text

from ziira.sdk import Session, periodic


@periodic("claims.sync_settled", every_seconds=3600)
def sync_settled(session: Session) -> None:
    """Payments made straight in Point of Sale also settle a claim: look at invoiced claims again once an hour."""
    from ziira.modules.claims.repository import claims_repo as repo
    from ziira.modules.claims.repository.models import Claim
    from ziira.modules.claims.services import receipts

    enabled = session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first()
    if enabled is None:
        return
    ids = session.execute(text("select id from claims.claim where status in ('invoiced', 'settled') "
                               "order by updated_at nulls first limit 200")).scalars().all()
    for claim_id in ids:
        claim = repo.get(session, Claim, claim_id)
        if claim is not None:
            receipts.sync_status(session, claim)
