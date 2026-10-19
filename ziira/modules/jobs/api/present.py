"""Turns jobs and their parts into the shapes the API returns (names looked up once, costs hidden from those who may
not see them)."""

from collections import defaultdict
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select

from ziira.modules.jobs.api import schemas as sc
from ziira.modules.jobs.permissions import JOBS_ESTIMATE, JOBS_INVOICE
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Asset, Estimate, Job, JobStatus
from ziira.modules.jobs.services import (
    access,
    approval,
    charges,
    claims_link,
    invoicing,
    photos,
    release,
    service_due,
    totals,
)
from ziira.modules.jobs.services.common import names_of
from ziira.sdk import Session, company_today, current_context, files

COST_PERMISSION = "stock.cost"


def status_ref(status: JobStatus) -> sc.StatusRef:
    return sc.StatusRef(id=status.id, code=status.code, name=status.name, kind=status.kind, role=status.role)


def summaries(session: Session, jobs: list[Job]) -> list[sc.JobSummaryOut]:
    """List rows for jobs: stage, item, person in charge and whether the job is late or locked."""
    stages = repo.statuses_by_ids(session, {j.status_id for j in jobs})
    assets = repo.assets_by_ids(session, {j.asset_id for j in jobs if j.asset_id})
    names = names_of(session, {j.assignee_id for j in jobs})
    counts = repo.task_counts(session, {j.id for j in jobs})
    blocked = repo.blockers(session, {j.id for j in jobs})
    for waiting_id in claims_link.waiting_on_payer(session, jobs):
        blocked.setdefault(waiting_id, []).append("insurer")
    days: dict[UUID, date] = {}
    now = datetime.now(UTC)
    out = []
    for job in jobs:
        today = days.setdefault(job.company_id, company_today(session, job.company_id))
        stage = stages[job.status_id]
        asset = assets.get(job.asset_id) if job.asset_id else None
        tasks_total, tasks_done = counts.get(job.id, (0, 0))
        out.append(sc.JobSummaryOut(
            id=job.id, company_id=job.company_id, branch_id=job.branch_id, number=job.number, title=job.title,
            status=status_ref(stage), customer_id=job.customer_id, customer_name=job.customer_name,
            customer_phone=job.customer_phone,
            asset=sc.AssetRef(id=asset.id, label=asset.label, kind=asset.kind) if asset else None,
            assignee_id=job.assignee_id, assignee_name=names.get(job.assignee_id) if job.assignee_id else None,
            received_at=job.received_at, promised_at=job.promised_at,
            overdue=bool(job.promised_at and job.promised_at < today and stage.kind in ("open", "waiting")),
            status_changed_at=job.status_changed_at, days_in_status=max((now - job.status_changed_at).days, 0),
            is_rework=job.is_rework, warranty_ends=job.warranty_ends, invoice_number=job.invoice_number,
            locked=job.invoiced_at is not None or stage.kind == "closed", tasks_total=tasks_total,
            tasks_done=tasks_done, job_type_code=job.job_type_code, waiting_on=blocked.get(job.id, []),
            has_claim=job.claim_id is not None, invoiced=job.invoiced_at is not None))
    return out


def asset_out(session: Session, asset: Asset) -> sc.AssetOut:
    """An item with how soon its next service is due."""
    out = sc.AssetOut.model_validate(asset)
    if asset.next_service_date is not None:
        out.service_due_in_days = (asset.next_service_date - company_today(session, asset.company_id)).days
    out.service_due_in_odometer = service_due.odometer_due(asset)
    return out


def estimate_out(session: Session, estimate: Estimate) -> sc.EstimateOut:
    lines = [sc.EstimateLineOut(id=x.id, kind=x.kind, product_id=x.product_id, description=x.description,
                                quantity=x.quantity, unit_price=x.unit_price, net=x.net, tax=x.tax, total=x.net + x.tax,
                                work_type_code=x.work_type_code, part_class=x.part_class)
             for x in repo.estimate_lines(session, estimate.id)]
    return sc.EstimateOut(
        id=estimate.id, job_id=estimate.job_id, version=estimate.version, kind=estimate.kind, status=estimate.status,
        notes=estimate.notes, valid_until=estimate.valid_until, net=estimate.net, tax=estimate.tax,
        total=estimate.total, sent_at=estimate.sent_at, decided_at=estimate.decided_at,
        decided_by_name=estimate.decided_by_name, decision_channel=estimate.decision_channel,
        decision_note=estimate.decision_note, lines=lines)


def detail(session: Session, job: Job) -> sc.JobOut:
    """Everything on one job: timeline, checklist, tasks, parts, labour, estimates, totals and what can happen next."""
    ctx = current_context()
    base = summaries(session, [job])[0]
    stage = repo.get(session, JobStatus, job.status_id)
    assert stage is not None
    names = names_of(session, {job.assignee_id, *(t.assignee_id for t in repo.tasks(session, job.id)),
                               *(x.assignee_id for x in repo.labour(session, job.id)),
                               *(e.created_by for e in repo.events(session, job.id))})
    status_names = {s.id: s.name for s in repo.statuses(session, job.company_id)}
    today = company_today(session, job.company_id)
    rates = totals.Rates(session)
    labour_rate = rates.of(totals.labour_tax_code(session, job.company_id))
    sees_cost = ctx.can(COST_PERMISSION, company_id=job.company_id, branch_id=job.branch_id)

    parts = []
    for p in repo.parts(session, job.id):
        total, tax = totals.part_amount(p, rates)
        parts.append(sc.PartOut(
            id=p.id, product_id=p.product_id, description=p.description, quantity=p.quantity, unit_price=p.unit_price,
            total=total, tax=tax, is_stock=p.is_stock, unit_cost=p.unit_cost if sees_cost else None,
            cost_value=p.cost_value if sees_cost else None, voided=p.voided_at is not None, source=p.source,
            part_class=p.part_class, category_code=p.category_code, order_status=p.order_status,
            supplier_name=p.supplier_name, purchase_order_number=p.purchase_order_number, expected_on=p.expected_on,
            arrived_at=p.arrived_at, keep_old_part=p.keep_old_part, old_part_note=p.old_part_note,
            void_reason=p.void_reason))
    labour = []
    for x in repo.labour(session, job.id):
        total, tax = totals.labour_amount(x, labour_rate)
        labour.append(sc.LabourOut(
            id=x.id, description=x.description, hours=x.hours, rate=x.rate, total=total, tax=tax,
            assignee_id=x.assignee_id, assignee_name=names.get(x.assignee_id) if x.assignee_id else None,
            work_date=x.work_date, source=x.source, voided=x.voided_at is not None,
            work_type_code=x.work_type_code, task_code=x.task_code, booked_hours=x.booked_hours,
            flat_price=x.flat_price))
    money = totals.job_totals(session, job)
    asset = repo.get(session, Asset, job.asset_id) if job.asset_id else None
    loans = _loans(session, job)
    bookings = _bookings(session, job)
    state = approval.state(session, job)
    found = release.check(session, job)
    original = repo.get(session, Job, job.rework_of_id) if job.rework_of_id else None
    visits = repo.list_jobs(session, access.view_scopes(), rework_of_id=job.id, limit=50)
    next_ids = [m for m in repo.moves_from(session, stage.id) if status_names.get(m) is not None]
    active = {s.id for s in repo.statuses(session, job.company_id, only_active=True)}
    return sc.JobOut(
        **base.model_dump(), description=job.description, condition_notes=job.condition_notes,
        collected_at=job.collected_at, collected_by_name=job.collected_by_name, warranty_days=job.warranty_days,
        rework_of=sc.JobRef(id=original.id, number=original.number) if original else None,
        return_visits=[sc.JobRef(id=v.id, number=v.number, in_warranty=v.rework_in_warranty) for v in visits],
        invoice_id=job.invoice_id, odometer_in=job.odometer_in, odometer_out=job.odometer_out,
        fuel_level=job.fuel_level, key_tag=job.key_tag, belongings=job.belongings,
        acknowledged_by_name=job.acknowledged_by_name, acknowledged_at=job.acknowledged_at,
        deposit_amount=job.deposit_amount, deposit_at=job.deposit_at, deposit_note=job.deposit_note,
        claim_id=job.claim_id, storage_days=charges.storage_days(session, job),
        storage_fee=charges.storage_fee(session, job), storage_fee_waived=job.storage_fee_waived,
        asset_detail=asset_out(session, asset) if asset else None,
        charges=[sc.JobChargeOut(id=c.id, kind=c.kind, description=c.description, quantity=c.quantity,
                                 unit_price=c.unit_price, total=amount[0], tax=amount[1],
                                 voided=c.voided_at is not None)
                 for c in repo.charges(session, job.id) for amount in [totals.charge_amount(c, rates)]],
        loans=loans, bay_bookings=bookings,
        claim=claim_section(session, job), photos=photo_section(session, job), photo_count=photo_total(session, job),
        approval=sc.JobApprovalOut(mode=state.mode, quoted=state.quoted, approved_total=state.approved_total,
                                   live_total=state.live_total, extra=state.extra),
        release=sc.JobReleaseOut(mode=found.mode, ok=found.ok, invoiced=found.invoiced, balance=found.balance,
                                 message=found.message),
        checklist=[sc.ChecklistItemOut(id=i.id, position=i.position, label=i.label, state=i.state, note=i.note)
                   for i in repo.checklist(session, job.id)],
        events=[sc.JobEventOut(id=e.id, kind=e.kind, note=e.note, from_status=status_names.get(e.from_status_id)
                            if e.from_status_id else None,
                            to_status=status_names.get(e.to_status_id) if e.to_status_id else None,
                            by=names.get(e.created_by) if e.created_by else None, created_at=e.created_at)
                for e in repo.events(session, job.id)],
        tasks=[sc.TaskOut(id=t.id, title=t.title, assignee_id=t.assignee_id,
                          assignee_name=names.get(t.assignee_id) if t.assignee_id else None, due_date=t.due_date,
                          done_at=t.done_at, overdue=bool(t.due_date and t.done_at is None and t.due_date < today))
               for t in repo.tasks(session, job.id)],
        parts=parts, labour=labour, estimates=[estimate_out(session, e) for e in repo.estimates(session, job.id)],
        totals=sc.TotalsOut(parts_total=money.parts.total, labour_total=money.labour.total,
                            charges_total=money.charges.total, tax=money.grand.tax, net=money.grand.net,
                            total=money.grand.total,
                            cost=money.cost if sees_cost else None),
        next_status_ids=[m for m in next_ids if m in active],
        can_invoice=(job.invoiced_at is None and stage.role != "cancelled"
                     and invoicing.invoicing_available(session)
                     and ctx.can(JOBS_INVOICE, company_id=job.company_id, branch_id=job.branch_id)))


def photo_section(session: Session, job: Job) -> list[sc.JobPhotoStatusOut]:
    return [sc.JobPhotoStatusOut(category=p.category, name=p.name, minimum=p.minimum, before=p.before, have=p.have,
                                 ok=p.ok) for p in photos.status(session, job)]


def photo_total(session: Session, job: Job) -> int:
    return files.counts(session, photos.ENTITY, [job.id]).get(job.id, 0)


def claim_section(session: Session, job: Job) -> sc.JobClaimOut | None:
    """The job's claim. A person who cannot make estimates or invoice sees only the authorised work, without prices."""
    state = claims_link.state(session, job)
    if state is None:
        return None
    ctx = current_context()
    limited = not (ctx.can(JOBS_ESTIMATE, company_id=job.company_id, branch_id=job.branch_id)
                   or ctx.can(JOBS_INVOICE, company_id=job.company_id, branch_id=job.branch_id))
    found = claims_link.gate(session, job)
    lines = claims_link.lines(session, job)
    if limited:
        lines = [x for x in lines if x.work_authorised]
    terms = claims_link.terms(session, job)
    return sc.JobClaimOut(
        id=state.id, number=state.number, status=state.status, closed_reason=state.closed_reason,
        payer_id=state.payer_id, payer_name=state.payer_name, waiting_on=state.waiting_on,
        policy_number=state.policy_number, claim_number=state.claim_number,
        excess=None if limited else state.excess, authorised_total=None if limited else state.authorised_total,
        payer_pays=None if limited else state.payer_pays, customer_pays=None if limited else state.customer_pays,
        open_total=None if limited else state.open_total, authority_ref=state.authority_ref,
        completed=state.completed, invoiced=state.invoiced,
        gate=sc.JobClaimGateOut(allowed=found.allowed, policy=found.policy, message=found.message, state=found.state,
                                decision_recorded=found.decision_recorded) if found else None,
        lines=[sc.JobClaimLineOut(
            id=x.id, description=x.description, kind=x.kind, quantity=x.quantity, state=x.state,
            work_authorised=x.work_authorised, payer_pays=None if limited else x.payer_pays,
            customer_pays=None if limited else x.customer_pays, asked_total=None if limited else x.asked_total,
            reason=x.reason, part_class=x.part_class, waiting_on=x.waiting_on) for x in lines],
        limited=limited, required_documents=terms.required_documents if terms else [])


def _loans(session: Session, job: Job) -> list[sc.JobLoanOut]:
    rows = repo.loans_of_job(session, job.id)
    cars = repo.assets_by_ids(session, {r.asset_id for r in rows})
    today = company_today(session, job.company_id)
    return [loan_out(r, cars[r.asset_id].label if r.asset_id in cars else "", job.number, today) for r in rows]


def loan_out(row, label: str, job_number: str | None, today: date) -> sc.JobLoanOut:  # type: ignore[no-untyped-def]
    return sc.JobLoanOut(
        id=row.id, job_id=row.job_id, asset_id=row.asset_id, asset_label=label, borrower_name=row.borrower_name,
        out_at=row.out_at, due_at=row.due_at, in_at=row.in_at, odometer_out=row.odometer_out,
        odometer_in=row.odometer_in, fuel_out=row.fuel_out, fuel_in=row.fuel_in, note=row.note,
        overdue=bool(row.in_at is None and row.due_at is not None and row.due_at < today), job_number=job_number)


def booking_out(booking, job: Job, bay_name: str | None, item: str | None, stage: str | None) -> sc.JobBayBookingOut:  # type: ignore[no-untyped-def]
    return sc.JobBayBookingOut(
        id=booking.id, job_id=booking.job_id, job_number=job.number, job_title=job.title, item=item, status=stage,
        bay_id=booking.bay_id, bay_name=bay_name, starts_at=booking.starts_at, ends_at=booking.ends_at,
        note=booking.note)


def _bookings(session: Session, job: Job) -> list[sc.JobBayBookingOut]:
    from ziira.modules.jobs.repository.models import Bay

    rows = repo.bay_bookings_of_job(session, job.id)
    bays = {b.id: b.name for b in session.scalars(select(Bay).where(Bay.id.in_({r.bay_id for r in rows})))} \
        if rows else {}
    return [booking_out(r, job, bays.get(r.bay_id), None, None) for r in rows]


def workflow(session: Session, rows: list[JobStatus], company_id: UUID) -> list[sc.StatusOut]:
    leaving: dict[UUID, list[UUID]] = defaultdict(list)
    for move in repo.moves(session, company_id):
        leaving[move.from_status_id].append(move.to_status_id)
    return [sc.StatusOut(id=s.id, company_id=s.company_id, code=s.code, name=s.name, kind=s.kind, role=s.role,
                         position=s.position, is_active=s.is_active, moves_to=leaving.get(s.id, [])) for s in rows]
