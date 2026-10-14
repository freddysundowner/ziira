"""Checks over what the platform itself records: approvals, who was given access, activity at odd hours, and the
exceptions inbox. They need no other unit, so they run for every business that has Intelligence.

Units supply checks over their own data (see public.py); these four are Intelligence's own because the data they read is
the kernel's: the approval matrix, the role grants, the audit log and the exceptions inbox.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import Session, provides


def _currency(session: Session, company_id: Any) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar() or "")


@provides(INTEL_CHECK)
class ApprovalByRequester(IntelCheck):
    """Approvals the matrix allows the requester to decide themselves, where they did."""

    code = "controls.approval_by_requester"
    title = "Approved by the person who asked"
    area = "controls"
    description = "Something was approved by the same person who requested it, so nobody else looked at it."
    default_severity = "high"
    params = {"days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("days")))
        rows = session.execute(text(
            "select a.id, a.doc_type, a.doc_id, a.decided_at, u.full_name, r.min_amount from kernel.approval_request a "
            "join kernel.approval_rule r on r.id = a.rule_id join kernel.app_user u on u.id = a.decided_by "
            "where r.company_id = :c and a.status = 'approved' and a.requested_by is not null "
            "and a.requested_by = a.decided_by and a.decided_at >= :since order by a.decided_at"),
            {"c": str(ctx.company_id), "since": since}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="high", company_id=ctx.company_id,
            entity_type="kernel.approval_request", entity_id=r.id, period_start=r.decided_at.date(),
            summary=f"{r.full_name} approved their own {r.doc_type.replace('_', ' ')} request on "
                    f"{r.decided_at.date().isoformat()}.",
            recommended_action="Ask a second person to review it, and make the approval rule forbid the requester.",
            amount=Decimal(r.min_amount) if r.min_amount else None,
            records=(Record("kernel.approval_request", r.id, f"{r.doc_type} approval"),),
            figures={"approved_by": r.full_name, "document_type": r.doc_type}) for r in rows]


@provides(INTEL_CHECK)
class NewFullAccess(IntelCheck):
    """Someone was given a role that reaches the whole business or a whole company."""

    code = "controls.new_wide_access"
    title = "Someone was given wide access"
    area = "controls"
    description = "A person was given a role over the whole business or a whole company in the last few days."
    default_severity = "medium"
    params = {"days": 14}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("days")))
        rows = session.execute(text(
            "select ur.id, ur.created_at, ur.scope, ur.company_id, r.name as role_name, u.full_name, "
            "g.full_name as granter from kernel.user_role ur join kernel.role r on r.id = ur.role_id "
            "join kernel.app_user u on u.id = ur.user_id "
            "left join kernel.app_user g on g.id = ur.created_by where ur.scope in ('tenant', 'company') "
            "and (ur.company_id is null or ur.company_id = :c) and ur.created_at >= :since order by ur.created_at"),
            {"c": str(ctx.company_id), "since": since}).all()
        out = []
        for r in rows:
            by = f" by {r.granter}" if r.granter else ""
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium", company_id=ctx.company_id,
                entity_type="kernel.user_role", entity_id=r.id, period_start=r.created_at.date(),
                summary=f"{r.full_name} was given the role {r.role_name} over "
                        f"{'the whole business' if r.scope == 'tenant' else 'the whole company'} on "
                        f"{r.created_at.date().isoformat()}{by}.",
                recommended_action="Confirm this person should see and do everything this role allows.",
                records=(Record("kernel.user_role", r.id, f"{r.role_name} for {r.full_name}"),),
                figures={"role": r.role_name, "scope": r.scope, "granted_by": r.granter or ""}))
        return out


@provides(INTEL_CHECK)
class AfterHoursActivity(IntelCheck):
    """A person doing a lot in the system outside the business's working hours."""

    code = "controls.after_hours_activity"
    title = "Activity at unusual hours"
    area = "controls"
    description = "A person made many changes outside working hours (read in the company's time zone)."
    default_severity = "low"
    params = {"days": 7, "start_hour": 6, "end_hour": 22, "min_actions": 10}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        days, start, end = int(ctx.number("days")), int(ctx.number("start_hour")), int(ctx.number("end_hour"))
        since = ctx.today - timedelta(days=days)
        rows = session.execute(text(
            "select a.user_id, u.full_name, (a.occurred_at at time zone :tz)::date as local_day, count(*) as n "
            "from kernel.audit_log a join kernel.app_user u on u.id = a.user_id where a.user_id is not null "
            "and a.channel <> 'system' and a.action not like 'auth.%' and a.action <> 'login' "
            "and (a.occurred_at at time zone :tz)::date >= :since "
            "and (extract(hour from a.occurred_at at time zone :tz) < :start "
            "     or extract(hour from a.occurred_at at time zone :tz) >= :end) "
            "group by a.user_id, u.full_name, local_day having count(*) >= :min order by local_day, u.full_name"),
            {"tz": ctx.timezone, "since": since, "start": start, "end": end,
             "min": int(ctx.number("min_actions"))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.user_id, r.local_day), severity="low", company_id=ctx.company_id,
            entity_type="kernel.app_user", entity_id=r.user_id, period_start=r.local_day, period_end=r.local_day,
            value=Decimal(r.n), summary=f"{r.full_name} made {r.n} changes on {r.local_day.isoformat()} outside "
                                         f"{start:02d}:00 to {end:02d}:00.",
            recommended_action="Ask them what they were working on.",
            records=(Record("kernel.app_user", r.user_id, r.full_name),), figures={"changes": str(r.n)}) for r in rows]


@provides(INTEL_CHECK)
class ExceptionsBacklog(IntelCheck):
    """Exceptions raised by the system that nobody has looked at."""

    code = "controls.exceptions_backlog"
    title = "Exceptions nobody has reviewed"
    area = "controls"
    description = "Items in the exceptions inbox have waited too long without anyone reviewing them."
    default_severity = "medium"
    params = {"days": 7, "min_items": 3}

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        row = session.execute(text(
            "select count(*) as n, coalesce(sum(amount), 0) as amount, min(created_at) as oldest, "
            "count(*) filter (where severity in ('high', 'critical')) as serious from kernel.exception_item "
            "where status = 'open' and (company_id = :c or company_id is null) "
            "and created_at < now() - make_interval(days => :d)"),
            {"c": str(ctx.company_id), "d": int(ctx.number("days"))}).one()
        if row.n < int(ctx.number("min_items")):
            return []
        currency = _currency(session, ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, ctx.company_id), severity="high" if row.serious else "medium",
            company_id=ctx.company_id, entity_type="kernel.exception_item", value=Decimal(row.n),
            amount=Decimal(row.amount) if row.amount else None,
            summary=f"{row.n} exceptions have waited more than {int(ctx.number('days'))} days for a review"
                    + (f", {row.serious} of them serious" if row.serious else "") + (
                        f" ({currency} {Decimal(row.amount):,.2f} involved)" if row.amount else "") + ".",
            recommended_action="Open the exceptions inbox and work through the oldest first.",
            figures={"items": str(row.n), "serious": str(row.serious), "oldest": row.oldest.date().isoformat()})]
