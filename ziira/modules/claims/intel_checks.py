"""Intelligence checks over claims: where a payer, the workshop or the office is holding money up.

Each check reads Claims' own tables (money owed comes through Point of Sale's public interface), reports questions with
their evidence and writes nothing. Limits are parameters a business can change.
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

# Lines of the latest sent version of each chain of estimates ("in play").
LIVE = ("select e.* from claims.estimate e where e.company_id = :c and e.status in ('submitted', 'answered') "
        "and not exists (select 1 from claims.estimate n where n.lineage_id = e.lineage_id and n.seq > e.seq "
        "and n.status in ('submitted', 'answered'))")


def money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount.quantize(CENT):,.2f}"


def _currency(session: Session, company_id: UUID) -> str:
    found = session.execute(text("select base_currency from kernel.company where id = :c"), {"c": company_id}).scalar()
    return str(found or "")


def _enabled(session: Session, unit: str) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = :u and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()"), {"u": unit}).first() is not None


class EstimateWaiting(IntelCheck):
    """A payer has had an estimate for days and has not answered every line."""

    code = "claims.estimate_waiting"
    title = "Estimates a payer has not answered"
    area = "customers"
    description = "An insurer or other payer has had an estimate for days without answering."
    default_severity = "medium"
    value_kind = "days"
    params: dict[str, Any] = {"waiting_days": 5, "serious_days": 14}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            f"with live as ({LIVE}) "
            "select l.id, l.total, c.id as claim_id, c.branch_id, c.number, p.name as payer, "
            "(cast(:today as date) - (l.submitted_at at time zone :tz)::date) as days "
            "from live l join claims.claim c on c.id = l.claim_id join claims.payer p on p.id = c.payer_id "
            "where l.status = 'submitted' and c.status <> 'closed' "
            "and (l.submitted_at at time zone :tz)::date <= :limit order by l.submitted_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id),
            severity="high" if r.days >= ctx.number("serious_days") else "medium",
            summary=(f"{r.payer} has had the estimate for claim {r.number} ({money(r.total, currency)}) for "
                     f"{r.days} days without answering."),
            recommended_action="Call the payer for an answer, or check that the estimate reached them.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.claim_id,
            value=Decimal(r.days), amount=r.total, period_end=ctx.today,
            records=(Record("claims.claim", r.claim_id, f"Claim {r.number}"),),
            figures={"days_waiting": str(r.days), "total": str(r.total), "currency": currency, "payer": r.payer})
            for r in rows]


class ApprovedNotStarted(IntelCheck):
    """The payer approved the work and the job or appointment has not started."""

    code = "claims.approved_not_started"
    title = "Approved work that has not started"
    area = "customers"
    description = "A payer approved the work days ago and the job has not been started."
    default_severity = "medium"
    value_kind = "days"
    params: dict[str, Any] = {"waiting_days": 2}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select c.id, c.branch_id, c.number, c.source_type, c.source_id, p.name as payer, "
            "(cast(:today as date) - (max(ev.created_at) at time zone :tz)::date) as days "
            "from claims.claim c join claims.payer p on p.id = c.payer_id "
            "join claims.claim_event ev on ev.claim_id = c.id and ev.kind in ('response', 'authority') "
            "where c.company_id = :c and c.status = 'authorised' and c.source_id is not null "
            "group by c.id, c.branch_id, c.number, c.source_type, c.source_id, p.name "
            "having (max(ev.created_at) at time zone :tz)::date <= :limit order by max(ev.created_at) limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        jobs_on, bookings_on = _enabled(session, "jobs"), _enabled(session, "bookings")
        out = []
        for r in rows:
            if not self._not_started(session, r.source_type, r.source_id, jobs_on, bookings_on):
                continue
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium",
                summary=f"{r.payer} approved claim {r.number} {r.days} days ago and the work has not started.",
                recommended_action="Book the work in, or tell the payer why it is waiting.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.id,
                value=Decimal(r.days), period_end=ctx.today, records=(Record("claims.claim", r.id,
                                                                              f"Claim {r.number}"),),
                figures={"days_waiting": str(r.days), "payer": r.payer}))
        return out

    @staticmethod
    def _not_started(session: Session, kind: str, source_id: UUID, jobs_on: bool, bookings_on: bool) -> bool:
        if kind == "job" and jobs_on:
            from ziira.modules.jobs.public import find_job

            job = find_job(session, source_id)
            return job is not None and job.status_role in ("initial", "quoted", "approved")
        if kind == "appointment" and bookings_on:
            from ziira.modules.bookings.public import find_appointment

            appt = find_appointment(session, source_id)
            return appt is not None and appt.status in ("requested", "confirmed")
        return False


class CounterUnanswered(IntelCheck):
    """A payer offered less for a line and the business has not answered."""

    code = "claims.counter_unanswered"
    title = "Counter-offers nobody answered"
    area = "customers"
    description = "A payer offered a lower amount and the business has not accepted or argued it."
    default_severity = "medium"
    value_kind = "days"
    params: dict[str, Any] = {"waiting_days": 3}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            f"with live as ({LIVE}) "
            "select c.id as claim_id, c.branch_id, c.number, p.name as payer, count(*) as n, "
            "sum(x.asked_total - x.payer_amount) as gap, "
            "(cast(:today as date) - (min(x.responded_at) at time zone :tz)::date) as days "
            "from live l join claims.estimate_line x on x.estimate_id = l.id "
            "join claims.claim c on c.id = l.claim_id join claims.payer p on p.id = c.payer_id "
            "where x.payer_state = 'countered' and x.our_decision is null and c.status <> 'closed' "
            "and (x.responded_at at time zone :tz)::date <= :limit "
            "group by c.id, c.branch_id, c.number, p.name order by min(x.responded_at) limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.claim_id), severity="medium",
            summary=(f"{r.payer} offered {money(r.gap, currency)} less on {r.n} line(s) of claim {r.number} "
                     f"{r.days} days ago and nobody has answered."),
            recommended_action="Accept the offer, or send a new version arguing the lines.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.claim_id,
            value=Decimal(r.days), amount=r.gap, period_end=ctx.today,
            records=(Record("claims.claim", r.claim_id, f"Claim {r.number}"),),
            figures={"days_waiting": str(r.days), "lines": str(r.n), "gap": str(r.gap), "currency": currency})
            for r in rows]


class SupplementaryNotSent(IntelCheck):
    """Extra work was written up and never sent to the payer."""

    code = "claims.supplementary_not_sent"
    title = "Extra work not sent to the payer"
    area = "customers"
    description = "A supplementary estimate has been sitting as a draft for days."
    default_severity = "high"
    value_kind = "days"
    params: dict[str, Any] = {"waiting_days": 2}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            "select e.id, e.total, c.id as claim_id, c.branch_id, c.number, "
            "(cast(:today as date) - (e.created_at at time zone :tz)::date) as days "
            "from claims.estimate e join claims.claim c on c.id = e.claim_id "
            "where e.company_id = :c and e.status = 'draft' and e.lineage_kind = 'supplementary' "
            "and c.status <> 'closed' and (e.created_at at time zone :tz)::date <= :limit "
            "order by e.created_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="high",
            summary=(f"Extra work of {money(r.total, currency)} on claim {r.number} was written up {r.days} days "
                     "ago and has not been sent to the payer."),
            recommended_action="Send it to the payer: work they have not approved may not be paid.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.claim_id,
            value=Decimal(r.days), amount=r.total, period_end=ctx.today,
            records=(Record("claims.claim", r.claim_id, f"Claim {r.number}"),),
            figures={"days_waiting": str(r.days), "total": str(r.total), "currency": currency}) for r in rows]


class CompletedNotInvoiced(IntelCheck):
    """The work is signed off and nobody invoiced it."""

    code = "claims.completed_not_invoiced"
    title = "Finished claims not invoiced"
    area = "customers"
    description = "A claim was signed off as done and has no invoice."
    default_severity = "high"
    value_kind = "money"
    params: dict[str, Any] = {"grace_days": 3, "look_back_days": 120}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            f"with live as ({LIVE}) "
            "select c.id, c.branch_id, c.number, p.name as payer, "
            "coalesce(sum(case when x.invoiced_run_id is null and (x.payer_state = 'approved' "
            "   or (x.payer_state = 'countered' and x.our_decision = 'accepted')) "
            "   then coalesce(x.payer_amount, x.asked_total) else 0 end), 0) as worth, "
            "(cast(:today as date) - (c.completed_at at time zone :tz)::date) as days "
            "from claims.claim c join claims.payer p on p.id = c.payer_id "
            "left join live l on l.claim_id = c.id left join claims.estimate_line x on x.estimate_id = l.id "
            "where c.company_id = :c and c.status = 'completed' "
            "and (c.completed_at at time zone :tz)::date between :first and :last "
            "group by c.id, c.branch_id, c.number, p.name, c.completed_at order by c.completed_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "first": ctx.today - timedelta(days=int(ctx.number("look_back_days"))),
             "last": ctx.today - timedelta(days=int(ctx.number("grace_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="high",
            summary=(f"Claim {r.number} with {r.payer} was signed off {r.days} days ago and is worth "
                     f"{money(r.worth, currency)} but has no invoice."),
            recommended_action="Open the claim and make the invoices.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.id,
            amount=r.worth, value=r.worth, period_end=ctx.today,
            records=(Record("claims.claim", r.id, f"Claim {r.number}"),),
            figures={"worth": str(r.worth), "days_waiting": str(r.days), "currency": currency, "payer": r.payer})
            for r in rows if r.worth > 0]


class PayerInvoiceOverdue(IntelCheck):
    """A payer is late paying an invoice."""

    code = "claims.payer_invoice_overdue"
    title = "Payers paying late"
    area = "customers"
    description = "A payer's invoice is past its due date and still unpaid."
    default_severity = "medium"
    value_kind = "money"
    params: dict[str, Any] = {"late_days": 7, "serious_days": 60, "look_back_days": 365}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        if not _enabled(session, "pos"):
            return []
        rows = session.execute(text(
            "select r.id, r.payer_invoice_id as invoice_id, c.id as claim_id, c.branch_id, c.number, p.name as payer "
            "from claims.invoice_run r join claims.claim c on c.id = r.claim_id "
            "join claims.payer p on p.id = c.payer_id where r.company_id = :c and r.payer_invoice_id is not null "
            "and (r.created_at at time zone :tz)::date >= :since order by r.created_at limit 500"),
            {"c": ctx.company_id, "tz": ctx.timezone,
             "since": ctx.today - timedelta(days=int(ctx.number("look_back_days")))}).all()
        from ziira.modules.pos.public import invoice_states

        states = invoice_states(session, {r.invoice_id for r in rows})
        currency = _currency(session, ctx.company_id)
        out = []
        for r in rows:
            s = states.get(r.invoice_id)
            if s is None or s.outstanding <= 0:
                continue
            late = (ctx.today - s.due_date).days
            if late < ctx.number("late_days"):
                continue
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="high" if late >= ctx.number("serious_days") else "medium",
                summary=(f"{r.payer} owes {money(s.outstanding, currency)} on invoice {s.number} (claim {r.number}), "
                         f"{late} days past due."),
                recommended_action="Chase the payer for the money, or ask what they dispute.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.claim_id,
                value=s.outstanding, amount=s.outstanding, period_end=ctx.today,
                records=(Record("claims.claim", r.claim_id, f"Claim {r.number}"),),
                figures={"days_late": str(late), "owed": str(s.outstanding), "currency": currency, "payer": r.payer}))
            if len(out) >= MAX_PER_RUN:
                break
        return out


class PayerRejectsMore(IntelCheck):
    """One payer turns down far more of what is asked than the others do."""

    code = "claims.payer_rejects_more"
    title = "A payer rejecting more than usual"
    area = "customers"
    description = "One payer rejects a much larger share of the money asked than your other payers."
    default_severity = "medium"
    value_kind = "percent"
    params: dict[str, Any] = {"look_back_days": 90, "min_lines": 10, "min_rate_percent": 25, "times_usual": 1.5}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select p.id, p.name, count(*) as n, sum(x.asked_total) as asked, "
            "sum(case when r.state = 'rejected' then x.asked_total else 0 end) as rejected "
            "from claims.line_response r join claims.estimate_line x on x.id = r.line_id "
            "join claims.claim c on c.id = r.claim_id join claims.payer p on p.id = c.payer_id "
            "where r.company_id = :c and r.state in ('approved', 'countered', 'rejected') "
            "and (r.answered_at at time zone :tz)::date >= :since group by p.id, p.name"),
            {"c": ctx.company_id, "tz": ctx.timezone,
             "since": ctx.today - timedelta(days=int(ctx.number("look_back_days")))}).all()
        total_asked = sum((r.asked for r in rows), Decimal(0))
        total_rejected = sum((r.rejected for r in rows), Decimal(0))
        out = []
        for r in rows:
            if r.n < ctx.number("min_lines") or r.asked <= 0:
                continue
            rate = r.rejected * 100 / r.asked
            others = total_asked - r.asked
            usual = (total_rejected - r.rejected) * 100 / others if others > 0 else Decimal(0)
            if rate < Decimal(str(ctx.number("min_rate_percent"))) \
                    or rate < usual * Decimal(str(ctx.number("times_usual"))):
                continue
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="medium",
                summary=(f"{r.name} rejected {rate:.0f}% of the money asked in the last "
                         f"{int(ctx.number('look_back_days'))} days; your other payers rejected {usual:.0f}%."),
                recommended_action="Look at what they reject and why: change how you write estimates, or take it up "
                                   "with the payer.",
                company_id=ctx.company_id, branch_id=None, entity_type="claims.payer", entity_id=r.id,
                value=rate.quantize(CENT), period_start=ctx.today - timedelta(days=int(ctx.number("look_back_days"))),
                period_end=ctx.today, records=(Record("claims.payer", r.id, r.name),),
                figures={"rate_percent": f"{rate:.0f}", "usual_percent": f"{usual:.0f}", "payer": r.name}))
        return out


class RejectionReasonsRepeat(IntelCheck):
    """The same reason for turning lines down keeps coming back from one payer."""

    code = "claims.rejection_reasons_repeat"
    title = "The same rejection reason again and again"
    area = "customers"
    description = "A payer keeps giving the same reason for rejecting lines."
    default_severity = "low"
    value_kind = "count"
    params: dict[str, Any] = {"look_back_days": 90, "min_repeats": 3}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select p.id as payer_id, p.name as payer, lower(btrim(r.reason)) as reason, count(*) as n, "
            "sum(x.asked_total) as amount, (array_agg(c.id order by r.answered_at desc))[1:5] as claim_ids, "
            "(array_agg(c.number order by r.answered_at desc))[1:5] as numbers "
            "from claims.line_response r join claims.estimate_line x on x.id = r.line_id "
            "join claims.claim c on c.id = r.claim_id join claims.payer p on p.id = c.payer_id "
            "where r.company_id = :c and r.state = 'rejected' and r.reason is not null and btrim(r.reason) <> '' "
            "and (r.answered_at at time zone :tz)::date >= :since "
            "group by p.id, p.name, lower(btrim(r.reason)) having count(*) >= :least order by n desc limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "cap": MAX_PER_RUN, "least": int(ctx.number("min_repeats")),
             "since": ctx.today - timedelta(days=int(ctx.number("look_back_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.payer_id, r.reason[:80]), severity="low",
            summary=f"{r.payer} rejected lines {r.n} times with the reason \"{r.reason[:80]}\".",
            recommended_action="Fix the cause once (the wording, a document, the price) instead of arguing each time.",
            company_id=ctx.company_id, branch_id=None, entity_type="claims.payer", entity_id=r.payer_id,
            value=Decimal(r.n), amount=r.amount, period_end=ctx.today,
            records=tuple(Record("claims.claim", i, f"Claim {n}") for i, n in zip(r.claim_ids, r.numbers,
                                                                                  strict=False)),
            figures={"times": str(r.n), "reason": r.reason[:80], "payer": r.payer}) for r in rows]


class ShortPayOpen(IntelCheck):
    """A payer paid less than the invoice and nobody has dealt with the difference."""

    code = "claims.short_pay_open"
    title = "Payers that paid short"
    area = "customers"
    description = "A payer paid less than it was invoiced and the difference is still open."
    default_severity = "medium"
    value_kind = "money"
    params: dict[str, Any] = {"waiting_days": 14}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        rows = session.execute(text(
            "select s.id, s.difference, c.id as claim_id, c.branch_id, c.number, p.name as payer, "
            "(cast(:today as date) - (s.created_at at time zone :tz)::date) as days "
            "from claims.short_pay s join claims.claim c on c.id = s.claim_id join claims.payer p on p.id = s.payer_id "
            "where s.company_id = :c and s.status = 'open' and (s.created_at at time zone :tz)::date <= :limit "
            "order by s.created_at limit :cap"),
            {"c": ctx.company_id, "tz": ctx.timezone, "today": ctx.today, "cap": MAX_PER_RUN,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="medium",
            summary=(f"{r.payer} paid {money(r.difference, currency)} less than invoiced on claim {r.number} "
                     f"{r.days} days ago and it is not dealt with."),
            recommended_action="Dispute it with the payer, charge the customer, or write down that you accept it.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="claims.claim", entity_id=r.claim_id,
            value=r.difference, amount=r.difference, period_end=ctx.today,
            records=(Record("claims.claim", r.claim_id, f"Claim {r.number}"),),
            figures={"short_by": str(r.difference), "days_waiting": str(r.days), "currency": currency,
                     "payer": r.payer}) for r in rows]


CHECKS = (EstimateWaiting, ApprovedNotStarted, CounterUnanswered, SupplementaryNotSent, CompletedNotInvoiced,
          PayerInvoiceOverdue, PayerRejectsMore, RejectionReasonsRepeat, ShortPayOpen)
