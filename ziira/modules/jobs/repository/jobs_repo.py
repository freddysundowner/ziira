"""Database access for the jobs schema. Row-level security scopes every query to the tenant."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Text, and_, cast, exists, false, func, or_, select, true
from sqlalchemy.orm import Session

from ziira.modules.jobs.repository.models import (
    Asset,
    BayBooking,
    ChecklistTemplate,
    Estimate,
    EstimateLine,
    Job,
    JobCharge,
    JobChecklistItem,
    JobEvent,
    JobLabour,
    JobPart,
    JobSetting,
    JobStatus,
    JobStatusMove,
    JobTask,
    JobType,
    LabourTask,
    Loan,
    PartCategory,
    WorkType,
)
from ziira.sdk import like_pattern

Scopes = list[tuple[UUID | None, UUID | None]] | None


def in_scope(scopes: Scopes, company_col: Any, branch_col: Any) -> ColumnElement[bool]:
    """Rows of the companies and branches the user may see (None means everywhere)."""
    if scopes is None:
        return true()
    return or_(false(), *(and_(company_col == c, true() if b is None else branch_col == b) for c, b in scopes))


def add(session: Session, record: Any) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def get[T](session: Session, model: type[T], record_id: UUID, *, lock: bool = False) -> T | None:
    if lock:
        return session.scalars(select(model).where(model.id == record_id)  # type: ignore[attr-defined]
                               .with_for_update().execution_options(populate_existing=True)).first()
    return session.get(model, record_id)


# --------------------------------------------------------------------------- settings, stages, checklists
def get_setting(session: Session, company_id: UUID) -> JobSetting | None:
    return session.scalar(select(JobSetting).where(JobSetting.company_id == company_id))


def statuses(session: Session, company_id: UUID, *, only_active: bool = False) -> list[JobStatus]:
    query = select(JobStatus).where(JobStatus.company_id == company_id)
    if only_active:
        query = query.where(JobStatus.is_active)
    return list(session.scalars(query.order_by(JobStatus.position, JobStatus.code)))


def status_by_role(session: Session, company_id: UUID, role: str) -> JobStatus | None:
    return session.scalar(select(JobStatus).where(JobStatus.company_id == company_id, JobStatus.role == role,
                                                  JobStatus.is_active))


def status_by_code(session: Session, company_id: UUID, code: str) -> JobStatus | None:
    return session.scalar(select(JobStatus).where(JobStatus.company_id == company_id, JobStatus.code == code))


def moves(session: Session, company_id: UUID) -> list[JobStatusMove]:
    return list(session.scalars(select(JobStatusMove).where(JobStatusMove.company_id == company_id)))


def move_pair(session: Session, from_id: UUID, to_id: UUID) -> JobStatusMove | None:
    return session.scalar(select(JobStatusMove).where(JobStatusMove.from_status_id == from_id,
                                                      JobStatusMove.to_status_id == to_id))


def templates(session: Session, company_id: UUID, *, only_active: bool = False) -> list[ChecklistTemplate]:
    query = select(ChecklistTemplate).where(ChecklistTemplate.company_id == company_id)
    if only_active:
        query = query.where(ChecklistTemplate.is_active)
    return list(session.scalars(query.order_by(ChecklistTemplate.name)))


def template_by_name(session: Session, company_id: UUID, name: str) -> ChecklistTemplate | None:
    return session.scalar(select(ChecklistTemplate).where(ChecklistTemplate.company_id == company_id,
                                                          ChecklistTemplate.name == name))


# --------------------------------------------------------------------------- assets
def list_assets(session: Session, company_ids: set[UUID] | None, *, search: str | None, customer_id: UUID | None,
                only_active: bool, limit: int, offset: int) -> list[Asset]:
    query = select(Asset)
    if company_ids is not None:
        query = query.where(Asset.company_id.in_(company_ids))
    if customer_id is not None:
        query = query.where(Asset.customer_id == customer_id)
    if only_active:
        query = query.where(Asset.is_active)
    if search:
        pattern = like_pattern(search)
        query = query.where(or_(Asset.label.ilike(pattern), cast(Asset.identifiers, Text).ilike(pattern)))
    return list(session.scalars(query.order_by(Asset.label, Asset.id).limit(limit).offset(offset)))


def assets_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Asset]:
    if not ids:
        return {}
    return {a.id: a for a in session.scalars(select(Asset).where(Asset.id.in_(ids)))}


# --------------------------------------------------------------------------- jobs
def _job_filters(scopes: Scopes, *, company_id: UUID | None, branch_id: UUID | None, status_id: UUID | None,
                 kinds: tuple[str, ...] | None, assignee_id: UUID | None, asset_id: UUID | None,
                 customer_id: UUID | None, search: str | None, overdue_on: date | None,
                 rework_of_id: UUID | None, waiting_on: str | None = None,
                 job_type_code: str | None = None) -> list[ColumnElement[bool]]:
    conditions = [in_scope(scopes, Job.company_id, Job.branch_id)]
    if waiting_on == "parts":
        conditions.append(exists().where(JobPart.job_id == Job.id, JobPart.source == "special_order",
                                         JobPart.order_status.in_(("to_order", "ordered")),
                                         JobPart.voided_at.is_(None)))
    elif waiting_on == "approval":
        conditions.append(exists().where(Estimate.job_id == Job.id, Estimate.status == "sent"))
    elif waiting_on == "insurer":
        conditions.append(Job.claim_id.is_not(None))        # the caller keeps those whose claim waits for the payer
    if job_type_code:
        conditions.append(Job.job_type_code == job_type_code)
    if company_id is not None:
        conditions.append(Job.company_id == company_id)
    if branch_id is not None:
        conditions.append(Job.branch_id == branch_id)
    if status_id is not None:
        conditions.append(Job.status_id == status_id)
    if kinds:
        conditions.append(Job.status_id.in_(select(JobStatus.id).where(JobStatus.kind.in_(kinds))))
    if assignee_id is not None:
        conditions.append(Job.assignee_id == assignee_id)
    if asset_id is not None:
        conditions.append(Job.asset_id == asset_id)
    if customer_id is not None:
        conditions.append(Job.customer_id == customer_id)
    if rework_of_id is not None:
        conditions.append(Job.rework_of_id == rework_of_id)
    if overdue_on is not None:
        conditions.append(and_(Job.promised_at < overdue_on, Job.status_id.in_(
            select(JobStatus.id).where(JobStatus.kind.in_(("open", "waiting"))))))
    if search:
        p = like_pattern(search)
        conditions.append(or_(Job.number.ilike(p), Job.title.ilike(p), Job.customer_name.ilike(p),
                              Job.customer_phone.ilike(p),
                              Job.asset_id.in_(select(Asset.id).where(or_(Asset.label.ilike(p),
                                                                          cast(Asset.identifiers, Text).ilike(p))))))
    return conditions


def list_jobs(session: Session, scopes: Scopes, *, company_id: UUID | None = None, branch_id: UUID | None = None,
              status_id: UUID | None = None, kinds: tuple[str, ...] | None = None, assignee_id: UUID | None = None,
              asset_id: UUID | None = None, customer_id: UUID | None = None, search: str | None = None,
              overdue_on: date | None = None, rework_of_id: UUID | None = None, limit: int = 50,
              offset: int = 0, waiting_on: str | None = None, job_type_code: str | None = None) -> list[Job]:
    where = _job_filters(scopes, company_id=company_id, branch_id=branch_id, status_id=status_id, kinds=kinds,
                         assignee_id=assignee_id, asset_id=asset_id, customer_id=customer_id, search=search,
                         overdue_on=overdue_on, rework_of_id=rework_of_id, waiting_on=waiting_on,
                         job_type_code=job_type_code)
    return list(session.scalars(select(Job).where(*where).order_by(Job.received_at.desc(), Job.id)
                                .limit(limit).offset(offset)))


def blockers(session: Session, job_ids: set[UUID]) -> dict[UUID, list[str]]:
    """What each job waits on: 'parts' (a part ordered for it has not arrived) and 'approval' (an estimate is out with
    the customer). Waiting for the insurer comes from the claims unit (services/claims_link.py)."""
    if not job_ids:
        return {}
    out: dict[UUID, list[str]] = {}
    for (job_id,) in session.execute(select(JobPart.job_id).where(
            JobPart.job_id.in_(job_ids), JobPart.source == "special_order",
            JobPart.order_status.in_(("to_order", "ordered")), JobPart.voided_at.is_(None)).distinct()):
        out.setdefault(job_id, []).append("parts")
    for (job_id,) in session.execute(select(Estimate.job_id).where(Estimate.job_id.in_(job_ids),
                                                                   Estimate.status == "sent").distinct()):
        out.setdefault(job_id, []).append("approval")
    return out


def jobs_of_asset(session: Session, asset_id: UUID) -> list[Job]:
    return list(session.scalars(select(Job).where(Job.asset_id == asset_id).order_by(Job.received_at.desc())))


def events(session: Session, job_id: UUID) -> list[JobEvent]:
    return list(session.scalars(select(JobEvent).where(JobEvent.job_id == job_id)
                                .order_by(JobEvent.created_at, JobEvent.id)))


def checklist(session: Session, job_id: UUID) -> list[JobChecklistItem]:
    return list(session.scalars(select(JobChecklistItem).where(JobChecklistItem.job_id == job_id)
                                .order_by(JobChecklistItem.position)))


def tasks(session: Session, job_id: UUID) -> list[JobTask]:
    return list(session.scalars(select(JobTask).where(JobTask.job_id == job_id)
                                .order_by(JobTask.position, JobTask.created_at)))


def parts(session: Session, job_id: UUID, *, include_voided: bool = True) -> list[JobPart]:
    query = select(JobPart).where(JobPart.job_id == job_id)
    if not include_voided:
        query = query.where(JobPart.voided_at.is_(None))
    return list(session.scalars(query.order_by(JobPart.created_at, JobPart.id)))


def labour(session: Session, job_id: UUID, *, include_voided: bool = True) -> list[JobLabour]:
    query = select(JobLabour).where(JobLabour.job_id == job_id)
    if not include_voided:
        query = query.where(JobLabour.voided_at.is_(None))
    return list(session.scalars(query.order_by(JobLabour.work_date, JobLabour.created_at, JobLabour.id)))


def estimates(session: Session, job_id: UUID) -> list[Estimate]:
    return list(session.scalars(select(Estimate).where(Estimate.job_id == job_id).order_by(Estimate.version)))


def estimate_lines(session: Session, estimate_id: UUID) -> list[EstimateLine]:
    return list(session.scalars(select(EstimateLine).where(EstimateLine.estimate_id == estimate_id)
                                .order_by(EstimateLine.position, EstimateLine.created_at)))


def estimate_by_link(session: Session, link_hash: str) -> Estimate | None:
    return session.scalar(select(Estimate).where(Estimate.link_hash == link_hash))


def task_counts(session: Session, job_ids: set[UUID]) -> dict[UUID, tuple[int, int]]:
    """(tasks, tasks done) per job."""
    if not job_ids:
        return {}
    rows = session.execute(select(JobTask.job_id, func.count(), func.count(JobTask.done_at))
                           .where(JobTask.job_id.in_(job_ids)).group_by(JobTask.job_id))
    return {job: (int(n), int(done)) for job, n, done in rows}


def statuses_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, JobStatus]:
    if not ids:
        return {}
    return {s.id: s for s in session.scalars(select(JobStatus).where(JobStatus.id.in_(ids)))}


def moves_from(session: Session, status_id: UUID) -> list[UUID]:
    return list(session.scalars(select(JobStatusMove.to_status_id).where(JobStatusMove.from_status_id == status_id)))


# ----------------------------------------------------------- the garage catalogue (work types, tasks, categories)
def work_types(session: Session, company_id: UUID, *, only_active: bool = False) -> list[WorkType]:
    query = select(WorkType).where(WorkType.company_id == company_id)
    if only_active:
        query = query.where(WorkType.is_active)
    return list(session.scalars(query.order_by(WorkType.position, WorkType.name)))


def work_type_by_code(session: Session, company_id: UUID, code: str) -> WorkType | None:
    return session.scalar(select(WorkType).where(WorkType.company_id == company_id, WorkType.code == code))


def labour_tasks(session: Session, company_id: UUID, *, only_active: bool = False,
                 search: str | None = None) -> list[LabourTask]:
    query = select(LabourTask).where(LabourTask.company_id == company_id)
    if only_active:
        query = query.where(LabourTask.is_active)
    if search:
        pattern = like_pattern(search)
        query = query.where(or_(LabourTask.name.ilike(pattern), LabourTask.code.ilike(pattern)))
    return list(session.scalars(query.order_by(LabourTask.name)))


def labour_task_by_code(session: Session, company_id: UUID, code: str) -> LabourTask | None:
    return session.scalar(select(LabourTask).where(LabourTask.company_id == company_id, LabourTask.code == code))


def part_categories(session: Session, company_id: UUID, *, only_active: bool = False) -> list[PartCategory]:
    query = select(PartCategory).where(PartCategory.company_id == company_id)
    if only_active:
        query = query.where(PartCategory.is_active)
    return list(session.scalars(query.order_by(PartCategory.position, PartCategory.name)))


def part_category_by_code(session: Session, company_id: UUID, code: str) -> PartCategory | None:
    return session.scalar(select(PartCategory).where(PartCategory.company_id == company_id,
                                                     PartCategory.code == code))


def job_types(session: Session, company_id: UUID, *, only_active: bool = False) -> list[JobType]:
    query = select(JobType).where(JobType.company_id == company_id)
    if only_active:
        query = query.where(JobType.is_active)
    return list(session.scalars(query.order_by(JobType.position, JobType.name)))


def job_type_by_code(session: Session, company_id: UUID, code: str) -> JobType | None:
    return session.scalar(select(JobType).where(JobType.company_id == company_id, JobType.code == code))


def charges(session: Session, job_id: UUID, *, include_voided: bool = True) -> list[JobCharge]:
    query = select(JobCharge).where(JobCharge.job_id == job_id)
    if not include_voided:
        query = query.where(JobCharge.voided_at.is_(None))
    return list(session.scalars(query.order_by(JobCharge.created_at, JobCharge.id)))


def loans_of_job(session: Session, job_id: UUID) -> list[Loan]:
    return list(session.scalars(select(Loan).where(Loan.job_id == job_id).order_by(Loan.out_at)))


def bay_bookings_of_job(session: Session, job_id: UUID) -> list[BayBooking]:
    return list(session.scalars(select(BayBooking).where(BayBooking.job_id == job_id,
                                                         BayBooking.cancelled_at.is_(None))
                                .order_by(BayBooking.starts_at)))
