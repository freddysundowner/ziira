"""Use cases: quotations and sales orders for business customers.

    quotation: draft -> sent -> confirmed (becomes an order)      or expired / cancelled
    order:     draft -> (approval by amount) -> confirmed -> fulfilled (delivered and invoiced)   or cancelled

A quotation fixes prices for a customer until it expires. Confirming it makes a sales order with the same lines. An
order is delivered by invoicing it (`invoices.issue_invoice`): partly or all at once, each invoice delivering the stock
for the quantities on it, at the prices agreed. Prices include VAT, as everywhere in POS.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.public import CustomerView
from ziira.modules.inventory.public import location_scope
from ziira.modules.pos.domain import sales as rules
from ziira.modules.pos.permissions import INVOICES_MANAGE, PRICE_OVERRIDE
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import SalesDocument, SalesDocumentLine
from ziira.modules.pos.services import credit, invoices, tills
from ziira.modules.pos.services.common import unit_enabled
from ziira.modules.products.public import find_product, selling_prices
from ziira.sdk import (
    Conflict,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    next_document_number,
    submit_for_approval,
)

ORDER_DOC = "sales_order"
PRICE_OVERRIDE_REASONS = "price_override"
OPEN_QUOTE = ("draft", "sent")


@dataclass(frozen=True)
class DocLineIn:
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal | None = None          # tax-inclusive; None: the customer's list price
    discount: Decimal = Decimal(0)
    reason_code_id: UUID | None = None


@dataclass
class DocView:
    document: SalesDocument
    lines: list[SalesDocumentLine]


def _scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    return invoices.invoice_scopes()


def _can_see(document: SalesDocument) -> bool:
    scopes = _scopes()
    return scopes is None or any((c is None or c == document.company_id) and (b is None or b == document.branch_id)
                                 for c, b in scopes)


def _expire(session: Session, document: SalesDocument) -> None:
    """A quotation past its date is expired, whoever looks at it first."""
    if document.doc_kind == "quotation" and document.status in OPEN_QUOTE and document.valid_until is not None \
            and document.valid_until < tills.today():
        document.status = "expired"
        session.flush()


def expire_all(session: Session) -> int:
    """Expire every open quotation whose date has passed (the recurring task). Returns how many."""
    rows = session.execute(text(
        "update pos.sales_document set status = 'expired', updated_at = now() where doc_kind = 'quotation' "
        "and status in ('draft', 'sent') and valid_until < :today returning id"), {"today": tills.today()}).all()
    for row in rows:
        audit_record(session, "expire", "pos.sales_quotation", row.id, None)
    return len(rows)


def get_document(session: Session, document_id: UUID, kind: str | None = None) -> DocView:
    document = pos_repo.get_document(session, document_id)
    if document is None or not _can_see(document) or (kind is not None and document.doc_kind != kind):
        raise NotFound("Document not found")
    _expire(session, document)
    return DocView(document, pos_repo.document_lines(session, document.id))


def list_documents(session: Session, *, kind: str | None = None, customer_id: UUID | None = None,
                   status: str | None = None, limit: int = 50, offset: int = 0) -> list[SalesDocument]:
    found = pos_repo.list_documents(session, _scopes(), kind=kind, customer_id=customer_id, status=status,
                                    limit=min(limit, 200), offset=offset)
    for document in found:
        _expire(session, document)
    return [d for d in found if status is None or d.status == status]


def _price_lines(session: Session, customer: CustomerView, branch_id: UUID | None, lines: list[DocLineIn],
                 ) -> list[tuple[DocLineIn, UUID, UUID, Decimal, rules.LineAmounts]]:
    """Each line's product, tax code, the price used and its money."""
    ctx = current_context()
    if not lines or len(lines) > rules.MAX_LINES:
        raise ValidationFailed(f"A document has between 1 and {rules.MAX_LINES} lines")
    products = {}
    for line in lines:
        product = find_product(session, line.product_id)
        if product is None or product.company_id != customer.company_id or not product.is_active:
            raise ValidationFailed("A product was not found in this company")
        products[line.product_id] = product
    prices = selling_prices(session, customer.company_id, branch_id, set(products), tills.today(),
                            customer.customer_group)
    can_override = ctx.can(PRICE_OVERRIDE, company_id=customer.company_id, branch_id=branch_id)
    priced = []
    for line in lines:
        product = products[line.product_id]
        list_price = prices.get(product.id)
        unit = line.unit_price if line.unit_price is not None else list_price
        if unit is None:
            raise ValidationFailed(f"{product.sku} has no price: ask a manager to set one")
        if list_price is None or unit != list_price or line.discount > 0 or line.reason_code_id is not None:
            if not can_override:
                raise Forbidden("Changing a price or giving a discount needs the price override permission")
            check_reason(session, PRICE_OVERRIDE_REASONS, line.reason_code_id)
        priced.append((line, product.base_uom_id, product.tax_code_id, unit,
                       rules.price_line(line.quantity, unit, line.discount, product.vat_rate)))
    return priced


def _write(session: Session, document: SalesDocument,
           priced: list[tuple[DocLineIn, UUID, UUID, Decimal, rules.LineAmounts]]) -> None:
    ctx = current_context()
    for number, (line, uom_id, tax_code_id, unit, amount) in enumerate(priced, start=1):
        session.add(SalesDocumentLine(
            tenant_id=ctx.tenant_id, document_id=document.id, line_no=number, product_id=line.product_id,
            uom_id=uom_id, quantity=line.quantity, unit_price=unit, discount_amount=line.discount,
            tax_code_id=tax_code_id, tax_amount=amount.tax, line_total=amount.gross))
    document.total = sum((x[4].gross for x in priced), Decimal(0))
    document.tax_total = sum((x[4].tax for x in priced), Decimal(0))
    document.subtotal = document.total - document.tax_total
    session.flush()


def _create(session: Session, kind: str, *, customer_id: UUID, lines: list[DocLineIn], branch_id: UUID | None,
            location_id: UUID | None, valid_until: date | None, terms_days: int | None, notes: str | None,
            source_quotation_id: UUID | None = None) -> DocView:
    ctx = current_context()
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Enable CRM to quote and order for customers")
    from ziira.modules.crm.public import find_customer

    found = find_customer(session, customer_id)
    if found is None:
        raise ValidationFailed("Customer not found")
    customer = credit.load_customer(session, customer_id, found.company_id, for_credit=True)
    assert customer is not None
    if customer.status == "inactive":
        raise ValidationFailed(f"{customer.name} is inactive")
    stock_branch = None
    if location_id is not None:
        where = location_scope(session, location_id)
        if where is None or where[0] != customer.company_id:
            raise ValidationFailed("The stock location was not found in this company")
        stock_branch = where[1]
    branch_id = stock_branch or branch_id
    if branch_id is None:
        raise ValidationFailed("Say which branch this is for (or name the stock location)")
    ctx.require(INVOICES_MANAGE, company_id=customer.company_id, branch_id=branch_id)
    if valid_until is not None and valid_until < tills.today():
        raise ValidationFailed("A quotation cannot be valid until a date that has passed")
    terms = customer.payment_terms_days if terms_days is None else terms_days
    if terms < 0 or terms > 365:
        raise ValidationFailed("Payment terms are between 0 and 365 days")
    priced = _price_lines(session, customer, branch_id, lines)
    document = SalesDocument(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=customer.company_id, branch_id=branch_id,
        doc_kind=kind, number=next_document_number(
            session, company_id=customer.company_id, branch_id=branch_id, doc_type=f"sales_{kind}",
            prefix="QUO" if kind == "quotation" else "SO"), customer_id=customer.id, doc_date=tills.today(),
        valid_until=valid_until if kind == "quotation" else None, source_quotation_id=source_quotation_id,
        location_id=location_id, terms_days=terms, notes=(notes or "").strip()[:500] or None)
    pos_repo.add(session, document)
    _write(session, document, priced)
    audit_record(session, "create", f"pos.sales_{kind}", document.id,
                 {"number": document.number, "customer": customer.code, "total": document.total})
    return DocView(document, pos_repo.document_lines(session, document.id))


def create_quotation(session: Session, *, customer_id: UUID, lines: list[DocLineIn], branch_id: UUID | None = None,
                     location_id: UUID | None = None, valid_until: date | None = None, terms_days: int | None = None,
                     notes: str | None = None) -> DocView:
    """Quote a customer. By default it is valid for 14 days. Needs 'invoices.manage' at the branch."""
    return _create(session, "quotation", customer_id=customer_id, lines=lines, branch_id=branch_id,
                   location_id=location_id, valid_until=valid_until or tills.today() + timedelta(days=14),
                   terms_days=terms_days, notes=notes)


def create_order(session: Session, *, customer_id: UUID, lines: list[DocLineIn], branch_id: UUID | None = None,
                 location_id: UUID | None = None, terms_days: int | None = None, notes: str | None = None) -> DocView:
    """Take an order from a customer (without a quotation). Submit it to confirm it. Needs 'invoices.manage'."""
    return _create(session, "order", customer_id=customer_id, lines=lines, branch_id=branch_id,
                   location_id=location_id, valid_until=None, terms_days=terms_days, notes=notes)


def _own(session: Session, document_id: UUID, kind: str, *, lock: bool = True) -> SalesDocument:
    document = pos_repo.get_document(session, document_id, lock=lock)
    if document is None or document.doc_kind != kind or not _can_see(document):
        raise NotFound("Document not found")
    current_context().require(INVOICES_MANAGE, company_id=document.company_id, branch_id=document.branch_id)
    _expire(session, document)
    return document


def update_document(session: Session, document_id: UUID, *, lines: list[DocLineIn] | None = None,
                    notes: str | None = None, valid_until: date | None = None) -> DocView:
    """Change a draft quotation or order (replace its lines, notes or validity)."""
    document = pos_repo.get_document(session, document_id, lock=True)
    if document is None or not _can_see(document):
        raise NotFound("Document not found")
    current_context().require(INVOICES_MANAGE, company_id=document.company_id, branch_id=document.branch_id)
    _expire(session, document)
    if document.status != "draft":
        raise Conflict(f"A document that is {document.status.replace('_', ' ')} cannot be edited")
    if notes is not None:
        document.notes = notes.strip()[:500] or None
    if valid_until is not None and document.doc_kind == "quotation":
        if valid_until < tills.today():
            raise ValidationFailed("A quotation cannot be valid until a date that has passed")
        document.valid_until = valid_until
    if lines is not None:
        from ziira.modules.crm.public import find_customer

        customer = find_customer(session, document.customer_id) if document.customer_id else None
        if customer is None:
            raise ValidationFailed("Customer not found")
        priced = _price_lines(session, customer, document.branch_id, lines)
        pos_repo.delete_document_lines(session, document.id)
        _write(session, document, priced)
    session.flush()
    audit_record(session, "update", f"pos.sales_{document.doc_kind}", document.id, {"total": document.total})
    return DocView(document, pos_repo.document_lines(session, document.id))


# --------------------------------------------------------------------------- quotations
def send_quotation(session: Session, document_id: UUID) -> DocView:
    """Mark a draft quotation as sent to the customer."""
    document = _own(session, document_id, "quotation")
    if document.status != "draft":
        raise Conflict(f"This quotation is {document.status.replace('_', ' ')}")
    document.status = "sent"
    session.flush()
    audit_record(session, "send", "pos.sales_quotation", document.id, None)
    return DocView(document, pos_repo.document_lines(session, document.id))


def confirm_quotation(session: Session, document_id: UUID) -> DocView:
    """The customer accepted: make a sales order with the quotation's lines and prices. The order then needs
    submitting (and approval, if a rule applies to its amount) before anything is delivered."""
    quote = _own(session, document_id, "quotation")
    if quote.status not in OPEN_QUOTE:
        raise Conflict(f"This quotation is {quote.status.replace('_', ' ')}: it cannot be accepted")
    lines = pos_repo.document_lines(session, quote.id)
    if quote.customer_id is None:
        raise ValidationFailed("The quotation has no customer")
    ctx = current_context()
    order = SalesDocument(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=quote.company_id, branch_id=quote.branch_id,
        doc_kind="order", number=next_document_number(session, company_id=quote.company_id, branch_id=quote.branch_id,
                                                      doc_type="sales_order", prefix="SO"),
        customer_id=quote.customer_id, doc_date=tills.today(), source_quotation_id=quote.id,
        location_id=quote.location_id, terms_days=quote.terms_days, notes=quote.notes, subtotal=quote.subtotal,
        tax_total=quote.tax_total, total=quote.total)
    pos_repo.add(session, order)
    for line in lines:
        session.add(SalesDocumentLine(
            tenant_id=ctx.tenant_id, document_id=order.id, line_no=line.line_no, product_id=line.product_id,
            uom_id=line.uom_id, quantity=line.quantity, unit_price=line.unit_price,
            discount_amount=line.discount_amount, tax_code_id=line.tax_code_id, tax_amount=line.tax_amount,
            line_total=line.line_total))
    quote.status = "confirmed"
    session.flush()
    audit_record(session, "accept", "pos.sales_quotation", quote.id, {"order": order.number})
    return DocView(order, pos_repo.document_lines(session, order.id))


# --------------------------------------------------------------------------- orders
def submit_order(session: Session, document_id: UUID) -> DocView:
    """Confirm a draft order. It goes to an approver when a rule applies to its amount (document type `sales_order`)."""
    order = _own(session, document_id, "order")
    if order.status != "draft":
        raise Conflict(f"This order is {order.status.replace('_', ' ')}")
    order.status = "pending_approval"
    session.flush()
    if submit_for_approval(session, company_id=order.company_id, doc_type=ORDER_DOC, doc_id=order.id,
                           amount=order.total) == "approved":
        order.status = "confirmed"
        session.flush()
        audit_record(session, "confirm", "pos.sales_order", order.id, {"number": order.number})
    return DocView(order, pos_repo.document_lines(session, order.id))


def apply_order_decision(session: Session, document_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Confirm or send back an order once its approval has been decided (from `approval.decided`)."""
    order = pos_repo.get_document(session, document_id, lock=True)
    if order is None or order.status != "pending_approval":
        return
    order.status, order.approved_by = ("confirmed", decided_by) if approved else ("draft", None)
    session.flush()
    audit_record(session, "approve" if approved else "reject", "pos.sales_order", order.id, {"number": order.number})


def cancel_document(session: Session, document_id: UUID) -> DocView:
    """Cancel a quotation, or an order nothing has been delivered on."""
    document = pos_repo.get_document(session, document_id, lock=True)
    if document is None or not _can_see(document):
        raise NotFound("Document not found")
    current_context().require(INVOICES_MANAGE, company_id=document.company_id, branch_id=document.branch_id)
    lines = pos_repo.document_lines(session, document.id)
    if document.status in ("cancelled", "fulfilled", "expired"):
        raise Conflict(f"This document is {document.status}")
    if any(x.qty_delivered > 0 for x in lines):
        raise Conflict("Goods have been delivered on this order: it cannot be cancelled")
    document.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", f"pos.sales_{document.doc_kind}", document.id, None)
    return DocView(document, lines)


def invoice_order(session: Session, order_id: UUID, *, lines: list[tuple[UUID, Decimal]] | None = None,
                  location_id: UUID | None = None, issue_date: date | None = None) -> invoices.InvoiceView:
    """Deliver an order, all that is left or the quantities named, and invoice it at the agreed prices. Needs
    'invoices.manage'."""
    order = _own(session, order_id, "order")
    if order.status != "confirmed":
        raise Conflict(f"Only a confirmed order can be delivered; this one is {order.status.replace('_', ' ')}")
    order_lines = {x.id: x for x in pos_repo.document_lines(session, order.id, lock=True)}
    wanted = dict(lines) if lines is not None else {
        line_id: line.quantity - line.qty_delivered for line_id, line in order_lines.items()
        if line.quantity > line.qty_delivered}
    if not wanted:
        raise ValidationFailed("There is nothing left to deliver on this order")
    if lines is not None and len({i for i, _ in lines}) != len(lines):
        raise ValidationFailed("An order line appears once in a delivery")
    invoice_lines = []
    for line_id, quantity in sorted(wanted.items(), key=lambda x: str(x[0])):
        line = order_lines.get(line_id)
        if line is None:
            raise ValidationFailed("A line named does not belong to this order")
        rules.check_quantity(quantity)
        if quantity > line.quantity - line.qty_delivered:
            raise ValidationFailed(f"Only {line.quantity - line.qty_delivered} of that line is left to deliver")
        # the discount agreed for the whole line, shared out by the quantity delivered so far
        before = rules.cents(line.discount_amount * line.qty_delivered / line.quantity)
        after = rules.cents(line.discount_amount * (line.qty_delivered + quantity) / line.quantity)
        invoice_lines.append((line, invoices.InvoiceLineIn(
            product_id=line.product_id, quantity=quantity, unit_price=line.unit_price, discount=after - before,
            order_line_id=line.id)))
    view = invoices.issue_invoice(
        session, customer_id=order.customer_id, lines=[x for _, x in invoice_lines],  # type: ignore[arg-type]
        branch_id=order.branch_id, location_id=location_id or order.location_id, issue_date=issue_date,
        terms_days=order.terms_days, sales_order_id=order.id, notes=order.notes, agreed_prices=True)
    for line, item in invoice_lines:
        line.qty_delivered += item.quantity
    if all(x.qty_delivered >= x.quantity for x in order_lines.values()):
        order.status = "fulfilled"
    session.flush()
    audit_record(session, "deliver", "pos.sales_order", order.id, {"invoice": view.invoice.number})
    return view
