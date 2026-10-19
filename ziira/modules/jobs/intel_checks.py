"""Intelligence checks over repair and installation work.

Each check reads Jobs' own tables, reports questions with their evidence and writes nothing. Limits are parameters a
business can change.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import Session

CENT = Decimal("0.01")
MAX_PER_RUN = 100


def money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount.quantize(CENT):,.2f}"


def _currency(session: Session, company_id: UUID) -> str:
    found = session.execute(text("select base_currency from kernel.company where id = :c"), {"c": company_id}).scalar()
    return str(found or "")


class JobStuck(IntelCheck):
    """A job that has been in the same stage for too long."""

    code = "jobs.stuck_in_stage"
    title = "Jobs stuck in a stage"
    area = "customers"
    description = "A job has been in the same stage for many days without moving."
    default_severity = "medium"
    value_kind = "days"
    params: dict[str, Any] = {"open_days": 7, "waiting_days": 14, "serious_days": 30}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select j.id, j.branch_id, j.number, j.title, s.name as stage, s.kind, "
            "((cast(:today as date)) - (j.status_changed_at at time zone :tz)::date) as days "
            "from jobs.job j join jobs.job_status s on s.id = j.status_id "
            "where j.company_id = :c and s.kind in ('open', 'waiting') "
            "and (j.status_changed_at at time zone :tz)::date <= :latest "
            "order by j.status_changed_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "latest": ctx.today - timedelta(days=int(min(ctx.number("open_days"), ctx.number("waiting_days"))))}).all()
        out = []
        for r in rows:
            limit = ctx.number("open_days") if r.kind == "open" else ctx.number("waiting_days")
            if r.days < limit:
                continue
            serious = r.days >= ctx.number("serious_days")
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="high" if serious else "medium",
                summary=f"Job {r.number} ({r.title}) has been {r.stage.lower()} for {r.days} days.",
                recommended_action="Look at the job: move it on, or tell the customer what is holding it up.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="jobs.job", entity_id=r.id,
                value=Decimal(r.days), period_end=ctx.today,
                records=(Record("jobs.job", r.id, f"Job {r.number}"),),
                figures={"days_open": str(r.days), "stage": r.stage}))
        return out


class EstimateNotAnswered(IntelCheck):
    """An estimate was sent and the customer has not answered."""

    code = "jobs.estimate_not_approved"
    title = "Estimates nobody has answered"
    area = "customers"
    description = "A customer has had an estimate for days and has not approved or declined it."
    default_severity = "low"
    value_kind = "days"
    params: dict[str, Any] = {"waiting_days": 5}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            "select e.id, e.total, j.id as job_id, j.branch_id, j.number, "
            "(cast(:today as date) - (e.sent_at at time zone :tz)::date) as days "
            "from jobs.estimate e join jobs.job j on j.id = e.job_id join jobs.job_status s on s.id = j.status_id "
            "where e.company_id = :c and e.status = 'sent' and s.kind <> 'closed' "
            "and (e.sent_at at time zone :tz)::date <= :limit order by e.sent_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="low",
            summary=(f"The estimate for job {r.number} ({money(r.total, currency)}) has waited {r.days} days "
                     "for the customer's answer."),
            recommended_action="Call the customer for an answer, or close the job if they have gone quiet.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="jobs.job", entity_id=r.job_id,
            value=Decimal(r.days), amount=r.total, period_end=ctx.today,
            records=(Record("jobs.job", r.job_id, f"Job {r.number}"),),
            figures={"days_waiting": str(r.days), "total": str(r.total), "currency": currency}) for r in rows]


class PartsNotInvoiced(IntelCheck):
    """Parts were used (or labour done) on a job that was handed back or closed, and nobody invoiced it."""

    code = "jobs.parts_not_invoiced"
    title = "Work done but never invoiced"
    area = "customers"
    description = "A job was collected or closed with parts and labour on it, and no invoice was made."
    default_severity = "high"
    value_kind = "money"
    params: dict[str, Any] = {"grace_days": 2, "look_back_days": 90}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            "select j.id, j.branch_id, j.number, "
            "coalesce((select sum(round(p.quantity * p.unit_price, 2)) from jobs.job_part p "
            "         where p.job_id = j.id and p.voided_at is null), 0) "
            "+ coalesce((select sum(round(l.hours * l.rate, 2)) from jobs.job_labour l "
            "           where l.job_id = j.id and l.voided_at is null), 0) as worth "
            "from jobs.job j join jobs.job_status s on s.id = j.status_id "
            "where j.company_id = :c and j.invoiced_at is null and s.role is distinct from 'cancelled' "
            "and ((j.collected_at at time zone :tz)::date between :first and :last "
            "     or (s.kind = 'closed' and (j.closed_at at time zone :tz)::date between :first and :last)) "
            "order by j.collected_at nulls last limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "cap": MAX_PER_RUN,
             "first": ctx.today - timedelta(days=int(ctx.number("look_back_days"))),
             "last": ctx.today - timedelta(days=int(ctx.number("grace_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="high",
            summary=f"Job {r.number} is done and worth {money(r.worth, currency)} but has no invoice.",
            recommended_action="Open the job and make the invoice, or write down why it is free.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="jobs.job", entity_id=r.id,
            amount=r.worth, value=r.worth, period_end=ctx.today,
            records=(Record("jobs.job", r.id, f"Job {r.number}"),),
            figures={"worth": str(r.worth), "currency": currency}) for r in rows if r.worth > 0]


class RepeatReturns(IntelCheck):
    """Customers keep coming back inside the warranty for work one person did."""

    code = "jobs.repeat_returns"
    title = "Repeat returns inside the warranty"
    area = "customers"
    description = "Several return visits inside the warranty trace back to the same person's work."
    default_severity = "medium"
    value_kind = "count"
    params: dict[str, Any] = {"min_returns": 3, "look_back_days": 90}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select o.assignee_id, u.full_name as person, count(*) as n, "
            "(array_agg(r.id order by r.received_at desc))[1:5] as ids, "
            "(array_agg(r.number order by r.received_at desc))[1:5] as numbers, o.branch_id "
            "from jobs.job r join jobs.job o on o.id = r.rework_of_id "
            "left join kernel.app_user u on u.id = o.assignee_id "
            "where r.company_id = :c and r.is_rework and r.rework_in_warranty "
            "and (r.received_at at time zone :tz)::date >= :since and o.assignee_id is not null "
            "group by o.assignee_id, u.full_name, o.branch_id having count(*) >= :least order by n desc limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "cap": MAX_PER_RUN, "least": int(ctx.number("min_returns")),
             "since": ctx.today - timedelta(days=int(ctx.number("look_back_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.assignee_id, r.branch_id), severity="medium",
            summary=(f"{r.person or 'A technician'} had {r.n} customers come back inside the warranty in the last "
                     f"{int(ctx.number('look_back_days'))} days."),
            recommended_action="Look at these return visits together: is it the parts, the method or the checks?",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="kernel.app_user", entity_id=r.assignee_id,
            value=Decimal(r.n), period_start=ctx.today - timedelta(days=int(ctx.number("look_back_days"))),
            period_end=ctx.today,
            records=tuple(Record("jobs.job", i, f"Job {n}") for i, n in zip(r.ids, r.numbers, strict=False)),
            figures={"returns": str(r.n), "person": r.person or ""}) for r in rows]


class ReadyNotCollected(IntelCheck):
    """An item is ready and the customer has not come for it."""

    code = "jobs.ready_not_collected"
    title = "Items waiting to be collected"
    area = "customers"
    description = "A finished job has been waiting for the customer to collect it for many days."
    default_severity = "low"
    value_kind = "days"
    params: dict[str, Any] = {"waiting_days": 7, "serious_days": 30}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select j.id, j.branch_id, j.number, j.title, "
            "(cast(:today as date) - (j.ready_at at time zone :tz)::date) as days "
            "from jobs.job j join jobs.job_status s on s.id = j.status_id "
            "where j.company_id = :c and s.role = 'ready' and j.ready_at is not null "
            "and (j.ready_at at time zone :tz)::date <= :limit order by j.ready_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id),
            severity="medium" if r.days >= ctx.number("serious_days") else "low",
            summary=f"Job {r.number} ({r.title}) has been ready for {r.days} days and is not collected.",
            recommended_action="Call the customer to collect it: it takes up space and they may have forgotten.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="jobs.job", entity_id=r.id,
            value=Decimal(r.days), period_end=ctx.today, records=(Record("jobs.job", r.id, f"Job {r.number}"),),
            figures={"days_waiting": str(r.days)}) for r in rows]


class PartOverdue(IntelCheck):
    """A part ordered for a job has not arrived by its expected date."""

    code = "jobs.part_overdue"
    title = "Parts ordered for a job are late"
    area = "customers"
    description = "A part ordered for a job is past the date the supplier promised."
    default_severity = "medium"
    value_kind = "days"
    params: dict[str, Any] = {"late_days": 1}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select p.id, j.id as job_id, j.branch_id, j.number, p.description, p.supplier_name, "
            "(cast(:today as date) - p.expected_on) as days "
            "from jobs.job_part p join jobs.job j on j.id = p.job_id "
            "where j.company_id = :c and p.source = 'special_order' and p.order_status in ('to_order', 'ordered') "
            "and p.voided_at is null and p.expected_on is not null and p.expected_on <= :limit "
            "order by p.expected_on limit :cap"),
            {"c": ctx.company_id, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("late_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="medium",
            summary=f"{r.description} for job {r.number} is {r.days} days late"
                    + (f" (ordered from {r.supplier_name})." if r.supplier_name else "."),
            recommended_action="Call the supplier, then tell the customer the new date.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="jobs.job", entity_id=r.job_id,
            value=Decimal(r.days), period_end=ctx.today, records=(Record("jobs.job", r.job_id, f"Job {r.number}"),),
            figures={"days_late": str(r.days)}) for r in rows]


class CourtesyCarOverdue(IntelCheck):
    """A courtesy car lent with a return date has not come back."""

    code = "jobs.courtesy_car_overdue"
    title = "Courtesy cars not returned"
    area = "customers"
    description = "A courtesy car is past the date it was due back."
    default_severity = "medium"
    value_kind = "days"
    params: dict[str, Any] = {"late_days": 1}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select l.id, j.id as job_id, j.branch_id, j.number, a.label, (cast(:today as date) - l.due_at) as days "
            "from jobs.loan l join jobs.job j on j.id = l.job_id join jobs.asset a on a.id = l.asset_id "
            "where j.company_id = :c and l.in_at is null and l.due_at is not null and l.due_at <= :limit "
            "order by l.due_at limit :cap"),
            {"c": ctx.company_id, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("late_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="medium",
            summary=f"{r.label}, lent for job {r.number}, is {r.days} days overdue.",
            recommended_action="Call the customer and agree when the car comes back.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="jobs.job", entity_id=r.job_id,
            value=Decimal(r.days), period_end=ctx.today, records=(Record("jobs.job", r.job_id, f"Job {r.number}"),),
            figures={"days_overdue": str(r.days), "car": r.label}) for r in rows]


CHECKS = (JobStuck, EstimateNotAnswered, PartsNotInvoiced, RepeatReturns, ReadyNotCollected, PartOverdue,
          CourtesyCarOverdue)
