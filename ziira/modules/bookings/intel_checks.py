"""Intelligence checks over bookings: no-shows, late cancellations, time that goes unused, refused double bookings,
long idle gaps, and finished appointments never invoiced. Read only; every figure comes from records."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import Session, provides

APPT = "bookings.appointment"
RESOURCE = "bookings.resource"


def _since(ctx: CheckContext, days_name: str) -> datetime:
    zone = ZoneInfo(ctx.timezone)
    return datetime.combine(ctx.today - timedelta(days=int(ctx.number(days_name))), time(0, 0), tzinfo=zone)


def _until(ctx: CheckContext) -> datetime:
    return datetime.combine(ctx.today + timedelta(days=1), time(0, 0), tzinfo=ZoneInfo(ctx.timezone))


@provides(INTEL_CHECK)
class NoShowRate(IntelCheck):
    """A person or room whose clients too often do not turn up."""

    code = "bookings.no_show_rate"
    value_kind = "percent"
    title = "Clients not turning up"
    area = "customers"
    description = "A resource where the share of appointments ending as no-shows is above the limit."
    default_severity = "medium"
    params: dict[str, Any] = {"lookback_days": 30, "min_appointments": 5, "no_show_percent": "20.0"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        found: list[Candidate] = []
        for r in session.execute(text(
                "select r.id, r.name, r.branch_id, count(*) filter (where a.status = 'no_show') as missed, "
                "count(*) as total from bookings.appointment a "
                "join bookings.appointment_resource ar on ar.appointment_id = a.id "
                "join bookings.resource r on r.id = ar.resource_id "
                "where a.company_id = :c and a.kind = 'appointment' and a.status in ('completed', 'no_show') "
                "and a.starts_at >= :since and a.starts_at < :until group by r.id, r.name, r.branch_id "
                "having count(*) >= :min order by r.name"),
                {"c": str(ctx.company_id), "since": _since(ctx, "lookback_days"), "until": _until(ctx),
                 "min": int(ctx.number("min_appointments"))}):
            percent = Decimal(r.missed) * 100 / Decimal(r.total)
            if percent < ctx.number("no_show_percent"):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id),
                severity="high" if percent >= 2 * ctx.number("no_show_percent") else "medium",
                summary=(f"{r.missed} of {r.total} appointments with {r.name} in the last "
                         f"{int(ctx.number('lookback_days'))} days were no-shows ({percent:.0f}%)."),
                recommended_action="Send reminders earlier, ask for a deposit, or call clients the day before.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type=RESOURCE, entity_id=r.id,
                value=percent.quantize(Decimal("0.1")), expected_value=ctx.number("no_show_percent"),
                records=(Record(RESOURCE, r.id, r.name),),
                figures={"no_shows": str(r.missed), "total": str(r.total), "percent": f"{percent:.1f}"}))
        return found


@provides(INTEL_CHECK)
class LateCancellations(IntelCheck):
    """Clients cancelling inside the cancellation window, per branch."""

    code = "bookings.late_cancellations"
    value_kind = "count"
    title = "Late cancellations"
    area = "customers"
    description = "A branch where many appointments were cancelled inside the cancellation window."
    default_severity = "low"
    params: dict[str, Any] = {"lookback_days": 30, "late_cancel_count": 5}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        found: list[Candidate] = []
        for r in session.execute(text(
                "select branch_id, count(*) as late from bookings.appointment where company_id = :c "
                "and late_cancellation and status = 'cancelled' and cancelled_at >= :since and cancelled_at < :until "
                "group by branch_id having count(*) >= :n order by count(*) desc"),
                {"c": str(ctx.company_id), "since": _since(ctx, "lookback_days"), "until": _until(ctx),
                 "n": int(ctx.number("late_cancel_count"))}):
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="low",
                summary=(f"{r.late} appointments were cancelled late in the last "
                         f"{int(ctx.number('lookback_days'))} days."),
                recommended_action="Remind clients of the cancellation rule when they book, or ask for a deposit.",
                company_id=ctx.company_id, branch_id=r.branch_id, value=Decimal(r.late),
                expected_value=ctx.number("late_cancel_count"), figures={"cancelled_late": str(r.late)}))
        return found


@provides(INTEL_CHECK)
class LowUtilisation(IntelCheck):
    """Working time that is mostly empty."""

    code = "bookings.low_utilisation"
    value_kind = "percent"
    title = "Working time going unused"
    area = "customers"
    description = ("A resource whose booked time over the last days is a small share of its working hours. "
                   "(The limit is set by the business; Intelligence does not learn it from history.)")
    default_severity = "low"
    params: dict[str, Any] = {"lookback_days": 14, "utilisation_percent": "30.0", "min_hours": 8}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        days = int(ctx.number("lookback_days"))
        zone = ZoneInfo(ctx.timezone)
        start = datetime.combine(ctx.today - timedelta(days=days), time(0, 0), tzinfo=zone)
        end = datetime.combine(ctx.today, time(0, 0), tzinfo=zone)           # whole days that are over
        found: list[Candidate] = []
        resources = session.execute(text(
            "select id, name, branch_id from bookings.resource where company_id = :c and is_active order by name"),
            {"c": str(ctx.company_id)}).all()
        for r in resources:
            hours = session.execute(text("select weekday, start_time, end_time from bookings.resource_hours "
                                         "where resource_id = :r"), {"r": str(r.id)}).all()
            available = Decimal(0)
            for offset in range(days):
                day = ctx.today - timedelta(days=days - offset)
                for h in hours:
                    if h.weekday == day.weekday():
                        available += Decimal((datetime.combine(day, h.end_time) -
                                              datetime.combine(day, h.start_time)).total_seconds()) / 60
            off = session.execute(text(
                "select coalesce(sum(extract(epoch from least(ends_at, :e) - greatest(starts_at, :s))) / 60, 0) "
                "from bookings.resource_time_off where resource_id = :r and ends_at > :s and starts_at < :e"),
                {"r": str(r.id), "s": start, "e": end}).scalar_one()
            available = max(available - Decimal(off), Decimal(0))
            if available < ctx.number("min_hours") * 60:
                continue
            booked = Decimal(session.execute(text(
                "select coalesce(sum(extract(epoch from a.ends_at - a.starts_at)) / 60, 0) from bookings.appointment a "
                "join bookings.appointment_resource ar on ar.appointment_id = a.id where ar.resource_id = :r "
                "and a.status in ('completed', 'in_service', 'checked_in', 'confirmed') "
                "and a.starts_at >= :s and a.starts_at < :e"), {"r": str(r.id), "s": start, "e": end}).scalar_one())
            percent = min(booked * 100 / available, Decimal(100))
            if percent >= ctx.number("utilisation_percent"):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="low",
                summary=(f"{r.name} was booked for {percent:.0f}% of its working time in the last {days} days "
                         f"({booked / 60:.1f} of {available / 60:.1f} hours)."),
                recommended_action="Promote this service, offer a quiet-time discount, or change the working hours.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type=RESOURCE, entity_id=r.id,
                value=percent.quantize(Decimal("0.1")), expected_value=ctx.number("utilisation_percent"),
                records=(Record(RESOURCE, r.id, r.name),),
                figures={"percent": f"{percent:.1f}", "booked_hours": f"{booked / 60:.1f}",
                         "working_hours": f"{available / 60:.1f}"}))
        return found


@provides(INTEL_CHECK)
class DoubleBookingRefused(IntelCheck):
    """The same time being asked for more than once: a sign the calendar is being used in two places or is too small."""

    code = "bookings.double_booking_refused"
    value_kind = "count"
    title = "Times asked for twice"
    area = "customers"
    description = "A branch where many bookings were refused because the time was already taken."
    default_severity = "info"
    params: dict[str, Any] = {"lookback_days": 7, "refused_count": 5}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        found: list[Candidate] = []
        for r in session.execute(text(
                "select branch_id, count(*) as refused from bookings.booking_refusal where company_id = :c "
                "and source <> 'recurring' and created_at >= :since and created_at < :until "
                "group by branch_id having count(*) >= :n"),
                {"c": str(ctx.company_id), "since": _since(ctx, "lookback_days"), "until": _until(ctx),
                 "n": int(ctx.number("refused_count"))}):
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="info",
                summary=f"{r.refused} bookings were refused in the last {int(ctx.number('lookback_days'))} days "
                        "because the time was already taken.",
                recommended_action="Check that everyone books in Ziira, and add another person or room if clients "
                                   "keep asking for the same times.",
                company_id=ctx.company_id, branch_id=r.branch_id, value=Decimal(r.refused),
                expected_value=ctx.number("refused_count"), figures={"refused": str(r.refused)}))
        return found


@provides(INTEL_CHECK)
class LongIdleGaps(IntelCheck):
    """Holes in a person's coming days that nobody has been offered."""

    code = "bookings.idle_gaps"
    value_kind = "count"
    title = "Long gaps in the diary"
    area = "customers"
    description = "A resource with a long empty stretch between two appointments on the same coming day."
    default_severity = "info"
    params: dict[str, Any] = {"look_ahead_days": 3, "gap_minutes": 120, "max_findings": 30}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        zone = ZoneInfo(ctx.timezone)
        start = datetime.combine(ctx.today, time(0, 0), tzinfo=zone)
        end = start + timedelta(days=int(ctx.number("look_ahead_days")) + 1)
        rows = session.execute(text(
            "select r.id, r.name, r.branch_id, a.starts_at, a.ends_at from bookings.appointment a "
            "join bookings.appointment_resource ar on ar.appointment_id = a.id and ar.holds "
            "join bookings.resource r on r.id = ar.resource_id where a.company_id = :c "
            "and a.status in ('requested', 'confirmed') and a.starts_at >= :s and a.starts_at < :e "
            "order by r.id, a.starts_at"), {"c": str(ctx.company_id), "s": start, "e": end}).all()
        limit = timedelta(minutes=int(ctx.number("gap_minutes")))
        found: list[Candidate] = []
        previous: Any = None
        for row in rows:
            if previous is not None and previous.id == row.id and \
                    previous.ends_at.astimezone(zone).date() == row.starts_at.astimezone(zone).date() \
                    and row.starts_at - previous.ends_at >= limit and len(found) < int(ctx.number("max_findings")):
                day = row.starts_at.astimezone(zone).date()
                gap = row.starts_at - previous.ends_at
                found.append(Candidate(
                    fingerprint=fingerprint(self.code, row.id, day, previous.ends_at),
                    severity="info",
                    summary=(f"{row.name} has a gap of {int(gap.total_seconds() // 3600)} h "
                             f"{int(gap.total_seconds() % 3600 // 60)} min on {day} between "
                             f"{previous.ends_at.astimezone(zone):%H:%M} and {row.starts_at.astimezone(zone):%H:%M}."),
                    recommended_action="Offer the time to people on the waitlist or message regular clients.",
                    company_id=ctx.company_id, branch_id=row.branch_id, entity_type=RESOURCE, entity_id=row.id,
                    period_start=day, value=Decimal(int(gap.total_seconds() // 60)),
                    expected_value=ctx.number("gap_minutes"), records=(Record(RESOURCE, row.id, row.name),),
                    figures={"gap_minutes": str(int(gap.total_seconds() // 60)), "weekday": day.strftime("%A")}))
            previous = row
        return found


@provides(INTEL_CHECK)
class CompletedNotInvoiced(IntelCheck):
    """Appointments that were finished but never billed."""

    code = "bookings.completed_not_invoiced"
    value_kind = "money"
    title = "Finished appointments not invoiced"
    area = "customers"
    description = ("Appointments finished more than a few days ago, with a customer and a price, that have no invoice. "
                   "Only checked when Point of Sale is on.")
    default_severity = "medium"
    params: dict[str, Any] = {"invoice_after_days": 2, "lookback_days": 60}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        if session.execute(text(
                "select 1 from kernel.tenant_unit where unit_name = 'pos' and status = 'enabled' "
                "and tenant_id = kernel.current_tenant()")).first() is None:
            return []
        cutoff = datetime.combine(ctx.today - timedelta(days=int(ctx.number("invoice_after_days"))), time(23, 59),
                                  tzinfo=ZoneInfo(ctx.timezone))
        found: list[Candidate] = []
        currency = session.execute(text("select base_currency from kernel.company where id = :c"),
                                   {"c": str(ctx.company_id)}).scalar_one()
        for r in session.execute(text(
                "select branch_id, count(*) as n, sum(price) as total, min(completed_at) as oldest "
                "from bookings.appointment a where company_id = :c and status = 'completed' and kind = 'appointment' "
                "and invoice_id is null and customer_id is not null and price > 0 and completed_at <= :cut "
                "and not exists (select 1 from bookings.checkout_line l "
                "join bookings.checkout k on k.id = l.checkout_id "
                "where l.appointment_id = a.id and k.status = 'done') "
                "and completed_at >= :since group by branch_id order by sum(price) desc"),
                {"c": str(ctx.company_id), "cut": cutoff, "since": _since(ctx, "lookback_days")}):
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="medium",
                summary=(f"{r.n} finished appointments worth {currency} {r.total:,.2f} have no invoice, the oldest "
                         f"finished on {r.oldest.astimezone(ZoneInfo(ctx.timezone)).date()}."),
                recommended_action="Open Front desk or Appointments and create the invoices.",
                company_id=ctx.company_id, branch_id=r.branch_id, value=Decimal(r.total), amount=Decimal(r.total),
                period_start=r.oldest.astimezone(ZoneInfo(ctx.timezone)).date(),
                figures={"invoices": str(r.n), "amount": str(r.total)}))
        return found


@provides(INTEL_CHECK)
class TipsHeldTooLong(IntelCheck):
    """Tips the business holds for staff (card and mobile-money tips) that have not been handed over."""

    code = "bookings.tips_held"
    value_kind = "money"
    title = "Tips not paid out"
    area = "cash_sales"
    description = ("Tips the business holds for its staff that were taken more than a number of days ago "
                   "and not paid out.")
    default_severity = "medium"
    params: dict[str, Any] = {"older_than_days": 7, "min_amount": "1.00"}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        cutoff = datetime.combine(ctx.today - timedelta(days=int(ctx.number("older_than_days"))), time(23, 59),
                                  tzinfo=ZoneInfo(ctx.timezone))
        found: list[Candidate] = []
        for r in session.execute(text(
                "select t.branch_id, count(*) as n, sum(t.amount) as total, min(t.created_at) as oldest "
                "from bookings.checkout_tip t where t.company_id = :c and t.held and t.paid_out_at is null "
                "and t.created_at <= :cut group by t.branch_id having sum(t.amount) >= :min "
                "order by sum(t.amount) desc"),
                {"c": str(ctx.company_id), "cut": cutoff, "min": ctx.number("min_amount")}):
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id), severity="medium",
                summary=(f"The business holds {r.total:,.2f} in {r.n} tips for staff, the oldest taken on "
                         f"{r.oldest.astimezone(ZoneInfo(ctx.timezone)).date()}."),
                recommended_action="Open Staff pay, check the tips owed and pay them out.",
                company_id=ctx.company_id, branch_id=r.branch_id, value=Decimal(r.total), amount=Decimal(r.total),
                period_start=r.oldest.astimezone(ZoneInfo(ctx.timezone)).date(),
                figures={"tips": str(r.n), "amount": str(r.total)}))
        return found


@provides(INTEL_CHECK)
class DepositsUnpaid(IntelCheck):
    """Appointments soon that asked for a deposit nobody has paid."""

    code = "bookings.deposits_unpaid"
    value_kind = "count"
    title = "Deposits not paid"
    area = "customers"
    description = "Appointments in the next few days whose deposit is not paid."
    default_severity = "medium"
    params: dict[str, Any] = {"look_ahead_days": 2, "min_count": 1}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        zone = ZoneInfo(ctx.timezone)
        start = datetime.combine(ctx.today, time(0, 0), tzinfo=zone)
        end = start + timedelta(days=int(ctx.number("look_ahead_days")) + 1)
        found: list[Candidate] = []
        for r in session.execute(text(
                "select branch_id, count(*) as n, sum(deposit_amount - deposit_paid) as owed, min(starts_at) as first "
                "from bookings.appointment where company_id = :c and status in ('requested', 'confirmed') "
                "and kind = 'appointment' and deposit_amount > deposit_paid and starts_at >= :s and starts_at < :e "
                "group by branch_id having count(*) >= :min order by count(*) desc"),
                {"c": str(ctx.company_id), "s": start, "e": end, "min": int(ctx.number("min_count"))}):
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.branch_id, ctx.today), severity="medium",
                summary=(f"{r.n} appointments in the next {int(ctx.number('look_ahead_days'))} days have a deposit "
                         f"not paid ({r.owed:,.2f} in all), the first on {r.first.astimezone(zone).date()}."),
                recommended_action="Remind the clients to pay the deposit, or free the time for someone else.",
                company_id=ctx.company_id, branch_id=r.branch_id, value=Decimal(r.n), period_start=ctx.today,
                figures={"appointments": str(r.n), "owed": str(r.owed)}))
        return found


ALL_CHECKS = (NoShowRate, LateCancellations, LowUtilisation, DoubleBookingRefused, LongIdleGaps, CompletedNotInvoiced,
              TipsHeldTooLong, DepositsUnpaid)
