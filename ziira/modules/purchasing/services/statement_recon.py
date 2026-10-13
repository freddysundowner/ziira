"""Use case: check a supplier's statement against our books.

The supplier sends a statement of what it says happened on our account. Each line is matched to what we have -
invoices to our bills by the supplier's invoice number, credit notes by their credit note number, payments by the
reference we paid with (or, failing that, the amount and a date within a week) - and the two balances are compared.
What does not match is listed in both directions: lines the supplier has that we have not entered (a missing bill, a
credit we never received), and things we have that are not on its statement (a payment it has not yet received). What
is left unexplained once those are accounted for is a difference in the opening balance. Nothing is changed: it is a
report to act on.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.payments.public import payments_for_document
from ziira.modules.purchasing.domain import statements as rules
from ziira.modules.purchasing.domain.statements import StatementLine
from ziira.modules.purchasing.permissions import BILLS_MANAGE
from ziira.modules.purchasing.repository import purchasing_repo as repo
from ziira.modules.purchasing.services import access
from ziira.modules.purchasing.services.common import unit_enabled
from ziira.sdk import NotFound, Session, ValidationFailed, current_context

CENT = Decimal("0.01")
PAYMENT_WINDOW_DAYS = 7


@dataclass
class Ours:
    kind: str
    reference: str
    day: date
    amount: Decimal
    used: bool = False


def _ours(session: Session, supplier_id: UUID) -> list[Ours]:
    found: list[Ours] = []
    scopes = access.view_scopes()
    for bill in repo.list_bills(session, scopes, supplier_id=supplier_id, status=None, due_before=None, limit=500,
                                offset=0):
        if bill.status not in ("posted", "part_paid", "paid"):
            continue
        found.append(Ours("invoice", bill.supplier_invoice_no, bill.bill_date, bill.total))
        if unit_enabled(session, "payments"):
            for payment in payments_for_document(session, "supplier_bill", bill.id):
                if payment.status == "posted":
                    found.append(Ours("payment", payment.reference or payment.number, payment.business_date,
                                      payment.amount))
    for note in repo.list_credit_notes(session, scopes, supplier_id=supplier_id, bill_id=None, limit=500, offset=0):
        found.append(Ours("credit", note.supplier_credit_no, note.credit_date, note.total))
    return found


def _match(theirs: StatementLine, candidates: list[Ours]) -> Ours | None:
    wanted = rules.normalise_reference(theirs.reference)
    by_reference = [o for o in candidates if not o.used and o.kind == theirs.kind
                    and rules.normalise_reference(o.reference) == wanted]
    if by_reference:
        return by_reference[0]
    if theirs.kind != "payment":
        return None
    near = [o for o in candidates if not o.used and o.kind == "payment" and abs(o.amount - theirs.amount) < CENT
            and abs((o.day - theirs.day).days) <= PAYMENT_WINDOW_DAYS]
    return near[0] if near else None


def reconcile(session: Session, supplier_id: UUID, lines: list[StatementLine], *,
              their_balance: Decimal | None = None, as_of: date | None = None) -> dict[str, Any]:
    """Compare a supplier's statement with our records. Needs 'bills.manage' for the supplier's company."""
    supplier = repo.get_supplier(session, supplier_id)
    if supplier is None or not access.can_see_company(supplier.company_id):
        raise NotFound("Supplier not found")
    current_context().require(BILLS_MANAGE, company_id=supplier.company_id)
    if not lines:
        raise ValidationFailed("The statement has no lines")
    if len(lines) > rules.MAX_LINES:
        raise ValidationFailed(f"A statement has at most {rules.MAX_LINES} lines")
    end = as_of or max(x.day for x in lines)
    ours = [o for o in _ours(session, supplier_id) if o.day <= end]
    claimed = [x for x in lines if x.day <= end]
    items: list[dict[str, Any]] = []
    explained = Decimal(0)
    for theirs in claimed:
        mine = _match(theirs, ours)
        row: dict[str, Any] = {"date": theirs.day, "kind": theirs.kind, "reference": theirs.reference,
                               "their_amount": theirs.amount, "our_amount": None, "status": "missing_here", "note": ""}
        if mine is None:
            row["note"] = {"invoice": "We have no bill with this invoice number",
                           "credit": "We have no credit note with this number",
                           "payment": "We have no payment that matches"}[theirs.kind]
            explained += rules.effect(theirs.kind, theirs.amount)
        else:
            mine.used = True
            row["our_amount"] = mine.amount
            if abs(mine.amount - theirs.amount) < CENT:
                row["status"] = "matched"
            else:
                row["status"] = "amount_differs"
                row["note"] = f"They say {theirs.amount}, we have {mine.amount}"
                explained += rules.effect(theirs.kind, theirs.amount - mine.amount)
        items.append(row)
    leftover = [o for o in ours if not o.used]
    missing_there = [{"kind": o.kind, "reference": o.reference, "date": o.day, "amount": o.amount,
                      "note": {"invoice": "A bill we entered that is not on their statement",
                               "credit": "A credit note we have that is not on their statement",
                               "payment": "A payment we made that they have not shown"}[o.kind]} for o in leftover]
    for gone in leftover:
        explained -= rules.effect(gone.kind, gone.amount)
    our_balance = sum((rules.effect(o.kind, o.amount) for o in ours), Decimal(0))
    stated = their_balance if their_balance is not None else sum(
        (rules.effect(x.kind, x.amount) for x in claimed), Decimal(0))
    difference = stated - our_balance
    return {
        "supplier_id": supplier.id, "supplier": supplier.name, "as_of": end, "their_balance": stated,
        "our_balance": our_balance, "difference": difference, "explained_by_lines": explained,
        "unexplained": difference - explained, "items": items, "missing_there": missing_there,
        "summary": {s: sum(1 for i in items if i["status"] == s) for s in ("matched", "amount_differs", "missing_here")}
                   | {"missing_there": len(missing_there)}}



