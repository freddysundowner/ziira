"""Use cases: supplier bills and the three-way match.

    draft --submit--> matched / not required --(approval rule by amount)--> posted --pay--> part_paid / paid
                  \\-> exception --(a different person approves, with a reason)--> posted

A bill for goods is checked against the receipt and the order (the *three-way match*): the quantity billed cannot be
more than was received and not yet billed, and the cost per unit must be within the company's tolerance of the order's
cost. A bill that passes posts; one that does not is an *exception* that someone else must approve, with a reason,
before it posts. Posting publishes `bill.posted`, and Finance clears "goods received not invoiced" (at what was
received), books any price difference, VAT input and the amount owed to the supplier.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.finance.public import is_expense_account
from ziira.modules.payments.public import DocumentPayment, payments_for_document, record_payment, reverse_payment
from ziira.modules.products.public import find_product, tax_code_rate
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import BILLS_APPROVE, BILLS_MANAGE, BILLS_PAY
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import SupplierBill, SupplierBillLine
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import active_supplier, today, unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    check_reason,
    company_setting,
    current_context,
    flag_for_review,
    next_document_number,
    publish,
    submit_for_approval,
)

DOC_TYPE = "supplier_bill"
EXCEPTION_REASONS = "bill_exception"
PAYABLE = ("posted", "part_paid")


@dataclass(frozen=True)
class BillLineIn:
    quantity: Decimal
    unit_cost: Decimal                       # before VAT
    receipt_line_id: UUID | None = None      # goods: the receipt line being billed
    expense_account_id: UUID | None = None   # anything else: the expense account it belongs to
    description: str | None = None
    tax_code_id: UUID | None = None          # default for goods: the order's / product's; for expenses: none
    landed_receipt_id: UUID | None = None    # a transport or duty charge for the goods of this receipt


@dataclass
class BillView:
    bill: SupplierBill
    lines: list[SupplierBillLine]


def _view(session: Session, bill: SupplierBill) -> BillView:
    return BillView(bill, repo.bill_lines(session, bill.id))


def _own(session: Session, bill_id: UUID, *, lock: bool = False) -> SupplierBill:
    bill = repo.get_bill(session, bill_id, lock=lock)
    if bill is None or not access.can_view(bill.company_id, bill.branch_id):
        raise NotFound("Bill not found")
    return bill


def get_bill(session: Session, bill_id: UUID) -> BillView:
    return _view(session, _own(session, bill_id))


def list_bills(session: Session, *, supplier_id: UUID | None = None, status: str | None = None,
               due_before: date | None = None, limit: int = 50, offset: int = 0) -> list[SupplierBill]:
    return repo.list_bills(session, access.view_scopes(), supplier_id=supplier_id, status=status,
                           due_before=due_before, limit=min(limit, 200), offset=offset)


# --------------------------------------------------------------------------- drafting
@dataclass(frozen=True)
class Prepared:
    """A bill line checked and worked out, ready to store."""

    line: BillLineIn
    product_id: UUID | None
    order_line_id: UUID | None
    tax_code_id: UUID | None
    branch_id: UUID | None
    amounts: rules.Amounts


def _build(session: Session, company_id: UUID, supplier_id: UUID, lines: list[BillLineIn]) -> list[Prepared]:
    if not lines or len(lines) > 200:
        raise ValidationFailed("A bill has between 1 and 200 lines")
    built = []
    seen: set[UUID] = set()
    for line in lines:
        rules.check_quantity(line.quantity)
        rules.check_cost(line.unit_cost)
        product_id = order_line_id = tax_code_id = branch_id = None
        if line.receipt_line_id is not None:
            receipt_line = repo.get_receipt_line(session, line.receipt_line_id)
            receipt = repo.get_receipt(session, receipt_line.receipt_id) if receipt_line else None
            if receipt_line is None or receipt is None or receipt.supplier_id != supplier_id \
                    or receipt.company_id != company_id or receipt.status != "posted":
                raise ValidationFailed("A line names goods that this supplier did not deliver to this company")
            if line.receipt_line_id in seen:
                raise ValidationFailed("A receipt line appears once in a bill")
            seen.add(line.receipt_line_id)
            if line.expense_account_id is not None:
                raise ValidationFailed("A line is either goods received or an expense, not both")
            order_line = repo.get_order_line(session, receipt_line.order_line_id) if receipt_line.order_line_id \
                else None
            product = find_product(session, receipt_line.product_id)
            product_id, order_line_id = receipt_line.product_id, receipt_line.order_line_id
            branch_id = receipt.branch_id
            tax_code_id = line.tax_code_id or (order_line.tax_code_id if order_line else
                                               (product.tax_code_id if product else None))
        elif line.landed_receipt_id is not None:
            receipt = repo.get_receipt(session, line.landed_receipt_id)
            if receipt is None or receipt.company_id != company_id or receipt.status != "posted":
                raise ValidationFailed("A landed cost line names goods that were not received by this company")
            if line.expense_account_id is not None or line.receipt_line_id is not None:
                raise ValidationFailed("A landed cost line is not also goods or an expense")
            if line.quantity != 1:
                raise ValidationFailed("A landed cost line has a quantity of 1 and the charge as its cost")
            branch_id, tax_code_id = receipt.branch_id, line.tax_code_id
        else:
            if line.expense_account_id is None or not (line.description and line.description.strip()):
                raise ValidationFailed("A line that is not goods needs an expense account and a description")
            if not unit_enabled(session, "finance") or not is_expense_account(session, company_id,
                                                                              line.expense_account_id):
                raise ValidationFailed("Choose an active expense account of this company (Finance must be enabled)")
            tax_code_id = line.tax_code_id
        rate = Decimal(0)
        if tax_code_id is not None:
            found = tax_code_rate(session, tax_code_id)
            if found is None:
                raise ValidationFailed("The tax code was not found or is not in use")
            rate = found
        built.append(Prepared(line, product_id, order_line_id, tax_code_id, branch_id,
                              rules.line_amounts(line.quantity, line.unit_cost, rate)))
    return built


def _write(session: Session, bill: SupplierBill, built: list[Prepared]) -> None:
    ctx = current_context()
    for item in built:
        line = item.line
        session.add(SupplierBillLine(
            tenant_id=ctx.tenant_id, bill_id=bill.id, order_line_id=item.order_line_id,
            receipt_line_id=line.receipt_line_id, product_id=item.product_id,
            expense_account_id=line.expense_account_id, description=(line.description or "").strip() or None,
            quantity=line.quantity, unit_cost=line.unit_cost, tax_code_id=item.tax_code_id,
            tax_amount=item.amounts.tax, line_total=item.amounts.gross, landed_receipt_id=line.landed_receipt_id))
    bill.subtotal = sum((x.amounts.net for x in built), Decimal(0))
    bill.tax_total = sum((x.amounts.tax for x in built), Decimal(0))
    bill.total = bill.subtotal + bill.tax_total
    session.flush()


def create_bill(session: Session, *, supplier_id: UUID, supplier_invoice_no: str, bill_date: date,
                lines: list[BillLineIn], due_date: date | None = None, authority_ref: str | None = None) -> BillView:
    """Enter a supplier's invoice as a draft. Goods lines name the receipt line they bill; other costs name an expense
    account. Needs 'bills.manage' for the company (and branch of the goods)."""
    ctx = current_context()
    supplier = repo.get_supplier(session, supplier_id)
    if supplier is None or not access.can_see_company(supplier.company_id):
        raise ValidationFailed("Supplier not found")
    company_id = supplier.company_id
    active_supplier(supplier, company_id)
    ctx.require(BILLS_MANAGE, company_id=company_id)
    check_company(session, company_id)
    invoice_no = rules.check_invoice_no(supplier_invoice_no)
    if repo.bill_by_invoice(session, supplier.id, invoice_no) is not None:
        raise Conflict(f"{supplier.name}'s invoice {invoice_no} has already been entered")
    if due_date is None:
        due_date = bill_date + timedelta(days=supplier.payment_terms_days)
    if due_date < bill_date:
        raise ValidationFailed("The due date cannot be before the bill date")
    if bill_date > today() + timedelta(days=1):
        raise ValidationFailed("The bill date cannot be in the future")
    built = _build(session, company_id, supplier.id, lines)
    branches = {x.branch_id for x in built if x.branch_id is not None}
    branch_id = branches.pop() if len(branches) == 1 else None
    bill = SupplierBill(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="supplier_bill",
                                    prefix="BILL"), supplier_id=supplier.id, supplier_invoice_no=invoice_no,
        bill_date=bill_date, due_date=due_date, subtotal=Decimal(0), tax_total=Decimal(0), total=Decimal(0),
        authority_ref=(authority_ref or "").strip() or None)
    repo.add(session, bill)
    _write(session, bill, built)
    audit_record(session, "create", "purchasing.supplier_bill", bill.id,
                 {"number": bill.number, "supplier": supplier.code, "invoice": invoice_no, "total": bill.total})
    return _view(session, bill)


def update_bill(session: Session, bill_id: UUID, *, lines: list[BillLineIn] | None = None,
                due_date: date | None = None) -> BillView:
    """Change a draft bill's lines or due date. Needs 'bills.manage'."""
    bill = _own(session, bill_id, lock=True)
    current_context().require(BILLS_MANAGE, company_id=bill.company_id)
    if bill.status != "draft":
        raise Conflict(f"A bill that is {bill.status.replace('_', ' ')} cannot be edited")
    if due_date is not None:
        if due_date < bill.bill_date:
            raise ValidationFailed("The due date cannot be before the bill date")
        bill.due_date = due_date
    if lines is not None:
        built = _build(session, bill.company_id, bill.supplier_id, lines)
        repo.delete_bill_lines(session, bill.id)
        _write(session, bill, built)
    session.flush()
    audit_record(session, "update", "purchasing.supplier_bill", bill.id, {"total": bill.total})
    return _view(session, bill)


def cancel_bill(session: Session, bill_id: UUID) -> BillView:
    """Throw away a bill that was not posted (the supplier's invoice number can be entered again). Needs
    'bills.manage'."""
    bill = _own(session, bill_id, lock=True)
    current_context().require(BILLS_MANAGE, company_id=bill.company_id)
    if bill.status not in ("draft", "pending_approval"):
        raise Conflict(f"A bill that is {bill.status.replace('_', ' ')} cannot be cancelled")
    bill.status = "cancelled"
    session.flush()
    audit_record(session, "cancel", "purchasing.supplier_bill", bill.id, {"number": bill.number})
    return _view(session, bill)


# --------------------------------------------------------------------------- matching and posting
def _match(session: Session, bill: SupplierBill, lines: list[SupplierBillLine]) -> list[str]:
    """The problems found checking a bill's goods lines against their receipts and orders (goods already sent back do
    not count as received), and its landed cost lines against what the receipts recorded."""
    ids = [x.receipt_line_id for x in lines if x.receipt_line_id is not None]
    received = {x.id: x for x in repo.lock_receipt_lines(session, ids)}
    tolerance = Decimal(company_setting(session, bill.company_id, "bill_match_tolerance_percent"))
    problems: list[str] = []
    landed_now: dict[UUID, Decimal] = {}
    for line in lines:
        if line.landed_receipt_id is not None:
            receipt = repo.get_receipt(session, line.landed_receipt_id)
            assert receipt is not None
            net = line.line_total - line.tax_amount
            landed_now[receipt.id] = landed_now.get(receipt.id, Decimal(0)) + net
            if landed_now[receipt.id] + repo.landed_billed_for_receipt(session, receipt.id, exclude_bill=bill.id) \
                    > receipt.landed_cost:
                problems.append(f"Receipt {receipt.number}: landed cost billed would be more than the "
                                f"{rules.plain(receipt.landed_cost)} recorded on the receipt")
            continue
        if line.receipt_line_id is None:
            continue
        receipt_line = received[line.receipt_line_id]
        order_line = repo.get_order_line(session, line.order_line_id) if line.order_line_id else None
        product = find_product(session, receipt_line.product_id)
        problems += rules.match_problems(
            label=product.sku if product else "Goods", billed_qty=line.quantity, billed_cost=line.unit_cost,
            received_qty=receipt_line.quantity - repo.returned_on_receipt_line(session, receipt_line.id),
            already_billed=repo.billed_on_receipt_line(session, receipt_line.id, exclude_bill=bill.id),
            received_cost=receipt_line.unit_cost, ordered_cost=order_line.unit_cost if order_line else None,
            tolerance_percent=tolerance)
    return problems


def submit_bill(session: Session, bill_id: UUID) -> BillView:
    """Check a draft bill and post it. A bill for goods is matched to its receipts and orders; if it does not match it
    becomes an exception that someone else must approve. Needs 'bills.manage'."""
    bill = _own(session, bill_id, lock=True)
    ctx = current_context()
    ctx.require(BILLS_MANAGE, company_id=bill.company_id)
    if bill.status != "draft":
        raise Conflict(f"This bill is {bill.status.replace('_', ' ')}")
    supplier = active_supplier(repo.get_supplier(session, bill.supplier_id), bill.company_id)
    lines = repo.bill_lines(session, bill.id)
    if bill.total <= 0:
        raise ValidationFailed("A bill must be worth more than nothing")
    bill.submitted_by = ctx.user_id
    has_goods = any(x.receipt_line_id is not None or x.landed_receipt_id is not None for x in lines)
    problems = _match(session, bill, lines) if has_goods else []
    bill.match_status = "exception" if problems else ("matched" if has_goods else "not_required")
    bill.match_notes = problems
    bill.status = "pending_approval"
    session.flush()
    audit_record(session, "submit", "purchasing.supplier_bill", bill.id,
                 {"number": bill.number, "match": bill.match_status, "problems": problems})
    if problems:
        publish(session, Event("bill.match_exception", "purchasing.supplier_bill", bill.id, {
            "company_id": bill.company_id, "branch_id": bill.branch_id, "number": bill.number,
            "supplier_id": supplier.id, "total": bill.total, "problems": problems}))
        flag_for_review(session, unit="purchasing", kind="bill_match_exception", severity="medium",
                        company_id=bill.company_id, branch_id=bill.branch_id, ref_type="supplier_bill",
                        ref_id=bill.id, amount=bill.total, dedupe_key=f"bill_exception:{bill.id}",
                        message=f"Bill {bill.number} from {supplier.name} does not match its order and receipt: "
                                + "; ".join(problems))
    elif submit_for_approval(session, company_id=bill.company_id, doc_type=DOC_TYPE, doc_id=bill.id,
                             amount=bill.total) == "approved":
        _post(session, bill, lines, approved_by=None)
    return _view(session, bill)


def apply_bill_decision(session: Session, bill_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post or send back a bill whose amount needed approval (from `approval.decided`)."""
    bill = repo.get_bill(session, bill_id, lock=True)
    if bill is None or bill.status != "pending_approval" or bill.match_status == "exception":
        return
    current_context().require(BILLS_APPROVE, company_id=bill.company_id)
    if approved:
        _post(session, bill, repo.bill_lines(session, bill.id), approved_by=decided_by)
    else:
        bill.status = "draft"
        session.flush()
        audit_record(session, "reject", "purchasing.supplier_bill", bill.id, {"number": bill.number})


def approve_exception(session: Session, bill_id: UUID, *, reason_code_id: UUID, note: str | None = None) -> BillView:
    """Accept a bill that did not match, with a reason from the 'bill_exception' list. Not by the person who submitted
    it. Needs 'bills.approve'."""
    bill = _own(session, bill_id, lock=True)
    ctx = current_context()
    ctx.require(BILLS_APPROVE, company_id=bill.company_id)
    if bill.status != "pending_approval" or bill.match_status != "exception":
        raise Conflict("Only a bill waiting as a match exception can be approved here")
    if bill.submitted_by == ctx.user_id or bill.created_by == ctx.user_id:
        raise Forbidden("A bill's exception must be approved by someone who did not enter or submit it")
    check_reason(session, EXCEPTION_REASONS, reason_code_id, note)
    audit_record(session, "approve_exception", "purchasing.supplier_bill", bill.id,
                 {"reason_code_id": reason_code_id, "note": (note or "").strip() or None})
    _post(session, bill, repo.bill_lines(session, bill.id), approved_by=ctx.user_id)
    return _view(session, bill)


def reject_exception(session: Session, bill_id: UUID, *, note: str) -> BillView:
    """Send an exception back to draft so it can be corrected (or cancelled). Needs 'bills.approve'."""
    bill = _own(session, bill_id, lock=True)
    current_context().require(BILLS_APPROVE, company_id=bill.company_id)
    if bill.status != "pending_approval":
        raise Conflict("This bill is not waiting for a decision")
    if not note.strip():
        raise ValidationFailed("Say what is wrong with the bill")
    bill.status, bill.match_status = "draft", "pending"
    session.flush()
    audit_record(session, "reject_exception", "purchasing.supplier_bill", bill.id, {"note": note.strip()})
    return _view(session, bill)


def _figures(session: Session, bill: SupplierBill, lines: list[SupplierBillLine]) -> dict[str, Any]:
    """What a bill means to the books: the value of the goods it clears at what was received, the value billed, the
    expense lines, and the VAT."""
    received_value = billed_value = Decimal(0)
    expenses: dict[UUID, Decimal] = {}
    landed_left: dict[UUID, Decimal] = {}
    for line in lines:
        net = line.line_total - line.tax_amount
        if line.receipt_line_id is not None:
            receipt_line = repo.get_receipt_line(session, line.receipt_line_id)
            assert receipt_line is not None
            received_value += rules.cents(line.quantity * receipt_line.unit_cost)
            billed_value += net
        elif line.landed_receipt_id is not None:
            receipt = repo.get_receipt(session, line.landed_receipt_id)
            assert receipt is not None
            if receipt.id not in landed_left:
                landed_left[receipt.id] = receipt.landed_cost - repo.landed_billed_for_receipt(
                    session, receipt.id, exclude_bill=bill.id)
            cleared = max(min(net, landed_left[receipt.id]), Decimal(0))
            landed_left[receipt.id] -= cleared
            received_value += cleared
            billed_value += net
        elif line.expense_account_id is not None:
            expenses[line.expense_account_id] = expenses.get(line.expense_account_id, Decimal(0)) + net
    return {"stock_received_value": received_value, "stock_billed_value": billed_value, "tax": bill.tax_total,
            "expenses": [{"account_id": a, "amount": v} for a, v in expenses.items()]}


def _plain_json(figures: dict[str, Any]) -> dict[str, Any]:
    """The figures with every amount and id as text, so that they are stored exactly."""
    return dict(json.loads(json.dumps(figures, default=str)))


def _bill_event(bill: SupplierBill, figures: dict[str, Any]) -> dict[str, Any]:
    return {"company_id": bill.company_id, "branch_id": bill.branch_id, "business_date": bill.bill_date,
            "number": bill.number, "supplier_id": bill.supplier_id, "total": bill.total, **figures}


def _post(session: Session, bill: SupplierBill, lines: list[SupplierBillLine], *, approved_by: UUID | None) -> None:
    """Make the bill real: count what is now billed on the orders and tell Finance what is owed."""
    figures = _figures(session, bill, lines)
    for line in lines:
        if line.receipt_line_id is not None and line.order_line_id is not None:
            order_line = repo.get_order_line(session, line.order_line_id, lock=True)
            if order_line is not None:
                order_line.qty_billed += line.quantity
    bill.status, bill.approved_by, bill.posted_at = "posted", approved_by, datetime.now(UTC)
    bill.posted_figures = _plain_json(figures)
    session.flush()
    audit_record(session, "post", "purchasing.supplier_bill", bill.id, {"number": bill.number, "total": bill.total})
    publish(session, Event("bill.posted", "purchasing.supplier_bill", bill.id, _bill_event(bill, figures)))


def reverse_bill(session: Session, bill_id: UUID, *, reason: str) -> BillView:
    """Undo a posted bill that was entered wrongly: the books are reversed, what was billed on the orders goes back, and
    the supplier's invoice number can be entered again. Refused while the bill has payments or credit notes (reverse
    the payments first). Needs 'bills.approve'; a reason is required."""
    bill = _own(session, bill_id, lock=True)
    ctx = current_context()
    ctx.require(BILLS_APPROVE, company_id=bill.company_id)
    if bill.status not in PAYABLE and bill.status != "paid":
        raise Conflict(f"A bill that is {bill.status.replace('_', ' ')} cannot be reversed")
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if bill.amount_paid > 0:
        raise ValidationFailed("This bill has payments: reverse them first")
    if bill.credited > 0 or bill.refunded > 0:
        raise ValidationFailed("This bill has supplier credit notes or refunds against it and cannot be reversed")
    lines = repo.bill_lines(session, bill.id)
    for line in lines:
        if line.receipt_line_id is not None and line.order_line_id is not None:
            order_line = repo.get_order_line(session, line.order_line_id, lock=True)
            if order_line is not None:
                order_line.qty_billed -= line.quantity
    figures = bill.posted_figures or _plain_json(_figures(session, bill, lines))
    bill.status, bill.reversed_at, bill.reversed_by = "reversed", datetime.now(UTC), ctx.user_id
    bill.reverse_reason = reason.strip()
    session.flush()
    audit_record(session, "reverse", "purchasing.supplier_bill", bill.id,
                 {"number": bill.number, "reason": reason.strip()})
    publish(session, Event("bill.reversed", "purchasing.supplier_bill", bill.id, _bill_event(bill, figures)))
    return _view(session, bill)


# --------------------------------------------------------------------------- paying
def pay_bill(session: Session, bill_id: UUID, *, amount: Decimal, method: str,
             payment_account_id: UUID | None = None, external_ref: str | None = None,
             paid_on: date | None = None) -> BillView:
    """Record a payment to the supplier against a posted bill (through Payments). Needs 'bills.pay'. The payment can
    be part of the amount owed but not more."""
    bill = _own(session, bill_id, lock=True)
    ctx = current_context()
    ctx.require(BILLS_PAY, company_id=bill.company_id, branch_id=bill.branch_id)
    if bill.status not in PAYABLE:
        raise Conflict(f"A bill that is {bill.status.replace('_', ' ')} cannot be paid")
    supplier = repo.get_supplier(session, bill.supplier_id)
    if supplier is None or supplier.status == "on_hold":
        raise ValidationFailed("This supplier is on hold: payments are stopped")
    if not unit_enabled(session, "payments"):
        raise ValidationFailed("Enable Payments to pay bills")
    if amount <= 0 or amount != amount.quantize(rules.CENT):
        raise ValidationFailed("A payment is more than zero with at most 2 decimal places")
    owed = bill.total - bill.amount_paid - bill.credited
    if amount > owed:
        raise ValidationFailed(f"Only {rules.plain(owed)} is still owed on this bill")
    day = paid_on or today()
    paid = record_payment(
        session, company_id=bill.company_id, branch_id=bill.branch_id, method=method, direction="out", amount=amount,
        payment_account_id=payment_account_id, business_date=day, external_ref=external_ref, party_type="supplier",
        party_id=bill.supplier_id, allocations=[("supplier_bill", bill.id, amount)])
    bill.amount_paid += amount
    bill.status = "paid" if bill.amount_paid + bill.credited >= bill.total else "part_paid"
    session.flush()
    audit_record(session, "pay", "purchasing.supplier_bill", bill.id,
                 {"amount": amount, "method": method, "payment": paid.number})
    publish(session, Event("supplier.paid", "payments.payment", paid.id, {
        "company_id": bill.company_id, "branch_id": bill.branch_id, "business_date": day, "amount": amount,
        "method": method, "supplier_id": bill.supplier_id, "number": bill.number, "bill_id": bill.id}))
    return _view(session, bill)


# --------------------------------------------------------------------------- what is owed
def payables(session: Session, *, as_of: date | None = None,
             supplier_id: UUID | None = None) -> dict[str, Any]:
    """What the business owes suppliers on posted bills, by supplier, aged by due date."""
    as_of = as_of or today()
    totals: dict[UUID, dict[str, Decimal]] = {}
    for bill in repo.open_bills(session, access.view_scopes(), as_of):
        if supplier_id is not None and bill.supplier_id != supplier_id:
            continue
        owed = bill.total - bill.amount_paid - bill.credited
        row = totals.setdefault(bill.supplier_id, {b: Decimal(0) for b in rules.AGEING_BUCKETS})
        row[rules.ageing_bucket(bill.due_date, as_of)] += owed
    rows: list[dict[str, Any]] = []
    for sid, buckets in totals.items():
        supplier = repo.get_supplier(session, sid)
        rows.append({"supplier_id": sid, "supplier": supplier.name if supplier else "", "total": sum(
            buckets.values(), Decimal(0)), **buckets})
    rows.sort(key=lambda r: str(r["supplier"]))
    grand = {b: sum((Decimal(r[b]) for r in rows), Decimal(0)) for b in rules.AGEING_BUCKETS}
    return {"as_of": as_of, "suppliers": rows, "total": sum(grand.values(), Decimal(0)), "buckets": grand}


# --------------------------------------------------------------------------- payments made on a bill
def list_bill_payments(session: Session, bill_id: UUID) -> list[DocumentPayment]:
    """The payments made against a bill (empty when Payments is not on)."""
    bill = _own(session, bill_id)
    if not unit_enabled(session, "payments"):
        return []
    return payments_for_document(session, "supplier_bill", bill.id)


def reverse_bill_payment(session: Session, bill_id: UUID, *, payment_id: UUID, reason: str) -> BillView:
    """Cancel a payment made against a bill (it went to the wrong place, or bounced). The bill owes that amount
    again and the books follow. Needs 'bills.pay'."""
    bill = _own(session, bill_id, lock=True)
    current_context().require(BILLS_PAY, company_id=bill.company_id, branch_id=bill.branch_id)
    if not unit_enabled(session, "payments"):
        raise ValidationFailed("Payments is not enabled")
    if payment_id not in {p.payment_id for p in payments_for_document(session, "supplier_bill", bill.id)}:
        raise NotFound("That payment was not made against this bill")
    reverse_payment(session, payment_id, reason)             # the event below brings the bill and the books up to date
    return _view(session, bill)


def apply_payment_reversal(session: Session, event: Event) -> None:
    """A payment was reversed in Payments (from `payment.reversed`): any supplier bill it paid is owed again."""
    payload = event.payload
    if payload.get("direction") != "out":
        return
    for allocation in payload.get("allocations") or []:
        if allocation.get("doc_type") != "supplier_bill":
            continue
        bill = repo.get_bill(session, UUID(str(allocation["doc_id"])), lock=True)
        if bill is None:
            continue
        amount = Decimal(str(allocation["amount"]))
        if bill.refunded > rules.refundable(bill.total, bill.amount_paid - amount, bill.credited, Decimal(0)):
            raise ValidationFailed("The supplier has refunded part of this payment: reverse the refund first")
        bill.amount_paid = max(bill.amount_paid - amount, Decimal(0))
        if bill.status in ("part_paid", "paid"):
            bill.status = "paid" if bill.amount_paid + bill.credited >= bill.total else (
                "part_paid" if bill.amount_paid > 0 else "posted")
        session.flush()
        audit_record(session, "payment_reversed", "purchasing.supplier_bill", bill.id,
                     {"payment": payload.get("number"), "amount": amount})
        publish(session, Event("supplier.payment_reversed", "payments.payment", event.aggregate_id, {
            "company_id": bill.company_id, "branch_id": bill.branch_id, "business_date": today(), "amount": amount,
            "method": payload.get("method"), "supplier_id": bill.supplier_id, "number": bill.number,
            "bill_id": bill.id}))
