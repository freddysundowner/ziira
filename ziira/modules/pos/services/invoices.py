"""Use cases: sales invoices - what a customer owes.

Two kinds share one table and one set of rules for payment:

* a **credit sale** at the till makes an invoice for the part of the sale left on account (`kind = credit_sale`; its
  lines are the sale's), and
* an **invoice** issued to a business customer, directly or from a sales order, which delivers the goods
  (`kind = invoice`).

Issuing an invoice publishes `sale.posted` (the stock leaves and Finance debits accounts receivable against sales and
VAT) and `invoice.issued`. An invoice is paid by customer receipts (`customer_receipts`) and reduced by credit notes
(`returns`); it is never edited - a wrong invoice is cancelled and issued again.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.crm.public import CustomerView
from ziira.modules.inventory.public import location_scope, posted_cost
from ziira.modules.pos.domain import sales as rules
from ziira.modules.pos.permissions import INVOICES_MANAGE, PRICE_OVERRIDE, RECEIVABLES_MANAGE, RECEIVABLES_VIEW
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import Sale, SalesDocumentLine, SalesInvoice, SalesInvoiceLine
from ziira.modules.pos.services import credit, tills
from ziira.modules.pos.services.common import unit_enabled
from ziira.modules.products.public import find_product, selling_prices
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    next_document_number,
    publish,
)

PRICE_OVERRIDE_REASONS = "price_override"
CANCEL_ALLOWED = ("issued",)


@dataclass(frozen=True)
class InvoiceLineIn:
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal | None = None          # tax-inclusive; None: the customer's list price
    discount: Decimal = Decimal(0)
    reason_code_id: UUID | None = None         # why the price or discount differs from the list
    batch_id: UUID | None = None
    order_line_id: UUID | None = None          # a line of the sales order being delivered
    description: str | None = None             # the line's own wording (a service line: "Design, 3 h")


@dataclass
class InvoiceView:
    invoice: SalesInvoice
    lines: list[SalesInvoiceLine]


# --------------------------------------------------------------------------- reading
def invoice_scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in (INVOICES_MANAGE, RECEIVABLES_VIEW, RECEIVABLES_MANAGE):
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found.update(scopes)
    return sorted(found, key=str)


def can_see(invoice: SalesInvoice) -> bool:
    scopes = invoice_scopes()
    if scopes is None:
        return True
    return any((c is None or c == invoice.company_id) and (b is None or b == invoice.branch_id) for c, b in scopes)


def get_invoice(session: Session, invoice_id: UUID) -> InvoiceView:
    invoice = pos_repo.get_invoice(session, invoice_id)
    if invoice is None or not can_see(invoice):
        raise NotFound("Invoice not found")
    return InvoiceView(invoice, pos_repo.invoice_lines(session, invoice.id))


def list_invoices(session: Session, *, customer_id: UUID | None = None, status: str | None = None,
                  due_before: date | None = None, number: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[SalesInvoice]:
    return pos_repo.list_invoices(session, invoice_scopes(), customer_id=customer_id, status=status,
                                  due_before=due_before, number=number.strip().upper() if number else None,
                                  limit=min(limit, 200), offset=offset)


def outstanding(invoice: SalesInvoice) -> Decimal:
    """What is still owed on an invoice."""
    if invoice.status == "cancelled":
        return Decimal(0)
    return invoice.total - invoice.amount_paid - invoice.credited


def settle_status(invoice: SalesInvoice) -> None:
    """Set the status from what has been paid and credited."""
    if invoice.status == "cancelled":
        return
    settled = invoice.amount_paid + invoice.credited
    invoice.status = "paid" if settled >= invoice.total else ("part_paid" if settled > 0 else "issued")


# --------------------------------------------------------------------------- credit sales
def issue_credit_sale_invoice(session: Session, sale: Sale, customer: CustomerView,
                              credit_amount: Decimal) -> SalesInvoice:
    """The invoice for the part of a till sale left on account. Its VAT is the sale's, in proportion."""
    ctx = current_context()
    tax = rules.cents(sale.tax_total * credit_amount / sale.total)
    invoice = SalesInvoice(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=sale.company_id, branch_id=sale.branch_id,
        number=next_document_number(session, company_id=sale.company_id, branch_id=sale.branch_id,
                                    doc_type="sales_invoice", prefix="INV"), customer_id=customer.id,
        sale_id=sale.id, issue_date=sale.business_date, due_date=credit.due_date(sale.business_date, customer),
        subtotal=credit_amount - tax, tax_total=tax, total=credit_amount, kind="credit_sale",
        location_id=sale.location_id)
    pos_repo.add(session, invoice)
    audit_record(session, "issue", "pos.sales_invoice", invoice.id,
                 {"number": invoice.number, "customer": customer.code, "total": credit_amount, "sale": sale.number})
    publish(session, Event("invoice.issued", "pos.sales_invoice", invoice.id, {
        "company_id": sale.company_id, "branch_id": sale.branch_id, "number": invoice.number,
        "customer_id": customer.id, "total": credit_amount, "due_date": invoice.due_date, "sale_id": sale.id}))
    return invoice


# --------------------------------------------------------------------------- invoices to business customers
def issue_invoice(session: Session, *, customer_id: UUID, lines: list[InvoiceLineIn], branch_id: UUID | None = None,
                  location_id: UUID | None = None, issue_date: date | None = None, terms_days: int | None = None,
                  sales_order_id: UUID | None = None, notes: str | None = None,
                  agreed_prices: bool = False, settled_now: Decimal = Decimal(0)) -> InvoiceView:
    """Invoice a customer and deliver the goods. Prices include VAT; the customer's group price list applies. The credit
    check applies as for a credit sale. Needs 'invoices.manage' at the branch (that of the stock location when one is
    named). `agreed_prices` (a confirmed sales order) takes the prices and discounts as agreed with the customer.
    `settled_now` is the part the caller will pay or settle in the same transaction (a checkout paid at the desk): it
    does not count against the customer's credit limit."""
    ctx = current_context()
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Enable CRM to invoice customers")
    company_id = _customer_company(session, customer_id)
    customer = credit.load_customer(session, customer_id, company_id, for_credit=True)
    assert customer is not None
    if not lines or len(lines) > rules.MAX_LINES:
        raise ValidationFailed(f"An invoice has between 1 and {rules.MAX_LINES} lines")

    stock_branch = None
    if location_id is not None:
        found = location_scope(session, location_id)
        if found is None or found[0] != company_id:
            raise ValidationFailed("The stock location was not found in this company")
        stock_branch = found[1]
    branch_id = stock_branch or branch_id
    if branch_id is None:
        raise ValidationFailed("Say which branch is invoicing (or name the stock location)")
    ctx.require(INVOICES_MANAGE, company_id=company_id, branch_id=branch_id)
    day = issue_date or tills.today(session, company_id)

    products = {}
    for line in lines:
        product = find_product(session, line.product_id)
        if product is None or product.company_id != company_id or not product.is_active:
            raise ValidationFailed("A product on the invoice was not found in this company")
        products[line.product_id] = product
    if location_id is None and any(p.product_type == "stock" for p in products.values()):
        raise ValidationFailed("Name the stock location the goods leave from")
    prices = selling_prices(session, company_id, branch_id, set(products), day, customer.customer_group)
    can_override = ctx.can(PRICE_OVERRIDE, company_id=company_id, branch_id=branch_id)

    rows: list[SalesInvoiceLine] = []
    amounts: list[rules.LineAmounts] = []
    for number, line in enumerate(lines, start=1):
        product = products[line.product_id]
        list_price = prices.get(product.id)
        unit = line.unit_price if line.unit_price is not None else list_price
        if unit is None:
            raise ValidationFailed(f"{product.sku} has no price: ask a manager to set one")
        if not agreed_prices and (list_price is None or unit != list_price or line.discount > 0
                                  or line.reason_code_id is not None):
            if not can_override:
                raise Forbidden("Changing a price or giving a discount needs the price override permission")
            check_reason(session, PRICE_OVERRIDE_REASONS, line.reason_code_id)
        amount = rules.price_line(line.quantity, unit, line.discount, product.vat_rate)
        amounts.append(amount)
        rows.append(SalesInvoiceLine(
            tenant_id=ctx.tenant_id, invoice_id=UUID(int=0), line_no=number, product_id=product.id,
            uom_id=product.base_uom_id, quantity=line.quantity, unit_price=unit, discount_amount=line.discount,
            tax_code_id=product.tax_code_id, tax_amount=amount.tax, line_total=amount.gross, batch_id=line.batch_id,
            order_line_id=line.order_line_id, price_reason_code_id=line.reason_code_id,
            list_price=list_price if list_price is not None else unit,
            description=(line.description or "").strip()[:300] or None))
    total = sum((a.gross for a in amounts), Decimal(0))
    tax_total = sum((a.tax for a in amounts), Decimal(0))
    if total <= 0:
        raise ValidationFailed("An invoice must be worth more than nothing")
    credit.check_credit(session, customer, max(total - settled_now, Decimal(0)), offline=False)
    terms = customer.payment_terms_days if terms_days is None else terms_days
    if terms < 0 or terms > 365:
        raise ValidationFailed("Payment terms are between 0 and 365 days")

    invoice = SalesInvoice(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="sales_invoice",
                                    prefix="INV"), customer_id=customer.id, sales_order_id=sales_order_id,
        issue_date=day, due_date=day + timedelta(days=terms), subtotal=total - tax_total, tax_total=tax_total,
        total=total, kind="invoice", location_id=location_id, notes=(notes or "").strip()[:500] or None)
    pos_repo.add(session, invoice)
    for row in rows:
        row.invoice_id = invoice.id
        session.add(row)
    session.flush()
    publish(session, Event("sale.posted", "pos.sales_invoice", invoice.id, {
        "company_id": company_id, "branch_id": branch_id, "business_date": day, "number": invoice.number,
        "location_id": location_id, "net": total - tax_total, "tax": tax_total, "customer_id": customer.id,
        "offline": False, "payments": [{"method": "credit", "amount": total}],
        "lines": [{"line_id": row.id, "product_id": row.product_id, "quantity": row.quantity,
                   "batch_id": row.batch_id} for row in rows]}))
    costs = posted_cost(session, "sale", invoice.id)
    for row in rows:
        if row.id in costs:
            row.cost_amount = costs[row.id]
    session.flush()
    audit_record(session, "issue", "pos.sales_invoice", invoice.id,
                 {"number": invoice.number, "customer": customer.code, "total": total})
    publish(session, Event("invoice.issued", "pos.sales_invoice", invoice.id, {
        "company_id": company_id, "branch_id": branch_id, "number": invoice.number, "customer_id": customer.id,
        "total": total, "due_date": invoice.due_date}))
    return InvoiceView(invoice, rows)


def _customer_company(session: Session, customer_id: UUID) -> UUID:
    from ziira.modules.crm.public import find_customer

    found = find_customer(session, customer_id)
    if found is None:
        raise ValidationFailed("Customer not found")
    return found.company_id


def cancel_invoice(session: Session, invoice_id: UUID, reason: str) -> InvoiceView:
    """Cancel an invoice nothing has been paid or credited on: the goods come back into stock at the cost they left with
    and the books are reversed. A credit sale is cancelled by voiding the sale. Needs 'invoices.manage'; a reason is
    required."""
    invoice = pos_repo.get_invoice(session, invoice_id, lock=True)
    if invoice is None or not can_see(invoice):
        raise NotFound("Invoice not found")
    current_context().require(INVOICES_MANAGE, company_id=invoice.company_id, branch_id=invoice.branch_id)
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if invoice.kind == "credit_sale":
        raise ValidationFailed("This invoice is for a sale on credit: void the sale instead")
    if invoice.kind == "opening_balance":
        raise ValidationFailed("This is an opening balance brought in when the business started on Ziira: it is "
                               "taken out by reversing the whole import (Admin > Import data)")
    if invoice.status not in CANCEL_ALLOWED:
        raise Conflict(f"An invoice that is {invoice.status.replace('_', ' ')} cannot be cancelled"
                       + (": reverse its payments first" if invoice.amount_paid > 0 else ""))
    if invoice.credited > 0 or pos_repo.returns_of_invoice(session, invoice.id):
        raise ValidationFailed("Goods have been taken back on this invoice: it cannot be cancelled")
    lines = pos_repo.invoice_lines(session, invoice.id)
    for line in lines:
        if line.order_line_id is not None:
            order_line = session.get(SalesDocumentLine, line.order_line_id)
            if order_line is not None:
                order_line.qty_delivered = max(order_line.qty_delivered - line.quantity, Decimal(0))
    invoice.status, invoice.cancelled_at = "cancelled", datetime.now(UTC)
    invoice.cancelled_by, invoice.cancel_reason = current_context().user_id, reason.strip()
    session.flush()
    audit_record(session, "cancel", "pos.sales_invoice", invoice.id,
                 {"number": invoice.number, "reason": reason.strip()})
    publish(session, Event("sale.returned", "pos.sales_invoice", invoice.id, {
        "company_id": invoice.company_id, "branch_id": invoice.branch_id,
        "business_date": tills.today(session, invoice.company_id),
        "number": f"{invoice.number} (cancelled)", "sale_id": invoice.id, "location_id": invoice.location_id,
        "net": invoice.subtotal, "tax": invoice.tax_total, "customer_id": invoice.customer_id, "voided": True,
        "payments": [{"method": "credit", "amount": invoice.total}],
        "lines": [{"line_id": x.id, "sale_line_id": x.id, "product_id": x.product_id, "quantity": x.quantity,
                   "batch_id": x.batch_id} for x in lines]}))
    publish(session, Event("invoice.cancelled", "pos.sales_invoice", invoice.id, {
        "company_id": invoice.company_id, "number": invoice.number, "customer_id": invoice.customer_id,
        "total": invoice.total, "reason": reason.strip()}))
    return InvoiceView(invoice, lines)
