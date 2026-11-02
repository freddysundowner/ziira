"""A deposit on an order (a tailor's advance, a garage's deposit on a special-order part).

The money is an **advance** on the customer's account taken through Point of Sale (`pos.public.take_payment`, so the
till count, mobile-money references and the books all work as everywhere else). The job remembers the total received so
far. When the job is invoiced the advance is set against the invoice (see invoicing.py); what is left stays on the
customer's account. Without Point of Sale it is a plain payment through Payments and nothing is set against an invoice.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import invoicing
from ziira.modules.jobs.services.common import add_event, clean, load_job, unit_enabled
from ziira.sdk import Session, ValidationFailed, audit_record, current_context

PAYMENTS_RECORD = "payments.record"


def take_deposit(session: Session, job_id: UUID, *, amount: Decimal, method: str = "cash",
                 reference: str | None = None, payment_account_id: UUID | None = None,
                 note: str | None = None) -> Job:
    """Take money in advance for the job. Needs 'jobs.manage' and 'payments.record' at the branch."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    if not invoicing.invoicing_available(session):
        ctx.require(PAYMENTS_RECORD, company_id=job.company_id, branch_id=job.branch_id)
    if job.invoiced_at is not None:
        raise ValidationFailed("This job is already invoiced. Take the payment against the invoice")
    if amount <= 0:
        raise ValidationFailed("A deposit is more than zero")
    if not unit_enabled(session, "payments"):
        raise ValidationFailed("Taking a deposit needs Payments to be switched on")
    customer_id = invoicing.invoice_customer(session, job)
    if invoicing.invoicing_available(session):
        from ziira.modules.pos.public import take_payment

        taken = take_payment(session, customer_id=customer_id, branch_id=job.branch_id, amount=amount, method=method,
                             external_ref=reference, payment_account_id=payment_account_id)
        paid_id, paid_amount, paid_number = taken.id, taken.amount, taken.number
    else:
        from ziira.modules.payments.public import account_for_method, record_payment

        account = payment_account_id or account_for_method(session, job.company_id, job.branch_id, method)
        paid = record_payment(session, company_id=job.company_id, branch_id=job.branch_id, method=method,
                              amount=amount, payment_account_id=account, external_ref=reference,
                              party_type="customer", party_id=customer_id, allocations=[])
        paid_id, paid_amount, paid_number = paid.id, paid.amount, paid.number
    job.deposit_amount = (job.deposit_amount or Decimal(0)) + paid_amount
    job.deposit_payment_id, job.deposit_at = paid_id, datetime.now(UTC)
    job.deposit_note = clean(note, 300) or job.deposit_note
    session.flush()
    add_event(session, job, "deposit", f"Deposit of {paid_amount:,.2f} taken ({method}, payment {paid_number})")
    audit_record(session, "deposit", "jobs.job", job.id, {"payment": paid_number, "amount": str(paid_amount)})
    return job
