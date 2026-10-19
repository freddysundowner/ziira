"""Public interface of the Point of Sale and Sales module.

Other units use these; they normally talk to POS through events (`sale.posted`, `sale.returned`, `till.closed`).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal
from uuid import UUID

from sqlalchemy import select, text

from ziira.sdk import Session

RECEIPT_EXTRAS = "pos.receipt_extras"


class ReceiptExtra(ABC):
    """Contract of the "pos.receipt_extras" extension point: lines a plugin adds to the foot of a printed document
    (a tax-authority control code, a QR code's text, ...). `kind` is "sale", "invoice" or "receipt"."""

    @abstractmethod
    def lines(self, session: Session, kind: str, document_id: UUID) -> list[str]:
        """Extra lines for the document, or none."""


def open_till_sessions(session: Session, branch_id: UUID, day: date) -> int:
    """How many till sessions of a branch and business date are still open (a day cannot be closed while any is)."""
    return int(session.execute(text(
        "select count(*) from pos.till_session where branch_id = :b and business_date = :d and status = 'open'"),
        {"b": str(branch_id), "d": day}).scalar_one())


def customer_balance(session: Session, customer_id: UUID) -> Decimal:
    """What a customer owes on invoices that are not paid or cancelled, less money they hold on account in advance
    (negative: they are in credit). For statements and credit decisions."""
    owed = Decimal(session.execute(text(
        "select coalesce(sum(total - amount_paid - credited), 0) from pos.sales_invoice where customer_id = :c "
        "and status in ('issued', 'part_paid')"), {"c": str(customer_id)}).scalar_one())
    held = Decimal(session.execute(text(
        "select coalesce(sum(unallocated), 0) from pos.customer_receipt where customer_id = :c and status = 'posted'"),
        {"c": str(customer_id)}).scalar_one())
    return owed - held


def customer_balances(session: Session, customer_ids: list[UUID]) -> dict[UUID, Decimal]:
    """`customer_balance` for many customers at once (two queries, not two per customer)."""
    ids = [str(c) for c in customer_ids]
    balances: dict[UUID, Decimal] = {c: Decimal(0) for c in customer_ids}
    if not ids:
        return balances
    for r in session.execute(text(
            "select customer_id, sum(total - amount_paid - credited) as owed from pos.sales_invoice "
            "where customer_id = any(cast(:ids as uuid[])) and status in ('issued', 'part_paid') group by customer_id"),
            {"ids": ids}):
        balances[r.customer_id] += Decimal(r.owed)
    for r in session.execute(text(
            "select customer_id, sum(unallocated) as held from pos.customer_receipt "
            "where customer_id = any(cast(:ids as uuid[])) and status = 'posted' group by customer_id"),
            {"ids": ids}):
        balances[r.customer_id] -= Decimal(r.held)
    return balances


@dataclass(frozen=True)
class InvoiceLineIn:
    """One line of an invoice made for another unit's work. `unit_price` includes tax, as everywhere in POS; the
    tax code and rate come from the product (a service item: `product_type = service`, so no stock moves).
    `income_account_hint` is reserved (the posting rules decide the account); it is accepted and ignored in v1."""

    product_id: UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal = Decimal(0)
    income_account_hint: str | None = None


@dataclass(frozen=True)
class InvoiceRef:
    """A small view of an issued invoice."""

    id: UUID
    number: str
    total: Decimal
    tax_total: Decimal
    customer_id: UUID
    issue_date: date
    due_date: date
    status: str


def _ref(invoice: object) -> InvoiceRef:
    from ziira.modules.pos.repository.models import SalesInvoice

    assert isinstance(invoice, SalesInvoice)
    return InvoiceRef(invoice.id, invoice.number, invoice.total, invoice.tax_total, invoice.customer_id,
                      invoice.issue_date, invoice.due_date, invoice.status)


def invoice_for_source(session: Session, source_type: str, source_id: UUID) -> InvoiceRef | None:
    """The live (not cancelled) invoice made for a source, or none."""
    from ziira.modules.pos.repository.models import SalesInvoice

    found = session.scalars(select(SalesInvoice).where(
        SalesInvoice.source_type == source_type, SalesInvoice.source_id == source_id,
        SalesInvoice.status != "cancelled")).first()
    return _ref(found) if found else None


def invoice_balance(session: Session, invoice_id: UUID) -> Decimal | None:
    """What is still owed on an invoice (total less payments received and credit notes), or None when there is no such
    live invoice. Added for Jobs (release the item only when paid); read only."""
    from ziira.modules.pos.repository.models import SalesInvoice

    found = session.get(SalesInvoice, invoice_id)
    if found is None or found.status == "cancelled":
        return None
    return max(found.total - found.amount_paid - found.credited, Decimal(0))


def issue_invoice_from_lines(session: Session, *, company_id: UUID, branch_id: UUID, customer_id: UUID,
                             lines: list[InvoiceLineIn], source_type: str, source_id: UUID,
                             due_days: int | None = None, memo: str | None = None,
                             issue_date: date | None = None, location_id: UUID | None = None,
                             settled_now: Decimal = Decimal(0)) -> InvoiceRef:
    """Issue a customer invoice for plain lines (services, time, a membership period) with the normal invoice service:
    numbering, tax, credit limit, `sale.posted` / `invoice.issued` events, posting rules and audit all apply, and the
    caller needs 'invoices.manage' at the branch. Idempotent by (`source_type`, `source_id`): asking again returns the
    first invoice and creates nothing (after it is cancelled, asking again issues a new one). Lines are at the agreed
    price (no price-override permission needed). `settled_now` is what the caller pays or settles in the same
    transaction (it does not count against the customer's credit limit). `location_id` names the stock location goods
    on the lines leave from (needed only when a line is a stocked product: a retail item sold with a service). Raises
    `ValidationFailed` for a bad line or a customer of another company, and the whole call rolls back with the
    caller's transaction."""
    from ziira.modules.pos.services import invoices
    from ziira.sdk import ValidationFailed

    if not source_type.strip():
        raise ValidationFailed("Name the source of the invoice")
    session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                   {"k": f"inv:{source_type}:{source_id}"})
    existing = invoice_for_source(session, source_type, source_id)
    if existing is not None:
        return existing
    if not lines:
        raise ValidationFailed("An invoice has at least one line")
    for line in lines:
        if line.quantity <= 0 or line.unit_price < 0 or line.discount < 0:
            raise ValidationFailed("Quantities must be above zero and prices cannot be negative")
    from ziira.modules.crm.public import find_customer

    customer = find_customer(session, customer_id)
    if customer is None or customer.company_id != company_id:
        raise ValidationFailed("The customer was not found in this company")
    view = invoices.issue_invoice(
        session, customer_id=customer_id, branch_id=branch_id, issue_date=issue_date, terms_days=due_days,
        notes=memo, agreed_prices=True, location_id=location_id, settled_now=settled_now,
        lines=[invoices.InvoiceLineIn(product_id=x.product_id, quantity=x.quantity, unit_price=x.unit_price,
                                      discount=x.discount, description=x.description) for x in lines])
    view.invoice.source_type, view.invoice.source_id = source_type.strip(), source_id
    session.flush()
    return _ref(view.invoice)


# ----------------------------------------------------- taking money against invoices (added for Bookings)
@dataclass(frozen=True)
class PaymentTaken:
    """A small view of the receipt made when a customer pays."""

    id: UUID
    number: str
    amount: Decimal
    method: str


def take_payment(session: Session, *, customer_id: UUID, branch_id: UUID, amount: Decimal, method: str,
                 allocations: list[tuple[UUID, Decimal]] | None = None, external_ref: str | None = None,
                 use_open_till: bool = True) -> PaymentTaken:
    """Record money a customer pays: against the named invoices (`allocations`: invoice id and amount), or, with
    no allocations, as an **advance** kept on their account (a deposit; any part not allocated is also kept). Cash goes
    through the caller's open till at the branch when they have one (`use_open_till`), so the drawer count includes
    it. The caller needs 'receivables.manage' at the branch. Method is one of cash, mobile_money, bank, card, cheque,
    other."""
    from ziira.modules.pos.repository import pos_repo
    from ziira.modules.pos.services import customer_receipts
    from ziira.sdk import current_context

    till_id = None
    if use_open_till and method == "cash":
        user = current_context().user_id
        till = pos_repo.open_till_of_user(session, user) if user is not None else None
        if till is not None and till.branch_id == branch_id:
            till_id = till.id
    view = customer_receipts.receive_payment(
        session, customer_id=customer_id, amount=amount, method=method, branch_id=branch_id,
        external_ref=external_ref, allocations=list(allocations or []), till_session_id=till_id,
        hold_balance=True)
    r = view.receipt
    return PaymentTaken(r.id, r.number, r.amount, r.method)


def customer_credit(session: Session, customer_id: UUID) -> Decimal:
    """Money the customer holds on account in advance (deposits, overpayments) and has not used or had back."""
    from ziira.modules.pos.services import customer_receipts

    return customer_receipts.credit_on_account(session, customer_id)


def apply_account_credit(session: Session, customer_id: UUID, allocations: list[tuple[UUID, Decimal]]) -> Decimal:
    """Pay invoices with money the customer holds on account (a deposit taken earlier). No money moves. Returns the
    amount applied. The caller needs 'receivables.manage' at the branch."""
    from ziira.modules.pos.services import customer_receipts

    done = customer_receipts.apply_credit(session, customer_id, allocations=allocations)
    return sum((Decimal(str(d["amount"])) for d in done), Decimal(0))


# ---------------------------------------------------- credit notes and refunds by amount (added for Memberships)
@dataclass(frozen=True)
class InvoiceCredit:
    """A credit note or refund made against an invoice with `credit_invoice`."""

    id: UUID
    number: str
    total: Decimal
    status: str                  # posted | pending_approval


def credit_invoice(session: Session, invoice_id: UUID, *, reason_code_id: UUID, refund_method: str,
                   amount: Decimal | None = None, note: str | None = None) -> InvoiceCredit:
    """Take back what an invoice charged, for service lines (no stock): all of what is left to credit, or `amount` of it
    (taken proportionally from the lines, never more than `amount`, so a few cents can remain with large amounts).
    `refund_method` is `credit_note` (less owed, while unpaid), or `cash` / `mobile_money` once the invoice is paid.
    The reason is one of the 'sale_return' reasons. Goes through the normal return rules and approval; the caller needs
    'sales.refund' at the branch. This is how a membership period is written off or refunded."""
    from ziira.modules.pos.domain import sales as rules
    from ziira.modules.pos.repository import pos_repo
    from ziira.modules.pos.services import returns
    from ziira.sdk import NotFound, ValidationFailed

    invoice = pos_repo.get_invoice(session, invoice_id)
    if invoice is None:
        raise NotFound("Invoice not found")
    lines = pos_repo.invoice_lines(session, invoice_id)
    back = pos_repo.invoice_returned_quantities(session, invoice_id)
    left = [(x, x.quantity - back.get(x.id, Decimal(0))) for x in lines]
    left = [(x, q) for x, q in left if q > 0]
    if not left:
        raise ValidationFailed("There is nothing left to credit on this invoice")
    available = sum((rules.return_amounts(x.line_total, x.tax_amount, x.quantity, back.get(x.id, Decimal(0)), q)[0]
                     for x, q in left), Decimal(0))
    share = Decimal(1)
    if amount is not None:
        if amount <= 0:
            raise ValidationFailed("The amount to credit must be more than zero")
        share = min(amount / available, Decimal(1)) if available > 0 else Decimal(1)
    chosen: list[tuple[UUID, Decimal]] = []
    for line, q in left:
        take = q if share >= 1 else (q * share).quantize(Decimal("0.0001"), rounding=ROUND_FLOOR)
        if take > 0:
            chosen.append((line.id, take))
    if not chosen:
        raise ValidationFailed("That amount is too small to credit")
    done = returns.create_invoice_return(session, invoice_id, lines=chosen, reason_code_id=reason_code_id,
                                         refund_method=refund_method, note=note)
    r = done.sales_return
    return InvoiceCredit(r.id, r.number, r.total, r.status)


def settle_invoice_non_cash(session: Session, invoice_id: UUID, amount: Decimal, *, kind: str,
                            reference: str) -> Decimal:
    """Mark part of an invoice as paid by something that is not money received here: a gift voucher, loyalty points,
    a package. The caller (the unit that owns that credit) has already moved its own liability and keeps its own
    record; this only reduces what the invoice owes and audits it. Returns the invoice's remaining balance. Needs
    'receivables.manage' at the branch."""
    from ziira.modules.pos.permissions import RECEIVABLES_MANAGE
    from ziira.modules.pos.repository import pos_repo
    from ziira.modules.pos.services import invoices
    from ziira.sdk import NotFound, ValidationFailed, audit_record, current_context

    invoice = pos_repo.get_invoice(session, invoice_id)
    if invoice is None or invoice.status == "cancelled":
        raise NotFound("Invoice not found")
    current_context().require(RECEIVABLES_MANAGE, company_id=invoice.company_id, branch_id=invoice.branch_id)
    if amount <= 0 or amount > invoices.outstanding(invoice):
        raise ValidationFailed(f"{invoice.number}: only {invoices.outstanding(invoice)} is owed")
    invoice.amount_paid += amount
    invoices.settle_status(invoice)
    session.flush()
    audit_record(session, "settle_non_cash", "pos.sales_invoice", invoice.id,
                 {"number": invoice.number, "amount": amount, "kind": kind, "reference": reference})
    return invoices.outstanding(invoice)


# --------------------------------------------------------------------------- for units that bill someone else (claims)
@dataclass(frozen=True)
class InvoiceLineRef:
    """A line of an issued invoice, in invoice order (`line_no` starts at 1)."""

    id: UUID
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    line_total: Decimal


def invoice_lines(session: Session, invoice_id: UUID) -> list[InvoiceLineRef]:
    """The lines of an invoice in the order they were given to `issue_invoice_from_lines`."""
    from ziira.modules.pos.repository import pos_repo
    from ziira.sdk import NotFound

    invoice = pos_repo.get_invoice(session, invoice_id)
    if invoice is None:
        raise NotFound("Invoice not found")
    return [InvoiceLineRef(x.id, x.line_no or index, x.description or "", x.quantity, x.unit_price, x.discount_amount,
                           x.line_total)
            for index, x in enumerate(sorted(pos_repo.invoice_lines(session, invoice_id),
                                             key=lambda x: x.line_no or 0), start=1)]


@dataclass(frozen=True)
class InvoiceState:
    """Where an invoice stands: what it was for, what has been paid and credited, and what is still owed."""

    id: UUID
    number: str
    customer_id: UUID
    total: Decimal
    amount_paid: Decimal
    credited: Decimal
    outstanding: Decimal
    status: str
    issue_date: date
    due_date: date


def invoice_states(session: Session, invoice_ids: set[UUID]) -> dict[UUID, InvoiceState]:
    """`InvoiceState` of many invoices at once (one query). An invoice that is paid or cancelled owes nothing."""
    if not invoice_ids:
        return {}
    rows = session.execute(text(
        "select id, number, customer_id, total, amount_paid, credited, status, issue_date, due_date "
        "from pos.sales_invoice where id = any(cast(:ids as uuid[]))"), {"ids": [str(i) for i in invoice_ids]})
    out: dict[UUID, InvoiceState] = {}
    for r in rows:
        owed = Decimal(r.total) - Decimal(r.amount_paid) - Decimal(r.credited) \
            if r.status in ("issued", "part_paid") else Decimal(0)
        out[r.id] = InvoiceState(r.id, r.number, r.customer_id, Decimal(r.total), Decimal(r.amount_paid),
                                 Decimal(r.credited), max(owed, Decimal(0)), r.status, r.issue_date, r.due_date)
    return out


@dataclass(frozen=True)
class CreditRef:
    """A credit note made against an invoice: its number, the amount and whether it is already posted."""

    number: str
    total: Decimal
    status: str


def credit_invoice_lines(session: Session, invoice_id: UUID, lines: list[tuple[UUID, Decimal]], *,
                         note: str) -> CreditRef:
    """Credit lines of an unpaid invoice by returning (all or part of) them as a credit note: the invoice is never
    edited, the customer owes less and the books follow. `lines` are (invoice line id, quantity). The caller needs
    'sales.refund' at the invoice's branch; a credit above the approval limit waits for approval (status
    'pending_approval'). Uses the first active reason of the 'sale_return' list."""
    from ziira.modules.pos.services import returns
    from ziira.sdk import ValidationFailed

    reason = session.execute(text(
        "select id from kernel.reason_code where category = 'sale_return' and is_active "
        "and tenant_id = kernel.current_tenant() order by code limit 1")).first()
    if reason is None:
        raise ValidationFailed("No reason is set up for credit notes (the sale return reasons)")
    view = returns.create_invoice_return(session, invoice_id, lines=lines, reason_code_id=reason.id,
                                         refund_method="credit_note", note=note)
    ret = view.sales_return
    return CreditRef(ret.number, ret.total, ret.status)


@dataclass(frozen=True)
class ReceiptRef:
    id: UUID
    number: str
    amount: Decimal
    unallocated: Decimal


def receive_invoice_payment(session: Session, *, customer_id: UUID, amount: Decimal, method: str,
                            allocations: list[tuple[UUID, Decimal]], reference: str | None = None,
                            received_on: date | None = None, branch_id: UUID | None = None) -> ReceiptRef:
    """Record money received from a customer account against named invoices (the rest, if any, stays on the account
    as an advance). The caller needs 'receivables.manage' at the branch."""
    from ziira.modules.pos.services import customer_receipts

    view = customer_receipts.receive_payment(
        session, customer_id=customer_id, amount=amount, method=method, branch_id=branch_id, external_ref=reference,
        received_on=received_on, allocations=allocations, hold_balance=True)
    r = view.receipt
    return ReceiptRef(r.id, r.number, r.amount, r.unallocated)
