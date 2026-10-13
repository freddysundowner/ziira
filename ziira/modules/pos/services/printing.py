"""Use cases: printable till receipts, invoices and payment receipts (text for thermal printers, HTML, or data).

Reading is covered by the same access rules as the documents themselves. Other units may add lines to the foot of a
document through the `pos.receipt_extras` extension point (e.g. a tax-authority control code).
"""

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.crm.public import find_customer
from ziira.modules.pos.domain.printing import PrintDocument, PrintLine, VatRow, render_html, render_text
from ziira.modules.pos.public import RECEIPT_EXTRAS
from ziira.modules.pos.repository import pos_repo
from ziira.modules.pos.services import customer_receipts, invoices, sales
from ziira.modules.pos.services.common import unit_enabled
from ziira.modules.products.public import product_labels, tax_code_rate
from ziira.sdk import Session, ValidationFailed, company_setting, implementations

log = logging.getLogger("ziira.pos.printing")
FORMATS = ("json", "text", "html")


def _header(session: Session, company_id: UUID, branch_id: UUID | None) -> list[str]:
    company = session.execute(text("select name, kra_pin from kernel.company where id = :c"),
                              {"c": str(company_id)}).first()
    rows = [company.name] if company else []
    if branch_id is not None:
        branch = session.execute(text("select name, address, phone from kernel.branch where id = :b"),
                                 {"b": str(branch_id)}).first()
        if branch:
            rows += [x for x in (branch.name, branch.address, f"Tel {branch.phone}" if branch.phone else None) if x]
    if company and company.kra_pin:
        rows.append(f"PIN {company.kra_pin}")
    return rows


def _user_name(session: Session, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    row = session.execute(text("select full_name as name from kernel.app_user where id = :u"),
                          {"u": str(user_id)}).first()
    return row.name if row else None


def _vat_rows(session: Session, lines: list[Any]) -> list[VatRow]:
    gross: dict[Decimal, Decimal] = defaultdict(Decimal)
    tax: dict[Decimal, Decimal] = defaultdict(Decimal)
    rates: dict[UUID, Decimal] = {}
    for line in lines:
        if line.tax_code_id not in rates:
            rates[line.tax_code_id] = tax_code_rate(session, line.tax_code_id) or Decimal(0)
        rate = rates[line.tax_code_id]
        gross[rate] += line.line_total
        tax[rate] += line.tax_amount
    return [VatRow(rate, gross[rate] - tax[rate], tax[rate]) for rate in sorted(gross)]


def _print_lines(session: Session, lines: list[Any]) -> list[PrintLine]:
    names = product_labels(session, {x.product_id for x in lines})
    return [PrintLine(names.get(x.product_id, ("", "Item"))[1], x.quantity, x.unit_price + 0, x.line_total)
            for x in sorted(lines, key=lambda x: x.line_no or 0)]


def _extras(session: Session, kind: str, document_id: UUID) -> list[str]:
    found: list[str] = []
    for extra in implementations(session, RECEIPT_EXTRAS):
        try:
            found += [str(x) for x in extra.lines(session, kind, document_id)]
        except Exception:                                       # a broken plugin must never stop a sale being printed
            log.exception("Receipt extra %s failed for %s %s", type(extra).__name__, kind, document_id)
    return found


def _customer_name(session: Session, customer_id: UUID | None) -> str | None:
    if customer_id is None or not unit_enabled(session, "crm"):
        return None
    customer = find_customer(session, customer_id)
    return customer.name if customer else None


def sale_document(session: Session, sale_id: UUID, *, copy: bool = False) -> PrintDocument:
    view = sales.get_sale(session, sale_id)
    sale = view.sale
    meta = [("Date", sale.sold_at.strftime("%Y-%m-%d %H:%M")),
            ("Served by", _user_name(session, sale.cashier_id) or "")]
    customer = _customer_name(session, sale.customer_id)
    if customer:
        meta.append(("Customer", customer))
    totals = [("Subtotal", sale.subtotal)]
    if sale.discount_total:
        totals.append(("Discount", -sale.discount_total))
    totals.append(("TOTAL", sale.total))
    invoice = pos_repo.invoice_for_sale(session, sale.id)
    paid = [(p.method.upper(), p.amount) for p in view.payments]
    notes = ["VOIDED"] if sale.status == "voided" else []
    if invoice is not None and invoice.status != "cancelled":
        notes.append(f"On account: invoice {invoice.number}, due {invoice.due_date}")
    footer = [str(company_setting(session, sale.company_id, "receipt_footer"))]
    return PrintDocument(
        title="Receipt", number=sale.number, header=_header(session, sale.company_id, sale.branch_id),
        meta=[m for m in meta if m[1]], lines=_print_lines(session, view.lines), vat=_vat_rows(session, view.lines),
        totals=totals, payments=paid, notes=notes,
        footer=[f for f in footer if f] + _extras(session, "sale", sale.id), copy=copy)


def invoice_document(session: Session, invoice_id: UUID, *, copy: bool = False) -> PrintDocument:
    view = invoices.get_invoice(session, invoice_id)
    inv = view.invoice
    meta = [("Date", str(inv.issue_date)), ("Due", str(inv.due_date))]
    customer = _customer_name(session, inv.customer_id)
    if customer:
        meta.append(("Customer", customer))
    totals = [("Subtotal", inv.subtotal), ("VAT", inv.tax_total), ("TOTAL", inv.total)]
    paid: list[tuple[str, Decimal]] = []
    if inv.amount_paid:
        paid.append(("Paid", inv.amount_paid))
    if inv.credited:
        paid.append(("Credited", inv.credited))
    paid.append(("BALANCE DUE", invoices.outstanding(inv)))
    notes = ["CANCELLED"] if inv.status == "cancelled" else ([inv.notes] if inv.notes else [])
    footer = str(company_setting(session, inv.company_id, "invoice_footer"))
    return PrintDocument(
        title="Invoice", number=inv.number, header=_header(session, inv.company_id, inv.branch_id), meta=meta,
        lines=_print_lines(session, view.lines), vat=_vat_rows(session, view.lines), totals=totals, payments=paid,
        notes=notes, footer=([footer] if footer else []) + _extras(session, "invoice", inv.id), copy=copy)


def receipt_document(session: Session, receipt_id: UUID, *, copy: bool = False) -> PrintDocument:
    view = customer_receipts.get_receipt(session, receipt_id)
    rec = view.receipt
    meta = [("Date", str(rec.received_on)), ("Method", rec.method.upper())]
    customer = _customer_name(session, rec.customer_id)
    if customer:
        meta.append(("Customer", customer))
    if rec.reference:
        meta.append(("Reference", rec.reference))
    applied: list[tuple[str, Decimal]] = []
    for allocation in view.allocations:
        invoice = pos_repo.get_invoice(session, allocation.invoice_id)
        applied.append((f"Invoice {invoice.number if invoice else '?'}", allocation.amount))
    if rec.unallocated:
        applied.append(("Held on account", rec.unallocated))
    notes = ["REVERSED"] if rec.status == "reversed" else []
    footer = str(company_setting(session, rec.company_id, "receipt_footer"))
    return PrintDocument(
        title="Payment receipt", number=rec.number, header=_header(session, rec.company_id, rec.branch_id), meta=meta,
        totals=[("AMOUNT RECEIVED", rec.amount)], payments=applied, notes=notes,
        footer=([footer] if footer else []) + _extras(session, "receipt", rec.id), copy=copy)


def render(doc: PrintDocument, fmt: str, width: int) -> str:
    if fmt == "text":
        return render_text(doc, width)
    if fmt == "html":
        return render_html(doc)
    raise ValidationFailed(f"Unknown format '{fmt}'")
