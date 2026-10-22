"""HTTP endpoints of the Jobs module. Routes only convert HTTP to service calls.

`public_router` holds the customer's estimate page (no sign-in): the link's secret is its credential.
"""

from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from ziira.modules.jobs.api import present
from ziira.modules.jobs.api import schemas as sc
from ziira.modules.jobs.permissions import (
    ALL,
    JOBS_ESTIMATE,
    JOBS_INVOICE,
    JOBS_MANAGE,
    JOBS_PARTS,
    JOBS_SETTINGS,
)
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job
from ziira.modules.jobs.services import (
    assets,
    bays,
    catalog,
    charges,
    claims_link,
    deposit,
    estimates,
    invoicing,
    jobs,
    loans,
    pack_steps,
    parts,
    photos,
    public_approval,
    reports,
    sample_data,
    service_due,
    statuses,
)
from ziira.modules.jobs.services import settings as job_settings
from ziira.modules.jobs.services.common import load_job
from ziira.modules.products.public import product_labels
from ziira.sdk import (
    DB_SESSION,
    Forbidden,
    RequestContext,
    Session,
    client_ip,
    idempotency_key_header,
    idempotent,
    page_limit,
    page_offset,
    request_context,
)

router = APIRouter()
public_router = APIRouter()
CREATED = status.HTTP_201_CREATED
NO_CONTENT = status.HTTP_204_NO_CONTENT


def any_of(*permissions: str):  # type: ignore[no-untyped-def]
    """Dependency: the actor holds at least one of the permissions somewhere (the service checks the scope)."""

    def check(ctx: RequestContext = Depends(request_context)) -> RequestContext:
        if not any(ctx.has_anywhere(p) for p in permissions):
            raise Forbidden(f"You need one of: {', '.join(permissions)}")
        return ctx

    return check


VIEW = [Depends(any_of(*ALL))]
MANAGE = [Depends(any_of(JOBS_MANAGE))]
PARTS = [Depends(any_of(JOBS_PARTS))]
ESTIMATE = [Depends(any_of(JOBS_ESTIMATE))]
INVOICE = [Depends(any_of(JOBS_INVOICE))]
SETTINGS = [Depends(any_of(JOBS_SETTINGS))]


def _job(session: Session, job_id: UUID) -> sc.JobOut:
    return present.detail(session, load_job(session, job_id))


# --------------------------------------------------------------------------- stages and settings
@router.get("/workflow", response_model=list[sc.StatusOut], dependencies=VIEW)
def get_workflow(company_id: UUID, include_inactive: bool = False, session: Session = DB_SESSION) -> object:
    """The company's stages in order, each with the stages a job can go to from it."""
    rows = statuses.list_statuses(session, company_id, only_active=not include_inactive)
    return present.workflow(session, rows, company_id)


@router.post("/statuses", response_model=sc.StatusOut, status_code=CREATED, dependencies=SETTINGS)
def post_status(body: sc.JobStatusIn, session: Session = DB_SESSION) -> object:
    row = statuses.create_status(session, **body.model_dump())
    return present.workflow(session, [row], row.company_id)[0]


@router.patch("/statuses/{status_id}", response_model=sc.StatusOut, dependencies=SETTINGS)
def patch_status(status_id: UUID, body: sc.StatusUpdate, session: Session = DB_SESSION) -> object:
    row = statuses.update_status(session, status_id, **body.model_dump(exclude_unset=True))
    return present.workflow(session, [row], row.company_id)[0]


@router.delete("/statuses/{status_id}", status_code=NO_CONTENT, dependencies=SETTINGS)
def delete_status(status_id: UUID, session: Session = DB_SESSION) -> Response:
    statuses.delete_status(session, status_id)
    return Response(status_code=NO_CONTENT)


@router.put("/statuses/{status_id}/moves", response_model=sc.StatusOut, dependencies=SETTINGS)
def put_moves(status_id: UUID, body: sc.MovesIn, session: Session = DB_SESSION) -> object:
    """Replace the stages a job may go to from this one."""
    statuses.set_moves_from(session, status_id, body.to_status_ids)
    row = repo.statuses_by_ids(session, {status_id})[status_id]
    return present.workflow(session, [row], row.company_id)[0]


@router.get("/settings", response_model=sc.JobSettingsOut, dependencies=VIEW)
def get_settings_(company_id: UUID, session: Session = DB_SESSION) -> object:
    return _settings_out(session, job_settings.get_settings(session, company_id))


def _settings_out(session: Session, row) -> sc.JobSettingsOut:  # type: ignore[no-untyped-def]
    wanted = (row.labour_product_id, row.parts_product_id, row.fees_product_id)
    labels = product_labels(session, {p for p in wanted if p})
    out = sc.JobSettingsOut.model_validate(row)
    if row.labour_product_id in labels:
        out.labour_product_name = labels[row.labour_product_id][1]
    if row.parts_product_id in labels:
        out.parts_product_name = labels[row.parts_product_id][1]
    if row.fees_product_id in labels:
        out.fees_product_name = labels[row.fees_product_id][1]
    out.invoicing_available = invoicing.invoicing_available(session)
    return out


@router.patch("/settings", response_model=sc.JobSettingsOut, dependencies=SETTINGS)
def patch_settings(company_id: UUID, body: sc.JobSettingsUpdate, session: Session = DB_SESSION) -> object:
    row = job_settings.update_settings(session, company_id, **body.model_dump(exclude_unset=True))
    return _settings_out(session, row)


@router.get("/checklist-templates", response_model=list[sc.JobTemplateOut], dependencies=VIEW)
def get_templates(company_id: UUID, only_active: bool = False, session: Session = DB_SESSION) -> object:
    return job_settings.list_templates(session, company_id, only_active=only_active)


@router.post("/checklist-templates", response_model=sc.JobTemplateOut, status_code=CREATED, dependencies=SETTINGS)
def post_template(body: sc.TemplateIn, session: Session = DB_SESSION) -> object:
    return job_settings.create_template(session, **body.model_dump())


@router.patch("/checklist-templates/{template_id}", response_model=sc.JobTemplateOut, dependencies=SETTINGS)
def patch_template(template_id: UUID, body: sc.TemplateUpdate, session: Session = DB_SESSION) -> object:
    return job_settings.update_template(session, template_id, **body.model_dump(exclude_unset=True))


@router.get("/people", response_model=list[sc.PersonOut], dependencies=VIEW)
def get_people(session: Session = DB_SESSION) -> object:
    """Staff who can be put in charge of a job or a task."""
    rows = session.execute(text("select id, full_name from kernel.app_user where status = 'active' "
                                "order by full_name limit 500"))
    return [sc.PersonOut(id=r.id, name=r.full_name) for r in rows]


# --------------------------------------------------------------------------- assets
@router.post("/assets", response_model=sc.AssetOut, status_code=CREATED, dependencies=MANAGE)
def post_asset(body: sc.AssetIn, session: Session = DB_SESSION) -> object:
    return assets.create_asset(session, **body.model_dump())


@router.get("/assets", response_model=list[sc.AssetOut], dependencies=VIEW)
def get_assets(search: str | None = Query(default=None, max_length=100), customer_id: UUID | None = None,
               include_inactive: bool = False, limit: int = page_limit(50), offset: int = page_offset(),
               session: Session = DB_SESSION) -> object:
    return assets.list_assets(session, search=search, customer_id=customer_id, only_active=not include_inactive,
                              limit=limit, offset=offset)


@router.get("/assets/{asset_id}", response_model=sc.AssetDetailOut, dependencies=VIEW)
def get_asset(asset_id: UUID, session: Session = DB_SESSION) -> object:
    """An item with every job it has had."""
    asset = assets.load_asset(session, asset_id)
    out = sc.AssetDetailOut.model_validate({**present.asset_out(session, asset).model_dump(), "jobs": []})
    out.jobs = present.summaries(session, assets.history(session, asset_id))
    return out


@router.get("/assets/{asset_id}/visits", response_model=list[sc.JobVisitOut], dependencies=VIEW)
def get_asset_visits(asset_id: UUID, limit: int = Query(default=10, ge=1, le=30),
                     session: Session = DB_SESSION) -> object:
    """The item's earlier visits with what was done on each: shown on the intake screen when it comes in again."""
    found = assets.visits(session, asset_id, limit)
    summaries = present.summaries(session, [v.job for v in found])
    return [sc.JobVisitOut(job=summaries[i], odometer_in=v.job.odometer_in, work=v.work, total=v.total)
            for i, v in enumerate(found)]


@router.get("/service-due", response_model=list[sc.JobServiceDueOut], dependencies=VIEW)
def get_service_due(company_id: UUID, within_days: int = Query(default=30, ge=0, le=365),
                    session: Session = DB_SESSION) -> object:
    """Items whose next service is near or past: who to call."""
    from ziira.modules.jobs.services.common import unit_enabled

    rows = service_due.due_items(session, company_id, within_days=within_days)
    names: dict[UUID, str] = {}
    if unit_enabled(session, "crm") and rows:
        from ziira.modules.crm.public import find_customers

        names = {k: v.name for k, v in find_customers(session, {a.customer_id for a in rows if a.customer_id}).items()}
    today = date.today()
    return [sc.JobServiceDueOut(asset=present.asset_out(session, a),
                                customer_name=names.get(a.customer_id) if a.customer_id else None,
                                overdue=bool(a.next_service_date and a.next_service_date < today)) for a in rows]


@router.patch("/assets/{asset_id}", response_model=sc.AssetOut, dependencies=MANAGE)
def patch_asset(asset_id: UUID, body: sc.AssetUpdate, session: Session = DB_SESSION) -> object:
    changes = body.model_dump(exclude_unset=True)
    service = {k: changes.pop(k) for k in ("next_service_date", "next_service_odometer", "next_service_note")
               if k in changes}
    row = assets.update_asset(session, asset_id, **changes)
    if service:
        row = assets.set_next_service(session, row, date_=service.get("next_service_date", row.next_service_date),
                                      odometer=service.get("next_service_odometer", row.next_service_odometer),
                                      note=service.get("next_service_note", row.next_service_note))
    return present.asset_out(session, row)


# --------------------------------------------------------------------------- jobs
@router.post("/jobs", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_job(body: sc.JobIn, key: str | None = Depends(idempotency_key_header),
             session: Session = DB_SESSION) -> object:
    """Take an item in. Send an Idempotency-Key so a retry from the counter does not make a second job."""

    def create() -> object:
        data = body.model_dump(exclude={"new_asset"})
        new_asset = jobs.NewAsset(**body.new_asset.model_dump()) if body.new_asset else None
        job = jobs.receive_job(session, new_asset=new_asset, **data)
        return jsonable_encoder(present.detail(session, job))

    response, _ = idempotent(session, key, body.model_dump(mode="json"), create)
    return response


@router.get("/jobs", response_model=list[sc.JobSummaryOut], dependencies=VIEW)
def get_jobs(company_id: UUID | None = None, branch_id: UUID | None = None, status_id: UUID | None = None,
             open_only: bool = False, assignee_id: UUID | None = None, asset_id: UUID | None = None,
             customer_id: UUID | None = None, search: str | None = Query(default=None, max_length=100),
             overdue: bool = False, waiting_on: str | None = Query(default=None, pattern="^(parts|approval|insurer)$"),
             job_type_code: str | None = Query(default=None, max_length=40),
             limit: int = page_limit(50), offset: int = page_offset(), session: Session = DB_SESSION) -> object:
    found = jobs.list_jobs(session, company_id=company_id, branch_id=branch_id, status_id=status_id,
                           open_only=open_only, assignee_id=assignee_id, asset_id=asset_id, customer_id=customer_id,
                           search=search, overdue=overdue, limit=limit, offset=offset, waiting_on=waiting_on,
                           job_type_code=job_type_code)
    return present.summaries(session, found)


@router.get("/jobs/board", response_model=sc.BoardOut, dependencies=VIEW)
def get_board(company_id: UUID, branch_id: UUID | None = None, assignee_id: UUID | None = None,
              asset_id: UUID | None = None, overdue: bool = False, include_closed: bool = False,
              search: str | None = Query(default=None, max_length=100), session: Session = DB_SESSION) -> object:
    """The job board: the stages as columns and the live jobs in them."""
    board = jobs.board(session, company_id=company_id, branch_id=branch_id, assignee_id=assignee_id,
                       asset_id=asset_id, overdue=overdue, include_closed=include_closed, search=search)
    return sc.BoardOut(statuses=[present.status_ref(s) for s in board.statuses],
                       jobs=present.summaries(session, board.jobs), truncated=board.truncated)


@router.get("/jobs/{job_id}", response_model=sc.JobOut, dependencies=VIEW)
def get_job(job_id: UUID, session: Session = DB_SESSION) -> object:
    return _job(session, job_id)


@router.patch("/jobs/{job_id}", response_model=sc.JobOut, dependencies=MANAGE)
def patch_job(job_id: UUID, body: sc.JobUpdate, session: Session = DB_SESSION) -> object:
    jobs.update_job(session, job_id, **body.model_dump(exclude_unset=True))
    return _job(session, job_id)


@router.post("/jobs/{job_id}/status", response_model=sc.JobOut, dependencies=MANAGE)
def post_status_change(job_id: UUID, body: sc.StatusChangeIn, session: Session = DB_SESSION) -> object:
    """Move the job to another stage (only the moves the workflow allows)."""
    jobs.change_status(session, job_id, body.to_status_id, body.note, collected_by_name=body.collected_by_name,
                       acknowledge_unpaid=body.acknowledge_unpaid, odometer_out=body.odometer_out)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/notes", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_note(job_id: UUID, body: sc.JobNoteIn, session: Session = DB_SESSION) -> object:
    jobs.add_note(session, job_id, body.text)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/collect", response_model=sc.JobOut, dependencies=MANAGE)
def post_collect(job_id: UUID, body: sc.CollectIn, session: Session = DB_SESSION) -> object:
    """The customer collects the item; the warranty starts today."""
    jobs.collect_job(session, job_id, collected_by_name=body.collected_by_name, note=body.note,
                     acknowledge_unpaid=body.acknowledge_unpaid, odometer_out=body.odometer_out)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/return-visit", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_return_visit(job_id: UUID, body: sc.ReturnVisitIn, session: Session = DB_SESSION) -> object:
    """A new job for the same customer and item, flagged as a return visit (warranty rework)."""
    visit = jobs.create_return_visit(session, job_id, title=body.title, description=body.description)
    return present.detail(session, visit)


@router.post("/jobs/{job_id}/invoice", response_model=sc.JobOut, dependencies=INVOICE)
def post_invoice(job_id: UUID, body: sc.JobInvoiceIn | None = None, session: Session = DB_SESSION) -> object:
    """Invoice the job to the customer (optionally paid now); the job is locked afterwards."""
    given = body or sc.JobInvoiceIn()
    invoicing.invoice_job(session, job_id, pay_method=given.pay_method, pay_reference=given.pay_reference)
    return _job(session, job_id)


# --- checklist and tasks
@router.post("/jobs/{job_id}/checklist", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_checklist_item(job_id: UUID, body: sc.ChecklistItemIn, session: Session = DB_SESSION) -> object:
    jobs.add_checklist_item(session, job_id, body.label)
    return _job(session, job_id)


@router.patch("/jobs/{job_id}/checklist/{item_id}", response_model=sc.JobOut, dependencies=MANAGE)
def patch_checklist_item(job_id: UUID, item_id: UUID, body: sc.ChecklistItemUpdate,
                         session: Session = DB_SESSION) -> object:
    jobs.set_checklist_item(session, job_id, item_id, **body.model_dump(exclude_unset=True))
    return _job(session, job_id)


@router.post("/jobs/{job_id}/tasks", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_task(job_id: UUID, body: sc.TaskIn, session: Session = DB_SESSION) -> object:
    jobs.add_task(session, job_id, **body.model_dump())
    return _job(session, job_id)


@router.patch("/jobs/{job_id}/tasks/{task_id}", response_model=sc.JobOut, dependencies=MANAGE)
def patch_task(job_id: UUID, task_id: UUID, body: sc.TaskUpdate, session: Session = DB_SESSION) -> object:
    jobs.update_task(session, job_id, task_id, **body.model_dump(exclude_unset=True))
    return _job(session, job_id)


@router.delete("/jobs/{job_id}/tasks/{task_id}", response_model=sc.JobOut, dependencies=MANAGE)
def delete_task(job_id: UUID, task_id: UUID, session: Session = DB_SESSION) -> object:
    jobs.delete_task(session, job_id, task_id)
    return _job(session, job_id)


# --- parts and labour
@router.post("/jobs/{job_id}/parts", response_model=sc.JobOut, status_code=CREATED, dependencies=PARTS)
def post_part(job_id: UUID, body: sc.PartIn, session: Session = DB_SESSION) -> object:
    """Use a part: stock products are issued from the branch's store; anything else is priced by hand."""
    parts.add_part(session, job_id, **body.model_dump())
    return _job(session, job_id)


@router.delete("/jobs/{job_id}/parts/{part_id}", response_model=sc.JobOut, dependencies=PARTS)
def delete_part(job_id: UUID, part_id: UUID, reason: str | None = Query(default=None, max_length=300),
                session: Session = DB_SESSION) -> object:
    """Take a part off the job; stock goes back where it came from."""
    parts.remove_part(session, job_id, part_id, reason)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/parts/{part_id}/ordered", response_model=sc.JobOut, dependencies=PARTS)
def post_part_ordered(job_id: UUID, part_id: UUID, body: sc.JobPartOrderedIn, session: Session = DB_SESSION) -> object:
    """A part for this job has been ordered from a supplier."""
    parts.mark_ordered(session, job_id, part_id, **body.model_dump())
    return _job(session, job_id)


@router.post("/jobs/{job_id}/parts/{part_id}/arrived", response_model=sc.JobOut, dependencies=PARTS)
def post_part_arrived(job_id: UUID, part_id: UUID, body: sc.JobPartArrivedIn, session: Session = DB_SESSION) -> object:
    """The ordered part arrived (stock parts are taken from the store now)."""
    parts.mark_arrived(session, job_id, part_id, location_id=body.location_id)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/parts/{part_id}/return", response_model=sc.JobOut, dependencies=PARTS)
def post_part_return(job_id: UUID, part_id: UUID, body: sc.JobPartReturnIn, session: Session = DB_SESSION) -> object:
    """Some of a part was not used: put that quantity back."""
    parts.return_unused(session, job_id, part_id, quantity=body.quantity, reason=body.reason)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/charges", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_charge(job_id: UUID, body: sc.JobChargeIn, session: Session = DB_SESSION) -> object:
    """Towing, a courtesy car, an agreed fee: a charge that is not a part or labour."""
    charges.add_charge(session, job_id, **body.model_dump())
    return _job(session, job_id)


@router.delete("/jobs/{job_id}/charges/{charge_id}", response_model=sc.JobOut, dependencies=MANAGE)
def delete_charge(job_id: UUID, charge_id: UUID, session: Session = DB_SESSION) -> object:
    charges.remove_charge(session, job_id, charge_id)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/storage-fee", response_model=sc.JobOut, dependencies=MANAGE)
def post_storage_fee(job_id: UUID, session: Session = DB_SESSION) -> object:
    """Add the storage owed so far (the item stayed after it was ready) as a charge."""
    charges.add_storage_fee(session, job_id)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/storage-fee/waive", response_model=sc.JobOut, dependencies=MANAGE)
def post_waive_storage(job_id: UUID, waived: bool = True, session: Session = DB_SESSION) -> object:
    charges.waive_storage_fee(session, job_id, waived)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/deposit", response_model=sc.JobOut, dependencies=MANAGE)
def post_deposit(job_id: UUID, body: sc.JobDepositIn, session: Session = DB_SESSION) -> object:
    """Take money in advance (a deposit on an order)."""
    deposit.take_deposit(session, job_id, **body.model_dump())
    return _job(session, job_id)


# --- the insurer (or fleet) claim of a job
@router.post("/jobs/{job_id}/claim", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_claim(job_id: UUID, body: sc.JobClaimOpenIn, session: Session = DB_SESSION) -> object:
    """Open a claim for this job: an insurer or a fleet owner pays all or part of it."""
    claims_link.open_claim(session, load_job(session, job_id, lock=True), **body.model_dump())
    return _job(session, job_id)


@router.post("/jobs/{job_id}/claim/estimate", response_model=sc.JobClaimEstimateOut, status_code=CREATED,
             dependencies=ESTIMATE)
def post_claim_estimate(job_id: UUID, body: sc.JobClaimEstimateIn, session: Session = DB_SESSION) -> object:
    """Draft the estimate for the payer from the job's parts and labour; open it in Claims to send it."""
    estimate_id = claims_link.draft_estimate(session, load_job(session, job_id, lock=True), kind=body.kind)
    return sc.JobClaimEstimateOut(claim_estimate_id=estimate_id)


@router.post("/jobs/{job_id}/claim/complete", response_model=sc.JobOut, dependencies=MANAGE)
def post_claim_complete(job_id: UUID, body: sc.JobClaimCompleteIn, session: Session = DB_SESSION) -> object:
    """Write down who signed the finished work off: the claim can then be invoiced."""
    claims_link.complete(session, load_job(session, job_id, lock=True), signed_by=body.signed_by, note=body.note)
    return _job(session, job_id)


@router.post("/jobs/{job_id}/customer-record", response_model=sc.JobOut, dependencies=MANAGE)
def post_customer_record(job_id: UUID, session: Session = DB_SESSION) -> object:
    """Give a walk-in job a customer record (matched or made from its phone, else the walk-in customer): needed
    before an insurer claim, whose excess is invoiced to the customer."""
    job = load_job(session, job_id, lock=True)
    jobs.require_editable(session, job)
    invoicing.invoice_customer(session, job)
    return _job(session, job_id)


# --- courtesy cars
@router.post("/jobs/{job_id}/loans", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_loan(job_id: UUID, body: sc.JobLoanIn, session: Session = DB_SESSION) -> object:
    loans.lend(session, job_id, **body.model_dump())
    return _job(session, job_id)


@router.post("/loans/{loan_id}/return", response_model=sc.JobOut, dependencies=MANAGE)
def post_loan_return(loan_id: UUID, body: sc.JobLoanReturnIn, session: Session = DB_SESSION) -> object:
    row = loans.take_back(session, loan_id, **body.model_dump())
    return _job(session, row.job_id)


@router.get("/loans/out", response_model=list[sc.JobLoanOut], dependencies=VIEW)
def get_loans_out(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Courtesy cars out on loan now."""
    rows = loans.out_now(session, company_id)
    cars = repo.assets_by_ids(session, {r.asset_id for r in rows})
    numbers = {j.id: j.number for j in (repo.get(session, Job, r.job_id) for r in rows) if j}
    today = date.today()
    return [present.loan_out(r, cars[r.asset_id].label if r.asset_id in cars else "", numbers.get(r.job_id), today)
            for r in rows]


# --- bays and the bay board
@router.get("/bays", response_model=list[sc.JobBayOut], dependencies=VIEW)
def get_bays(company_id: UUID, branch_id: UUID | None = None, include_inactive: bool = False,
             session: Session = DB_SESSION) -> object:
    return bays.list_bays(session, company_id, branch_id, only_active=not include_inactive)


@router.post("/bays", response_model=sc.JobBayOut, status_code=CREATED, dependencies=SETTINGS)
def post_bay(body: sc.JobBayIn, session: Session = DB_SESSION) -> object:
    return bays.create_bay(session, **body.model_dump())


@router.patch("/bays/{bay_id}", response_model=sc.JobBayOut, dependencies=SETTINGS)
def patch_bay(bay_id: UUID, body: sc.JobBayUpdate, session: Session = DB_SESSION) -> object:
    return bays.update_bay(session, bay_id, **body.model_dump(exclude_unset=True))


@router.get("/bay-board", response_model=sc.JobBayBoardOut, dependencies=VIEW)
def get_bay_board(company_id: UUID, branch_id: UUID,
                  day: Annotated[date, Query(ge=date(1900, 1, 1), le=date(2200, 12, 31))] | None = None,
                  days: int = Query(default=7, ge=1, le=31), session: Session = DB_SESSION) -> object:
    """The bays of a branch and the jobs booked into them for the coming days."""
    from ziira.sdk import company_today

    first = day or company_today(session, company_id)
    found = bays.board(session, company_id, branch_id, first, days)
    names = {b.id: b.name for b in bays.list_bays(session, company_id, branch_id)}
    assets_by_id = repo.assets_by_ids(session, {j.asset_id for _, j in found if j.asset_id})
    stages = repo.statuses_by_ids(session, {j.status_id for _, j in found})
    return sc.JobBayBoardOut(
        bays=[sc.JobBayOut.model_validate(b) for b in bays.list_bays(session, company_id, branch_id, only_active=True)],
        bookings=[present.booking_out(b, j, names.get(b.bay_id), assets_by_id[j.asset_id].label if j.asset_id
                                      in assets_by_id else None, stages[j.status_id].name) for b, j in found])


@router.post("/jobs/{job_id}/bay-bookings", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_bay_booking(job_id: UUID, body: sc.JobBayBookingIn, session: Session = DB_SESSION) -> object:
    """Put the job in a bay for a time (refused when the bay is busy then)."""
    bays.book(session, job_id, **body.model_dump())
    return _job(session, job_id)


@router.delete("/bay-bookings/{booking_id}", response_model=sc.JobOut, dependencies=MANAGE)
def delete_bay_booking(booking_id: UUID, session: Session = DB_SESSION) -> object:
    row = bays.cancel(session, booking_id)
    return _job(session, row.job_id)


# --- the pack's first-run steps and sample week
@router.get("/pack-steps", response_model=list[sc.JobPackStepOut], dependencies=VIEW)
def get_pack_steps(company_id: UUID, session: Session = DB_SESSION) -> object:
    """The first-run checklist an industry pack gave this business (ticks itself)."""
    return [sc.JobPackStepOut(id=r["id"], pack=r["pack"], step_id=r["step_id"], title=r["title"], hint=r["hint"],
                              to_path=r["to_path"], check_key=r["check_key"], done=r["done"], hidden=r["hidden"])
            for r in pack_steps.steps_for(session, company_id)]


@router.post("/pack-steps/hide", status_code=NO_CONTENT, dependencies=SETTINGS)
def post_hide_pack_steps(company_id: UUID, hidden: bool = True, session: Session = DB_SESSION) -> Response:
    pack_steps.hide(session, company_id, hidden)
    return Response(status_code=NO_CONTENT)


@router.post("/pack-steps/{step_id}/done", status_code=NO_CONTENT, dependencies=MANAGE)
def post_pack_step_done(step_id: UUID, done: bool = True, session: Session = DB_SESSION) -> Response:
    pack_steps.mark_done(session, step_id, done)
    return Response(status_code=NO_CONTENT)


@router.get("/sample-data", response_model=sc.JobSampleStatusOut, dependencies=VIEW)
def get_sample_status(company_id: UUID, session: Session = DB_SESSION) -> object:
    return sample_data.status(session, company_id)


@router.post("/sample-data", response_model=sc.JobSampleResultOut, status_code=CREATED, dependencies=SETTINGS)
def post_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Fill the business with the sample week its industry pack ships."""
    return sc.JobSampleResultOut(counts=sample_data.load(session, company_id))


@router.delete("/sample-data", response_model=sc.JobSampleResultOut, dependencies=SETTINGS)
def delete_sample_data(company_id: UUID, session: Session = DB_SESSION) -> object:
    """Take the sample week away again (a sample job that was invoiced stays)."""
    return sc.JobSampleResultOut(counts=sample_data.remove(session, company_id))


# --- technicians
@router.get("/reports/technicians", response_model=list[sc.JobTechnicianOut], dependencies=VIEW)
def get_technicians(company_id: UUID, date_from: date | None = None, date_to: date | None = None,
                    branch_id: UUID | None = None, session: Session = DB_SESSION) -> object:
    """Hours booked against hours billed per technician (default: the last 30 days)."""
    from ziira.sdk import company_today

    end = date_to or company_today(session, company_id)
    rows = reports.technicians(session, company_id=company_id, date_from=date_from or end - timedelta(days=29),
                               date_to=end, branch_id=branch_id)
    return [sc.JobTechnicianOut(user_id=r.user_id, name=r.name, lines=r.lines, booked_hours=r.booked_hours,
                                billed_hours=r.billed_hours, lines_without_booked=r.lines_without_booked,
                                billed_value=r.billed_value, jobs_open=r.jobs_open) for r in rows]


# --- the workshop's catalogue
@router.get("/work-types", response_model=list[sc.JobWorkTypeOut], dependencies=VIEW)
def get_work_types(company_id: UUID, only_active: bool = False, session: Session = DB_SESSION) -> object:
    return catalog.list_work_types(session, company_id, only_active=only_active)


@router.post("/work-types", response_model=sc.JobWorkTypeOut, status_code=CREATED, dependencies=SETTINGS)
def post_work_type(body: sc.JobWorkTypeIn, session: Session = DB_SESSION) -> object:
    return catalog.create_work_type(session, **body.model_dump())


@router.patch("/work-types/{row_id}", response_model=sc.JobWorkTypeOut, dependencies=SETTINGS)
def patch_work_type(row_id: UUID, body: sc.JobWorkTypeUpdate, session: Session = DB_SESSION) -> object:
    return catalog.update_work_type(session, row_id, **body.model_dump(exclude_unset=True))


@router.get("/labour-tasks", response_model=list[sc.JobTaskLibraryOut], dependencies=VIEW)
def get_labour_tasks(company_id: UUID, only_active: bool = False,
                     search: str | None = Query(default=None, max_length=100), session: Session = DB_SESSION) -> object:
    """The flat-rate library: standard jobs with a standard time (and maybe a fixed price)."""
    return catalog.list_tasks(session, company_id, only_active=only_active, search=search)


@router.post("/labour-tasks", response_model=sc.JobTaskLibraryOut, status_code=CREATED, dependencies=SETTINGS)
def post_labour_task(body: sc.JobTaskLibraryIn, session: Session = DB_SESSION) -> object:
    return catalog.create_task(session, **body.model_dump())


@router.patch("/labour-tasks/{row_id}", response_model=sc.JobTaskLibraryOut, dependencies=SETTINGS)
def patch_labour_task(row_id: UUID, body: sc.JobTaskLibraryUpdate, session: Session = DB_SESSION) -> object:
    return catalog.update_task(session, row_id, **body.model_dump(exclude_unset=True))


@router.get("/part-categories", response_model=list[sc.JobPartCategoryOut], dependencies=VIEW)
def get_part_categories(company_id: UUID, only_active: bool = False, session: Session = DB_SESSION) -> object:
    return catalog.list_part_categories(session, company_id, only_active=only_active)


@router.post("/part-categories", response_model=sc.JobPartCategoryOut, status_code=CREATED, dependencies=SETTINGS)
def post_part_category(body: sc.JobPartCategoryIn, session: Session = DB_SESSION) -> object:
    return catalog.create_part_category(session, **body.model_dump())


@router.patch("/part-categories/{row_id}", response_model=sc.JobPartCategoryOut, dependencies=SETTINGS)
def patch_part_category(row_id: UUID, body: sc.JobPartCategoryUpdate, session: Session = DB_SESSION) -> object:
    return catalog.update_part_category(session, row_id, **body.model_dump(exclude_unset=True))


@router.get("/photo-categories", response_model=list[sc.JobPhotoCategoryOut], dependencies=VIEW)
def get_photo_categories(company_id: UUID, only_active: bool = False, session: Session = DB_SESSION) -> object:
    """The kinds of photo this workshop takes (intake, damage, odometer ...)."""
    return photos.list_categories(session, company_id, only_active=only_active)


@router.post("/photo-categories", response_model=sc.JobPhotoCategoryOut, status_code=CREATED, dependencies=SETTINGS)
def post_photo_category(body: sc.JobPhotoCategoryIn, session: Session = DB_SESSION) -> object:
    return photos.create_category(session, **body.model_dump())


@router.patch("/photo-categories/{row_id}", response_model=sc.JobPhotoCategoryOut, dependencies=SETTINGS)
def patch_photo_category(row_id: UUID, body: sc.JobPhotoCategoryUpdate, session: Session = DB_SESSION) -> object:
    return photos.update_category(session, row_id, **body.model_dump(exclude_unset=True))


@router.get("/job-types", response_model=list[sc.JobTypeOut], dependencies=VIEW)
def get_job_types(company_id: UUID, only_active: bool = False, session: Session = DB_SESSION) -> object:
    return catalog.list_job_types(session, company_id, only_active=only_active)


@router.post("/job-types", response_model=sc.JobTypeOut, status_code=CREATED, dependencies=SETTINGS)
def post_job_type(body: sc.JobTypeIn, session: Session = DB_SESSION) -> object:
    return catalog.create_job_type(session, **body.model_dump())


@router.patch("/job-types/{row_id}", response_model=sc.JobTypeOut, dependencies=SETTINGS)
def patch_job_type(row_id: UUID, body: sc.JobTypeUpdate, session: Session = DB_SESSION) -> object:
    return catalog.update_job_type(session, row_id, **body.model_dump(exclude_unset=True))


@router.post("/jobs/{job_id}/labour", response_model=sc.JobOut, status_code=CREATED, dependencies=MANAGE)
def post_labour(job_id: UUID, body: sc.LabourIn, session: Session = DB_SESSION) -> object:
    """Labour by hours and rate, by work type, or a task from the flat-rate library."""
    parts.add_labour(session, job_id, **body.model_dump())
    return _job(session, job_id)


@router.post("/jobs/{job_id}/labour/{line_id}/booked", response_model=sc.JobOut, dependencies=MANAGE)
def post_booked_hours(job_id: UUID, line_id: UUID, body: sc.JobBookedIn, session: Session = DB_SESSION) -> object:
    """How long the technician really worked on this line (the billed hours stay as quoted)."""
    parts.book_hours(session, job_id, line_id, body.booked_hours)
    return _job(session, job_id)


@router.delete("/jobs/{job_id}/labour/{line_id}", response_model=sc.JobOut, dependencies=MANAGE)
def delete_labour(job_id: UUID, line_id: UUID, session: Session = DB_SESSION) -> object:
    parts.remove_labour(session, job_id, line_id)
    return _job(session, job_id)


# --- estimates
def _lines(body: list[sc.EstimateLineBody]) -> list[estimates.EstimateLineIn]:
    return [estimates.EstimateLineIn(**x.model_dump()) for x in body]


@router.post("/jobs/{job_id}/estimates", response_model=sc.EstimateOut, status_code=CREATED, dependencies=ESTIMATE)
def post_estimate(job_id: UUID, body: sc.EstimateIn, session: Session = DB_SESSION) -> object:
    """A new version of the estimate, as a draft. `from_job` fills it with the parts and labour on the job."""
    made = estimates.create_estimate(session, job_id, lines=_lines(body.lines), from_job=body.from_job,
                                     notes=body.notes, valid_until=body.valid_until, kind=body.kind)
    return present.estimate_out(session, made)


@router.patch("/estimates/{estimate_id}", response_model=sc.EstimateOut, dependencies=ESTIMATE)
def patch_estimate(estimate_id: UUID, body: sc.EstimateUpdate, session: Session = DB_SESSION) -> object:
    given = body.model_fields_set
    changed = estimates.update_estimate(
        session, estimate_id, lines=_lines(body.lines) if body.lines is not None else None, notes=body.notes,
        valid_until=body.valid_until, change_notes="notes" in given, change_valid_until="valid_until" in given)
    return present.estimate_out(session, changed)


@router.post("/estimates/{estimate_id}/send", response_model=sc.EstimateSentOut, dependencies=ESTIMATE)
def post_send_estimate(estimate_id: UUID, body: sc.EstimateSendIn, session: Session = DB_SESSION) -> object:
    """Send the estimate. The reply holds the customer's link once; sending again makes a new link."""
    sent, secret = estimates.send_estimate(session, estimate_id, tell_customer=body.tell_customer)
    return sc.EstimateSentOut(estimate=present.estimate_out(session, sent), link_path=f"/job-approval/{secret}")


@router.post("/estimates/{estimate_id}/decision", response_model=sc.EstimateOut, dependencies=ESTIMATE)
def post_decision(estimate_id: UUID, body: sc.EstimateDecisionIn, session: Session = DB_SESSION) -> object:
    """Record the customer's answer for them (they said yes or no in person or by phone)."""
    done = estimates.decide(session, estimate_id, approved=body.approved, note=body.note,
                            customer_name=body.customer_name)
    return present.estimate_out(session, done)


# =========================================================================== the customer's page (no sign-in)
@public_router.get("/public/job-approval/{token}", response_model=sc.PublicEstimateOut, include_in_schema=True)
def get_public_estimate(token: str, request: Request) -> object:
    """The estimate behind a link: lines and totals only."""
    return public_approval.view(token, client_ip(request))


@public_router.post("/public/job-approval/{token}", response_model=sc.PublicAnswerOut)
def post_public_answer(token: str, body: sc.PublicAnswerIn, request: Request) -> object:
    """The customer approves or declines. One answer per link."""
    return public_approval.answer(token, client_ip(request), approve=body.approve, name=body.name, note=body.note)


