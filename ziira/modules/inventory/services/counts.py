"""Use cases: physical stock counts.

    counting --finish--> review --submit, small--> posted
                           |   '--submit, large--> pending_approval --approved--> posted
                           |                              '--rejected--> review
                           '--cancel--> cancelled          (also possible while counting)

Starting a count takes a snapshot of what the system holds at the location. Sales and receipts carry on
while people count, so each line remembers when it was counted: its difference is the counted quantity minus
what the system held *at that moment* (the snapshot plus whatever moved before it), and posting that
difference corrects the stock without double-counting later movements.

A count whose differences are worth more than the company's `count_variance_threshold` goes through the
approval matrix before posting; smaller ones post when submitted. Every difference needs a reason.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.domain import counts, documents
from ziira.modules.inventory.domain.counts import VarianceLine
from ziira.modules.inventory.permissions import STOCK_APPROVE, STOCK_COUNT, STOCK_VIEW
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import StockCount, StockCountLine
from ziira.modules.inventory.services.ledger import (
    MovementRequest,
    check_batch,
    load_location,
    load_stock_product,
    post_movement,
)
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    check_reason,
    company_setting,
    current_context,
    next_document_number,
    publish,
    submit_for_approval,
)

DOC_TYPE = "stock_count"
OPEN = ("counting", "review", "pending_approval")


@dataclass(frozen=True)
class CountEntry:
    """What was counted for a product (and batch, for batch-tracked products)."""

    product_id: UUID
    counted_qty: Decimal
    batch_id: UUID | None = None
    reason_code_id: UUID | None = None


@dataclass(frozen=True)
class CountDetail:
    count: StockCount
    lines: list[StockCountLine]


def start_count(session: Session, *, company_id: UUID, location_id: UUID,
                product_ids: set[UUID] | None = None) -> CountDetail:
    """Start counting a location (all of it, or only some products). Takes the snapshot of what the system
    holds. One count at a time per location. Needs 'stock.count' for the location's branch."""
    check_company(session, company_id)
    location = load_location(session, company_id, location_id)
    ctx = current_context()
    ctx.require(STOCK_COUNT, company_id=company_id, branch_id=location.branch_id)
    if location.kind == "transit":
        raise ValidationFailed("The in-transit location cannot be counted")
    for product_id in product_ids or ():
        load_stock_product(session, company_id, product_id)
    open_count = inventory_repo.list_counts(session, None, location_id=location_id, limit=500)
    if any(c.status in OPEN for c in open_count):
        raise Conflict("This location already has a count in progress")

    snapshot_seq = inventory_repo.lock_for_snapshot(session)
    balances = inventory_repo.balances_at(session, location_id, product_ids)
    count = StockCount(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, location_id=location_id,
        snapshot_at=datetime.now(UTC), snapshot_seq=snapshot_seq,
        number=next_document_number(session, company_id=company_id, branch_id=location.branch_id,
                                    doc_type=DOC_TYPE, prefix="CNT"))
    inventory_repo.add(session, count)
    lines = []
    for balance in balances:
        line = StockCountLine(tenant_id=ctx.tenant_id, count_id=count.id, product_id=balance.product_id,
                              batch_id=balance.batch_id, expected_qty=balance.quantity)
        inventory_repo.add(session, line)
        lines.append(line)
    audit_record(session, "start", "inventory.stock_count", count.id,
                 {"number": count.number, "location_id": location_id, "lines": len(lines)})
    return CountDetail(count, lines)


def _load(session: Session, count_id: UUID, *, lock: bool = False) -> CountDetail:
    count = inventory_repo.get_document(session, StockCount, count_id, lock=lock)
    location = inventory_repo.get_location(session, count.location_id) if count else None
    if count is None or location is None or not current_context().can(
            STOCK_VIEW, company_id=count.company_id, branch_id=location.branch_id):
        raise NotFound("Stock count not found")
    return CountDetail(count, inventory_repo.document_lines(session, StockCountLine, "count_id", count_id))


def _require_count_permission(session: Session, count: StockCount) -> None:
    location = inventory_repo.get_location(session, count.location_id)
    assert location is not None
    current_context().require(STOCK_COUNT, company_id=count.company_id, branch_id=location.branch_id)


def get_count(session: Session, count_id: UUID) -> CountDetail:
    """One count with its lines (404 if the user may not see its branch)."""
    return _load(session, count_id)


def list_counts(session: Session, *, location_id: UUID | None = None, status: str | None = None,
                limit: int = 100, offset: int = 0) -> list[StockCount]:
    """Counts at the branches the user may see, newest first."""
    return inventory_repo.list_counts(session, current_context().scopes_with(STOCK_VIEW), location_id=location_id,
                                      status=status, limit=min(limit, 500), offset=offset)


def _count_line(session: Session, detail: CountDetail, entry: CountEntry, company_id: UUID) -> None:
    """Record one counted quantity on the matching line (adding a line for stock found that was not in the snapshot)."""
    count = detail.count
    counts.check_counted_quantity(entry.counted_qty)
    product = load_stock_product(session, company_id, entry.product_id)
    check_batch(session, product, entry.batch_id)
    line = next((x for x in detail.lines if x.product_id == entry.product_id and x.batch_id == entry.batch_id), None)
    if line is None:
        ctx = current_context()
        line = StockCountLine(tenant_id=ctx.tenant_id, count_id=count.id, product_id=entry.product_id,
                              batch_id=entry.batch_id, expected_qty=Decimal(0))
        inventory_repo.add(session, line)
        detail.lines.append(line)
    counted_seq = inventory_repo.last_movement_seq(session)
    moved = inventory_repo.moved_between(session, count.location_id, line.product_id, line.batch_id,
                                         count.snapshot_seq, counted_seq)
    line.counted_qty = entry.counted_qty
    line.variance_qty = counts.variance(entry.counted_qty, counts.expected_when_counted(line.expected_qty, moved))
    line.counted_seq = counted_seq
    line.counted_at = datetime.now(UTC)
    if entry.reason_code_id is not None:
        check_reason(session, "count_variance", entry.reason_code_id)
        line.reason_code_id = entry.reason_code_id
    elif line.variance_qty == 0:
        line.reason_code_id = None


def record_counts(session: Session, count_id: UUID, entries: list[CountEntry]) -> CountDetail:
    """Enter counted quantities. A product can be counted again to correct it. Needs 'stock.count'."""
    detail = _load(session, count_id, lock=True)
    _require_count_permission(session, detail.count)
    documents.check_status("stock count", detail.count.status, ("counting",), "counted into")
    if len({(e.product_id, e.batch_id) for e in entries}) != len(entries):
        raise ValidationFailed("Each product (and batch) can appear once")
    if not entries:
        raise ValidationFailed("Add at least one counted quantity")
    for entry in entries:
        _count_line(session, detail, entry, detail.count.company_id)
    session.flush()
    return detail


def finish_counting(session: Session, count_id: UUID, *, uncounted_as_zero: bool = False) -> CountDetail:
    """End the counting and move to review. Lines nobody counted are left out, or counted as zero."""
    detail = _load(session, count_id, lock=True)
    _require_count_permission(session, detail.count)
    documents.check_status("stock count", detail.count.status, ("counting",), "finished")
    uncounted = [x for x in detail.lines if x.counted_qty is None]
    if uncounted_as_zero:
        for line in uncounted:
            _count_line(session, detail, CountEntry(line.product_id, Decimal(0), line.batch_id),
                        detail.count.company_id)
    detail.count.status = "review"
    session.flush()
    audit_record(session, "finish", "inventory.stock_count", detail.count.id,
                 {"number": detail.count.number, "uncounted": 0 if uncounted_as_zero else len(uncounted)})
    return detail


def submit_count(session: Session, count_id: UUID, reasons: dict[UUID, UUID] | None = None) -> CountDetail:
    """Submit a reviewed count. `reasons` maps a line id to its reason (category 'count_variance').

    Differences worth no more than the company's threshold post at once; larger ones go through the approval
    matrix first. Needs 'stock.count'.
    """
    detail = _load(session, count_id, lock=True)
    count = detail.count
    _require_count_permission(session, count)
    documents.check_status("stock count", count.status, ("review",), "submitted")
    by_id = {x.id: x for x in detail.lines}
    for line_id, reason_id in (reasons or {}).items():
        if line_id not in by_id:
            raise ValidationFailed(f"Line {line_id} is not on this count")
        check_reason(session, "count_variance", reason_id)
        by_id[line_id].reason_code_id = reason_id

    differing = [x for x in detail.lines if x.variance_qty not in (None, 0)]
    measured = []
    for line in differing:
        cost = inventory_repo.get_cost(session, count.company_id, line.product_id)
        assert line.variance_qty is not None
        measured.append(VarianceLine(line.variance_qty, cost.average_cost if cost else Decimal(0),
                                     line.reason_code_id is not None))
    counts.check_ready_to_submit(measured)
    amount = counts.variance_amount(measured)
    threshold: Decimal = company_setting(session, count.company_id, "count_variance_threshold")
    audit_record(session, "submit", "inventory.stock_count", count.id, {"number": count.number, "amount": amount})
    if amount <= threshold or submit_for_approval(
            session, company_id=count.company_id, doc_type=DOC_TYPE, doc_id=count.id, amount=amount) == "approved":
        _post(session, detail, approved_by=None)
    else:
        count.status = "pending_approval"
        session.flush()
    return detail


def cancel_count(session: Session, count_id: UUID) -> CountDetail:
    """Abandon a count that has not been posted. Nothing changes in the stock."""
    detail = _load(session, count_id, lock=True)
    _require_count_permission(session, detail.count)
    documents.check_status("stock count", detail.count.status, ("counting", "review"), "cancelled")
    detail.count.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", "inventory.stock_count", detail.count.id, {"number": detail.count.number})
    return detail


def apply_decision(session: Session, count_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post a count's differences once approved, or send it back to review (from `approval.decided`)."""
    count = inventory_repo.get_document(session, StockCount, count_id, lock=True)
    if count is None:
        return
    documents.check_status("stock count", count.status, ("pending_approval",), "decided")
    location = inventory_repo.get_location(session, count.location_id)
    assert location is not None
    current_context().require(STOCK_APPROVE, company_id=count.company_id, branch_id=location.branch_id)
    if approved:
        lines = inventory_repo.document_lines(session, StockCountLine, "count_id", count.id)
        _post(session, CountDetail(count, lines), approved_by=decided_by)
        return
    count.status = "review"
    session.flush()
    audit_record(session, "reject", "inventory.stock_count", count.id, {"number": count.number})


def _post(session: Session, detail: CountDetail, *, approved_by: UUID | None) -> None:
    """Post the differences as `count_variance` movements."""
    count = detail.count
    total = Decimal(0)
    for line in sorted(detail.lines, key=lambda x: (str(x.product_id), str(x.batch_id))):   # fixed lock order
        if line.variance_qty in (None, 0):
            continue
        assert line.variance_qty is not None
        movement = post_movement(session, MovementRequest(
            company_id=count.company_id, location_id=count.location_id, product_id=line.product_id,
            quantity=line.variance_qty, movement_type="count_variance", source_type=DOC_TYPE, source_id=count.id,
            source_line_id=line.id, batch_id=line.batch_id, reason_code_id=line.reason_code_id,
            approved_by=approved_by))
        total += movement.value
    count.status = "posted"
    count.approved_by = approved_by
    count.posted_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "post", "inventory.stock_count", count.id,
                 {"number": count.number, "value": total, "approved_by": approved_by})
    publish(session, Event("count.posted", "inventory.stock_count", count.id, {
        "company_id": count.company_id, "location_id": count.location_id, "number": count.number, "value": total}))
