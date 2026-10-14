"""Use cases: purchase requests and purchase orders.

    request: draft -> (approval) -> approved -> ordered
    order:   draft -> (approval by amount) -> approved -> sent -> part_received -> received      (or closed / cancelled)

Costs on an order are tax-exclusive; VAT is added on top at each line's tax code. An order is approved through the
approval matrix (document type `purchase_order`, by amount); with no rule it is approved on submit.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.inventory.public import location_scope
from ziira.modules.products.public import find_product, tax_code_rate
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import PO_APPROVE, PO_CREATE
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
)
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import active_supplier, unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    company_today,
    current_context,
    next_document_number,
    publish,
    submit_for_approval,
)

ORDER_DOC = "purchase_order"
REQUEST_DOC = "purchase_request"
MAX_LINES = 200


@dataclass(frozen=True)
class OrderLineIn:
    product_id: UUID
    quantity: Decimal
    unit_cost: Decimal                       # before VAT
    tax_code_id: UUID | None = None          # default: the product's


@dataclass
class OrderView:
    order: PurchaseOrder
    lines: list[PurchaseOrderLine]


@dataclass
class RequestView:
    request: PurchaseRequest
    lines: list[PurchaseRequestLine]


# --------------------------------------------------------------------------- requests
def create_request(session: Session, *, company_id: UUID, lines: list[tuple[UUID, Decimal, str | None]],
                   branch_id: UUID | None = None, needed_by: date | None = None) -> RequestView:
    """Ask for goods to be bought. `lines` are (product, quantity, note). Needs 'po.create'."""
    ctx = current_context()
    ctx.require(PO_CREATE, company_id=company_id, branch_id=branch_id)
    check_company(session, company_id, branch_id)
    if not lines or len(lines) > MAX_LINES:
        raise ValidationFailed(f"A request has between 1 and {MAX_LINES} lines")
    request = PurchaseRequest(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="purchase_request",
                                    prefix="PRQ"), needed_by=needed_by)
    repo.add(session, request)
    rows = []
    for product_id, quantity, note in lines:
        product = find_product(session, product_id)
        if product is None or product.company_id != company_id or not product.is_active:
            raise ValidationFailed("A product in the request was not found in this company")
        rules.check_quantity(quantity)
        rows.append(PurchaseRequestLine(tenant_id=ctx.tenant_id, request_id=request.id, product_id=product_id,
                                        quantity=quantity, note=(note or "").strip() or None))
    session.add_all(rows)
    session.flush()
    audit_record(session, "create", "purchasing.purchase_request", request.id, {"number": request.number})
    return RequestView(request, rows)


def get_request(session: Session, request_id: UUID) -> RequestView:
    request = repo.get_request(session, request_id)
    if request is None or not access.can_view(request.company_id, request.branch_id):
        raise NotFound("Request not found")
    return RequestView(request, repo.request_lines(session, request.id))


def list_requests(session: Session, *, status: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[PurchaseRequest]:
    return repo.list_requests(session, access.view_scopes(), status=status, limit=min(limit, 200), offset=offset)


def submit_request(session: Session, request_id: UUID) -> RequestView:
    """Send a draft request for approval (approved at once when there is no rule). Needs 'po.create'."""
    request = repo.get_request(session, request_id, lock=True)
    if request is None or not access.can_view(request.company_id, request.branch_id):
        raise NotFound("Request not found")
    current_context().require(PO_CREATE, company_id=request.company_id, branch_id=request.branch_id)
    if request.status != "draft":
        raise Conflict(f"This request is {request.status.replace('_', ' ')}")
    request.status = "pending_approval"
    session.flush()
    if submit_for_approval(session, company_id=request.company_id, doc_type=REQUEST_DOC, doc_id=request.id) \
            == "approved":
        request.status = "approved"
        session.flush()
    return RequestView(request, repo.request_lines(session, request.id))


def apply_request_decision(session: Session, request_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    request = repo.get_request(session, request_id, lock=True)
    if request is None or request.status != "pending_approval":
        return
    current_context().require(PO_APPROVE, company_id=request.company_id, branch_id=request.branch_id)
    request.status, request.approved_by = ("approved", decided_by) if approved else ("rejected", None)
    session.flush()
    audit_record(session, "approve" if approved else "reject", "purchasing.purchase_request", request.id, None)


# --------------------------------------------------------------------------- orders
def _build_lines(session: Session, company_id: UUID, lines: list[OrderLineIn]) -> list[tuple[OrderLineIn, UUID, UUID,
                                                                                            rules.Amounts]]:
    if not lines or len(lines) > MAX_LINES:
        raise ValidationFailed(f"An order has between 1 and {MAX_LINES} lines")
    built = []
    for line in lines:
        product = find_product(session, line.product_id)
        if product is None or product.company_id != company_id or not product.is_active:
            raise ValidationFailed("A product in the order was not found in this company")
        if product.product_type != "stock":
            raise ValidationFailed(f"{product.sku} is not a stock product: services and costs go on a supplier bill")
        tax_code_id = line.tax_code_id or product.tax_code_id
        rate = tax_code_rate(session, tax_code_id)
        if rate is None:
            raise ValidationFailed("The tax code was not found or is not in use")
        built.append((line, product.base_uom_id, tax_code_id, rules.line_amounts(line.quantity, line.unit_cost, rate)))
    return built


def _check_location(session: Session, location_id: UUID | None, company_id: UUID) -> UUID | None:
    """The branch of the delivery location (when Inventory is on and one was named)."""
    if location_id is None:
        return None
    if not unit_enabled(session, "inventory"):
        raise ValidationFailed("Enable Inventory to name a delivery location")
    found = location_scope(session, location_id)
    if found is None or found[0] != company_id:
        raise ValidationFailed("The delivery location was not found in this company")
    return found[1]


def _write(session: Session, order: PurchaseOrder, built: list[tuple[OrderLineIn, UUID, UUID, rules.Amounts]]) -> None:
    ctx = current_context()
    for line, uom_id, tax_code_id, _ in built:
        session.add(PurchaseOrderLine(tenant_id=ctx.tenant_id, order_id=order.id, product_id=line.product_id,
                                      uom_id=uom_id, quantity=line.quantity, unit_cost=line.unit_cost,
                                      tax_code_id=tax_code_id))
    order.subtotal = sum((a.net for *_, a in built), Decimal(0))
    order.tax_total = sum((a.tax for *_, a in built), Decimal(0))
    order.total = order.subtotal + order.tax_total
    session.flush()


def create_order(session: Session, *, company_id: UUID, supplier_id: UUID, lines: list[OrderLineIn],
                 branch_id: UUID | None = None, deliver_to_location_id: UUID | None = None,
                 order_date: date | None = None, expected_date: date | None = None,
                 request_id: UUID | None = None) -> OrderView:
    """Draft an order to a supplier. The branch is the delivery location's when one is named. Needs 'po.create'."""
    ctx = current_context()
    check_company(session, company_id, branch_id)
    supplier = active_supplier(repo.get_supplier(session, supplier_id), company_id)
    location_branch = _check_location(session, deliver_to_location_id, company_id)
    branch_id = location_branch or branch_id
    ctx.require(PO_CREATE, company_id=company_id, branch_id=branch_id)
    if expected_date is not None and order_date is not None and expected_date < order_date:
        raise ValidationFailed("The expected date cannot be before the order date")
    built = _build_lines(session, company_id, lines)
    if request_id is not None:
        request = repo.get_request(session, request_id, lock=True)
        if request is None or request.company_id != company_id:
            raise ValidationFailed("The request was not found in this company")
        if request.status != "approved":
            raise ValidationFailed("Only an approved request can be turned into an order")
        request.status = "ordered"
    order = PurchaseOrder(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="purchase_order",
                                    prefix="PO"), supplier_id=supplier.id, request_id=request_id,
        deliver_to_location_id=deliver_to_location_id,
        order_date=order_date or company_today(session, company_id), expected_date=expected_date)
    repo.add(session, order)
    _write(session, order, built)
    audit_record(session, "create", "purchasing.purchase_order", order.id,
                 {"number": order.number, "supplier": supplier.code, "total": order.total})
    return OrderView(order, repo.order_lines(session, order.id))


def _own(session: Session, order_id: UUID, *, lock: bool = False) -> PurchaseOrder:
    order = repo.get_order(session, order_id, lock=lock)
    if order is None or not access.can_view(order.company_id, order.branch_id):
        raise NotFound("Order not found")
    return order


def get_order(session: Session, order_id: UUID) -> OrderView:
    order = _own(session, order_id)
    return OrderView(order, repo.order_lines(session, order.id))


def list_orders(session: Session, *, supplier_id: UUID | None = None, status: str | None = None, limit: int = 50,
                offset: int = 0) -> list[PurchaseOrder]:
    return repo.list_orders(session, access.view_scopes(), supplier_id=supplier_id, status=status,
                            limit=min(limit, 200), offset=offset)


def update_order(session: Session, order_id: UUID, *, lines: list[OrderLineIn] | None = None,
                 expected_date: date | None = None, deliver_to_location_id: UUID | None = None) -> OrderView:
    """Change a draft order (replace its lines, dates or delivery place). Needs 'po.create'."""
    order = _own(session, order_id, lock=True)
    current_context().require(PO_CREATE, company_id=order.company_id, branch_id=order.branch_id)
    if order.status != "draft":
        raise Conflict(f"An order that is {order.status.replace('_', ' ')} cannot be edited: cancel it and start again")
    if expected_date is not None:
        if expected_date < order.order_date:
            raise ValidationFailed("The expected date cannot be before the order date")
        order.expected_date = expected_date
    if deliver_to_location_id is not None:
        _check_location(session, deliver_to_location_id, order.company_id)
        order.deliver_to_location_id = deliver_to_location_id
    if lines is not None:
        built = _build_lines(session, order.company_id, lines)
        repo.delete_order_lines(session, order.id)
        _write(session, order, built)
    session.flush()
    audit_record(session, "update", "purchasing.purchase_order", order.id, {"total": order.total})
    return OrderView(order, repo.order_lines(session, order.id))


def submit_order(session: Session, order_id: UUID) -> OrderView:
    """Send a draft order for approval; with no approval rule for its amount it is approved at once. Needs
    'po.create'."""
    order = _own(session, order_id, lock=True)
    current_context().require(PO_CREATE, company_id=order.company_id, branch_id=order.branch_id)
    if order.status != "draft":
        raise Conflict(f"This order is {order.status.replace('_', ' ')}")
    if order.total <= 0 and not any(line.unit_cost > 0 for line in repo.order_lines(session, order.id)):
        raise ValidationFailed("An order with no costs on it cannot be sent for approval: enter the costs")
    order.status = "pending_approval"
    session.flush()
    if submit_for_approval(session, company_id=order.company_id, doc_type=ORDER_DOC, doc_id=order.id,
                           amount=order.total) == "approved":
        _approve(session, order, approved_by=None)
    return OrderView(order, repo.order_lines(session, order.id))


def apply_order_decision(session: Session, order_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Approve or reject an order once its approval has been decided (from `approval.decided`)."""
    order = repo.get_order(session, order_id, lock=True)
    if order is None or order.status != "pending_approval":
        return
    current_context().require(PO_APPROVE, company_id=order.company_id, branch_id=order.branch_id)
    if approved:
        _approve(session, order, approved_by=decided_by)
    else:
        order.status = "draft"
        session.flush()
        audit_record(session, "reject", "purchasing.purchase_order", order.id, {"number": order.number})


def _approve(session: Session, order: PurchaseOrder, *, approved_by: UUID | None) -> None:
    order.status, order.approved_by = "approved", approved_by
    session.flush()
    audit_record(session, "approve", "purchasing.purchase_order", order.id, {"number": order.number})
    publish(session, Event("po.approved", "purchasing.purchase_order", order.id, {
        "company_id": order.company_id, "branch_id": order.branch_id, "number": order.number,
        "supplier_id": order.supplier_id, "total": order.total}))


def send_order(session: Session, order_id: UUID) -> OrderView:
    """Mark an approved order as sent to the supplier. Needs 'po.create'."""
    order = _own(session, order_id, lock=True)
    current_context().require(PO_CREATE, company_id=order.company_id, branch_id=order.branch_id)
    if order.status != "approved":
        raise Conflict("Only an approved order can be sent")
    order.status = "sent"
    session.flush()
    audit_record(session, "send", "purchasing.purchase_order", order.id, None)
    return OrderView(order, repo.order_lines(session, order.id))


def cancel_order(session: Session, order_id: UUID) -> OrderView:
    """Cancel an order nothing has been received on. Needs 'po.create'."""
    order = _own(session, order_id, lock=True)
    current_context().require(PO_CREATE, company_id=order.company_id, branch_id=order.branch_id)
    if order.status not in ("draft", "pending_approval", "approved", "sent"):
        raise Conflict(f"An order that is {order.status.replace('_', ' ')} cannot be cancelled")
    if repo.receipt_has_lines_for_order(session, order.id):
        raise Conflict("Goods have been received on this order: close it instead")
    order.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", "purchasing.purchase_order", order.id, None)
    return OrderView(order, repo.order_lines(session, order.id))


def close_order(session: Session, order_id: UUID) -> OrderView:
    """Stop waiting for the rest of a part-received order. Needs 'po.create'."""
    order = _own(session, order_id, lock=True)
    current_context().require(PO_CREATE, company_id=order.company_id, branch_id=order.branch_id)
    if order.status != "part_received":
        raise Conflict("Only an order that is part received can be closed")
    order.status = "closed"
    session.flush()
    audit_record(session, "close", "purchasing.purchase_order", order.id, None)
    return OrderView(order, repo.order_lines(session, order.id))


