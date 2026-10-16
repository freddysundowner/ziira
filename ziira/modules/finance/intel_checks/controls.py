"""Checks on how the books are kept: late and back-dated entries, closed periods, manual journals, self-approval."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ziira.modules.finance.intel_checks.common import currency, ids, money, since
from ziira.modules.intel.public import INTEL_CHECK, Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.sdk import Session, provides

ENTRY = "finance.journal_entry"
MANUAL = "finance.manual_journal"


@provides(INTEL_CHECK)
class BackdatedEntries(IntelCheck):
    """Journal entries posted long after the date they carry."""

    code = "finance.backdated_entries"

    value_kind = "days"
    title = "Entries posted long after their date"
    area = "books"
    description = "A journal entry was posted to the books many days after the date it carries."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 60, "late_days": 14, "manual_only": 1}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        late = int(ctx.number("late_days"))
        floor = since(ctx.today, ctx.number("days"))
        rows = session.execute(text(
            "select e.id, e.number, e.entry_date, (e.posted_at at time zone :tz)::date as posted_on, p.status, "
            "coalesce(sum(l.debit), 0) as total, "
            "case when count(distinct l.branch_id) = 1 and bool_and(l.branch_id is not null) "
            "then min(l.branch_id::text)::uuid end as branch_id "
            "from finance.journal_entry e join finance.journal_line l on l.entry_id = e.id "
            "join finance.period p on p.id = e.period_id "
            "where e.company_id = :c and e.reversal_of_id is null and (:manual = 0 or e.is_manual) "
            "and e.entry_date >= :floor - 366 and (e.posted_at at time zone :tz)::date >= :floor "
            "group by e.id, p.status "
            "having (e.posted_at at time zone :tz)::date - e.entry_date > :late order by e.posted_at"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "manual": int(ctx.number("manual_only")),
             "floor": floor, "late": late}).all()
        unit = currency(session, ctx.company_id)
        found = []
        for r in rows:
            days_late = (r.posted_on - r.entry_date).days
            severity = "high" if r.status != "open" else ("medium" if days_late >= 2 * late else "low")
            where = "" if r.status == "open" else f" The month was already {r.status.replace('_', ' ')}."
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity=severity, company_id=ctx.company_id,
                branch_id=ids(r.branch_id), entity_type=ENTRY, entity_id=r.id, value=Decimal(days_late),
                expected_value=Decimal(late), amount=r.total,
                summary=(f"Journal entry {r.number} for {unit} {money(r.total)} is dated {r.entry_date} but was posted "
                         f"on {r.posted_on}, {days_late} days later.{where}"),
                recommended_action="Ask the person who posted it why the entry was dated back.",
                period_start=r.entry_date, period_end=r.posted_on,
                records=(Record(ENTRY, r.id, f"Entry {r.number}"),),
                figures={"entry_date": str(r.entry_date), "posted_on": str(r.posted_on),
                         "days_late": str(days_late), "period_status": r.status}))
        return found


@provides(INTEL_CHECK)
class PeriodReopened(IntelCheck):
    """An accounting period that was closed has been opened again."""

    code = "finance.period_reopened"

    value_kind = "count"
    title = "Closed month reopened"
    area = "books"
    description = "A month that had been closed was opened again, so its figures could change."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select a.id as audit_id, a.occurred_at, p.id, p.start_date, p.end_date, u.full_name, "
            "(select count(*) from finance.journal_entry e where e.period_id = p.id and e.posted_at > a.occurred_at) "
            "as posted_since "
            "from kernel.audit_log a join finance.period p on p.id = a.entity_id "
            "left join kernel.app_user u on u.id = a.user_id "
            "where a.entity_type = 'finance.period' and a.action = 'status' and a.changes->>'to' = 'open' "
            "and p.company_id = :c and (a.occurred_at at time zone :tz)::date >= :floor order by a.occurred_at"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "floor": since(ctx.today, ctx.number("days"))}).all()
        found = []
        for r in rows:
            day = r.occurred_at.astimezone(ZoneInfo(ctx.timezone)).date()
            who = r.full_name or "Someone"
            n = r.posted_since
            more = f" Since then {n} entr{'y has' if n == 1 else 'ies have'} been posted into it." if n else ""
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.audit_id), severity="high" if r.posted_since else "medium",
                company_id=ctx.company_id, entity_type="finance.period", entity_id=r.id,
                period_start=r.start_date, period_end=r.end_date, value=Decimal(r.posted_since),
                summary=f"{who} reopened the closed period {r.start_date} to {r.end_date} on {day}.{more}",
                recommended_action="Confirm why the period was reopened and make sure it is closed again.",
                records=(Record("finance.period", r.id, f"Period {r.start_date} to {r.end_date}"),),
                figures={"reopened_on": str(day), "reopened_by": who, "entries_posted_since": str(r.posted_since)}))
        return found


@provides(INTEL_CHECK)
class PostedAfterClose(IntelCheck):
    """Entries posted into a month after it was closed."""

    code = "finance.posted_after_close"
    title = "Entries posted into a closed month"
    area = "books"
    description = "A journal entry was posted into a month after that month had been closed."
    default_severity = "high"
    params: dict[str, Any] = {"days": 60}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        rows = session.execute(text(
            "select e.id, e.number, e.entry_date, (e.posted_at at time zone :tz)::date as posted_on, p.status, "
            "p.start_date, p.end_date, coalesce(sum(l.debit), 0) as total, u.full_name "
            "from finance.journal_entry e join finance.period p on p.id = e.period_id "
            "join finance.journal_line l on l.entry_id = e.id left join kernel.app_user u on u.id = e.created_by "
            "where e.company_id = :c and p.status in ('soft_closed', 'locked') and p.closed_at is not null "
            "and e.posted_at > p.closed_at and (e.posted_at at time zone :tz)::date >= :floor "
            "group by e.id, p.id, u.full_name order by e.posted_at"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "floor": since(ctx.today, ctx.number("days"))}).all()
        unit = currency(session, ctx.company_id)
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="high", company_id=ctx.company_id,
            entity_type=ENTRY, entity_id=r.id, amount=r.total, period_start=r.start_date, period_end=r.end_date,
            summary=(f"Journal entry {r.number} for {unit} {money(r.total)} was posted on {r.posted_on} into "
                     f"{r.start_date} to {r.end_date}, which had already been closed."
                     + (f" It was posted by {r.full_name}." if r.full_name else "")),
            recommended_action="Check the entry and why it was needed after the month was closed.",
            records=(Record(ENTRY, r.id, f"Entry {r.number}"),),
            figures={"posted_on": str(r.posted_on), "period_status": r.status}) for r in rows]


def _manual_rows(session: Session, ctx: CheckContext, extra: str = "",
                 params: dict[str, Any] | None = None) -> list[Any]:
    """Manual journals created in the look-back window that are posted or waiting for approval."""
    return list(session.execute(text(
        "select m.id, m.number, m.total, m.status, m.description, m.created_at, m.created_by, m.approved_by, "
        "e.posted_at, u.full_name from finance.manual_journal m left join finance.journal_entry e on e.id = m.entry_id "
        "left join kernel.app_user u on u.id = m.created_by "
        "where m.company_id = :c and m.status in ('pending_approval', 'posted') "
        "and (m.created_at at time zone :tz)::date >= :floor " + extra + " order by m.created_at"),
        {"c": str(ctx.company_id), "tz": ctx.timezone, "floor": since(ctx.today, ctx.number("days")),
         **(params or {})}).all())


def _journal_record(r: Any) -> Record:
    return Record(MANUAL, r.id, f"Manual journal {r.number}")


def _state(r: Any) -> str:
    return "is waiting for approval" if r.status == "pending_approval" else "has been posted"


@provides(INTEL_CHECK)
class LargeManualJournal(IntelCheck):
    """Manual journals above a value limit."""

    code = "finance.large_manual_journal"

    value_kind = "money"
    title = "Large manual journal"
    area = "controls"
    description = "A manual journal was written for more than the limit the business set for hand-made entries."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30, "limit": "100000.00"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        limit = ctx.number("limit")
        unit = currency(session, ctx.company_id)
        rows = _manual_rows(session, ctx, "and m.total >= cast(:limit as numeric)", {"limit": str(limit)})
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="high" if r.total >= 5 * limit else "medium",
            company_id=ctx.company_id, entity_type=MANUAL, entity_id=r.id, value=r.total, expected_value=limit,
            amount=r.total,
            summary=(f"Manual journal {r.number} for {unit} {money(r.total)} (\"{r.description}\"), written by "
                     f"{r.full_name or 'a user'}, {_state(r)}. The limit for hand-made entries is "
                     f"{unit} {money(limit)}."),
            recommended_action="Check the journal against its supporting papers.",
            records=(_journal_record(r),), figures={"total": str(r.total), "status": r.status}) for r in rows]


@provides(INTEL_CHECK)
class RoundManualJournal(IntelCheck):
    """Manual journals for round sums."""

    code = "finance.round_manual_journal"

    value_kind = "money"
    title = "Round-number manual journal"
    area = "controls"
    description = "A manual journal was written for a perfectly round amount, which real transactions rarely are."
    default_severity = "low"
    params: dict[str, Any] = {"days": 30, "round_unit": "1000.00", "min_amount": "10000.00"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        unit = currency(session, ctx.company_id)
        rows = _manual_rows(session, ctx, "and m.total >= cast(:min as numeric) "
                            "and m.total % cast(:round as numeric) = 0",
                            {"min": str(ctx.number("min_amount")), "round": str(ctx.number("round_unit"))})
        return [Candidate(
            fingerprint=fingerprint(self.code, r.id), severity="low", company_id=ctx.company_id,
            entity_type=MANUAL, entity_id=r.id, value=r.total, amount=r.total,
            summary=(f"Manual journal {r.number} for exactly {unit} {money(r.total)} (\"{r.description}\"), written by "
                     f"{r.full_name or 'a user'}, {_state(r)}."),
            recommended_action="Ask what the amount is based on and look at the supporting papers.",
            records=(_journal_record(r),), figures={"total": str(r.total), "status": r.status}) for r in rows]


@provides(INTEL_CHECK)
class OddHoursManualJournal(IntelCheck):
    """Manual journals written or posted at night."""

    code = "finance.odd_hours_manual_journal"
    title = "Manual journal at unusual hours"
    area = "controls"
    description = "A manual journal was created or posted late at night or very early in the morning."
    default_severity = "low"
    params: dict[str, Any] = {"days": 30, "start_hour": 22, "end_hour": 5}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        start, end = int(ctx.number("start_hour")), int(ctx.number("end_hour"))
        zone = ZoneInfo(ctx.timezone)

        def odd(moment: datetime | None) -> bool:
            if moment is None:
                return False
            hour = moment.astimezone(zone).hour
            return (start <= hour < end) if start <= end else (hour >= start or hour < end)

        unit = currency(session, ctx.company_id)
        found = []
        for r in _manual_rows(session, ctx):
            if not (odd(r.created_at) or odd(r.posted_at)):
                continue
            moment = r.created_at if odd(r.created_at) else r.posted_at
            what = "written" if moment is r.created_at else "posted"
            local = moment.astimezone(zone)
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="low", company_id=ctx.company_id,
                entity_type=MANUAL, entity_id=r.id, value=Decimal(local.hour), amount=r.total,
                summary=(f"Manual journal {r.number} for {unit} {money(r.total)} was {what} by "
                         f"{r.full_name or 'a user'} at {local:%H:%M} on {local.date()}, outside working hours."),
                recommended_action="Ask why the journal was done at that hour.",
                records=(_journal_record(r),), figures={"time": f"{local:%Y-%m-%d %H:%M}", "total": str(r.total)}))
        return found


@provides(INTEL_CHECK)
class SamePersonApproval(IntelCheck):
    """The same person prepared and approved a manual journal or an expense."""

    code = "finance.same_person_approval"
    title = "Prepared and approved by the same person"
    area = "controls"
    description = "One person both prepared and approved a manual journal or an expense."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        floor = since(ctx.today, ctx.number("days"))
        unit = currency(session, ctx.company_id)
        found = []
        journals = session.execute(text(
            "select m.id, m.number, m.total, u.full_name from finance.manual_journal m "
            "join kernel.app_user u on u.id = m.created_by where m.company_id = :c and m.status = 'posted' "
            "and m.approved_by = m.created_by and (m.created_at at time zone :tz)::date >= :floor "
            "order by m.created_at"),
            {"c": str(ctx.company_id), "tz": ctx.timezone, "floor": floor}).all()
        for r in journals:
            found.append(Candidate(
                fingerprint=fingerprint(self.code, MANUAL, r.id), severity="medium", company_id=ctx.company_id,
                entity_type=MANUAL, entity_id=r.id, amount=r.total,
                summary=(f"{r.full_name} both prepared and approved manual journal {r.number} for "
                         f"{unit} {money(r.total)}."),
                recommended_action="Have someone else review the journal.",
                records=(Record(MANUAL, r.id, f"Manual journal {r.number}"),), figures={"person": r.full_name}))
        expenses = session.execute(text(
            "select x.id, x.number, x.amount, x.branch_id, x.payee, u.full_name from finance.expense x "
            "join kernel.app_user u on u.id = x.created_by where x.company_id = :c "
            "and x.status in ('approved', 'posted') "
            "and x.approved_by = x.created_by and x.expense_date >= :floor order by x.expense_date, x.number"),
            {"c": str(ctx.company_id), "floor": floor}).all()
        for x in expenses:
            found.append(Candidate(
                fingerprint=fingerprint(self.code, "finance.expense", x.id), severity="medium",
                company_id=ctx.company_id, branch_id=ids(x.branch_id), entity_type="finance.expense", entity_id=x.id,
                amount=x.amount,
                summary=(f"{x.full_name} both prepared and approved expense {x.number} for {unit} {money(x.amount)}"
                         + (f" paid to {x.payee}." if x.payee else ".")),
                recommended_action="Have someone else review the expense and its receipt.",
                records=(Record("finance.expense", x.id, f"Expense {x.number}"),), figures={"person": x.full_name}))
        return found

