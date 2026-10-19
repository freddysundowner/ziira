"""Charges that are neither a part nor labour: towing, a courtesy car, an agreed fee, and storage after the item is
ready. They are invoiced under the 'Fees' item of the job settings (else the Labour item), so its tax code is theirs.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.domain import pricing
from ziira.modules.jobs.permissions import JOBS_MANAGE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobCharge
from ziira.modules.jobs.services import approval
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, clean, load_job
from ziira.modules.jobs.services.jobs import require_editable
from ziira.modules.products.public import find_product
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, company_today, current_context

KINDS = ("towing", "storage", "courtesy_car", "other")
MAX_CHARGES = 50


def tax_code(session: Session, company_id: UUID) -> UUID | None:
    """The tax code of the Fees item, else of the Labour item."""
    settings = job_settings.get_settings(session, company_id)
    product_id = settings.fees_product_id or settings.labour_product_id
    product = find_product(session, product_id) if product_id else None
    return product.tax_code_id if product is not None else None


def add_charge(session: Session, job_id: UUID, *, kind: str, description: str, unit_price: Decimal,
               quantity: Decimal = Decimal(1)) -> JobCharge:
    """Put a charge on the job (towing, courtesy car, an agreed fee). Needs 'jobs.manage'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    if kind not in KINDS:
        raise ValidationFailed("A charge is towing, storage, a courtesy car or other")
    if quantity <= 0 or unit_price < 0:
        raise ValidationFailed("Quantity must be more than zero and the price cannot be negative")
    name = clean(description, 300)
    if name is None:
        raise ValidationFailed("Say what the charge is for")
    if len([c for c in repo.charges(session, job.id) if c.voided_at is None]) >= MAX_CHARGES:
        raise ValidationFailed(f"At most {MAX_CHARGES} charges on a job")
    approval.guard(session, job, pricing.line_total(quantity, unit_price), name)
    row = JobCharge(tenant_id=ctx.tenant_id, created_by=ctx.user_id, job_id=job.id, kind=kind, description=name,
                    quantity=quantity, unit_price=unit_price, tax_code_id=tax_code(session, job.company_id))
    repo.add(session, row)
    add_event(session, job, "charge", name)
    audit_record(session, "add_charge", "jobs.job", job.id, {"charge": str(row.id), "kind": kind})
    return row


def remove_charge(session: Session, job_id: UUID, charge_id: UUID) -> JobCharge:
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    row = repo.get(session, JobCharge, charge_id)
    if row is None or row.job_id != job.id:
        raise NotFound("Charge not found")
    if row.voided_at is None:
        row.voided_at, row.voided_by = datetime.now(UTC), ctx.user_id
        session.flush()
        add_event(session, job, "charge", f"Removed {row.description}")
    return row


# --------------------------------------------------------------------------- storage after the item is ready
def storage_days(session: Session, job: Job) -> int:
    """Days the finished item stayed beyond the free days (0 when the business charges nothing)."""
    settings = job_settings.get_settings(session, job.company_id)
    if settings.storage_fee_per_day <= 0 or job.ready_at is None or job.storage_fee_waived:
        return 0
    end = job.collected_at.date() if job.collected_at else company_today(session, job.company_id)
    days = (end - job.ready_at.date()).days - settings.storage_grace_days
    return max(days, 0)


def storage_fee(session: Session, job: Job) -> Decimal:
    days = storage_days(session, job)
    return pricing.cents(job_settings.get_settings(session, job.company_id).storage_fee_per_day * days) if days else \
        Decimal(0)


def add_storage_fee(session: Session, job_id: UUID) -> JobCharge | None:
    """Turn the storage owed so far into a charge on the job (once; a second call replaces nothing and adds nothing
    unless more days have passed since). Needs 'jobs.manage'. None when nothing is owed."""
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    days = storage_days(session, job)
    already = sum((c.quantity for c in repo.charges(session, job.id, include_voided=False) if c.kind == "storage"),
                  Decimal(0))
    if days <= already:
        return None
    rate = job_settings.get_settings(session, job.company_id).storage_fee_per_day
    return add_charge(session, job_id, kind="storage", description=f"Storage ({int(days - already)} days)",
                      unit_price=rate, quantity=Decimal(days) - already)


def waive_storage_fee(session: Session, job_id: UUID, waived: bool = True) -> Job:
    job = load_job(session, job_id, lock=True)
    current_context().require(JOBS_MANAGE, company_id=job.company_id, branch_id=job.branch_id)
    job.storage_fee_waived = waived
    session.flush()
    add_event(session, job, "charge", "Storage fee waived" if waived else "Storage fee applies again")
    return job
