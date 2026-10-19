"""Technician productivity: hours booked (what they actually worked) against hours billed (what the customer pays for),
per person over a period. People who manage invoicing or settings see everyone; anyone else sees only their own row."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.permissions import JOBS_INVOICE, JOBS_SETTINGS
from ziira.modules.jobs.services import access
from ziira.modules.jobs.services.common import names_of
from ziira.sdk import NotFound, Session, ValidationFailed, current_context


@dataclass(frozen=True)
class TechnicianRow:
    user_id: UUID | None
    name: str | None
    lines: int
    booked_hours: Decimal
    billed_hours: Decimal
    lines_without_booked: int
    billed_value: Decimal
    jobs_open: int


def technicians(session: Session, *, company_id: UUID, date_from: date, date_to: date,
                branch_id: UUID | None = None) -> list[TechnicianRow]:
    """One row per person who has labour lines worked in the period (by the line's work date)."""
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    if date_to < date_from or (date_to - date_from).days > 400:
        raise ValidationFailed("Pick a period of at most about a year")
    ctx = current_context()
    sees_all = ctx.can(JOBS_INVOICE, company_id=company_id, branch_id=branch_id) \
        or ctx.can(JOBS_SETTINGS, company_id=company_id)
    rows = session.execute(text(
        "select l.assignee_id, count(*) as lines, coalesce(sum(coalesce(l.booked_hours, 0)), 0) as booked, "
        "coalesce(sum(l.hours), 0) as billed, count(*) filter (where l.booked_hours is null) as no_booked, "
        "coalesce(sum(coalesce(l.flat_price, l.hours * l.rate)), 0) as value, j.branch_id "
        "from jobs.job_labour l join jobs.job j on j.id = l.job_id "
        "where j.company_id = :c and l.voided_at is null and l.work_date between :a and :b "
        "and (cast(:br as uuid) is null or j.branch_id = :br) "
        "group by l.assignee_id, j.branch_id"),
        {"c": str(company_id), "a": date_from, "b": date_to, "br": str(branch_id) if branch_id else None}).all()
    merged: dict[UUID | None, list[Decimal | int]] = {}
    for r in rows:
        if not access.can_view(company_id, r.branch_id):
            continue
        if not sees_all and r.assignee_id != ctx.user_id:
            continue
        cur = merged.setdefault(r.assignee_id, [0, Decimal(0), Decimal(0), 0, Decimal(0)])
        cur[0] += r.lines                    
        cur[1] += Decimal(r.booked)          
        cur[2] += Decimal(r.billed)          
        cur[3] += r.no_booked                
        cur[4] += Decimal(r.value)           
    open_jobs = {r.assignee_id: r.n for r in session.execute(text(
        "select j.assignee_id, count(*) as n from jobs.job j join jobs.job_status s on s.id = j.status_id "
        "where j.company_id = :c and s.kind in ('open', 'waiting') group by j.assignee_id"), {"c": str(company_id)})}
    names = names_of(session, set(merged))
    out = [TechnicianRow(uid, names.get(uid) if uid else None, int(v[0]), Decimal(v[1]), Decimal(v[2]), int(v[3]),
                         Decimal(v[4]), int(open_jobs.get(uid, 0)))           
           for uid, v in merged.items()]
    out.sort(key=lambda t: (-t.billed_hours, t.name or ""))
    return out
