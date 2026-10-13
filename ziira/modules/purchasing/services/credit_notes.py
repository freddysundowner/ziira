"""Use cases: supplier credit notes.

A supplier credits a bill when goods were sent back, when it overcharged, or for any other allowance. A credit note
reduces what is owed on that bill. For goods that were sent back (see `returns`) the books clear "goods received not
invoiced" at the stock's value and put the difference with the credit given to purchase price variance; other credits
name the expense account they reduce.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.public import is_expense_account
from ziira.modules.products.public import tax_code_rate
from ziira.modules.purchasing.domain import rules
from ziira.modules.purchasing.permissions import BILLS_APPROVE
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.repository.models import SupplierCreditNote, SupplierCreditNoteLine
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import today, unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    next_document_number,
    publish,
)

CREDITABLE = ("posted", "part_paid", "paid")


@dataclass(frozen=True)
class CreditLineIn:
    quantity: Decimal
    unit_cost: Decimal                       # before VAT
    return_line_id: UUID | None = None       # goods sent back that this credits
    expense_account_id: UUID | None = None   # anything else: the expense it reduces
    description: str | None = None
    tax_code_id: UUID | None = None          # default for returned goods: the tax code they were billed with


@dataclass
class CreditNoteView:
    credit_note: SupplierCreditNote
    lines: list[SupplierCreditNoteLine]


def get_credit_note(session: Session, note_id: UUID) -> CreditNoteView:
    note = repo.get_credit_note(session, note_id)
    if note is None or not access.can_view(note.company_id, note.branch_id):
        raise NotFound("Credit note not found")
    return CreditNoteView(note, repo.credit_note_lines(session, note.id))


def list_credit_notes(session: Session, *, supplier_id: UUID | None = None, bill_id: UUID | None = None,
                      limit: int = 50, offset: int = 0) -> list[SupplierCreditNote]:
    return repo.list_credit_notes(session, access.view_scopes(), supplier_id=supplier_id, bill_id=bill_id,
                                  limit=min(limit, 200), offset=offset)


def create_credit_note(session: Session, bill_id: UUID, *, supplier_credit_no: str, credit_date: date,
                       lines: list[CreditLineIn]) -> CreditNoteView:
    """Record a credit note from the supplier against one of its posted bills. All the credit notes of a bill together
    cannot be for more than the bill. A bill that was already paid is credited too: the supplier then owes a refund
    (see `refunds`). Needs 'bills.approve'."""
    ctx = current_context()
    bill = repo.get_bill(session, bill_id, lock=True)
    if bill is None or not access.can_view(bill.company_id, bill.branch_id):
        raise NotFound("Bill not found")
    ctx.require(BILLS_APPROVE, company_id=bill.company_id)
    if bill.status not in CREDITABLE:
        raise Conflict(f"A credit note goes against a posted bill; this one is {bill.status.replace('_', ' ')}")
    credit_no = rules.check_invoice_no(supplier_credit_no)
    if repo.credit_note_by_supplier_no(session, bill.supplier_id, credit_no) is not None:
        raise Conflict(f"The supplier's credit note {credit_no} has already been entered")
    if credit_date > today() + timedelta(days=1):
        raise ValidationFailed("The credit note date cannot be in the future")
    if not lines or len(lines) > 200:
        raise ValidationFailed("A credit note has between 1 and 200 lines")

    billed_receipt_lines = {x.receipt_line_id: x for x in repo.bill_lines(session, bill.id)
                            if x.receipt_line_id is not None}
    prepared = []
    stock_value = goods_credit = Decimal(0)
    expenses: dict[UUID, Decimal] = {}
    seen: set[UUID] = set()
    for line in lines:
        rules.check_quantity(line.quantity)
        rules.check_cost(line.unit_cost)
        tax_code_id = line.tax_code_id
        return_line = None
        if line.return_line_id is not None:
            return_line = repo.get_return_line(session, line.return_line_id, lock=True)
            if return_line is None or return_line.receipt_line_id not in billed_receipt_lines:
                raise ValidationFailed("That returned line was not billed on this bill")
            if line.expense_account_id is not None:
                raise ValidationFailed("A line is either returned goods or an expense, not both")
            if line.return_line_id in seen:
                raise ValidationFailed("A returned line appears once in a credit note")
            seen.add(line.return_line_id)
            left = return_line.quantity - return_line.qty_credited
            if line.quantity > left:
                raise ValidationFailed(f"Only {rules.plain(left)} of that returned line can still be credited")
            tax_code_id = tax_code_id or billed_receipt_lines[return_line.receipt_line_id].tax_code_id
        else:
            if line.expense_account_id is None or not (line.description and line.description.strip()):
                raise ValidationFailed("A line that is not returned goods needs an expense account and a description")
            if not unit_enabled(session, "finance") or not is_expense_account(session, bill.company_id,
                                                                              line.expense_account_id):
                raise ValidationFailed("Choose an active expense account of this company (Finance must be enabled)")
        rate = Decimal(0)
        if tax_code_id is not None:
            found = tax_code_rate(session, tax_code_id)
            if found is None:
                raise ValidationFailed("The tax code was not found or is not in use")
            rate = found
        amounts = rules.line_amounts(line.quantity, line.unit_cost, rate)
        prepared.append((line, return_line, tax_code_id, amounts))
        if return_line is not None:
            goods_credit += amounts.net
            stock_value += rules.cents(return_line.stock_value * line.quantity / return_line.quantity)
        else:
            assert line.expense_account_id is not None
            expenses[line.expense_account_id] = expenses.get(line.expense_account_id, Decimal(0)) + amounts.net

    subtotal = sum((a.net for *_, a in prepared), Decimal(0))
    tax_total = sum((a.tax for *_, a in prepared), Decimal(0))
    total = subtotal + tax_total
    room = bill.total - bill.credited
    if total <= 0:
        raise ValidationFailed("A credit note must be worth more than nothing")
    if total > room:
        raise ValidationFailed(f"This credit note ({rules.plain(total)}) is more than is left to credit on the bill "
                               f"({rules.plain(room)})")

    note = SupplierCreditNote(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=bill.company_id, branch_id=bill.branch_id,
        number=next_document_number(session, company_id=bill.company_id, branch_id=bill.branch_id,
                                    doc_type="supplier_credit_note", prefix="CRN"), supplier_id=bill.supplier_id,
        bill_id=bill.id, supplier_credit_no=credit_no, credit_date=credit_date, subtotal=subtotal,
        tax_total=tax_total, total=total)
    repo.add(session, note)
    for line, return_line, tax_code_id, amounts in prepared:
        session.add(SupplierCreditNoteLine(
            tenant_id=ctx.tenant_id, credit_note_id=note.id, return_line_id=line.return_line_id,
            expense_account_id=line.expense_account_id, description=(line.description or "").strip() or None,
            quantity=line.quantity, unit_cost=line.unit_cost, tax_code_id=tax_code_id, tax_amount=amounts.tax,
            line_total=amounts.gross))
        if return_line is not None:
            return_line.qty_credited += line.quantity
            source = repo.get_receipt_line(session, return_line.receipt_line_id)
            if source is not None and source.order_line_id is not None:
                order_line = repo.get_order_line(session, source.order_line_id, lock=True)
                if order_line is not None:
                    order_line.qty_billed = max(order_line.qty_billed - line.quantity, Decimal(0))
    bill.credited += total
    if bill.amount_paid + bill.credited >= bill.total:
        bill.status = "paid"
    session.flush()
    audit_record(session, "credit", "purchasing.supplier_credit_note", note.id,
                 {"number": note.number, "bill": bill.number, "total": total})
    publish(session, Event("credit_note.posted", "purchasing.supplier_credit_note", note.id, {
        "company_id": bill.company_id, "branch_id": bill.branch_id, "business_date": credit_date,
        "number": note.number, "supplier_id": bill.supplier_id, "total": total, "tax": tax_total,
        "stock_value": stock_value, "goods_credit": goods_credit,
        "expenses": [{"account_id": a, "amount": v} for a, v in expenses.items()]}))
    return CreditNoteView(note, repo.credit_note_lines(session, note.id))
