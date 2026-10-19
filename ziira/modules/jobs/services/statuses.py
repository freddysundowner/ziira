"""Use cases: the stages a job moves through and the moves allowed between them (data per company).

A company starts with the default stages the first time anything needs them. A business edits them in settings; an
industry pack adds its own with `seed_statuses` (only adds what is missing, never changes or removes anything).
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, or_, select

from ziira.modules.jobs.domain import workflow
from ziira.modules.jobs.domain.workflow import Definition, StatusDef
from ziira.modules.jobs.permissions import JOBS_SETTINGS
from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Job, JobEvent, JobStatus, JobStatusMove
from ziira.modules.jobs.services import access
from ziira.sdk import (
    Conflict,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
)


@dataclass(frozen=True)
class Seeded:
    statuses_added: int
    moves_added: int


def seed_statuses(session: Session, company_id: UUID, definition: Definition) -> Seeded:
    """Add the stages and moves of `definition` that the company does not have yet. A stage whose code exists is left as
    it is; a stage asking for a role another stage already holds is added without the role. Idempotent. No permission
    check: the platform and industry packs call it on behalf of the business."""
    workflow.check_statuses(definition.statuses)
    check_company(session, company_id)
    ctx = current_context()
    existing = {s.code: s for s in repo.statuses(session, company_id)}
    roles_taken = {s.role for s in existing.values() if s.role}
    position = max((s.position for s in existing.values()), default=0)
    added = 0
    for item in definition.statuses:
        if item.code in existing:
            continue
        role = item.role if item.role and item.role not in roles_taken else None
        position += 10
        row = JobStatus(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=item.code,
                        name=item.name.strip(), kind=item.kind, role=role, position=position)
        repo.add(session, row)
        existing[item.code] = row
        if role:
            roles_taken.add(role)
        added += 1
    have = {(m.from_status_id, m.to_status_id) for m in repo.moves(session, company_id)}
    moved = 0
    for a, b in definition.moves:
        if a in existing and b in existing and (existing[a].id, existing[b].id) not in have:
            repo.add(session, JobStatusMove(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                            from_status_id=existing[a].id, to_status_id=existing[b].id))
            have.add((existing[a].id, existing[b].id))
            moved += 1
    if added or moved:
        audit_record(session, "seed", "jobs.job_status", None, {"company_id": str(company_id), "statuses": added,
                                                               "moves": moved})
    return Seeded(added, moved)


def ensure_seeded(session: Session, company_id: UUID) -> None:
    """Give a company with no stages the default ones."""
    if not repo.statuses(session, company_id):
        seed_statuses(session, company_id, workflow.DEFAULT)


def list_statuses(session: Session, company_id: UUID, *, only_active: bool = False) -> list[JobStatus]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    ensure_seeded(session, company_id)
    return repo.statuses(session, company_id, only_active=only_active)


def list_moves(session: Session, company_id: UUID) -> list[JobStatusMove]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    ensure_seeded(session, company_id)
    return repo.moves(session, company_id)


def _status(session: Session, status_id: UUID) -> JobStatus:
    found = repo.get(session, JobStatus, status_id, lock=True)
    if found is None or not access.can_see_company(found.company_id):
        raise NotFound("Stage not found")
    return found


def _jobs_in(session: Session, status_id: UUID) -> int:
    return int(session.scalar(select(func.count()).select_from(Job).where(Job.status_id == status_id)) or 0)


def _check_role(session: Session, company_id: UUID, role: str | None, except_id: UUID | None) -> None:
    if role is None:
        return
    if role not in workflow.ROLES:
        raise ValidationFailed(f"A stage role is one of: {', '.join(workflow.ROLES)}")
    holder = repo.status_by_role(session, company_id, role)
    if holder is not None and holder.id != except_id:
        raise Conflict(f"{holder.name} already has the role '{role}'. Take it off that stage first")


def create_status(session: Session, *, company_id: UUID, code: str, name: str, kind: str, role: str | None = None,
                  position: int | None = None) -> JobStatus:
    """Add a stage. Needs 'jobs.settings'."""
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=company_id)
    check_company(session, company_id)
    ensure_seeded(session, company_id)
    code = workflow.check_code(code)
    if kind not in workflow.KINDS:
        raise ValidationFailed(f"Stage kind must be one of: {', '.join(workflow.KINDS)}")
    if not name.strip():
        raise ValidationFailed("A stage needs a name")
    if repo.status_by_code(session, company_id, code) is not None:
        raise Conflict(f"There is already a stage with the code {code}")
    existing = repo.statuses(session, company_id)
    if len(existing) >= workflow.MAX_STATUSES:
        raise ValidationFailed(f"A workflow has at most {workflow.MAX_STATUSES} stages")
    _check_role(session, company_id, role, None)
    row = JobStatus(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=code,
                    name=name.strip()[:60], kind=kind, role=role,
                    position=position if position is not None else max((s.position for s in existing), default=0) + 10)
    repo.add(session, row)
    audit_record(session, "create", "jobs.job_status", row.id, {"code": code})
    return row


def update_status(session: Session, status_id: UUID, **changes: object) -> JobStatus:
    """Rename a stage, change its kind, role or place, or switch it off (not while jobs sit in it). Needs
    'jobs.settings'."""
    row = _status(session, status_id)
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=row.company_id)
    if "name" in changes:
        name = str(changes["name"] or "").strip()
        if not name:
            raise ValidationFailed("A stage needs a name")
        row.name = name[:60]
    if "kind" in changes:
        kind = str(changes["kind"])
        if kind not in workflow.KINDS:
            raise ValidationFailed(f"Stage kind must be one of: {', '.join(workflow.KINDS)}")
        row.kind = kind
    if "role" in changes:
        role = changes["role"]
        _check_role(session, row.company_id, role if isinstance(role, str) else None, row.id)
        row.role = role if isinstance(role, str) else None
    if "position" in changes and isinstance(changes["position"], int):
        row.position = changes["position"]
    if changes.get("is_active") is False and row.is_active:
        if row.role == "initial":
            raise ValidationFailed("The first stage new jobs start in cannot be switched off")
        waiting = _jobs_in(session, row.id)
        if waiting:
            raise ValidationFailed(f"{waiting} job(s) are in {row.name}. Move them first")
        row.is_active = False
    elif changes.get("is_active") is True:
        row.is_active = True
    row.updated_by = ctx.user_id
    session.flush()
    audit_record(session, "update", "jobs.job_status", row.id, {k: str(v) for k, v in changes.items()})
    return row


def delete_status(session: Session, status_id: UUID) -> None:
    """Remove a stage nothing has ever used. Needs 'jobs.settings'."""
    row = _status(session, status_id)
    current_context().require(JOBS_SETTINGS, company_id=row.company_id)
    if _jobs_in(session, row.id) or row.role == "initial":
        raise ValidationFailed("This stage is in use; switch it off instead")
    used = session.scalar(select(func.count()).select_from(JobEvent).where(
        or_(JobEvent.from_status_id == row.id, JobEvent.to_status_id == row.id)))
    if used:
        raise ValidationFailed("This stage appears in a job's history; switch it off instead")
    session.execute(delete(JobStatusMove).where(or_(JobStatusMove.from_status_id == row.id,
                                                    JobStatusMove.to_status_id == row.id)))
    session.delete(row)
    session.flush()
    audit_record(session, "delete", "jobs.job_status", status_id, {"code": row.code})


def set_moves_from(session: Session, status_id: UUID, to_status_ids: list[UUID]) -> list[JobStatusMove]:
    """Replace the moves that leave a stage with exactly these. Needs 'jobs.settings'."""
    row = _status(session, status_id)
    ctx = current_context()
    ctx.require(JOBS_SETTINGS, company_id=row.company_id)
    targets = set(to_status_ids)
    valid = {s.id for s in repo.statuses(session, row.company_id)}
    if row.id in targets or not targets <= valid:
        raise ValidationFailed("A move goes to a different stage of this company")
    current = {m.to_status_id: m for m in repo.moves(session, row.company_id) if m.from_status_id == row.id}
    for to_id, move in current.items():
        if to_id not in targets:
            session.delete(move)
    for to_id in targets - set(current):
        repo.add(session, JobStatusMove(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=row.company_id,
                                        from_status_id=row.id, to_status_id=to_id))
    session.flush()
    audit_record(session, "set_moves", "jobs.job_status", row.id, {"to": sorted(str(t) for t in targets)})
    return [m for m in repo.moves(session, row.company_id) if m.from_status_id == row.id]


def definition_of(session: Session, company_id: UUID) -> Definition:
    """The company's stages and moves as a Definition (for exports and tests)."""
    rows = repo.statuses(session, company_id)
    by_id = {r.id: r.code for r in rows}
    return Definition([StatusDef(r.code, r.name, r.kind, r.role) for r in rows],
                      [(by_id[m.from_status_id], by_id[m.to_status_id]) for m in repo.moves(session, company_id)
                       if m.from_status_id in by_id and m.to_status_id in by_id])
