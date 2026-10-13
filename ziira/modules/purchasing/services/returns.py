"""Use cases: send goods back to a supplier.

A return names the receipt and the lines going back, with a reason. The stock leaves the receipt's location (Inventory
reacts to `goods.returned` in the same transaction, at the average cost the stock is held at) and the order's received
quantity goes down, so a replacement can be received on the same order. If the goods were already billed, the supplier
owes a credit note: it is entered with `credit_notes` and until then the return is flagged so it is not forgotten.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.public import posted_cost
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import GOODS_RETURN
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import PurchaseReturn, PurchaseReturnLine
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import NAIROBI, unit_enabled
from ziira.sdk import (
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    flag_for_review,
    next_document_number,
    publish,
)

REASONS = "purchase_return"


@dataclass
class ReturnView:
    purchase_return: PurchaseReturn
    lines: list[PurchaseReturnLine]


def get_return(session: Session, return_id: UUID) -> ReturnView:
    found = repo.get_return(session, return_id)
    if found is None or not access.can_view(found.company_id, found.branch_id):
        raise NotFound("Return not found")
    return ReturnView(found, repo.return_lines(session, found.id))


def list_returns(session: Session, *, supplier_id: UUID | None = None, limit: int = 50,
                 offset: int = 0) -> list[PurchaseReturn]:
    return repo.list_returns(session, access.view_scopes(), supplier_id=supplier_id, limit=min(limit, 200),
                             offset=offset)


def return_goods(session: Session, receipt_id: UUID, *, lines: list[tuple[UUID, Decimal]], reason_code_id: UUID,
                 note: str | None = None, returned_at: datetime | None = None) -> ReturnView:
    """Send received goods back. `lines` are (receipt line, quantity). Needs 'goods.return' at the receipt's branch and
    a reason from the 'purchase_return' list."""
    receipt = repo.get_receipt(session, receipt_id)
    if receipt is None or not access.can_view(receipt.company_id, receipt.branch_id):
        raise NotFound("Receipt not found")
    ctx = current_context()
    ctx.require(GOODS_RETURN, company_id=receipt.company_id, branch_id=receipt.branch_id)
    if not unit_enabled(session, "inventory"):
        raise ValidationFailed("Enable Inventory to return goods")
    if receipt.status != "posted" or receipt.location_id is None:
        raise ValidationFailed("Only goods that were received into a stock location can be returned")
    check_reason(session, REASONS, reason_code_id, note)
    if not lines or len(lines) > 200:
        raise ValidationFailed("A return has between 1 and 200 lines")
    if len({line_id for line_id, _ in lines}) != len(lines):
        raise ValidationFailed("A receipt line appears once in a return")

    received = {x.id: x for x in repo.lock_receipt_lines(session, [line_id for line_id, _ in lines])}
    order_lines = {x.id: x for x in repo.order_lines(session, receipt.order_id, lock=True)} if receipt.order_id else {}
    prepared = []
    for line_id, quantity in sorted(lines, key=lambda x: str(x[0])):
        rules.check_quantity(quantity)
        source = received.get(line_id)
        if source is None or source.receipt_id != receipt.id:
            raise ValidationFailed("A line to return does not belong to this receipt")
        back = repo.returned_on_receipt_line(session, source.id)
        if back + quantity > source.quantity:
            raise ValidationFailed(f"Only {rules.plain(source.quantity - back)} of this line can still be returned "
                                   f"(received {rules.plain(source.quantity)}, returned {rules.plain(back)})")
        prepared.append((source, quantity))

    moment = returned_at or datetime.now(UTC)
    ret = PurchaseReturn(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=receipt.company_id, branch_id=receipt.branch_id,
        number=next_document_number(session, company_id=receipt.company_id, branch_id=receipt.branch_id,
                                    doc_type="purchase_return", prefix="PRT"), supplier_id=receipt.supplier_id,
        receipt_id=receipt.id, location_id=receipt.location_id, reason_code_id=reason_code_id,
        note=(note or "").strip() or None, returned_at=moment)
    repo.add(session, ret)
    rows = [PurchaseReturnLine(tenant_id=ctx.tenant_id, return_id=ret.id, receipt_line_id=source.id,
                               product_id=source.product_id, quantity=quantity, unit_cost=source.unit_cost)
            for source, quantity in prepared]
    session.add_all(rows)
    session.flush()
    day = moment.astimezone(NAIROBI).date()
    publish(session, Event("goods.returned", "purchasing.purchase_return", ret.id, {
        "company_id": receipt.company_id, "branch_id": receipt.branch_id, "location_id": receipt.location_id,
        "business_date": day, "number": ret.number, "supplier_id": receipt.supplier_id,
        "lines": [{"line_id": row.id, "product_id": row.product_id, "quantity": row.quantity,
                   "batch_no": source.batch_no, "expiry_date": source.expiry_date}
                  for row, (source, _) in zip(rows, prepared, strict=True)]}))
    costs = posted_cost(session, "purchase_return", ret.id)
    for row in rows:
        row.stock_value = costs.get(row.id, Decimal(0))
    session.flush()

    owing = False
    for source, quantity in prepared:
        if source.order_line_id is not None and source.order_line_id in order_lines:
            order_line = order_lines[source.order_line_id]
            order_line.qty_received -= quantity
        if repo.billed_on_receipt_line(session, source.id) > source.quantity - repo.returned_on_receipt_line(
                session, source.id):
            owing = True
    if receipt.order_id is not None:
        order = repo.get_order(session, receipt.order_id, lock=True)
        if order is not None and order.status in ("received", "part_received"):
            lines_now = [(x.quantity, x.qty_received) for x in order_lines.values()]
            order.status = "received" if all(r >= q for q, r in lines_now) else (
                "part_received" if any(r > 0 for _, r in lines_now) else "approved")
    session.flush()
    audit_record(session, "return", "purchasing.purchase_return", ret.id,
                 {"number": ret.number, "receipt": receipt.number, "lines": len(rows)})
    if owing:
        flag_for_review(session, unit="purchasing", kind="return_needs_credit_note", severity="medium",
                        company_id=receipt.company_id, branch_id=receipt.branch_id, ref_type="purchase_return",
                        ref_id=ret.id, dedupe_key=f"return_credit:{ret.id}",
                        message=f"Goods on return {ret.number} were already billed: ask the supplier for a credit note")
    return ReturnView(ret, rows)
