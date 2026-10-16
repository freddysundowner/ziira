"""Use cases: take goods back from a customer and refund them.

A return names the sale and the lines it covers; the refund is worked out from what each line was really sold for
(discounts and VAT included), so returning every unit of a line gives back exactly what it fetched. Stock goes back at
the cost it left with and the books are reversed (both by reacting to `sale.returned`). Refunds above the approval
threshold wait for an approver, and the stock and money only move when they agree.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.payments.public import account_for_method, record_payment
from ziira.modules.pos.domain import sales as rules
from ziira.modules.pos.permissions import SALES_REFUND
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import Sale, SalesInvoice, SalesReturn, SalesReturnLine
from ziira.modules.pos.services import access, invoices, tills
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    next_document_number,
    publish,
    submit_for_approval,
)

DOC_TYPE = "sales_return"
RETURN_REASONS = "sale_return"
REFUND_METHODS = ("cash", "mobile_money", "exchange", "credit_note")


@dataclass
class ReturnView:
    sales_return: SalesReturn
    lines: list[SalesReturnLine]


def _view(session: Session, ret: SalesReturn) -> ReturnView:
    return ReturnView(ret, pos_repo.return_lines(session, ret.id))


def get_return(session: Session, return_id: UUID) -> ReturnView:
    ret = pos_repo.get_return(session, return_id)
    scopes = access.sale_scopes()
    if ret is None or (scopes is not None and not any(
            (c is None or c == ret.company_id) and (b is None or b == ret.branch_id) for c, b in scopes)):
        raise NotFound("Return not found")
    return _view(session, ret)


def list_returns(session: Session, *, branch_id: UUID | None = None, status: str | None = None, limit: int = 50,
                 offset: int = 0) -> list[SalesReturn]:
    return pos_repo.list_returns(session, access.sale_scopes(), branch_id=branch_id, status=status,
                                 limit=min(limit, 200), offset=offset)


@dataclass
class Source:
    """What is being returned from: a till sale or an invoice, with its lines and what has already come back."""

    id: UUID
    company_id: UUID
    branch_id: UUID | None
    customer_id: UUID | None
    location_id: UUID | None
    number: str
    invoice: SalesInvoice | None
    # line id -> (product, batch, quantity, unit price, line total, line tax)
    lines: dict[UUID, tuple[UUID, UUID | None, Decimal, Decimal, Decimal, Decimal]]
    returned: dict[UUID, Decimal]
    is_invoice: bool


def _sale_source(session: Session, sale: Sale) -> Source:
    return Source(
        sale.id, sale.company_id, sale.branch_id, sale.customer_id, sale.location_id, sale.number,
        pos_repo.invoice_for_sale(session, sale.id, lock=True),
        {x.id: (x.product_id, x.batch_id, x.quantity, x.unit_price, x.line_total, x.tax_amount)
         for x in pos_repo.lines_of(session, sale.id)}, pos_repo.returned_quantities(session, sale.id), False)


def _invoice_source(session: Session, invoice: SalesInvoice) -> Source:
    return Source(
        invoice.id, invoice.company_id, invoice.branch_id, invoice.customer_id, invoice.location_id, invoice.number,
        invoice, {x.id: (x.product_id, x.batch_id, x.quantity, x.unit_price, x.line_total, x.tax_amount)
                  for x in pos_repo.invoice_lines(session, invoice.id)},
        pos_repo.invoice_returned_quantities(session, invoice.id), True)


def create_return(session: Session, sale_id: UUID, *, lines: list[tuple[UUID, Decimal]], reason_code_id: UUID,
                  refund_method: str, note: str | None = None, restock_location_id: UUID | None = None) -> ReturnView:
    """Return part or all of a sale. `lines` are (sale line, quantity). Needs 'sales.refund' at the sale's branch and a
    reason from the 'sale_return' list. A cash refund comes out of the cashier's open till."""
    sale = pos_repo.get_sale(session, sale_id, lock=True)
    scopes = access.sale_scopes()
    if sale is None or (scopes is not None and not any(
            (c is None or c == sale.company_id) and (b is None or b == sale.branch_id) for c, b in scopes)):
        raise NotFound("Sale not found")
    current_context().require(SALES_REFUND, company_id=sale.company_id, branch_id=sale.branch_id)
    if sale.status != "posted":
        raise Conflict("A voided sale has nothing to return")
    return _create(session, _sale_source(session, sale), lines, reason_code_id, refund_method, note,
                   restock_location_id)


def create_invoice_return(session: Session, invoice_id: UUID, *, lines: list[tuple[UUID, Decimal]],
                          reason_code_id: UUID, refund_method: str, note: str | None = None,
                          restock_location_id: UUID | None = None) -> ReturnView:
    """Take goods back from an invoice - the customer's credit note. `lines` are (invoice line, quantity). The refund
    is a credit note (less owed) while the invoice is unpaid, and cash or mobile money once it is paid. Needs
    'sales.refund' at the invoice's branch and a reason from the 'sale_return' list."""
    invoice = pos_repo.get_invoice(session, invoice_id, lock=True)
    if invoice is None or not invoices.can_see(invoice):
        raise NotFound("Invoice not found")
    current_context().require(SALES_REFUND, company_id=invoice.company_id, branch_id=invoice.branch_id)
    if invoice.kind != "invoice":
        raise ValidationFailed("This invoice is an opening balance or a sale on credit, with no goods of its own: "
                               "take goods back against the sale that made it")
    if invoice.status == "cancelled":
        raise Conflict("A cancelled invoice has nothing to return")
    return _create(session, _invoice_source(session, invoice), lines, reason_code_id, refund_method, note,
                   restock_location_id)


def _create(session: Session, source: Source, lines: list[tuple[UUID, Decimal]], reason_code_id: UUID,
            refund_method: str, note: str | None, restock_location_id: UUID | None) -> ReturnView:
    ctx = current_context()
    check_reason(session, RETURN_REASONS, reason_code_id, note)
    if refund_method not in REFUND_METHODS:
        raise ValidationFailed(f"Refund method must be one of: {', '.join(REFUND_METHODS)}")
    if not lines:
        raise ValidationFailed("Choose what is being returned")
    if len({line_id for line_id, _ in lines}) != len(lines):
        raise ValidationFailed("Each line appears once in a return")
    if restock_location_id is not None:
        found = pos_repo.location_branch(session, restock_location_id)
        if found is None or found[0] != source.company_id:
            raise ValidationFailed("The restock location was not found in this company")

    rows: list[SalesReturnLine] = []
    total = tax = Decimal(0)
    for line_id, quantity in sorted(lines, key=lambda x: str(x[0])):
        original = source.lines.get(line_id)
        if original is None:
            raise ValidationFailed("A line to return does not belong to this " + ("invoice" if source.is_invoice
                                                                                  else "sale"))
        product_id, batch_id, sold, price, line_total, line_tax_total = original
        rules.check_quantity(quantity)
        back = source.returned.get(line_id, Decimal(0))
        gross, line_tax = rules.return_amounts(line_total, line_tax_total, sold, back, quantity)
        total += gross
        tax += line_tax
        rows.append(SalesReturnLine(
            tenant_id=ctx.tenant_id, return_id=UUID(int=0), product_id=product_id, batch_id=batch_id,
            quantity=quantity, unit_price=price, tax_amount=line_tax, line_total=gross,
            sale_line_id=None if source.is_invoice else line_id,
            invoice_line_id=line_id if source.is_invoice else None))
    _check_credit_refund(source.invoice, refund_method, total)
    if refund_method == "cash" and pos_repo.open_till_of_user(session, ctx.user_id) is None:  # type: ignore[arg-type]
        raise ValidationFailed("Open a till to pay a cash refund")
    ret = SalesReturn(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=source.company_id, branch_id=source.branch_id,
        number=next_document_number(session, company_id=source.company_id, branch_id=source.branch_id,
                                    doc_type="sales_return", prefix="RET"),
        original_sale_id=None if source.is_invoice else source.id,
        original_invoice_id=source.id if source.is_invoice else None, reason_code_id=reason_code_id,
        refund_method=refund_method, total=total, restock_location_id=restock_location_id,
        status="pending_approval", business_date=tills.today(session, source.company_id), net=total - tax, tax=tax)
    pos_repo.add(session, ret)
    for row in rows:
        row.return_id = ret.id
        session.add(row)
    session.flush()
    audit_record(session, "create", "pos.sales_return", ret.id, {"number": ret.number, "total": total,
                                                                  "from": source.number})
    if submit_for_approval(session, company_id=source.company_id, doc_type=DOC_TYPE, doc_id=ret.id,
                           amount=total) == "approved":
        _post(session, ret, source, rows, approved_by=None)
    return _view(session, ret)


def apply_decision(session: Session, return_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post or reject a return once its approval has been decided (called from `approval.decided`)."""
    ret = pos_repo.get_return(session, return_id, lock=True)
    if ret is None or ret.status != "pending_approval":
        return
    if approved:
        if ret.original_invoice_id is not None:
            invoice = pos_repo.get_invoice(session, ret.original_invoice_id, lock=True)
            if invoice is None or invoice.status == "cancelled":
                raise ValidationFailed("The invoice was cancelled while the return waited: it cannot be refunded")
            source = _invoice_source(session, invoice)
        else:
            sale = pos_repo.get_sale(session, ret.original_sale_id, lock=True) if ret.original_sale_id else None
            if sale is None or sale.status != "posted":
                raise ValidationFailed("The sale was voided while the return waited: it cannot be refunded")
            source = _sale_source(session, sale)
        _post(session, ret, source, pos_repo.return_lines(session, ret.id), approved_by=decided_by)
    else:
        ret.status = "rejected"
        session.flush()
        audit_record(session, "reject", "pos.sales_return", ret.id, {"number": ret.number})


def _post(session: Session, ret: SalesReturn, source: Source, lines: list[SalesReturnLine], *,
          approved_by: UUID | None) -> None:
    """Move the stock and the money for an approved return."""
    till = pos_repo.open_till_of_user(session, ret.created_by) if ret.created_by else None
    day = till.business_date if till is not None else tills.today(session, ret.company_id)
    method = ret.refund_method
    if method == "credit_note":
        target = pos_repo.get_invoice(session, source.invoice.id, lock=True) if source.invoice else None
        _check_credit_refund(target, method, ret.total)
        assert target is not None
        target.credited += ret.total
        invoices.settle_status(target)
        session.flush()
    elif method != "exchange":
        account_id = account_for_method(session, ret.company_id, ret.branch_id, method)
        if account_id is None and method != "cash":
            raise ValidationFailed(f"No {method.replace('_', ' ')} account is set up for this branch")
        paid = record_payment(
            session, company_id=ret.company_id, branch_id=ret.branch_id, method=method, direction="out",
            amount=ret.total, payment_account_id=account_id, business_date=day, party_type="customer",
            party_id=source.customer_id, allocations=[("sales_return", ret.id, ret.total)],
            till_session_id=till.id if (till is not None and method == "cash") else None)
        ret.refund_payment_id = paid.id
    ret.status, ret.approved_by, ret.business_date = "posted", approved_by, day
    session.flush()
    audit_record(session, "post", "pos.sales_return", ret.id, {"number": ret.number, "total": ret.total})
    publish(session, Event("sale.returned", "pos.sales_return", ret.id, {
        "company_id": ret.company_id, "branch_id": ret.branch_id, "business_date": day, "number": ret.number,
        "sale_id": source.id, "location_id": ret.restock_location_id or source.location_id,
        "net": ret.net, "tax": ret.tax, "customer_id": source.customer_id,
        "payments": [{"method": {"exchange": "other", "credit_note": "credit"}.get(method, method),
                      "amount": ret.total}],
        "lines": [{"line_id": line.id, "sale_line_id": line.sale_line_id or line.invoice_line_id,
                   "product_id": line.product_id, "quantity": line.quantity, "batch_id": line.batch_id}
                  for line in lines]}))


def _check_credit_refund(invoice: SalesInvoice | None, method: str, total: Decimal) -> None:
    """A sale left on account is refunded by reducing what the customer owes, until they have paid it."""
    if method == "credit_note":
        if invoice is None:
            raise ValidationFailed("A credit note is for a sale that was left on account")
        if total > invoices.outstanding(invoice):
            raise ValidationFailed(f"The customer owes {invoices.outstanding(invoice)} on this sale: a credit note "
                                   "cannot be for more. Refund the rest in cash or mobile money once it is paid")
    elif invoice is not None and method in ("cash", "mobile_money") and invoices.outstanding(invoice) > 0:
        raise ValidationFailed("This sale was left on account and is still owed: give a credit note instead")
