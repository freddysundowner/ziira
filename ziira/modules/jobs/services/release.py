"""Handing the item back: is the job paid for?

A business chooses (job settings) what happens when an item is released before its invoice is paid: nothing, a warning
the person must confirm, or a block. A customer on credit terms (a fleet, a company account) is released without a
warning: their invoice is meant to be paid later. Reads POS through its public functions only.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import claims_link
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, unit_enabled
from ziira.sdk import Conflict, Session, ValidationFailed, audit_record

if TYPE_CHECKING:
    from ziira.modules.claims.public import ClaimState


@dataclass(frozen=True)
class ReleaseCheck:
    mode: str                       # off | warn | block
    ok: bool                        # nothing to warn about
    invoiced: bool
    balance: Decimal | None         # still owed on the invoice
    message: str | None


def check(session: Session, job: Job) -> ReleaseCheck:
    mode = job_settings.get_settings(session, job.company_id).release_unpaid
    if mode == "off":
        return ReleaseCheck(mode, True, job.invoice_id is not None, None, None)
    if not unit_enabled(session, "pos"):
        return ReleaseCheck(mode, True, job.invoice_id is not None, None, None)
    claim = claims_link.state(session, job)
    if claim is not None and claim.status != "closed":
        return _claim_check(session, job, mode, claim)
    if job.invoice_id is None:
        return ReleaseCheck(mode, False, False, None, "This job has not been invoiced yet")
    from ziira.modules.pos.public import customer_balance, invoice_balance

    owed = invoice_balance(session, job.invoice_id)
    if owed is None or owed <= 0:
        return ReleaseCheck(mode, True, True, Decimal(0), None)
    if job.customer_id is not None:
        if customer_balance(session, job.customer_id) <= 0:               # an advance or deposit covers it
            return ReleaseCheck(mode, True, True, owed, None)
        if unit_enabled(session, "crm"):
            from ziira.modules.crm.public import find_customer

            customer = find_customer(session, job.customer_id)
            if customer is not None and customer.payment_terms_days > 0 and customer.credit_limit > 0:
                return ReleaseCheck(mode, True, True, owed, None)         # an account customer pays later
    return ReleaseCheck(mode, False, True, owed, f"The invoice {job.invoice_number} still has {owed:,.2f} to pay")


def _claim_check(session: Session, job: Job, mode: str, claim: "ClaimState") -> ReleaseCheck:
    """An insurer job: the payer pays its part later; what the customer owes (the excess and anything they agreed to
    pay) is what must be settled before the item is handed over."""
    from ziira.modules.pos.public import customer_balance

    share = max(claim.customer_pays, claim.excess)
    if not claim.invoiced:
        if share > 0:
            return ReleaseCheck(mode, False, False, share,
                                f"The customer's share ({share:,.2f}, the excess) has not been invoiced yet")
        return ReleaseCheck(mode, True, False, None, None)
    if job.customer_id is not None:
        owed = customer_balance(session, job.customer_id)
        if owed > 0:
            return ReleaseCheck(mode, False, True, owed, f"The customer still owes {owed:,.2f} on the claim")
    return ReleaseCheck(mode, True, True, Decimal(0), None)


def guard(session: Session, job: Job, *, acknowledged: bool) -> None:
    """Before the item is handed over: refuse (block), or ask for confirmation (warn), when it is not paid for."""
    found = check(session, job)
    if found.ok:
        return
    if found.mode == "block":
        raise ValidationFailed(f"{found.message}. This business does not release an item before it is paid")
    if not acknowledged:
        raise Conflict(f"{found.message}. Confirm to hand the item over anyway")
    add_event(session, job, "release", f"Released before payment: {found.message}")
    audit_record(session, "release_unpaid", "jobs.job", job.id, {"message": found.message or ""})
