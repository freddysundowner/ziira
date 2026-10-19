"""Use cases: money from payers, what they still owe (ageing) and payments that came up short.

Money is recorded through Point of Sale's receipt service against the payer's invoices (the payer is a customer account
there). A payer often pays less than an invoice and calls it settled; when staff say a payment *closes* the invoice, the
difference is kept as a short payment to be recharged to the customer, disputed with the payer, or accepted.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.claims.domain import ageing as ageing_rules
from ziira.modules.claims.domain.money import ZERO
from ziira.modules.claims.permissions import CLAIMS_PAYMENTS
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import (
    Claim,
    InvoiceLine,
    InvoiceRun,
    Payer,
    PayerReceipt,
    ReceiptAllocation,
    ShortPay,
)
from ziira.modules.claims.services import access, status
from ziira.modules.claims.services import settings as claim_settings
from ziira.modules.claims.services.common import add_event, clean, now, unit_enabled
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_today,
    current_context,
    flag_for_review,
    publish,
)

METHODS = ("cash", "mobile_money", "bank", "card", "cheque", "other")
RESOLUTIONS = ("recharge", "accept", "dispute")


@dataclass(frozen=True)
class AllocationIn:
    run_id: UUID
    amount: Decimal
    closes_invoice: bool = False


@dataclass(frozen=True)
class OwedInvoice:
    payer_id: UUID
    payer_name: str
    claim_id: UUID
    claim_number: str
    run_id: UUID
    invoice_id: UUID
    invoice_number: str
    issue_date: date
    due_date: date
    total: Decimal
    outstanding: Decimal
    days_late: int
    bucket: str


def _pos() -> Any:
    import ziira.modules.pos.public as pos_public

    return pos_public


def owed_invoices(session: Session, payer_id: UUID | None, as_of: date | None = None, *,
                  company_id: UUID | None = None) -> list[OwedInvoice]:
    """The payers' invoices that are not fully paid, with how late they are."""
    if not unit_enabled(session, "pos"):
        return []
    if payer_id is not None:
        payers = {payer_id: claim_settings.load_payer(session, payer_id)}
    else:
        payers = {p.id: p for p in claim_settings.list_payers(session, company_id)}
    out: list[OwedInvoice] = []
    pos = _pos()
    for pid, payer in payers.items():
        runs = repo.payer_runs(session, pid)
        states = pos.invoice_states(session, {r.payer_invoice_id for r, _ in runs if r.payer_invoice_id})
        today = as_of or company_today(session, payer.company_id)
        for run, claim in runs:
            state = states.get(run.payer_invoice_id)
            if state is None or state.outstanding <= 0:
                continue
            late = (today - state.due_date).days
            out.append(OwedInvoice(pid, payer.name, claim.id, claim.number, run.id, state.id, state.number,
                                   state.issue_date, state.due_date, state.total, state.outstanding, max(late, 0),
                                   ageing_rules.bucket(state.due_date, today)))
    return sorted(out, key=lambda o: (o.payer_name, o.due_date))


def ageing(session: Session, *, company_id: UUID | None = None, as_of: date | None = None) -> list[dict[str, Any]]:
    """What each payer owes, by how late it is: not yet due, 1-30, 31-60, 61-90 and over 90 days."""
    by_payer: dict[UUID, dict[str, Any]] = {}
    for item in owed_invoices(session, None, as_of, company_id=company_id):
        row = by_payer.setdefault(item.payer_id, {"payer_id": item.payer_id, "payer": item.payer_name,
                                                  "buckets": ageing_rules.empty(), "total": ZERO, "invoices": 0})
        row["buckets"][item.bucket] += item.outstanding
        row["total"] += item.outstanding
        row["invoices"] += 1
    return sorted(by_payer.values(), key=lambda r: -r["total"])


def record_receipt(session: Session, payer_id: UUID, *, amount: Decimal, method: str, reference: str | None,
                   received_on: date | None, allocations: list[AllocationIn], branch_id: UUID,
                   note: str | None = None) -> tuple[PayerReceipt, bool]:
    """Record money received from a payer (a remittance) against its invoices. A payment with the same reference as one
    already recorded returns that one and changes nothing (the second bool is False). Anything not allocated stays on
    the
    payer's account as an advance. Needs 'claims.payments' (and Point of Sale's receivables permission)."""
    payer = claim_settings.load_payer(session, payer_id)
    ctx = current_context()
    ctx.require(CLAIMS_PAYMENTS, company_id=payer.company_id, branch_id=branch_id)
    ref = clean(reference, 60)
    if ref is not None:
        again = repo.receipt_by_reference(session, payer.id, ref)
        if again is not None:
            return again, False
    if method not in METHODS:
        raise ValidationFailed(f"The payment method is one of: {', '.join(METHODS)}")
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailed("A payment is more than zero with at most 2 decimal places")
    if payer.customer_id is None:
        raise ValidationFailed("The payer has no customer account to receive money on")
    if not unit_enabled(session, "pos"):
        raise ValidationFailed("Recording payments needs Point of Sale to be switched on")
    if sum((a.amount for a in allocations), ZERO) > amount:
        raise ValidationFailed("More is allocated to invoices than was received")
    if len({a.run_id for a in allocations}) != len(allocations):
        raise ValidationFailed("An invoice appears once in a payment")
    runs: dict[UUID, tuple[InvoiceRun, Claim]] = {}
    for run, claim in repo.payer_runs(session, payer.id):
        runs[run.id] = (run, claim)
    plan: list[tuple[UUID, Decimal]] = []
    for item in allocations:
        found = runs.get(item.run_id)
        if found is None or found[0].payer_invoice_id is None:
            raise ValidationFailed("An invoice named is not one of this payer's claim invoices")
        if item.amount <= 0:
            raise ValidationFailed("Each allocation is more than zero")
        plan.append((found[0].payer_invoice_id, item.amount))
    pos = _pos()
    paid = pos.receive_invoice_payment(session, customer_id=payer.customer_id, amount=amount, method=method,
                                       allocations=plan, reference=ref, received_on=received_on, branch_id=branch_id)
    receipt = PayerReceipt(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=payer.company_id,
                           payer_id=payer.id, pos_receipt_id=paid.id, pos_receipt_number=paid.number, amount=amount,
                           method=method, reference=ref, received_on=received_on or company_today(
                               session, payer.company_id), note=clean(note, 500))
    repo.add(session, receipt)
    settings = claim_settings.get_settings(session, payer.company_id)
    touched: dict[UUID, Claim] = {}
    for item in allocations:
        run, claim = runs[item.run_id]
        invoice_id = run.payer_invoice_id
        session.add(ReceiptAllocation(tenant_id=ctx.tenant_id, company_id=payer.company_id, receipt_id=receipt.id,
                                      run_id=run.id, claim_id=claim.id, invoice_id=invoice_id,
                                      amount=item.amount, closes_invoice=item.closes_invoice))
        touched[claim.id] = claim
        add_event(session, claim, "payment", f"{payer.name} paid {item.amount} toward {run.payer_invoice_number} "
                  f"(receipt {paid.number}" + (f", ref {ref}" if ref else "") + ")")
        if item.closes_invoice:
            state = pos.invoice_states(session, {invoice_id}).get(invoice_id)
            if state is not None and state.outstanding > settings.short_pay_tolerance:
                _flag_short_pay(session, payer, claim, run, state.outstanding, state.total - state.credited)
    session.flush()
    audit_record(session, "receive", "claims.payer", payer.id, {"receipt": paid.number, "amount": str(amount),
                                                                "reference": ref})
    for claim in touched.values():
        sync_status(session, claim)
        publish(session, Event("claim.payment_recorded", "claims.claim", claim.id, {
            "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number,
            "payer_id": payer.id, "amount": amount, "receipt": paid.number}))
    return receipt, True


def _flag_short_pay(session: Session, payer: Payer, claim: Claim, run: InvoiceRun, outstanding: Decimal,
                    expected: Decimal) -> None:
    existing = [s for s in repo.short_pays(session, None, claim_id=claim.id) if s.run_id == run.id
                and s.status in ("open", "disputed")]
    if existing:
        existing[0].paid, existing[0].difference = expected - outstanding, outstanding
        return
    ctx = current_context()
    row = ShortPay(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=claim.company_id, claim_id=claim.id,
                   payer_id=payer.id, run_id=run.id, invoice_id=run.payer_invoice_id or run.id,
                   expected=expected, paid=expected - outstanding, difference=outstanding)
    repo.add(session, row)
    add_event(session, claim, "short_pay", f"{payer.name} paid {row.paid} of {expected} on {run.payer_invoice_number} "
              f"and treats it as settled: {outstanding} short")
    flag_for_review(session, unit="claims", kind="short_payment", severity="medium", company_id=claim.company_id,
                    branch_id=claim.branch_id, ref_type="claim", ref_id=claim.id, amount=outstanding,
                    message=f"{payer.name} paid {outstanding} less than invoice {run.payer_invoice_number} "
                            f"(claim {claim.number})", dedupe_key=f"short_pay:{row.id}")
    publish(session, Event("claim.short_paid", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number, "payer_id": payer.id,
        "difference": outstanding, "short_pay_id": row.id}))


def resolve_short_pay(session: Session, short_pay_id: UUID, *, resolution: str, note: str | None = None
                      ) -> ShortPay:
    """Decide what to do with a short payment. `recharge` invoices the customer for the difference; `accept` writes down
    that the business takes the loss (the invoice stays open in Point of Sale until a credit note is made there);
    `dispute` keeps it open while the business argues with the payer. A note is required for accept and dispute. Needs
    'claims.payments' (and Point of Sale's invoicing permission to recharge)."""
    row = repo.get(session, ShortPay, short_pay_id, lock=True)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Short payment not found")
    claim = repo.get(session, Claim, row.claim_id)
    assert claim is not None
    ctx = current_context()
    ctx.require(CLAIMS_PAYMENTS, company_id=claim.company_id, branch_id=claim.branch_id)
    if resolution not in RESOLUTIONS:
        raise ValidationFailed(f"Resolve a short payment by: {', '.join(RESOLUTIONS)}")
    if row.status in ("recharged", "accepted"):
        raise Conflict(f"This short payment was already {row.status}")
    if resolution in ("accept", "dispute") and not (note or "").strip():
        raise ValidationFailed("Add a note saying why")
    if resolution == "recharge":
        _recharge(session, row, claim)
        row.status = "recharged"
    else:
        row.status = "accepted" if resolution == "accept" else "disputed"
    row.note, row.resolved_by = clean(note, 500), ctx.user_id
    row.resolved_at = now() if row.status != "disputed" else None
    session.flush()
    add_event(session, claim, "short_pay", f"Short payment of {row.difference}: {row.status}"
              + (f" ({note.strip()})" if note and note.strip() else ""))
    audit_record(session, "resolve", "claims.short_pay", row.id, {"resolution": resolution})
    sync_status(session, claim)
    return row


def _recharge(session: Session, row: ShortPay, claim: Claim) -> None:
    if claim.customer_id is None:
        raise ValidationFailed("The claim has no customer to recharge")
    product_id = claim_settings.get_settings(session, claim.company_id).invoice_product_id
    if product_id is None:
        raise ValidationFailed("Choose the service item for claim invoices in the claim settings")
    pos = _pos()
    made = pos.issue_invoice_from_lines(
        session, company_id=claim.company_id, branch_id=claim.branch_id, customer_id=claim.customer_id,
        lines=[pos.InvoiceLineIn(product_id=product_id, quantity=Decimal(1), unit_price=row.difference,
                                 description=f"Balance of claim {claim.number} not paid by the insurer")],
        source_type="claim_shortpay", source_id=row.id, due_days=0, memo=f"Claim {claim.number}")
    row.recharge_invoice_number = made.number


def sync_status(session: Session, claim: Claim) -> None:
    """Mark the claim settled when every payer invoice is paid (or its short payment was dealt with), else invoiced."""
    if claim.status not in ("invoiced", "settled") or not unit_enabled(session, "pos"):
        return
    runs = [r for r in repo.runs(session, claim.id)]
    ids = {r.payer_invoice_id for r in runs if r.payer_invoice_id}
    states = _pos().invoice_states(session, ids)
    shorts = repo.short_pays(session, None, claim_id=claim.id)
    open_short = {s.invoice_id for s in shorts if s.status in ("open", "disputed")}
    accepted = {s.invoice_id for s in shorts if s.status in ("accepted", "recharged")}
    unpaid = any(states[i].outstanding > 0 and i not in accepted for i in ids if i in states) or bool(open_short)
    customer_ids = {r.customer_invoice_id for r in runs if r.customer_invoice_id}
    customer_states = _pos().invoice_states(session, customer_ids)
    customer_unpaid = any(s.outstanding > 0 for s in customer_states.values())
    claim.status = "invoiced" if (unpaid or customer_unpaid or not ids and not customer_ids) else "settled"
    session.flush()


def payer_statement(session: Session, payer_id: UUID) -> dict[str, Any]:
    """A payer's picture: what it owes, receipts and short payments."""
    payer = claim_settings.load_payer(session, payer_id)
    return {"payer": payer, "owed": owed_invoices(session, payer.id),
            "receipts": repo.receipts_of_payer(session, payer.id),
            "short_pays": repo.short_pays(session, {payer.company_id}, payer_id=payer.id)}


def invoice_lines_of(session: Session, claim_id: UUID) -> list[InvoiceLine]:
    return repo.claim_invoice_lines(session, claim_id)


def settle_check(session: Session, claim: Claim) -> str:
    sync_status(session, claim)
    return claim.status


def refresh_after_external_payment(session: Session, claim: Claim) -> str:
    """Payments made directly in Point of Sale also settle a claim: re-check it (used by the periodic task)."""
    status.refresh(session, claim)
    sync_status(session, claim)
    return claim.status
