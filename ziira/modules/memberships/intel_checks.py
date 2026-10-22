"""Intelligence checks over Memberships: memberships about to end, packages about to expire unused, recurring invoices
that failed, and monthly income at risk. Read only; every figure comes from records."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import Session, provides


def currency_of(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def money(currency: str, value: Decimal) -> str:
    return f"{currency} {value:,.2f}"


# --------------------------------------------------------------------------- memberships about to end
@provides(INTEL_CHECK)
class MembershipsEnding(IntelCheck):
    """An active membership that will end soon: cancelled for the end of the period, or reaching its end date."""

    code = "memberships.ending"

    value_kind = "days"
    title = "Memberships ending soon"
    area = "customers"
    description = ("An active membership that is due to be cancelled, or reaches its end date, within the next few "
                   "days. A chance to talk to the member before they leave.")
    default_severity = "low"
    params: dict[str, Any] = {"days": 14, "max_members": 200}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        found: list[Candidate] = []
        horizon = ctx.today + timedelta(days=int(ctx.number("days")))
        rows = session.execute(text(
            "select m.id, m.number, m.branch_id, m.plan_name, m.price, m.billing_interval, "
            "  least(coalesce(m.cancel_at, date '9999-12-31'), coalesce(m.end_date, date '9999-12-31')) as ends_on, "
            "  (m.cancel_at is not null) as cancelled "
            "from memberships.member m where m.company_id = :c and m.status = 'active' "
            "and (m.cancel_at between :t and :h or m.end_date between :t and :h) order by ends_on, m.number limit :n"),
            {"c": str(ctx.company_id), "t": ctx.today, "h": horizon, "n": int(ctx.number("max_members"))}).all()
        for r in rows:
            days = (r.ends_on - ctx.today).days
            why = "is cancelling" if r.cancelled else "reaches its end date"
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id, r.ends_on), severity="low",
                summary=(f"Membership {r.number} ({r.plan_name}) {why} on {r.ends_on}, in {days} days. It brings in "
                         f"{money(currency, r.price)} every {r.billing_interval}."),
                recommended_action="Speak to the member before they go, and offer to renew or change their plan.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="memberships.member", entity_id=r.id,
                period_start=ctx.today, period_end=r.ends_on, value=Decimal(days), expected_value=ctx.number("days"),
                amount=r.price, records=(Record("memberships.member", r.id, f"{r.number} ({r.plan_name})"),),
                figures={"days_left": str(days), "ends_on": str(r.ends_on), "fee": str(r.price)}))
        return found


# --------------------------------------------------------------------------- packages expiring unused
@provides(INTEL_CHECK)
class PackagesExpiringUnused(IntelCheck):
    """A package with credits left that expires soon."""

    code = "memberships.packages_expiring"

    value_kind = "days"
    title = "Packages about to expire with credits left"
    area = "customers"
    description = ("A package a customer paid for that still has unused credits and expires within the next few days. "
                   "They will lose what they paid for unless they book.")
    default_severity = "low"
    params: dict[str, Any] = {"days": 14, "min_credits": 1, "max_packages": 200}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        found: list[Candidate] = []
        rows = session.execute(text(
            "select p.id, p.number, p.branch_id, p.name, p.price, p.credits, p.expires_on, "
            "  (select coalesce(sum(e.quantity), 0) from memberships.credit_entry e where e.holder_id = p.id) as left "
            "from memberships.sold_package p where p.company_id = :c and p.status = 'active' "
            "and p.expires_on between :t and :h order by p.expires_on, p.number limit :n"),
            {"c": str(ctx.company_id), "t": ctx.today, "h": ctx.today + timedelta(days=int(ctx.number("days"))),
             "n": int(ctx.number("max_packages"))}).all()
        for r in rows:
            left = Decimal(r.left)
            if left < ctx.number("min_credits"):
                continue
            days = (r.expires_on - ctx.today).days
            unused_value = ((Decimal(r.price) * left / Decimal(r.credits)).quantize(Decimal("0.01"))
                            if r.credits else Decimal(0))
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id, r.expires_on), severity="low",
                summary=(f"Package {r.number} ({r.name}) expires on {r.expires_on}, in {days} days, with {left:g} of "
                         f"{Decimal(r.credits):g} credits unused."),
                recommended_action="Remind the customer to book before the package expires.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="memberships.sold_package",
                entity_id=r.id, period_start=ctx.today, period_end=r.expires_on, value=Decimal(days),
                expected_value=ctx.number("days"), amount=unused_value,
                records=(Record("memberships.sold_package", r.id, f"{r.number} ({r.name})"),),
                figures={"days_left": str(days), "credits_left": str(left), "credits": str(r.credits),
                         "expires_on": str(r.expires_on), "unused_value": money(currency, unused_value)}))
        return found


# --------------------------------------------------------------------------- recurring invoices that failed
@provides(INTEL_CHECK)
class RecurringInvoiceFailed(IntelCheck):
    """A recurring invoice or membership renewal that could not be issued."""

    code = "memberships.recurring_invoice_failed"

    value_kind = "days"
    title = "Recurring invoices that failed"
    area = "customers"
    description = ("An invoice that was due on a schedule or at a membership renewal but could not be issued. Until it "
                   "is fixed, that customer is not being billed.")
    default_severity = "medium"
    params: dict[str, Any] = {"high_after_days": 3, "lookback_days": 90, "max_runs": 200}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        found: list[Candidate] = []
        rows = session.execute(text(
            "select r.id, r.branch_id, r.owner_type, r.owner_id, r.period_start, r.attempts, r.message, "
            "  coalesce(s.name, m.number, p.number) as label, "
            "  (r.created_at at time zone :tz)::date as first_failed "
            "from memberships.invoice_run r "
            "left join memberships.schedule s on r.owner_type = 'schedule' and s.id = r.owner_id "
            "left join memberships.member m on r.owner_type = 'member' and m.id = r.owner_id "
            "left join memberships.sold_package p on r.owner_type = 'package' and p.id = r.owner_id "
            "where r.company_id = :c and r.status = 'failed' "
            "and (r.created_at at time zone :tz)::date >= :since order by r.created_at limit :n"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "since": ctx.today - timedelta(
                days=int(ctx.number("lookback_days"))), "n": int(ctx.number("max_runs"))}).all()
        for r in rows:
            days = (ctx.today - r.first_failed).days
            severe = days >= ctx.number("high_after_days")
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="high" if severe else "medium",
                summary=(f"The invoice for {r.label} for the period starting {r.period_start} could not be issued "
                         f"({r.message or 'no reason given'})."),
                recommended_action="Open the recurring invoice, fix the cause, and issue it again.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="memberships.invoice_run", entity_id=r.id,
                period_start=r.period_start, value=Decimal(days), expected_value=ctx.number("high_after_days"),
                records=(Record("memberships.invoice_run", r.id, str(r.label)),),
                figures={"days_failed": str(days), "attempts": str(r.attempts), "period_start": str(r.period_start)}))
        return found


# --------------------------------------------------------------------------- income at risk
@provides(INTEL_CHECK)
class MembershipRevenueAtRisk(IntelCheck):
    """A large share of monthly membership income is cancelling, on hold, or not being billed."""

    code = "memberships.revenue_at_risk"

    value_kind = "percent"
    title = "Membership income at risk"
    area = "customers"
    description = ("The share of monthly membership income that comes from memberships that are cancelling, on hold, "
                   "or whose renewal invoice failed.")
    default_severity = "medium"
    params: dict[str, Any] = {"min_percent": "20.0", "high_percent": "40.0", "min_members": 3}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        row = session.execute(text(
            "with live as (select m.id, m.price / (case m.billing_interval when 'month' then 1 when 'quarter' then 3 "
            "else 12 end) as monthly, (m.status in ('paused', 'frozen') or m.cancel_at is not null or exists ("
            "  select 1 from memberships.invoice_run r where r.owner_type = 'member' and r.owner_id = m.id "
            "  and r.status = 'failed')) as risky from memberships.member m "
            "where m.company_id = :c and m.status in ('active', 'paused', 'frozen')) "
            "select coalesce(sum(monthly), 0) as total, coalesce(sum(monthly) filter (where risky), 0) as risk, "
            "count(*) filter (where risky) as n from live"), {"c": str(ctx.company_id)}).one()
        total, risk = Decimal(row.total), Decimal(row.risk)
        if total <= 0 or row.n < ctx.number("min_members"):
            return []
        percent = (risk * 100 / total).quantize(Decimal("0.1"))
        if percent < ctx.number("min_percent"):
            return []
        return [Candidate(
            fingerprint=fingerprint(self.code, ctx.company_id), severity="high" if percent >= ctx.number(
                "high_percent") else "medium",
            summary=(f"{row.n} memberships worth {money(currency, risk.quantize(Decimal('0.01')))} a month "
                     f"({percent}% of monthly membership income) are cancelling, on hold or not being billed."),
            recommended_action="Look at the members leaving or on hold, and at any renewal invoices that failed.",
            company_id=ctx.company_id, entity_type="memberships.member", period_start=ctx.today,
            value=percent, expected_value=ctx.number("min_percent"), amount=risk.quantize(Decimal("0.01")),
            figures={"at_risk_monthly": str(risk.quantize(Decimal("0.01"))), "total_monthly": str(
                total.quantize(Decimal("0.01"))), "members": str(row.n)})]


# --------------------------------------------------------------------------- members who stopped coming
@provides(INTEL_CHECK)
class MembersGoneQuiet(IntelCheck):
    """Active members who have not visited for several weeks (only where check-in is used)."""

    code = "memberships.members_inactive"

    value_kind = "count"
    title = "Members who stopped coming"
    area = "customers"
    description = ("Paying members who have not been in for several weeks. They are the ones who cancel next. Silent "
                   "when the gym does not use check-in at all.")
    default_severity = "low"
    params: dict[str, Any] = {"idle_weeks": 3, "min_members": 5, "max_members": 5000}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        weeks = int(ctx.number("idle_weeks"))
        cutoff = ctx.today - timedelta(weeks=weeks)
        used = session.execute(text(
            "select 1 from memberships.checkin where company_id = :c and counted and business_date >= :s limit 1"),
            {"c": str(ctx.company_id), "s": ctx.today - timedelta(weeks=weeks * 2)}).first()
        if used is None:
            return []
        currency = currency_of(session, ctx.company_id)
        rows = session.execute(text(
            "select m.branch_id, count(*) as n, "
            "  coalesce(sum(m.price / (case m.billing_interval when 'month' then 1 when 'quarter' then 3 else 12 end)), "  # noqa: E501
            "    0) as monthly "
            "from (select * from memberships.member where company_id = :c and status = 'active' and not is_trial "
            "      and start_date < :cut limit :n) m "
            "left join memberships.profile p on p.customer_id = m.customer_id "
            "where coalesce(p.last_visit_on, m.start_date) < :cut group by m.branch_id"),
            {"c": str(ctx.company_id), "cut": cutoff, "n": int(ctx.number("max_members"))}).all()
        found: list[Candidate] = []
        for r in rows:
            if r.n < ctx.number("min_members"):
                continue
            monthly = Decimal(r.monthly).quantize(Decimal("0.01"))
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="low",
                summary=(f"{r.n} paying members have not visited for {weeks} weeks or more. Together they pay "
                         f"{money(currency, monthly)} a month."),
                recommended_action="Call or message them this week; the 'we miss you' message can be switched on in "
                                   "the membership policies.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="memberships.member",
                period_start=cutoff, period_end=ctx.today, value=Decimal(r.n), expected_value=ctx.number("min_members"),
                amount=monthly, figures={"members": str(r.n), "weeks": str(weeks), "total_monthly": str(monthly)}))
        return found


# --------------------------------------------------------------------------- members who owe money
@provides(INTEL_CHECK)
class MembershipPaymentLate(IntelCheck):
    """Members whose membership fee is unpaid past its due date."""

    code = "memberships.payment_late"

    value_kind = "money"
    title = "Members who have not paid"
    area = "customers"
    description = "Membership invoices that are overdue, per branch, with how long the oldest has waited."
    default_severity = "medium"
    params: dict[str, Any] = {"min_days_late": 7, "high_days_late": 30, "min_amount": "0.00"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        rows = session.execute(text(
            "select r.branch_id, count(distinct r.customer_id) as people, sum(r.outstanding) as owed, "
            "  min(r.due_date) as oldest from memberships.invoice_run r where r.company_id = :c and r.status = 'issued' "  # noqa: E501
            "and r.settle_state = 'open' and r.invoice_id is not null and r.outstanding > 0 "
            "and r.due_date <= :late group by r.branch_id"),
            {"c": str(ctx.company_id), "late": ctx.today - timedelta(days=int(ctx.number("min_days_late")))}).all()
        found: list[Candidate] = []
        for r in rows:
            owed = Decimal(r.owed).quantize(Decimal("0.01"))
            if owed < ctx.number("min_amount"):
                continue
            days = (ctx.today - r.oldest).days
            severe = days >= ctx.number("high_days_late")
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="high" if severe else "medium",
                summary=(f"{r.people} members owe {money(currency, owed)} in membership fees. The oldest invoice is "
                         f"{days} days late."),
                recommended_action="Open Members, Money owed, and collect or write off what is owed. Late-payment "
                                   "reminders go out by themselves.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="memberships.invoice_run",
                period_start=r.oldest, period_end=ctx.today, value=Decimal(days),
                expected_value=ctx.number("min_days_late"), amount=owed,
                figures={"members": str(r.people), "owed": str(owed), "oldest_days": str(days)}))
        return found


# --------------------------------------------------------------------------- a term or contract ending with fees unpaid
@provides(INTEL_CHECK)
class TermEndingUnpaid(IntelCheck):
    """A fixed term (a school term, a course, a contract) that ends soon while fees on it are still unpaid."""

    code = "memberships.term_ending_unpaid"

    value_kind = "money"
    title = "Terms ending with unpaid fees"
    area = "customers"
    description = ("Memberships and recurring invoices with an end date in the next few days that still have an "
                   "unpaid invoice, per branch.")
    default_severity = "medium"
    params: dict[str, Any] = {"look_ahead_days": 14, "min_amount": "0.00"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        horizon = ctx.today + timedelta(days=int(ctx.number("look_ahead_days")))
        rows = session.execute(text(
            "select r.branch_id, count(distinct r.customer_id) as payers, sum(r.outstanding) as owed, "
            "  min(e.ends_on) as first_end from memberships.invoice_run r join ("
            "    select 'member' as owner_type, id, end_date as ends_on from memberships.member "
            "      where company_id = :c and status = 'active' and end_date between :t and :h "
            "    union all select 'schedule', id, end_date from memberships.schedule "
            "      where company_id = :c and status in ('active', 'paused') and end_date between :t and :h"
            "  ) e on e.owner_type = r.owner_type and e.id = r.owner_id "
            "where r.company_id = :c and r.status = 'issued' and r.settle_state = 'open' and r.outstanding > 0 "
            "and r.invoice_id is not null group by r.branch_id"),
            {"c": str(ctx.company_id), "t": ctx.today, "h": horizon}).all()
        found: list[Candidate] = []
        for r in rows:
            owed = Decimal(r.owed).quantize(Decimal("0.01"))
            if owed < ctx.number("min_amount"):
                continue
            days = (r.first_end - ctx.today).days
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="medium",
                summary=(f"{r.payers} payers still owe {money(currency, owed)} on terms that end within "
                         f"{int(ctx.number('look_ahead_days'))} days (the first in {days} days)."),
                recommended_action="Collect the fees before the term ends: once it is over, families are harder to "
                                   "reach and the money is usually lost.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="memberships.invoice_run",
                period_start=ctx.today, period_end=r.first_end, value=Decimal(days),
                expected_value=ctx.number("look_ahead_days"), amount=owed,
                figures={"payers": str(r.payers), "owed": str(owed), "days_left": str(days)}))
        return found


# --------------------------------------------------------------------------- staff who let refused people in
@provides(INTEL_CHECK)
class EntryOverrides(IntelCheck):
    """A staff member who overrode many refused entries lately."""

    code = "memberships.entry_overrides"

    value_kind = "count"
    title = "Many refused entries overridden"
    area = "controls"
    description = ("A person at the front desk let in many people the check-in had refused (unpaid, expired, frozen). Now "  # noqa: E501
                   "and then is normal; a lot may mean free entry for friends.")
    default_severity = "medium"
    params: dict[str, Any] = {"lookback_days": 7, "max_overrides": 5}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("lookback_days")))
        rows = session.execute(text(
            "select k.created_by as person, u.full_name, k.branch_id, count(*) as n from memberships.checkin k "
            "left join kernel.app_user u on u.id = k.created_by where k.company_id = :c and k.overridden "
            "and k.business_date >= :s group by k.created_by, u.full_name, k.branch_id having count(*) > :m"),
            {"c": str(ctx.company_id), "s": since, "m": int(ctx.number("max_overrides"))}).all()
        return [Candidate(
            fingerprint=fingerprint(self.code, r.person, r.branch_id), severity="medium",
            summary=(f"{r.full_name or 'A staff member'} let in {r.n} people the check-in had refused in the last "
                     f"{int(ctx.number('lookback_days'))} days."),
            recommended_action="Look at the entries with a staff override and ask for the reasons they gave.",
            company_id=ctx.company_id, branch_id=r.branch_id, entity_type="kernel.app_user", entity_id=r.person,
            period_start=since, period_end=ctx.today, value=Decimal(r.n), expected_value=ctx.number("max_overrides"),
            figures={"person": str(r.full_name or ""), "refused": str(r.n)}) for r in rows]
