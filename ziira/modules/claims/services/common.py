"""Small helpers shared by the claims services."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import text

from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import Claim, ClaimEvent, Estimate, EstimateLine
from ziira.modules.claims.services import access
from ziira.sdk import NotFound, Session, current_context

MAX_LINES = 300


def unit_enabled(session: Session, unit: str) -> bool:
    """True when the unit is enabled for this business (optional units may be missing)."""
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


def now() -> datetime:
    return datetime.now(UTC)


def clean(value: str | None, limit: int) -> str | None:
    text_ = (value or "").strip()
    return text_[:limit] or None


def names_of(session: Session, ids: set[UUID | None]) -> dict[UUID, str]:
    """Display names of staff members, for screens."""
    wanted = [str(i) for i in ids if i is not None]
    if not wanted:
        return {}
    rows = session.execute(text("select id, full_name from kernel.app_user where id = any(cast(:ids as uuid[]))"),
                           {"ids": wanted})
    return {r.id: r.full_name for r in rows}


def actor_name(session: Session) -> str | None:
    user = current_context().user_id
    return names_of(session, {user}).get(user) if user else None


def currency_of(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def business_name(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def load_claim(session: Session, claim_id: UUID, *, lock: bool = False) -> Claim:
    """A claim the user may see, or NotFound."""
    claim = repo.get(session, Claim, claim_id, lock=lock)
    if claim is None or not access.can_view(claim.company_id, claim.branch_id):
        raise NotFound("Claim not found")
    return claim


def load_estimate(session: Session, estimate_id: UUID, *, lock: bool = False) -> tuple[Estimate, Claim]:
    estimate = repo.get(session, Estimate, estimate_id, lock=lock)
    if estimate is None:
        raise NotFound("Estimate not found")
    return estimate, load_claim(session, estimate.claim_id, lock=lock)


def load_line(session: Session, line_id: UUID, *, lock: bool = False) -> tuple[EstimateLine, Estimate, Claim]:
    line = repo.get(session, EstimateLine, line_id, lock=lock)
    if line is None:
        raise NotFound("Line not found")
    estimate, claim = load_estimate(session, line.estimate_id, lock=lock)
    return line, estimate, claim


def add_event(session: Session, claim: Claim, kind: str, note: str | None = None, *, estimate_id: UUID | None = None,
              occurred_on: date | None = None, actor: str | None = None, channel: str | None = None,
              system: bool = False) -> ClaimEvent:
    """Put something on the claim's timeline. `actor` is a name typed by a person outside Ziira (the payer's adjuster);
    otherwise the signed-in user."""
    ctx = current_context()
    user = None if system else ctx.user_id
    event = ClaimEvent(tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id, estimate_id=estimate_id,
                       kind=kind, note=clean(note, 2000), occurred_on=occurred_on,
                       actor_name=clean(actor, 160) or (actor_name(session) if user else None), actor_id=user,
                       channel=channel)
    repo.add(session, event)
    return event
