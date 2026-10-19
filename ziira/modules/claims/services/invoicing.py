"""Use cases: invoice a claim, and credit an invoice when the payer reduces what it pays.

Invoices are made only by Point of Sale (`pos.public.issue_invoice_from_lines`); a posted invoice is never edited. A
claim is
billed in *runs*: the first run bills what is authorised once the work is signed off; a supplementary estimate approved
later, or a line the payer reduced, is billed in a later run.

Each run makes up to two invoices:
* to the **payer**: what it pays, less the customer's excess (spread over the lines as discounts);
* to the **customer**: the excess, rejected lines they agreed to pay and the difference of counter-offers they agreed to
  carry.
Every amount goes under the one service item chosen in the claim settings, so that item's tax code is the claim's tax.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from ziira.modules.claims.domain import lines as rules
from ziira.modules.claims.domain.money import ZERO
from ziira.modules.claims.domain.split import BillableLine, Split, compute_split
from ziira.modules.claims.permissions import CLAIMS_INVOICE
from ziira.modules.claims.repository import claims_repo as repo
from ziira.modules.claims.repository.models import (
    Claim,
    EstimateLine,
    EstimateResponse,
    InvoiceLine,
    InvoiceRun,
    LineResponse,
    Payer,
)
from ziira.modules.claims.services import settings as claim_settings
from ziira.modules.claims.services import status
from ziira.modules.claims.services.common import add_event, clean, load_claim, now, unit_enabled
from ziira.sdk import Conflict, Event, Session, ValidationFailed, audit_record, current_context, publish


@dataclass
class Billing:
    """What the next run would bill."""

    split: Split
    lines: list[EstimateLine]
    waiting: list[EstimateLine]               # lines nobody has decided yet: left for a later run
    blockers: list[str]


def _describe(line: EstimateLine) -> str:
    if line.quantity == 1:
        return line.description
    return f"{line.description} ({line.quantity:g} x {line.unit_price:,.2f})"


def preview(session: Session, claim_id: UUID) -> Billing:
    """Work out the next run without issuing anything."""
    claim = load_claim(session, claim_id)
    return _plan(session, claim)


def _plan(session: Session, claim: Claim) -> Billing:
    played = status.in_play(session, claim.id)
    billable: list[BillableLine] = []
    rows: list[EstimateLine] = []
    waiting: list[EstimateLine] = []
    for _, line in played:
        f = status.facts(line)
        if line.invoiced_run_id is not None:
            continue
        if rules.is_authorised_work(f):
            billable.append(BillableLine(line.id, _describe(line), line.quantity, line.unit_price, f))
            rows.append(line)
        elif rules.is_open(f):
            waiting.append(line)
    embedded, charged, gross_before = _billed_so_far(session, claim)
    split = compute_split(billable, excess=claim.excess_amount, embedded_before=embedded, charged_before=charged,
                          gross_before=gross_before)
    blockers: list[str] = []
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    if claim.status == "closed":
        blockers.append("The claim is closed")
    if claim.completed_at is None:
        blockers.append("The work has not been signed off yet")
    if not rows:
        blockers.append("Nothing is ready to invoice")
    if split.payer_net > 0 and payer.customer_id is None:
        blockers.append("The payer has no customer account to invoice")
    if split.customer_total > 0 and claim.customer_id is None:
        blockers.append("The claim has no customer to invoice")
    if claim_settings.get_settings(session, claim.company_id).invoice_product_id is None:
        blockers.append("Choose the service item for claim invoices in the claim settings")
    if not unit_enabled(session, "pos"):
        blockers.append("Invoicing needs Point of Sale to be switched on")
    return Billing(split, rows, waiting, blockers)


def _billed_so_far(session: Session, claim: Claim) -> tuple[Decimal, Decimal, Decimal]:
    """(excess carried as discounts on payer lines, excess charged to the customer, payer lines' gross) over the invoice
    lines of earlier runs that have not been credited."""
    embedded = charged = gross = ZERO
    for row in repo.claim_invoice_lines(session, claim.id):
        if row.credited_at is not None:
            continue
        if row.side == "payer":
            embedded += row.discount
            gross += row.amount + row.discount
        elif row.kind == "excess":
            charged += row.amount
    return embedded, charged, gross


def invoice_claim(session: Session, claim_id: UUID) -> InvoiceRun:
    """Bill what is authorised and not yet billed: the payer's invoice and the customer's invoice. Needs
    'claims.invoice'
    (and Point of Sale's invoicing permission). The work must be signed off."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_INVOICE, company_id=claim.company_id, branch_id=claim.branch_id)
    plan = _plan(session, claim)
    if plan.blockers:
        raise ValidationFailed(plan.blockers[0])
    settings = claim_settings.get_settings(session, claim.company_id)
    product_id = settings.invoice_product_id
    assert product_id is not None
    payer = repo.get(session, Payer, claim.payer_id)
    assert payer is not None
    split = plan.split
    from ziira.modules.pos.public import InvoiceLineIn, invoice_lines, issue_invoice_from_lines

    runs = repo.runs(session, claim.id)
    run = InvoiceRun(id=uuid4(), tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=claim.company_id,
                     claim_id=claim.id, seq=len(runs) + 1, excess_applied=split.excess_applied)
    session.add(run)
    session.flush()
    memo = f"Claim {claim.number}" + (f", policy {claim.policy_number}" if claim.policy_number else "") \
        + (f", claim {claim.claim_number}" if claim.claim_number else "")
    by_line = {row.id: row for row in plan.lines}
    if split.payer_net > 0 and payer.customer_id is not None:
        made = issue_invoice_from_lines(
            session, company_id=claim.company_id, branch_id=claim.branch_id, customer_id=payer.customer_id,
            lines=[InvoiceLineIn(product_id=product_id, description=part.description[:300], quantity=Decimal(1),
                                 unit_price=part.gross, discount=part.discount) for part in split.payer_parts],
            source_type="claim_payer", source_id=run.id, due_days=payer.payment_days, memo=memo[:480])
        run.payer_invoice_id, run.payer_invoice_number, run.payer_amount = made.id, made.number, made.total
        if made.total != split.payer_net:
            raise ValidationFailed(f"The payer invoice came to {made.total}, expected {split.payer_net}: check the "
                                   "tax item chosen in the claim settings")
        refs = invoice_lines(session, made.id)
        for part, ref in zip(split.payer_parts, refs, strict=True):
            session.add(InvoiceLine(tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id,
                                    run_id=run.id, side="payer", kind="line", estimate_line_id=part.line_id,
                                    invoice_line_id=ref.id, amount=part.net, discount=part.discount))
    elif split.payer_parts:                      # all of it went to the excess: nothing to invoice the payer, but
        for part in split.payer_parts:           # remember the discount so later runs do not take the excess twice
            session.add(InvoiceLine(tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id,
                                    run_id=run.id, side="payer", kind="line", estimate_line_id=part.line_id,
                                    invoice_line_id=None, amount=part.net, discount=part.discount))
    if split.customer_total > 0 and claim.customer_id is not None:
        made = issue_invoice_from_lines(
            session, company_id=claim.company_id, branch_id=claim.branch_id, customer_id=claim.customer_id,
            lines=[InvoiceLineIn(product_id=product_id, description=part.description[:300], quantity=Decimal(1),
                                 unit_price=part.amount) for part in split.customer_parts],
            source_type="claim_customer", source_id=run.id, due_days=0, memo=memo[:480])
        run.customer_invoice_id, run.customer_invoice_number, run.customer_amount = made.id, made.number, made.total
        refs = invoice_lines(session, made.id)
        for bill, ref in zip(split.customer_parts, refs, strict=True):
            session.add(InvoiceLine(tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id,
                                    run_id=run.id, side="customer", kind=bill.kind, estimate_line_id=bill.line_id,
                                    invoice_line_id=ref.id, amount=bill.amount))
    for row in by_line.values():
        row.invoiced_run_id = run.id
    claim.invoiced_at = claim.invoiced_at or now()
    session.flush()
    add_event(session, claim, "invoice", f"Run {run.seq}: payer invoice {run.payer_invoice_number or '-'} "
              f"({run.payer_amount}), customer invoice {run.customer_invoice_number or '-'} ({run.customer_amount})")
    audit_record(session, "invoice", "claims.claim", claim.id, {
        "run": run.seq, "payer": str(run.payer_amount), "customer": str(run.customer_amount),
        "excess": str(run.excess_applied)})
    status.refresh(session, claim)
    publish(session, Event("claim.invoiced", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number, "run": run.seq,
        "payer_invoice_id": run.payer_invoice_id, "customer_invoice_id": run.customer_invoice_id,
        "payer_amount": run.payer_amount, "customer_amount": run.customer_amount,
        "source_type": claim.source_type, "source_id": claim.source_id}))
    return run


def reduce_line(session: Session, claim_id: UUID, line_id: UUID, *, new_amount: Decimal, reason: str,
                by_name: str, shortfall_to: str = "business", customer_agreed_by: str | None = None) -> EstimateLine:
    """The payer now pays less for a line that was already invoiced. The invoice lines made for it are credited in
    full (a
    credit note; the invoice is never edited) and the line, now worth `new_amount`, is billed again in the next run.
    `new_amount` of zero means the payer refuses the line altogether (it then waits for the customer's decision).
    Needs 'claims.invoice' and Point of Sale's refund permission."""
    claim = load_claim(session, claim_id, lock=True)
    ctx = current_context()
    ctx.require(CLAIMS_INVOICE, company_id=claim.company_id, branch_id=claim.branch_id)
    if claim.status == "closed":
        raise Conflict("This claim is closed")
    line = repo.get(session, EstimateLine, line_id, lock=True)
    if line is None or line.claim_id != claim.id:
        raise ValidationFailed("That line is not on this claim")
    if line.invoiced_run_id is None:
        raise ValidationFailed("This line has not been invoiced: answer it on the estimate instead")
    f = status.facts(line)
    pays = rules.payer_pays(f)
    if pays <= 0 or new_amount < 0 or new_amount >= pays:
        raise ValidationFailed(f"The payer pays {pays} for this line: give a lower amount")
    who, why = clean(by_name, 160), clean(reason, 500)
    if who is None or why is None:
        raise ValidationFailed("Say who at the payer reduced it, and why")
    if shortfall_to not in ("customer", "business"):
        raise ValidationFailed("The difference is carried by the customer or the business")
    if new_amount > 0 and shortfall_to == "customer" and not (customer_agreed_by or "").strip():
        raise ValidationFailed("Type the name of the customer who agreed to pay the difference")
    from ziira.modules.pos.public import credit_invoice_lines

    credits: list[str] = []
    for row in repo.claim_invoice_lines(session, claim.id):
        if row.estimate_line_id != line.id or row.credited_at is not None or row.invoice_line_id is None:
            continue
        run = repo.get(session, InvoiceRun, row.run_id)
        assert run is not None
        invoice_id = run.payer_invoice_id if row.side == "payer" else run.customer_invoice_id
        if invoice_id is None:
            continue
        credit = credit_invoice_lines(session, invoice_id, [(row.invoice_line_id, Decimal(1))],
                                      note=f"Claim {claim.number}: {why}")
        if credit.status != "posted":
            raise ValidationFailed("The credit note needs approval in Point of Sale before the payer's reduction can "
                                   "be recorded: ask an approver, then try again")
        row.credited_at, row.credit_number = now(), credit.number
        credits.append(credit.number)
    old_state = line.payer_state
    if new_amount == 0:
        line.payer_state, line.payer_amount, line.our_decision = "rejected", None, None
        line.customer_decision = line.shortfall_to = None
    else:
        line.payer_state, line.payer_amount, line.our_decision = "countered", new_amount, "accepted"
        line.shortfall_to = shortfall_to
        line.customer_decision = "pays" if shortfall_to == "customer" else None
        line.customer_decision_by = clean(customer_agreed_by, 160) if shortfall_to == "customer" else None
    line.payer_reason, line.responded_at, line.invoiced_run_id = why, now(), None
    round_no = repo.rounds_so_far(session, line.estimate_id) + 1
    session.add(LineResponse(tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id,
                             estimate_id=line.estimate_id, line_id=line.id, round=round_no, state="reduced",
                             amount=new_amount, reason=why, by_name=who, by_user=ctx.user_id, channel="staff",
                             via="other"))
    repo.add(session, EstimateResponse(
        tenant_id=ctx.tenant_id, company_id=claim.company_id, claim_id=claim.id, estimate_id=line.estimate_id,
        round=round_no, response="countered" if new_amount > 0 else "rejected", by_name=who, by_user=ctx.user_id,
        channel="staff", via="other", occurred_at=now(), note=f"Reduced after invoicing: {why}"))
    session.flush()
    add_event(session, claim, "credit", f"{line.description}: the payer now pays {new_amount} instead of {pays} "
              f"({who}: {why}). Credit note {', '.join(credits) or 'not needed'}", actor=who)
    audit_record(session, "reduce", "claims.estimate_line", line.id, {"from": str(pays), "to": str(new_amount),
                                                                       "previous_state": old_state})
    status.refresh(session, claim)
    publish(session, Event("claim.credited", "claims.claim", claim.id, {
        "company_id": claim.company_id, "branch_id": claim.branch_id, "number": claim.number,
        "line_id": line.id, "from": pays, "to": new_amount, "credit_numbers": credits}))
    return line
