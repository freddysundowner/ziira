"""Use cases: stock adjustments. A person writes one (draft), submits it, and once approved (if the
approval matrix asks for it) it posts `adjustment` movements with the reason given.

    draft --submit--> pending_approval --approved--> posted
      |                      '--rejected--> rejected
      '--submit (no approval rule applies)--> posted
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.domain import documents
from ziira.modules.inventory.permissions import STOCK_ADJUST, STOCK_APPROVE, STOCK_VIEW
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import StockAdjustment, StockAdjustmentLine
from ziira.modules.inventory.services.ledger import (
    MovementRequest,
    check_batch,
    load_location,
    load_stock_product,
    post_movement,
    post_stock_out,
)
from ziira.sdk import (
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    check_reason,
    current_context,
    next_document_number,
    publish,
    submit_for_approval,
)

DOC_TYPE = "stock_adjustment"


@dataclass(frozen=True)
class AdjustmentLineIn:
    """Change a product's stock by `qty_change` (+ more, - less). A batch is needed to add to a batch-tracked
    product; taking from one without naming a batch uses first expiry, first out."""

    product_id: UUID
    qty_change: Decimal
    batch_id: UUID | None = None


@dataclass(frozen=True)
class AdjustmentDetail:
    adjustment: StockAdjustment
    lines: list[StockAdjustmentLine]


def create_adjustment(session: Session, *, company_id: UUID, location_id: UUID, reason_code_id: UUID,
                      note: str | None, lines: list[AdjustmentLineIn]) -> AdjustmentDetail:
    """Write a draft adjustment for a location. Needs 'stock.adjust' for the location's branch."""
    check_company(session, company_id)
    location = load_location(session, company_id, location_id)
    current_context().require(STOCK_ADJUST, company_id=company_id, branch_id=location.branch_id)
    check_reason(session, "stock_adjustment", reason_code_id, note)
    documents.check_adjustment_lines([(line.product_id, line.batch_id, line.qty_change) for line in lines])
    for line in lines:
        product = load_stock_product(session, company_id, line.product_id)
        if product.is_batch_tracked and line.batch_id is None and line.qty_change > 0:
            raise ValidationFailed(f"{product.sku} is batch-tracked: name the batch to add to")
        if line.batch_id is not None or not product.is_batch_tracked:
            check_batch(session, product, line.batch_id)

    ctx = current_context()
    adjustment = StockAdjustment(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, location_id=location_id,
        reason_code_id=reason_code_id, note=(note or "").strip() or None,
        number=next_document_number(session, company_id=company_id, branch_id=location.branch_id,
                                    doc_type=DOC_TYPE, prefix="ADJ"))
    inventory_repo.add(session, adjustment)
    saved = []
    for line in lines:
        row = StockAdjustmentLine(tenant_id=ctx.tenant_id, adjustment_id=adjustment.id, product_id=line.product_id,
                                  batch_id=line.batch_id, qty_change=line.qty_change)
        inventory_repo.add(session, row)
        saved.append(row)
    audit_record(session, "create", "inventory.stock_adjustment", adjustment.id,
                 {"number": adjustment.number, "location_id": location_id, "lines": len(saved)})
    return AdjustmentDetail(adjustment, saved)


def _load(session: Session, adjustment_id: UUID, *, lock: bool = False) -> AdjustmentDetail:
    adjustment = inventory_repo.get_document(session, StockAdjustment, adjustment_id, lock=lock)
    location = inventory_repo.get_location(session, adjustment.location_id) if adjustment else None
    if adjustment is None or location is None or not current_context().can(
            STOCK_VIEW, company_id=adjustment.company_id, branch_id=location.branch_id):
        raise NotFound("Stock adjustment not found")
    return AdjustmentDetail(adjustment, inventory_repo.document_lines(
        session, StockAdjustmentLine, "adjustment_id", adjustment_id))


def get_adjustment(session: Session, adjustment_id: UUID) -> AdjustmentDetail:
    """One adjustment with its lines (404 if the user may not see its branch)."""
    return _load(session, adjustment_id)


def list_adjustments(session: Session, *, location_id: UUID | None = None, status: str | None = None,
                     limit: int = 100, offset: int = 0) -> list[StockAdjustment]:
    """Adjustments at the branches the user may see, newest first."""
    return inventory_repo.list_adjustments(session, current_context().scopes_with(STOCK_VIEW), location_id=location_id,
                                           status=status, limit=min(limit, 500), offset=offset)


def submit_adjustment(session: Session, adjustment_id: UUID) -> AdjustmentDetail:
    """Send a draft for approval; it posts at once if no approval rule applies to its size.

    The size is the value of the change at the current average cost. Needs 'stock.adjust'.
    """
    detail = _load(session, adjustment_id, lock=True)
    adjustment = detail.adjustment
    location = inventory_repo.get_location(session, adjustment.location_id)
    assert location is not None
    current_context().require(STOCK_ADJUST, company_id=adjustment.company_id, branch_id=location.branch_id)
    documents.check_status("stock adjustment", adjustment.status, ("draft",), "submitted")

    changes = []
    for line in detail.lines:
        cost = inventory_repo.get_cost(session, adjustment.company_id, line.product_id)
        changes.append((line.qty_change, cost.average_cost if cost else Decimal(0)))
    amount = documents.adjustment_amount(changes)
    audit_record(session, "submit", "inventory.stock_adjustment", adjustment.id, {"amount": amount})
    if submit_for_approval(session, company_id=adjustment.company_id, doc_type=DOC_TYPE, doc_id=adjustment.id,
                           amount=amount) == "approved":
        _post(session, detail, approved_by=None)
    else:
        adjustment.status = "pending_approval"
        session.flush()
    return detail


def apply_decision(session: Session, adjustment_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post or reject an adjustment once its approval has been decided (called from `approval.decided`)."""
    adjustment = inventory_repo.get_document(session, StockAdjustment, adjustment_id, lock=True)
    if adjustment is None:
        return
    documents.check_status("stock adjustment", adjustment.status, ("pending_approval",),
                           "approved" if approved else "rejected")
    location = inventory_repo.get_location(session, adjustment.location_id)
    assert location is not None
    current_context().require(STOCK_APPROVE, company_id=adjustment.company_id, branch_id=location.branch_id)
    if approved:
        lines = inventory_repo.document_lines(session, StockAdjustmentLine, "adjustment_id", adjustment.id)
        _post(session, AdjustmentDetail(adjustment, lines), approved_by=decided_by)
    else:
        adjustment.status = "rejected"
        adjustment.approved_by = None
        session.flush()
        audit_record(session, "reject", "inventory.stock_adjustment", adjustment.id, {"number": adjustment.number})


def _post(session: Session, detail: AdjustmentDetail, *, approved_by: UUID | None) -> None:
    """Turn an approved adjustment into stock movements."""
    adjustment = detail.adjustment
    total = Decimal(0)
    for line in sorted(detail.lines, key=lambda x: (str(x.product_id), str(x.batch_id))):   # fixed lock order
        request = MovementRequest(
            company_id=adjustment.company_id, location_id=adjustment.location_id, product_id=line.product_id,
            quantity=line.qty_change, movement_type="adjustment", source_type=DOC_TYPE, source_id=adjustment.id,
            source_line_id=line.id, batch_id=line.batch_id, reason_code_id=adjustment.reason_code_id,
            approved_by=approved_by)
        posted = post_stock_out(session, request) if line.qty_change < 0 else [post_movement(session, request)]
        total += sum((m.value for m in posted), Decimal(0))
    adjustment.status = "posted"
    adjustment.approved_by = approved_by
    adjustment.posted_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "post", "inventory.stock_adjustment", adjustment.id,
                 {"number": adjustment.number, "value": total, "approved_by": approved_by})
    publish(session, Event("stock.adjusted", "inventory.stock_adjustment", adjustment.id, {
        "company_id": adjustment.company_id, "location_id": adjustment.location_id, "number": adjustment.number,
        "reason_code_id": adjustment.reason_code_id, "value": total}))
