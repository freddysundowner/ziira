"""Use cases: sales held at a till. A cashier parks the cart while the customer fetches something and resumes it later.

A held sale is a draft: it moves no stock and makes no entry in the books. It lives until it is resumed (the cart goes
back on the screen), discarded, or - when the till closes - expired. Holding with the same `local_id` twice keeps one
(a terminal that was offline uploads what it parked, and may send it again).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder

from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import HeldSale, TillSession
from ziira.modules.pos.services import access, tills
from ziira.sdk import Conflict, Forbidden, NotFound, Session, ValidationFailed, current_context

MAX_HELD_PER_TILL = 50


def _till_of(session: Session, till_id: UUID) -> TillSession:
    till = pos_repo.get_till(session, till_id)
    if till is None:
        raise NotFound("Till not found")
    return till


def _own(session: Session, held: HeldSale) -> HeldSale:
    """The held sale, if the signed-in person is its cashier. Others get 'not found'."""
    if held.cashier_id != current_context().user_id:
        raise NotFound("Held sale not found")
    return held


def hold(session: Session, till_id: UUID, *, local_id: UUID | None, label: str, customer_id: UUID | None,
         note: str | None, payload: dict[str, Any]) -> tuple[HeldSale, bool]:
    """Park a cart on the signed-in cashier's open till. Returns (held sale, already_existed)."""
    ctx = current_context()
    local_id = local_id or uuid4()
    pos_repo.lock_key(session, f"pos.held:{local_id}")
    earlier = pos_repo.held_by_local_id(session, local_id)
    if earlier is not None:
        return _own(session, earlier), True
    till = pos_repo.get_till(session, till_id, share=True)
    if till is None:
        raise NotFound("Till not found")
    company_id = tills.company_of(session, till)
    ctx.require("sales.sell", company_id=company_id, branch_id=till.branch_id)
    if till.cashier_id != ctx.user_id:
        raise Forbidden("This is another cashier's till")
    if till.status != "open":
        raise Conflict("This till is closed")
    if not payload.get("lines"):
        raise ValidationFailed("There is nothing in the cart to hold")
    if pos_repo.count_held(session, till.id) >= MAX_HELD_PER_TILL:
        raise Conflict(f"At most {MAX_HELD_PER_TILL} sales can be on hold at one till")
    held = HeldSale(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=till.branch_id,
                    till_session_id=till.id, cashier_id=ctx.user_id, local_id=local_id, label=label.strip(),
                    customer_id=customer_id, note=(note or "").strip() or None, payload=jsonable_encoder(payload))
    pos_repo.add(session, held)
    return held, False


def list_held(session: Session, till_id: UUID, status: str = "held") -> list[HeldSale]:
    """The held sales of a till (default: those still on hold), newest first. The cashier, or a reviewer."""
    till = _till_of(session, till_id)
    company_id = tills.company_of(session, till)
    if till.cashier_id != current_context().user_id and not access.can_review(company_id, till.branch_id):
        raise NotFound("Till not found")
    return pos_repo.list_held(session, till.id, None if status == "all" else status)


def get_held(session: Session, held_id: UUID) -> HeldSale:
    held = pos_repo.get_held(session, held_id)
    if held is None:
        raise NotFound("Held sale not found")
    return _own(session, held)


def resume(session: Session, held_id: UUID) -> HeldSale:
    """Take a held sale back to the screen. Asking again for one already resumed gives it again (a retry is safe)."""
    held = get_held(session, held_id)
    if held.status == "held":
        held.status, held.status_at, held.updated_at = "resumed", datetime.now(UTC), datetime.now(UTC)
        session.flush()
    elif held.status != "resumed":
        raise Conflict(f"This sale is no longer on hold ({held.status})")
    return held


def discard(session: Session, held_id: UUID) -> HeldSale:
    """Throw a held sale away. Discarding one already discarded is not an error."""
    held = get_held(session, held_id)
    if held.status == "held":
        held.status, held.status_at, held.updated_at = "discarded", datetime.now(UTC), datetime.now(UTC)
        session.flush()
    elif held.status not in ("discarded", "resumed"):
        raise Conflict(f"This sale is no longer on hold ({held.status})")
    return held
