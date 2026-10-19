"""Use cases: estimates (quotes) and the customer's answer.

An estimate is a priced list of parts and labour with a version number. It is made as a draft, sent (which gives a
one-use link the customer can open without signing in) and then approved or declined: by staff on the customer's behalf
(with a note) or by the customer through the link. Sending a new version replaces the older ones. An approved estimate
moves the job to the 'approved' stage when the workflow allows that move from where the job is.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from ziira.modules.jobs.domain import pricing
from ziira.modules.jobs.permissions import JOBS_ESTIMATE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Estimate, EstimateLine, Job
from ziira.modules.jobs.services import notify, totals
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import add_event, clean, load_job
from ziira.modules.jobs.services.jobs import move_to_role, require_editable
from ziira.modules.jobs.services.parts import MAX_LINES, part_tax_code
from ziira.modules.products.public import find_product, selling_prices
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    company_today,
    current_context,
    hash_secret,
    new_secret,
    publish,
    settings_public_base_url,
)

KINDS = ("part", "labour", "other")


@dataclass(frozen=True)
class EstimateLineIn:
    kind: str
    description: str | None
    quantity: Decimal
    unit_price: Decimal | None = None          # tax included; blank: the product's price, or the labour rate
    product_id: UUID | None = None
    tax_code_id: UUID | None = None
    work_type_code: str | None = None
    part_class: str | None = None


def _build_lines(session: Session, job: Job, lines: list[EstimateLineIn]) -> list[EstimateLine]:
    if not lines or len(lines) > MAX_LINES:
        raise ValidationFailed(f"An estimate has between 1 and {MAX_LINES} lines")
    rates = totals.Rates(session)
    labour_code = totals.labour_tax_code(session, job.company_id)
    labour_rate = job_settings.get_settings(session, job.company_id).default_labour_rate
    tenant_id = current_context().tenant_id
    rows: list[EstimateLine] = []
    for position, line in enumerate(lines, start=1):
        if line.kind not in KINDS:
            raise ValidationFailed("A line is a part, labour or other")
        if line.quantity <= 0:
            raise ValidationFailed("Quantities must be more than zero")
        product = None
        if line.product_id is not None:
            product = find_product(session, line.product_id)
            if product is None or product.company_id != job.company_id or not product.is_active:
                raise ValidationFailed("A product on the estimate was not found in this company")
        description = clean(line.description, 300) or (product.name if product else None)
        if description is None:
            raise ValidationFailed("Every line needs a description")
        price = line.unit_price
        if price is None and line.kind == "labour":
            price = labour_rate
        elif price is None and product is not None:
            price = selling_prices(session, job.company_id, job.branch_id, {product.id}).get(product.id)
        if price is None or price < 0:
            raise ValidationFailed(f"Enter a price for {description}")
        code: UUID | None
        if line.tax_code_id is not None:
            code = line.tax_code_id
        elif line.kind == "labour":
            code = labour_code
        else:
            code = part_tax_code(session, job, product)
        gross = pricing.line_total(line.quantity, price)
        tax = pricing.tax_inside(gross, rates.of(code))
        rows.append(EstimateLine(tenant_id=tenant_id, estimate_id=UUID(int=0), position=position, kind=line.kind,
                                 product_id=product.id if product else None, description=description,
                                 quantity=line.quantity, unit_price=price, tax_code_id=code, net=gross - tax,
                                 tax=tax, work_type_code=line.work_type_code, part_class=line.part_class))
    return rows


def lines_from_job(session: Session, job: Job, *, since: datetime | None = None) -> list[EstimateLineIn]:
    """The job's current parts and labour as estimate lines (a part the customer brought is listed at no charge). With
    `since`, only what was put on the job after that moment (the extra work found after an approval)."""
    found = []
    for p in repo.parts(session, job.id, include_voided=False):
        if since is not None and p.created_at <= since:
            continue
        found.append(EstimateLineIn("part", p.description + (" (customer's part)" if p.source == "customer_supplied"
                                                              else ""), p.quantity, p.unit_price, p.product_id,
                                    p.tax_code_id, None, p.part_class))
    for x in repo.labour(session, job.id, include_voided=False):
        if since is not None and x.created_at <= since:
            continue
        if x.flat_price is not None:
            found.append(EstimateLineIn("labour", f"{x.description} ({x.hours.normalize():f} h, fixed price)",
                                        Decimal(1), x.flat_price, None, None, x.work_type_code))
        else:
            found.append(EstimateLineIn("labour", x.description, x.hours, x.rate, None, None, x.work_type_code))
    return found


def _store_lines(session: Session, estimate: Estimate, rows: list[EstimateLine]) -> None:
    for old in repo.estimate_lines(session, estimate.id):
        session.delete(old)
    session.flush()
    for row in rows:
        row.estimate_id = estimate.id
        session.add(row)
    session.flush()
    estimate.net = sum((r.net for r in rows), Decimal(0))
    estimate.tax = sum((r.tax for r in rows), Decimal(0))
    estimate.total = estimate.net + estimate.tax


def _load(session: Session, estimate_id: UUID, *, lock: bool = False) -> tuple[Estimate, Job]:
    estimate = repo.get(session, Estimate, estimate_id, lock=lock)
    if estimate is None:
        raise NotFound("Estimate not found")
    return estimate, load_job(session, estimate.job_id)


def create_estimate(session: Session, job_id: UUID, *, lines: list[EstimateLineIn] | None = None,
                    from_job: bool = False, notes: str | None = None, valid_until: date | None = None,
                    kind: str = "main") -> Estimate:
    """Make a new estimate (the next version) as a draft. With `from_job` the lines are the job's parts and labour so
    far. `kind` 'additional' is a request for more work found after the first approval: with `from_job` it lists only
    what was added since the latest approval, and approving it adds to what the customer has agreed to. Needs
    'jobs.estimate'."""
    job = load_job(session, job_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_ESTIMATE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    existing = repo.estimates(session, job.id)
    if any(e.status == "draft" for e in existing):
        raise Conflict("There is already a draft estimate for this job. Change it or send it first")
    if kind not in ("main", "additional"):
        raise ValidationFailed("An estimate is the main one or an additional-work one")
    since = None
    if kind == "additional":
        approved = [e for e in existing if e.status == "approved" and e.decided_at is not None]
        if not approved:
            raise ValidationFailed("Additional work follows an approved estimate. Get the first one approved")
        since = max(e.decided_at for e in approved if e.decided_at is not None)
    rows = _build_lines(session, job, lines if lines else (lines_from_job(session, job, since=since)
                                                           if from_job else []))
    estimate = Estimate(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=job.company_id, job_id=job.id,
                        version=max((e.version for e in existing), default=0) + 1, notes=clean(notes, 1000),
                        valid_until=valid_until, kind=kind)
    repo.add(session, estimate)
    _store_lines(session, estimate, rows)
    add_event(session, job, "estimate", f"{'Additional-work estimate' if kind == 'additional' else 'Estimate'} "
              f"version {estimate.version} drafted")
    audit_record(session, "create", "jobs.estimate", estimate.id, {"job": job.number, "version": estimate.version})
    return estimate


def update_estimate(session: Session, estimate_id: UUID, *, lines: list[EstimateLineIn] | None = None,
                    notes: str | None = None, valid_until: date | None = None, change_valid_until: bool = False,
                    change_notes: bool = False) -> Estimate:
    """Change a draft estimate (a sent one is replaced by a new version instead). Needs 'jobs.estimate'."""
    estimate, job = _load(session, estimate_id, lock=True)
    current_context().require(JOBS_ESTIMATE, company_id=job.company_id, branch_id=job.branch_id)
    if estimate.status != "draft":
        raise Conflict("Only a draft can be changed. Make a new version instead")
    require_editable(session, job)
    if lines is not None:
        _store_lines(session, estimate, _build_lines(session, job, lines))
    if change_notes:
        estimate.notes = clean(notes, 1000)
    if change_valid_until:
        estimate.valid_until = valid_until
    estimate.updated_by = current_context().user_id
    session.flush()
    return estimate


def get_estimate(session: Session, estimate_id: UUID) -> tuple[Estimate, list[EstimateLine]]:
    estimate, _ = _load(session, estimate_id)
    return estimate, repo.estimate_lines(session, estimate.id)


def send_estimate(session: Session, estimate_id: UUID, *, tell_customer: bool = False) -> tuple[Estimate, str]:
    """Send the estimate: it becomes the live version (older ones are replaced) and gets a link for the customer.
    Returns the estimate and the link's secret, shown only now (sending again makes a new link and ends the old one).
    With `tell_customer` the link is also queued as a message. Needs 'jobs.estimate'."""
    estimate, job = _load(session, estimate_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_ESTIMATE, company_id=job.company_id, branch_id=job.branch_id)
    require_editable(session, job)
    if estimate.status not in ("draft", "sent"):
        raise Conflict(f"This estimate is {estimate.status}. Make a new version to send")
    if estimate.total <= 0:
        raise ValidationFailed("An estimate must be worth more than nothing")
    day = company_today(session, job.company_id)
    for other in repo.estimates(session, job.id):
        if other.id == estimate.id or other.kind != estimate.kind:
            continue
        if other.status in ("sent", "draft") or (other.status == "approved" and estimate.kind == "main"):
            other.status = "superseded"
    if estimate.kind == "main":                        # a revised main estimate replaces the extras that depended on it
        for other in repo.estimates(session, job.id):
            if other.kind == "additional" and other.status in ("sent", "draft"):
                other.status = "superseded"
    secret = f"{ctx.tenant_id.hex}.{new_secret()}"
    estimate.status, estimate.link_hash, estimate.sent_at = "sent", hash_secret(secret), datetime.now(UTC)
    if estimate.valid_until is None:
        estimate.valid_until = day + timedelta(days=job_settings.get_settings(session, job.company_id)
                                               .estimate_valid_days)
    job.estimate_sent_at = estimate.sent_at
    session.flush()
    add_event(session, job, "estimate", f"Estimate version {estimate.version} sent")
    if estimate.kind == "main":
        move_to_role(session, job, "quoted", f"Estimate version {estimate.version} sent")
    audit_record(session, "send", "jobs.estimate", estimate.id, {"job": job.number, "version": estimate.version})
    if tell_customer:
        link = f"{settings_public_base_url().rstrip('/')}/job-approval/{secret}"
        notify.send_to_customer(session, job, "job_extra_work" if estimate.kind == "additional" else "job_estimate",
                                {"link": link},
                                key=f"job_estimate:{estimate.id}:{estimate.link_hash[:12]}")
    return estimate, secret


def decide(session: Session, estimate_id: UUID, *, approved: bool, note: str | None = None,
           customer_name: str | None = None) -> Estimate:
    """Record the customer's answer on their behalf (they said yes or no in person or by phone). Needs
    'jobs.estimate'."""
    estimate, job = _load(session, estimate_id, lock=True)
    ctx = current_context()
    ctx.require(JOBS_ESTIMATE, company_id=job.company_id, branch_id=job.branch_id)
    if estimate.status not in ("draft", "sent"):
        raise Conflict(f"This estimate is already {estimate.status}")
    require_editable(session, job)
    apply_decision(session, job, estimate, approved=approved, channel="staff", by_user=ctx.user_id,
                   by_name=clean(customer_name, 160), note=note)
    return estimate


def apply_decision(session: Session, job: Job, estimate: Estimate, *, approved: bool, channel: str,
                   by_user: UUID | None, by_name: str | None, note: str | None) -> None:
    """Store an answer on an estimate, put it on the timeline and, if approved, move the job along."""
    estimate.status = "approved" if approved else "declined"
    estimate.decided_at, estimate.decided_by, estimate.decided_by_name = datetime.now(UTC), by_user, by_name
    estimate.decision_channel, estimate.decision_note = channel, clean(note, 1000)
    session.flush()
    who = by_name or ("the customer" if channel == "link" else "staff")
    add_event(session, job, "approval", f"Estimate version {estimate.version} {'approved' if approved else 'declined'}"
              f" by {who} ({'link' if channel == 'link' else 'on their behalf'})"
              + (f": {estimate.decision_note}" if estimate.decision_note else ""))
    event = "job.estimate_approved" if approved else "job.estimate_declined"
    publish(session, Event(event, "jobs.job", job.id, {
        "company_id": job.company_id, "branch_id": job.branch_id, "number": job.number,
        "estimate_id": estimate.id, "version": estimate.version, "total": estimate.total, "channel": channel}))
    audit_record(session, "approve" if approved else "decline", "jobs.estimate", estimate.id, {"channel": channel})
    if approved and estimate.kind == "main":
        move_to_role(session, job, "approved", f"Estimate version {estimate.version} approved")
