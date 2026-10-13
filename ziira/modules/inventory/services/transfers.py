"""Use cases: transfers of stock between two locations of a company.

    draft --dispatch--> dispatched --receive, nothing differs--> received
      |                     '--receive, something differs--> pending_approval --approved--> received
      '--cancel--> cancelled                                          '--rejected--> dispatched (count again)

Dispatch moves stock out of the source into the company's in-transit location. Receipt moves it on to the
destination. If less arrives than was sent, the missing part leaves in-transit as a write-off; if more
arrives, the extra is an adjustment at the destination. Either way a reason is required and, when the
approval matrix asks for it, an approver decides before anything posts. Batch-tracked products name their
batch on each line.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.domain import documents, transfers
from ziira.modules.inventory.domain.transfers import Receipt
from ziira.modules.inventory.permissions import STOCK_APPROVE, STOCK_TRANSFER, STOCK_VIEW
from ziira.modules.inventory.repository import inventory_repo
from ziira.modules.inventory.repository.models import Location, Transfer, TransferLine
from ziira.modules.inventory.services.ledger import (
    MovementRequest,
    check_batch,
    load_location,
    load_stock_product,
    post_movement,
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

DOC_TYPE = "transfer"


@dataclass(frozen=True)
class TransferLineIn:
    product_id: UUID
    quantity: Decimal
    batch_id: UUID | None = None


@dataclass(frozen=True)
class ReceivedLine:
    """What arrived for one line of the transfer. A reason is needed when it differs from what was sent."""

    line_id: UUID
    qty_received: Decimal
    reason_code_id: UUID | None = None


@dataclass(frozen=True)
class TransferDetail:
    transfer: Transfer
    lines: list[TransferLine]


def _locations(session: Session, transfer: Transfer) -> tuple[Location, Location]:
    source = inventory_repo.get_location(session, transfer.from_location_id)
    target = inventory_repo.get_location(session, transfer.to_location_id)
    assert source is not None and target is not None
    return source, target


def create_transfer(session: Session, *, company_id: UUID, from_location_id: UUID, to_location_id: UUID,
                    lines: list[TransferLineIn]) -> TransferDetail:
    """Write a draft transfer. Needs 'stock.transfer' for the source location's branch."""
    check_company(session, company_id)
    source = load_location(session, company_id, from_location_id)
    target = load_location(session, company_id, to_location_id)
    current_context().require(STOCK_TRANSFER, company_id=company_id, branch_id=source.branch_id)
    transfers.check_transfer_locations(source.id, target.id, source.kind, target.kind)
    transfers.check_transfer_lines([(x.product_id, x.batch_id, x.quantity) for x in lines])
    for line in lines:
        product = load_stock_product(session, company_id, line.product_id)
        check_batch(session, product, line.batch_id)

    ctx = current_context()
    transfer = Transfer(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, from_location_id=source.id,
        to_location_id=target.id,
        number=next_document_number(session, company_id=company_id, branch_id=source.branch_id,
                                    doc_type=DOC_TYPE, prefix="TRF"))
    inventory_repo.add(session, transfer)
    saved = []
    for line in lines:
        row = TransferLine(tenant_id=ctx.tenant_id, transfer_id=transfer.id, product_id=line.product_id,
                           batch_id=line.batch_id, qty_sent=line.quantity)
        inventory_repo.add(session, row)
        saved.append(row)
    audit_record(session, "create", "inventory.transfer", transfer.id,
                 {"number": transfer.number, "from": source.code, "to": target.code, "lines": len(saved)})
    return TransferDetail(transfer, saved)


def _load(session: Session, transfer_id: UUID, *, lock: bool = False) -> TransferDetail:
    transfer = inventory_repo.get_document(session, Transfer, transfer_id, lock=lock)
    if transfer is None:
        raise NotFound("Transfer not found")
    source, target = _locations(session, transfer)
    ctx = current_context()
    if not (ctx.can(STOCK_VIEW, company_id=transfer.company_id, branch_id=source.branch_id)
            or ctx.can(STOCK_VIEW, company_id=transfer.company_id, branch_id=target.branch_id)):
        raise NotFound("Transfer not found")
    return TransferDetail(transfer, inventory_repo.document_lines(session, TransferLine, "transfer_id", transfer_id))


def get_transfer(session: Session, transfer_id: UUID) -> TransferDetail:
    """One transfer with its lines (404 unless the user may see its source or destination)."""
    return _load(session, transfer_id)


def list_transfers(session: Session, *, location_id: UUID | None = None, status: str | None = None,
                   limit: int = 100, offset: int = 0) -> list[Transfer]:
    """Transfers touching the branches the user may see, newest first."""
    return inventory_repo.list_transfers(session, current_context().scopes_with(STOCK_VIEW), location_id=location_id,
                                         status=status, limit=min(limit, 500), offset=offset)


def cancel_transfer(session: Session, transfer_id: UUID) -> TransferDetail:
    """Cancel a draft. Stock that has been dispatched cannot be cancelled: receive it, with a reason if short."""
    detail = _load(session, transfer_id, lock=True)
    source, _ = _locations(session, detail.transfer)
    current_context().require(STOCK_TRANSFER, company_id=detail.transfer.company_id, branch_id=source.branch_id)
    documents.check_status("transfer", detail.transfer.status, ("draft",), "cancelled")
    detail.transfer.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", "inventory.transfer", detail.transfer.id, {"number": detail.transfer.number})
    return detail


def _transit_location(session: Session, company_id: UUID) -> Location:
    """The company's in-transit location, created the first time one is needed."""
    found = inventory_repo.find_transit_location(session, company_id)
    if found is not None:
        return found
    ctx = current_context()
    location = Location(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code="TRANSIT",
                        name="In transit", kind="transit")
    inventory_repo.add(session, location)
    audit_record(session, "create", "inventory.location", location.id, {"code": "TRANSIT", "kind": "transit"})
    return location


def dispatch_transfer(session: Session, transfer_id: UUID) -> TransferDetail:
    """Send the stock: it leaves the source and is held in transit. Needs 'stock.transfer' for the source branch."""
    detail = _load(session, transfer_id, lock=True)
    transfer = detail.transfer
    source, _ = _locations(session, transfer)
    ctx = current_context()
    ctx.require(STOCK_TRANSFER, company_id=transfer.company_id, branch_id=source.branch_id)
    documents.check_status("transfer", transfer.status, ("draft",), "dispatched")
    transit = _transit_location(session, transfer.company_id)

    for line in sorted(detail.lines, key=lambda x: (str(x.product_id), str(x.batch_id))):   # fixed lock order
        out = post_movement(session, MovementRequest(
            company_id=transfer.company_id, location_id=source.id, product_id=line.product_id,
            quantity=-line.qty_sent, movement_type="transfer_out", source_type=DOC_TYPE, source_id=transfer.id,
            source_line_id=line.id, batch_id=line.batch_id))
        post_movement(session, MovementRequest(
            company_id=transfer.company_id, location_id=transit.id, product_id=line.product_id,
            quantity=line.qty_sent, movement_type="transfer_in", source_type=DOC_TYPE, source_id=transfer.id,
            source_line_id=line.id, batch_id=line.batch_id, unit_cost=out.unit_cost))
    transfer.status = "dispatched"
    transfer.dispatched_at = datetime.now(UTC)
    transfer.dispatched_by = ctx.user_id
    session.flush()
    audit_record(session, "dispatch", "inventory.transfer", transfer.id, {"number": transfer.number})
    publish(session, Event("transfer.dispatched", "inventory.transfer", transfer.id, {
        "company_id": transfer.company_id, "number": transfer.number, "from_location_id": source.id,
        "to_location_id": transfer.to_location_id}))
    return detail


def receive_transfer(session: Session, transfer_id: UUID, received: list[ReceivedLine] | None = None) -> TransferDetail:
    """Record what arrived. With no `received` lines everything arrived as sent.

    A line that differs from what was sent needs a reason (category 'transfer_variance'); the receipt then waits
    for approval if the approval matrix asks for it. Needs 'stock.transfer' for the destination's branch.
    """
    detail = _load(session, transfer_id, lock=True)
    transfer = detail.transfer
    _, target = _locations(session, transfer)
    current_context().require(STOCK_TRANSFER, company_id=transfer.company_id, branch_id=target.branch_id)
    documents.check_status("transfer", transfer.status, ("dispatched",), "received")

    by_id = {line.id: line for line in detail.lines}
    arrived = {r.line_id: r for r in (received or [])}
    if unknown := set(arrived) - set(by_id):
        raise ValidationFailed(f"Line {sorted(unknown, key=str)[0]} is not on this transfer")
    if len(arrived) != len(received or []):
        raise ValidationFailed("Each line can be received once")
    differences: list[tuple[Decimal, Decimal]] = []
    for line in detail.lines:
        item = arrived.get(line.id)
        quantity = item.qty_received if item else line.qty_sent
        transfers.check_received_quantity(quantity)
        difference = Receipt(line.qty_sent, quantity).difference
        if difference != 0:
            check_reason(session, "transfer_variance", item.reason_code_id if item else None)
            cost = inventory_repo.movement_cost(session, transfer.id, line.id, "transfer_in") or Decimal(0)
            differences.append((difference, cost))
        line.qty_received = quantity
        line.variance_reason_code_id = item.reason_code_id if (item and difference != 0) else None
    transfer.received_by = current_context().user_id          # who counted it, even if an approver posts it
    session.flush()

    needs_approval = bool(differences) and submit_for_approval(
        session, company_id=transfer.company_id, doc_type=DOC_TYPE, doc_id=transfer.id,
        amount=transfers.variance_value(differences)) != "approved"
    if not needs_approval:
        _post_receipt(session, detail, approved_by=None)
    else:
        transfer.status = "pending_approval"
        session.flush()
        audit_record(session, "submit", "inventory.transfer", transfer.id, {"number": transfer.number})
    return detail


def apply_decision(session: Session, transfer_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post the receipt of a transfer with differences, or send it back for a recount (from `approval.decided`)."""
    transfer = inventory_repo.get_document(session, Transfer, transfer_id, lock=True)
    if transfer is None:
        return
    documents.check_status("transfer", transfer.status, ("pending_approval",), "decided")
    _, target = _locations(session, transfer)
    current_context().require(STOCK_APPROVE, company_id=transfer.company_id, branch_id=target.branch_id)
    lines = inventory_repo.document_lines(session, TransferLine, "transfer_id", transfer.id)
    if approved:
        _post_receipt(session, TransferDetail(transfer, lines), approved_by=decided_by)
        return
    for line in lines:                      # back to dispatched: the receiver counts again
        line.qty_received = None
        line.variance_reason_code_id = None
    transfer.status = "dispatched"
    session.flush()
    audit_record(session, "reject", "inventory.transfer", transfer.id, {"number": transfer.number})


def _post_receipt(session: Session, detail: TransferDetail, *, approved_by: UUID | None) -> None:
    """Move what arrived from in-transit to the destination, and account for any difference."""
    transfer = detail.transfer
    transit = _transit_location(session, transfer.company_id)
    for line in sorted(detail.lines, key=lambda x: (str(x.product_id), str(x.batch_id))):
        assert line.qty_received is not None
        cost = inventory_repo.movement_cost(session, transfer.id, line.id, "transfer_in")

        def request(location_id: UUID, quantity: Decimal, movement_type: str, unit_cost: Decimal | None = None,
                    reason: UUID | None = None, line: TransferLine = line) -> MovementRequest:
            return MovementRequest(
                company_id=transfer.company_id, location_id=location_id, product_id=line.product_id,
                quantity=quantity, movement_type=movement_type, source_type=DOC_TYPE, source_id=transfer.id,
                source_line_id=line.id, batch_id=line.batch_id, unit_cost=unit_cost, reason_code_id=reason,
                approved_by=approved_by)

        carried = min(line.qty_sent, line.qty_received)
        if carried > 0:
            post_movement(session, request(transit.id, -carried, "transfer_out", cost))
            post_movement(session, request(transfer.to_location_id, carried, "transfer_in", cost))
        if line.qty_received < line.qty_sent:                       # short: the rest is lost in transit
            post_movement(session, request(transit.id, line.qty_received - line.qty_sent, "write_off",
                                           reason=line.variance_reason_code_id))
        elif line.qty_received > line.qty_sent:                     # over: found at the destination
            post_movement(session, request(transfer.to_location_id, line.qty_received - line.qty_sent, "adjustment",
                                           reason=line.variance_reason_code_id))
    transfer.status = "received"
    transfer.received_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "receive", "inventory.transfer", transfer.id,
                 {"number": transfer.number, "approved_by": approved_by})
    publish(session, Event("transfer.received", "inventory.transfer", transfer.id, {
        "company_id": transfer.company_id, "number": transfer.number, "to_location_id": transfer.to_location_id,
        "with_differences": any(x.qty_received != x.qty_sent for x in detail.lines)}))
