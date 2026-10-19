"""Use case: invoice a job.

Invoices are made only by the POS unit (`pos.public.issue_invoice_from_lines`), which owns numbering, tax, credit
limits and the books. Stock parts have already left stock through Inventory, so the invoice must not take them out
again: every part is invoiced under the business's 'Parts' service item (hand-priced and stock parts) or under its own
service item, and labour under the 'Labour' service item. Those items' tax codes are the tax of the job (job_settings).
After invoicing the job is locked.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_INVOICE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import charges, claims_link, totals
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, load_job, unit_enabled
from ziira.modules.jobs.services.jobs import status_of
from ziira.sdk import Conflict, Event, Session, ValidationFailed, audit_record, current_context, publish

SOURCE = "job"


@dataclass(frozen=True)
class InvoiceLine:
    """A line of the invoice as the adapter takes it (tax-inclusive price)."""

    product_id: UUID
    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class Issued:
    id: UUID
    number: str
    total: Decimal


def invoicing_available(session: Session) -> bool:
    """True when Point of Sale, which makes the invoices, is switched on for the business."""
    return unit_enabled(session, "pos")


def _issue(session: Session, job: Job, customer_id: UUID, lines: list[InvoiceLine],
           settled_now: Decimal = Decimal(0)) -> Issued:
    """The one place that talks to POS. Everything else in this file is the job's own business."""
    from ziira.modules.pos.public import InvoiceLineIn, issue_invoice_from_lines

    made = issue_invoice_from_lines(
        session, company_id=job.company_id, branch_id=job.branch_id, customer_id=customer_id,
        lines=[InvoiceLineIn(product_id=x.product_id, description=x.description, quantity=x.quantity,
                             unit_price=x.unit_price) for x in lines],
        source_type=SOURCE, source_id=job.id, memo=_memo(job), settled_now=settled_now)
    return Issued(made.id, made.number, made.total)


def _memo(job: Job) -> str:
    memo = f"Job {job.number}: {job.title}"
    if job.deposit_amount:
        memo += f". Deposit of {job.deposit_amount:,.2f} received on account"
    return memo[:480]


def build_lines(session: Session, job: Job) -> list[InvoiceLine]:
    """The invoice lines for a job's live parts, labour and charges, or ValidationFailed saying what is missing. A part
    the customer brought is not invoiced. A fixed-price task is one line at its price."""
    settings = job_settings.get_settings(session, job.company_id)
    lines: list[InvoiceLine] = []
    for part in repo.parts(session, job.id, include_voided=False):
        if part.source == "customer_supplied":
            continue
        if part.source == "special_order" and part.order_status != "arrived":
            raise ValidationFailed(f"{part.description} has not arrived yet. Mark it as arrived or remove it first")
        if part.product_id is not None and not part.is_stock:
            product_id: UUID | None = part.product_id
        else:
            product_id = settings.parts_product_id
        if product_id is None:
            raise ValidationFailed("Choose the 'Parts' item in the job settings first: parts are invoiced under it")
        lines.append(InvoiceLine(product_id, part.description, part.quantity, part.unit_price))
    for work in repo.labour(session, job.id, include_voided=False):
        if settings.labour_product_id is None:
            raise ValidationFailed("Choose the 'Labour' item in the job settings first: labour is invoiced under it")
        if work.flat_price is not None:
            lines.append(InvoiceLine(settings.labour_product_id, f"Labour: {work.description}", Decimal(1),
                                     work.flat_price))
        else:
            lines.append(InvoiceLine(settings.labour_product_id, f"Labour: {work.description}", work.hours, work.rate))
    fee_item = settings.fees_product_id or settings.labour_product_id
    for charge in repo.charges(session, job.id, include_voided=False):
        if fee_item is None:
            raise ValidationFailed("Choose the 'Fees' or 'Labour' item in the job settings first: charges are "
                                   "invoiced under it")
        lines.append(InvoiceLine(fee_item, charge.description, charge.quantity, charge.unit_price))
    if not lines:
        raise ValidationFailed("There are no parts or labour on this job to invoice")
    return lines


def invoice_customer(session: Session, job: Job) -> UUID:
    """The customer record the invoice is made out to. A walk-in job (a name, maybe a phone, no record) gets one now:
    the customer with that phone if there is one, else a new one, else the shop's catch-all walk-in customer."""
    if job.customer_id is not None:
        return job.customer_id
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Invoicing needs Customers to be switched on")
    from ziira.modules.crm.public import match_or_create_customer, walk_in_customer
    from ziira.sdk import Forbidden

    try:
        if job.customer_phone:
            found, created = match_or_create_customer(session, job.company_id, name=job.customer_name or "Customer",
                                                      phone=job.customer_phone)
            how = "created" if created else "matched"
        else:
            found, how = walk_in_customer(session, job.company_id), "walk-in"
    except Forbidden:
        raise ValidationFailed("This job has no customer record yet and you may not create customers. Pick a customer "
                               "on the job first") from None
    job.customer_id = found.id
    add_event(session, job, "note", f"Invoiced to {found.name} (customer record {how})")
    return found.id


def _invoice_claim(session: Session, job: Job) -> Job:
    """A job with a live claim is billed by Claims: the payer is invoiced for what it approved (less the excess) and the
    customer for the excess and what they agreed to pay. The job then reads as invoiced under both numbers."""
    numbers, total = claims_link.bill(session, job)       # the claim's event may already have marked the job invoiced
    already = job.invoiced_at is not None
    job.invoice_number, job.invoiced_at = numbers[:60], job.invoiced_at or datetime.now(UTC)
    job.updated_by = current_context().user_id
    session.flush()
    if not already:
        add_event(session, job, "invoice", f"Claim invoiced: {numbers}")
    audit_record(session, "invoice", "jobs.job", job.id, {"invoice": numbers, "total": str(total)})
    publish(session, Event("job.invoiced", "jobs.job", job.id, {
        "company_id": job.company_id, "branch_id": job.branch_id, "number": job.number, "invoice_id": None,
        "invoice_number": numbers, "total": total}))
    return job


def invoice_job(session: Session, job_id: UUID, *, pay_method: str | None = None,
                pay_reference: str | None = None) -> Job:
    """Invoice the job to its customer for the parts, labour and charges on it, then lock it. Needs 'jobs.invoice' (and
    the invoicing permission of POS). A job with no customer record is invoiced to a customer made from its name and
    phone (or the walk-in customer). With `pay_method` the customer pays the whole invoice now (cash, mobile money ...):
    the invoice is not held against their credit limit and the payment is recorded against it in the same step (needs
    the receivables permission of POS)."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_INVOICE, company_id=job.company_id, branch_id=job.branch_id)
    if job.invoiced_at is not None:
        raise Conflict(f"This job was already invoiced ({job.invoice_number})")
    if status_of(session, job).role == "cancelled":
        raise ValidationFailed("A cancelled job cannot be invoiced")
    if not invoicing_available(session):
        raise ValidationFailed("Invoicing needs Point of Sale to be switched on")
    claim = claims_link.state(session, job)
    if claim is not None and claim.status != "closed":
        return _invoice_claim(session, job)
    charges.add_storage_fee(session, job.id)
    lines = build_lines(session, job)
    customer_id = invoice_customer(session, job)
    expected_total = totals.job_totals(session, job).grand.total
    issued = _issue(session, job, customer_id, lines, expected_total if pay_method else Decimal(0))
    if pay_method:
        from ziira.modules.pos.public import receive_invoice_payment

        receive_invoice_payment(session, customer_id=customer_id, amount=issued.total, method=pay_method,
                                allocations=[(issued.id, issued.total)], reference=pay_reference,
                                branch_id=job.branch_id)
    job.invoice_id, job.invoice_number, job.invoiced_at = issued.id, issued.number, datetime.now(UTC)
    job.updated_by = current_context().user_id
    session.flush()
    expected = expected_total
    note = f"Invoice {issued.number} made"
    if issued.total != expected:
        note += f" (total {issued.total}, the job showed {expected}: check the tax items in the job settings)"
    if pay_method:
        note += f", paid now ({pay_method})"
    add_event(session, job, "invoice", note)
    audit_record(session, "invoice", "jobs.job", job.id, {"invoice": issued.number, "total": str(issued.total)})
    publish(session, Event("job.invoiced", "jobs.job", job.id, {
        "company_id": job.company_id, "branch_id": job.branch_id, "number": job.number,
        "invoice_id": issued.id, "invoice_number": issued.number, "total": issued.total}))
    return job
