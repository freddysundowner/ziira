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
from ziira.modules.pos.repository.models import Sale, SalesReturn, SalesReturnLine
from ziira.modules.pos.services import access, tills
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
REFUND_METHODS = ("cash", "mpesa", "exchange")        # a credit note arrives with customer accounts (phase 6)


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


def create_return(session: Session, sale_id: UUID, *, lines: list[tuple[UUID, Decimal]], reason_code_id: UUID,
                  refund_method: str, note: str | None = None, restock_location_id: UUID | None = None) -> ReturnView:
    """Return part or all of a sale. `lines` are (sale line, quantity). Needs 'sales.refund' at the sale's branch and a
    reason from the 'sale_return' list. A cash refund comes out of the cashier's open till."""
    sale = pos_repo.get_sale(session, sale_id, lock=True)
    scopes = access.sale_scopes()
    if sale is None or (scopes is not None and not any(
            (c is None or c == sale.company_id) and (b is None or b == sale.branch_id) for c, b in scopes)):
        raise NotFound("Sale not found")
    ctx = current_context()
    ctx.require(SALES_REFUND, company_id=sale.company_id, branch_id=sale.branch_id)
    check_reason(session, RETURN_REASONS, reason_code_id, note)
    if sale.status != "posted":
        raise Conflict("A voided sale has nothing to return")
    if refund_method not in REFUND_METHODS:
        raise ValidationFailed(f"Refund method must be one of: {', '.join(REFUND_METHODS)}")
    if not lines:
        raise ValidationFailed("Choose what is being returned")
    if len({line_id for line_id, _ in lines}) != len(lines):
        raise ValidationFailed("Each sale line appears once in a return")
    if refund_method == "cash" and pos_repo.open_till_of_user(session, ctx.user_id) is None:  # type: ignore[arg-type]
        raise ValidationFailed("Open a till to pay a cash refund")
    if restock_location_id is not None:
        found = pos_repo.location_branch(session, restock_location_id)
        if found is None or found[0] != sale.company_id:
            raise ValidationFailed("The restock location was not found in this company")

    sold = {line.id: line for line in pos_repo.lines_of(session, sale.id)}
    returned = pos_repo.returned_quantities(session, sale.id)
    rows: list[SalesReturnLine] = []
    total = tax = Decimal(0)
    for line_id, quantity in sorted(lines, key=lambda x: str(x[0])):
        original = sold.get(line_id)
        if original is None:
            raise ValidationFailed("A line to return does not belong to this sale")
        rules.check_quantity(quantity)
        gross, line_tax = rules.return_amounts(original.line_total, original.tax_amount, original.quantity,
                                               returned.get(line_id, Decimal(0)), quantity)
        total += gross
        tax += line_tax
        rows.append(SalesReturnLine(
            tenant_id=ctx.tenant_id, return_id=UUID(int=0), product_id=original.product_id, batch_id=original.batch_id,
            quantity=quantity, unit_price=original.unit_price, tax_amount=line_tax, line_total=gross,
            sale_line_id=line_id))
    ret = SalesReturn(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=sale.company_id, branch_id=sale.branch_id,
        number=next_document_number(session, company_id=sale.company_id, branch_id=sale.branch_id,
                                    doc_type="sales_return", prefix="RET"),
        original_sale_id=sale.id, reason_code_id=reason_code_id, refund_method=refund_method, total=total,
        restock_location_id=restock_location_id, status="pending_approval", business_date=tills.today(),
        net=total - tax, tax=tax)
    pos_repo.add(session, ret)
    for row in rows:
        row.return_id = ret.id
        session.add(row)
    session.flush()
    audit_record(session, "create", "pos.sales_return", ret.id, {"number": ret.number, "total": total,
                                                                  "sale": sale.number})
    if submit_for_approval(session, company_id=sale.company_id, doc_type=DOC_TYPE, doc_id=ret.id,
                           amount=total) == "approved":
        _post(session, ret, sale, rows, approved_by=None)
    return _view(session, ret)


def apply_decision(session: Session, return_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post or reject a return once its approval has been decided (called from `approval.decided`)."""
    ret = pos_repo.get_return(session, return_id, lock=True)
    if ret is None or ret.status != "pending_approval":
        return
    if approved:
        sale = pos_repo.get_sale(session, ret.original_sale_id, lock=True) if ret.original_sale_id else None
        if sale is None or sale.status != "posted":
            raise ValidationFailed("The sale was voided while the return waited: it cannot be refunded")
        _post(session, ret, sale, pos_repo.return_lines(session, ret.id), approved_by=decided_by)
    else:
        ret.status = "rejected"
        session.flush()
        audit_record(session, "reject", "pos.sales_return", ret.id, {"number": ret.number})


def _post(session: Session, ret: SalesReturn, sale: Sale, lines: list[SalesReturnLine], *,
          approved_by: UUID | None) -> None:
    """Move the stock and the money for an approved return."""
    till = pos_repo.open_till_of_user(session, ret.created_by) if ret.created_by else None
    day = till.business_date if till is not None else tills.today()
    method = ret.refund_method
    if method != "exchange":
        account_id = account_for_method(session, ret.company_id, ret.branch_id, method)
        if account_id is None and method != "cash":
            raise ValidationFailed(f"No {method} account is set up for this branch")
        paid = record_payment(
            session, company_id=ret.company_id, branch_id=ret.branch_id, method=method, direction="out",
            amount=ret.total, payment_account_id=account_id, business_date=day, party_type="customer",
            party_id=sale.customer_id, allocations=[("sales_return", ret.id, ret.total)],
            till_session_id=till.id if (till is not None and method == "cash") else None)
        ret.refund_payment_id = paid.id
    ret.status, ret.approved_by, ret.business_date = "posted", approved_by, day
    session.flush()
    audit_record(session, "post", "pos.sales_return", ret.id, {"number": ret.number, "total": ret.total})
    publish(session, Event("sale.returned", "pos.sales_return", ret.id, {
        "company_id": ret.company_id, "branch_id": ret.branch_id, "business_date": day, "number": ret.number,
        "sale_id": sale.id, "location_id": ret.restock_location_id or sale.location_id,
        "net": ret.net, "tax": ret.tax, "customer_id": sale.customer_id,
        "payments": [{"method": "other" if method == "exchange" else method, "amount": ret.total}],
        "lines": [{"line_id": line.id, "sale_line_id": line.sale_line_id, "product_id": line.product_id,
                   "quantity": line.quantity, "batch_id": line.batch_id} for line in lines]}))


