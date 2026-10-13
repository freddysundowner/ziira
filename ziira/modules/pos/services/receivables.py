"""Use cases: what customers owe - ageing, statements, balances and reminders."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.crm.public import find_customer, find_customers
from ziira.modules.pos.permissions import INVOICES_MANAGE, RECEIVABLES_MANAGE, RECEIVABLES_VIEW
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.repository.models import InvoiceReminder
from ziira.modules.pos.services import credit, invoices, tills
from ziira.modules.pos.services.common import unit_enabled
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, current_context

BUCKETS = ("not_due", "1_30", "31_60", "61_90", "over_90")
CHANNELS = ("whatsapp", "sms", "email", "call", "visit")


def bucket(due: date, as_of: date) -> str:
    """Which age band an unpaid invoice falls in, by how many days past its due date it is."""
    late = (as_of - due).days
    if late <= 0:
        return "not_due"
    return "1_30" if late <= 30 else "31_60" if late <= 60 else "61_90" if late <= 90 else "over_90"


def ageing(session: Session, *, as_of: date | None = None, customer_id: UUID | None = None) -> dict[str, Any]:
    """What customers owe on unpaid invoices, by customer, aged by due date."""
    as_of = as_of or tills.today()
    totals: dict[UUID, dict[str, Decimal]] = {}
    for invoice in pos_repo.all_open_invoices(session, invoices.invoice_scopes(), as_of):
        if customer_id is not None and invoice.customer_id != customer_id:
            continue
        row = totals.setdefault(invoice.customer_id, {b: Decimal(0) for b in BUCKETS})
        row[bucket(invoice.due_date, as_of)] += invoices.outstanding(invoice)
    names = find_customers(session, set(totals)) if totals and unit_enabled(session, "crm") else {}
    rows: list[dict[str, Any]] = []
    for cid, buckets in totals.items():
        view = names.get(cid)
        rows.append({"customer_id": cid, "customer": view.name if view else "", "total": sum(
            buckets.values(), Decimal(0)), **buckets})
    rows.sort(key=lambda r: (str(r["customer"]), str(r["customer_id"])))
    grand = {b: sum((Decimal(r[b]) for r in rows), Decimal(0)) for b in BUCKETS}
    return {"as_of": as_of, "customers": rows, "total": sum(grand.values(), Decimal(0)), "buckets": grand}


@dataclass(frozen=True)
class Entry:
    day: date
    kind: str                      # invoice | receipt | credit_note
    number: str
    description: str
    debit: Decimal                 # adds to what is owed
    credit: Decimal                # reduces it


def _customer(session: Session, customer_id: UUID) -> Any:
    customer = find_customer(session, customer_id) if unit_enabled(session, "crm") else None
    if customer is None:
        raise NotFound("Customer not found")
    scopes = invoices.invoice_scopes()
    if scopes is not None and not any(c is None or c == customer.company_id for c, _ in scopes):
        raise NotFound("Customer not found")
    return customer


def statement(session: Session, customer_id: UUID, *, date_from: date | None = None,
              date_to: date | None = None) -> dict[str, Any]:
    """A customer's account: invoices, payments and credit notes in date order with a running balance, from an opening
    balance. Cancelled invoices and reversed receipts are left out (they never happened as far as the customer goes)."""
    customer = _customer(session, customer_id)
    entries: list[Entry] = []
    for invoice in pos_repo.invoices_of_customer(session, customer.id):
        entries.append(Entry(invoice.issue_date, "invoice", invoice.number,
                             f"Invoice due {invoice.due_date}", invoice.total, Decimal(0)))
    for receipt in pos_repo.receipts_of_customer(session, customer.id):
        entries.append(Entry(receipt.received_on, "receipt", receipt.number,
                             f"Payment by {receipt.method}" + (f" ({receipt.reference})" if receipt.reference else ""),
                             Decimal(0), receipt.amount))
    for note in pos_repo.credit_notes_of_customer(session, customer.id):
        entries.append(Entry(note.business_date or tills.today(), "credit_note", note.number,
                             "Goods taken back", Decimal(0), note.total))
    entries.sort(key=lambda e: (e.day, {"invoice": 0, "credit_note": 1, "receipt": 2}[e.kind], e.number))
    opening = sum((e.debit - e.credit for e in entries if date_from is not None and e.day < date_from), Decimal(0))
    shown = [e for e in entries if (date_from is None or e.day >= date_from) and (date_to is None or e.day <= date_to)]
    running, lines = opening, []
    for e in shown:
        running += e.debit - e.credit
        lines.append({"date": e.day, "kind": e.kind, "number": e.number, "description": e.description,
                      "debit": e.debit, "credit": e.credit, "balance": running})
    return {"customer_id": customer.id, "customer": customer.name, "code": customer.code,
            "date_from": date_from, "date_to": date_to, "opening_balance": opening, "lines": lines,
            "closing_balance": running, "owed_now": pos_repo.customer_exposure(session, customer.id)}


def balance(session: Session, customer_id: UUID) -> dict[str, Any]:
    """What the customer owes, their credit limit and how much more they can take on account."""
    customer = _customer(session, customer_id)
    owes = credit.owed(session, customer.id)
    return {"customer_id": customer.id, "customer": customer.name, "owes": owes, "credit_limit": customer.credit_limit,
            "available": max(customer.credit_limit - owes, Decimal(0)), "terms_days": customer.payment_terms_days,
            "status": customer.status}


def due_reminders(session: Session, *, as_of: date | None = None, min_days_overdue: int = 1,
                  repeat_days: int = 7, limit: int = 100) -> list[dict[str, Any]]:
    """Overdue invoices that have not had a reminder lately, oldest first - who to chase today."""
    as_of = as_of or tills.today()
    overdue = [i for i in pos_repo.all_open_invoices(session, invoices.invoice_scopes(), as_of)
               if (as_of - i.due_date).days >= min_days_overdue]
    last = pos_repo.last_reminders(session, [i.id for i in overdue])
    crm_on = unit_enabled(session, "crm")
    names = find_customers(session, {i.customer_id for i in overdue}) if overdue and crm_on else {}
    found = []
    for invoice in overdue:
        reminded = last.get(invoice.id)
        if reminded is not None and (as_of - reminded.date()).days < repeat_days:
            continue
        customer = names.get(invoice.customer_id)
        found.append({"invoice_id": invoice.id, "number": invoice.number, "customer_id": invoice.customer_id,
                      "customer": customer.name if customer else "", "phone": customer.phone if customer else None,
                      "due_date": invoice.due_date, "days_overdue": (as_of - invoice.due_date).days,
                      "outstanding": invoices.outstanding(invoice), "last_reminder": reminded})
    return found[:min(limit, 500)]


def record_reminder(session: Session, invoice_id: UUID, *, channel: str, note: str | None = None) -> InvoiceReminder:
    """Note that a customer was reminded about an invoice (by message, call or visit). Needs 'receivables.manage'."""
    invoice = pos_repo.get_invoice(session, invoice_id)
    if invoice is None or not invoices.can_see(invoice):
        raise NotFound("Invoice not found")
    ctx = current_context()
    if not (ctx.can(RECEIVABLES_MANAGE, company_id=invoice.company_id, branch_id=invoice.branch_id)
            or ctx.can(INVOICES_MANAGE, company_id=invoice.company_id, branch_id=invoice.branch_id)):
        ctx.require(RECEIVABLES_VIEW, company_id=invoice.company_id, branch_id=invoice.branch_id)
        ctx.require(RECEIVABLES_MANAGE, company_id=invoice.company_id, branch_id=invoice.branch_id)
    if channel not in CHANNELS:
        raise ValidationFailed(f"Channel must be one of: {', '.join(CHANNELS)}")
    if invoice.status not in pos_repo.OPEN_INVOICE:
        raise ValidationFailed("Only an unpaid invoice needs a reminder")
    reminder = InvoiceReminder(tenant_id=ctx.tenant_id, created_by=ctx.user_id, invoice_id=invoice.id,
                               channel=channel, note=(note or "").strip()[:300] or None)
    pos_repo.add(session, reminder)
    audit_record(session, "remind", "pos.sales_invoice", invoice.id, {"channel": channel})
    return reminder
