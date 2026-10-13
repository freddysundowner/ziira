"""Use cases: working offline. A device keeps selling without a connection and sends what happened when it is back.

    snapshot (products, prices, stock) --> device goes offline --> till_open, sale..., till_close --> upload

The upload is safe to repeat, in whole or in part: every operation carries an id made on the device, and one that was
already accepted is answered with what the server did the first time instead of being done again. That is what makes
"exactly once" true over a flaky network.

Operations run in the order sent, each on its own: one that cannot be accepted does not stop the others. Sales are
accepted whenever they are well formed (the customer has paid and left), with business problems raised for a manager.
What cannot be accepted at all is kept, whole, in `pos.sync_rejection` so no sale is lost.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import DataError, IntegrityError

from ziira.modules.pos.permissions import TILL_REVIEW
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import Device, SyncRejection, TillSession
from ziira.modules.pos.services import sales, tills
from ziira.sdk import (
    Event,
    NotFound,
    Session,
    ValidationFailed,
    ZiiraError,
    audit_record,
    current_context,
    flag_for_review,
    idempotent,
    publish,
)


@dataclass(frozen=True)
class TillRef:
    """A till, named by the id the server gave it or the id the device made when it opened it offline."""

    till_session_id: UUID | None = None
    till_local_id: UUID | None = None


@dataclass(frozen=True)
class SyncOp:
    type: str                                   # till_open | sale | till_close
    local_id: UUID
    at: datetime
    till: TillRef = field(default_factory=TillRef)
    opening_float: Decimal = Decimal(0)         # till_open
    lines: list[sales.LineIn] = field(default_factory=list)          # sale
    payments: list[sales.PaymentIn] = field(default_factory=list)    # sale
    number: str | None = None                   # sale: the device's own number
    customer_id: UUID | None = None
    counted_cash: Decimal = Decimal(0)          # till_close
    reason_code_id: UUID | None = None
    note: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)     # what the device sent, kept if the op is rejected


@dataclass
class OpResult:
    local_id: UUID
    type: str
    status: str                                 # ok | duplicate | rejected
    id: UUID | None = None
    number: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _resolve_till(session: Session, ref: TillRef) -> TillSession:
    till = None
    if ref.till_local_id is not None:
        till = pos_repo.till_by_local_id(session, ref.till_local_id)
    if till is None and ref.till_session_id is not None:
        till = pos_repo.get_till(session, ref.till_session_id)
    if till is None:
        raise NotFound("The till for this operation was not found: its opening may not have been accepted")
    return till


def _apply(session: Session, device: Device, op: SyncOp) -> OpResult:
    if op.type == "till_open":
        till, existed = tills.open_till(session, device.id, op.opening_float, local_id=op.local_id, opened_at=op.at)
        return OpResult(op.local_id, op.type, "duplicate" if existed else "ok", id=till.id)
    if op.type == "sale":
        till = _resolve_till(session, op.till)
        view = sales.post_sale(session, till_session_id=till.id, lines=op.lines, payments=op.payments,
                               local_id=op.local_id, customer_id=op.customer_id, offline_number=op.number,
                               sold_at=op.at, offline=True)
        return OpResult(op.local_id, op.type, "duplicate" if view.replayed else "ok", id=view.sale.id,
                        number=view.sale.number, warnings=view.warnings)
    if op.type == "till_close":
        till = _resolve_till(session, op.till)

        def close() -> dict[str, Any]:
            closed = tills.close_till(session, till.id, op.counted_cash, reason_code_id=op.reason_code_id,
                                      note=op.note, closed_at=op.at, strict=False)
            return {"id": str(closed.id)}

        done, replayed = idempotent(session, f"pos.sync.close:{device.id}:{op.local_id}",
                                    {"till": str(till.id), "counted": str(op.counted_cash)}, close)
        return OpResult(op.local_id, op.type, "duplicate" if replayed else "ok", id=UUID(done["id"]))
    raise ValidationFailed(f"Unknown operation type '{op.type}'")


def _reject(session: Session, device: Device, op: SyncOp, error: str) -> None:
    ctx = current_context()
    kept = pos_repo.rejection_by_local_id(session, op.local_id)
    if kept is None:
        kept = SyncRejection(tenant_id=ctx.tenant_id, device_id=device.id, user_id=ctx.user_id, local_id=op.local_id,
                             op_type=op.type, payload=jsonable_encoder(op.raw), error=error)
        pos_repo.add(session, kept)
    else:
        kept.attempts, kept.error, kept.resolved_at = kept.attempts + 1, error, None
        kept.payload = jsonable_encoder(op.raw)
        session.flush()
    company_id = pos_repo.branch_company(session, device.branch_id)
    flag_for_review(session, unit="pos", kind="sync_rejected", severity="high", company_id=company_id,
                    branch_id=device.branch_id, ref_type="sync_rejection", ref_id=kept.id,
                    dedupe_key=f"sync_rejected:{op.local_id}",
                    message=f"A {op.type.replace('_', ' ')} from device {device.code} could not be accepted: {error}")


def upload(session: Session, device: Device, ops: list[SyncOp]) -> list[OpResult]:
    """Apply a device's operations in order. Each is atomic on its own. Safe to repeat."""
    results: list[OpResult] = []
    for op in ops:
        try:
            with session.begin_nested():
                result = _apply(session, device, op)
            kept = pos_repo.rejection_by_local_id(session, op.local_id)
            if kept is not None and kept.resolved_at is None:
                kept.resolved_at = datetime.now(UTC)
                session.flush()
        except (ZiiraError, IntegrityError, DataError) as error:
            message = error.message if isinstance(error, ZiiraError) else "The operation breaks a rule of the data"
            _reject(session, device, op, message)
            result = OpResult(op.local_id, op.type, "rejected", error=message)
        results.append(result)
    audit_record(session, "sync", "pos.device", device.id, {
        "ops": len(ops), "rejected": sum(1 for r in results if r.status == "rejected")})
    publish(session, Event("pos.synced", "pos.device", device.id, {
        "branch_id": device.branch_id, "ops": len(ops), "rejected": sum(1 for r in results if r.status == "rejected")}))
    return results


def list_rejections(session: Session, *, include_resolved: bool = False, limit: int = 50,
                    offset: int = 0) -> list[SyncRejection]:
    """Offline operations that were not accepted, at the branches the user reviews. Needs 'till.review'."""
    scopes = current_context().scopes_with(TILL_REVIEW)
    if scopes is not None and not scopes:
        return []
    return pos_repo.list_rejections(session, scopes, include_resolved=include_resolved, limit=min(limit, 200),
                                    offset=offset)
