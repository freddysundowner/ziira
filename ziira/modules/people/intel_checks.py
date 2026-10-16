"""Intelligence checks over People data: payroll changes close to a run, attendance, overtime, approvals, pay jumps,
waiting leave, and runs left unpaid. All read only; every figure comes from records. Flags are questions to ask,
not accusations: each says what the records show and what to check."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text

from ziira.modules.intel.public import (
    INTEL_BASELINE_METRIC,
    INTEL_CHECK,
    BaselineMetric,
    Candidate,
    CheckContext,
    IntelCheck,
    Record,
    Sample,
    fingerprint,
    is_unusual,
)
from ziira.sdk import Session, provides

PAID_RUNS = "('approved', 'posted', 'paid')"
LIVE_RUNS = "('calculated', 'pending_approval', 'approved', 'posted', 'paid')"


def currency_of(session: Session, company_id: UUID) -> str:
    """The company's base currency code."""
    return str(session.execute(text("select base_currency from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def money(currency: str, value: Decimal) -> str:
    """'USD 1,250.00'-style text from the company's own currency code."""
    return f"{currency} {value:,.2f}"


def _run_label(r: Row[Any]) -> str:
    return f"Payroll {r.period_start} to {r.period_end}"


# --------------------------------------------------------------------------- changes just before a run
@provides(INTEL_CHECK)
class ChangesBeforePayroll(IntelCheck):
    """The ghost-employee pattern: someone added, or pay or payment details changed, just before a run."""

    code = "people.changes_before_payroll"

    value_kind = "money"
    title = "New people or pay changes just before payroll"
    area = "controls"
    description = ("An employee who was added, had their pay raised or changed, or had their bank or mobile money "
                   "details changed shortly before a payroll run that paid them.")
    default_severity = "high"
    params: dict[str, Any] = {"days": 14, "lookback_days": 90}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        window = int(ctx.number("days"))
        rows = session.execute(text(
            "select r.id as run_id, r.period_start, r.period_end, "
            "  r.created_at - make_interval(days => :w) as win_from, "
            "  coalesce(r.approved_at, r.submitted_at, r.created_at) as win_to, "
            "  p.employee_id, p.net_pay, p.branch_id, e.full_name, e.employee_no, e.created_at as emp_created "
            "from people.payroll_run r join people.payslip p on p.run_id = r.id "
            "join people.employee e on e.id = p.employee_id "
            f"where r.company_id = :c and r.status in {LIVE_RUNS} and p.net_pay > 0 "
            "and r.pay_date >= :since order by r.period_start, e.full_name"),
            {"c": str(ctx.company_id), "w": window,
             "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all()
        found: list[Candidate] = []
        for r in rows:
            reasons: list[str] = []
            records = [Record("people.payroll_run", r.run_id, _run_label(r)),
                       Record("people.employee", r.employee_id, f"{r.full_name} ({r.employee_no})")]
            figures: dict[str, str] = {}
            if r.win_from <= r.emp_created <= r.win_to:
                reasons.append(f"was added on {r.emp_created.date()}")
                figures["added"] = str(r.emp_created.date())
            else:
                terms = session.execute(text(
                    "select t.id, t.basic_pay, t.created_at, "
                    "  (select prev.basic_pay from people.employment_terms prev where prev.employee_id = t.employee_id "
                    "   and prev.approved_by is not null and not prev.rejected and prev.valid_from < t.valid_from "
                    "   order by prev.valid_from desc limit 1) as previous "
                    "from people.employment_terms t where t.employee_id = :e and t.approved_by is not null "
                    "and not t.rejected and t.created_at between :a and :b order by t.created_at desc limit 1"),
                    {"e": str(r.employee_id), "a": r.win_from, "b": r.win_to}).first()
                if terms is not None and terms.previous is not None:
                    reasons.append(f"had basic pay changed from {money(currency, terms.previous)} to "
                                   f"{money(currency, terms.basic_pay)} on {terms.created_at.date()}")
                    figures["basic_pay_before"], figures["basic_pay_after"] = str(terms.previous), str(terms.basic_pay)
                    records.append(Record("people.employment_terms", terms.id, f"Pay terms of {r.full_name}"))
                bank = session.execute(text(
                    "select b.id, b.valid_from, b.method from people.employee_bank_account b "
                    "where b.employee_id = :e and b.approved_by is not null and not b.rejected "
                    "and b.valid_from between :a and :b "
                    "and exists (select 1 from people.employee_bank_account o where o.employee_id = b.employee_id "
                    "  and o.id <> b.id and o.approved_by is not null and o.valid_from < b.valid_from) "
                    "order by b.valid_from desc limit 1"),
                    {"e": str(r.employee_id), "a": r.win_from, "b": r.win_to}).first()
                if bank is not None:
                    reasons.append(f"had payment details changed on {bank.valid_from.date()}")
                    figures["payment_details_changed"] = str(bank.valid_from.date())
                    records.append(Record("people.employee_bank_account", bank.id, f"Payment details of {r.full_name}"))
            if not reasons:
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.run_id, r.employee_id), severity="high",
                summary=(f"{r.full_name} {' and '.join(reasons)}, within {window} days of the payroll run for "
                         f"{r.period_start} to {r.period_end}, and was paid {money(currency, r.net_pay)} in it."),
                recommended_action="Confirm with the manager that this person and these details are genuine.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="people.employee",
                entity_id=r.employee_id, period_start=r.period_start, period_end=r.period_end,
                amount=r.net_pay, value=r.net_pay, records=tuple(records), figures=figures))
        return found


# --------------------------------------------------------------------------- paid, but no attendance or leave
@provides(INTEL_CHECK)
class PaidWithoutAttendance(IntelCheck):
    """Paid in a run, but nothing shows they worked or were on leave, in a business that records attendance."""

    code = "people.paid_without_attendance"
    title = "Paid with no attendance or leave"
    area = "people"
    description = ("An employee paid in a payroll run who has no attendance and no approved leave for that period, "
                   "while most other people paid in the same run do. Assumes the business uses attendance when at "
                   "least the stated share of those paid have records.")
    default_severity = "medium"
    params: dict[str, Any] = {"usage_pct": "50.0", "lookback_days": 90}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        runs = session.execute(text(
            "select id, period_start, period_end from people.payroll_run where company_id = :c "
            f"and status in {PAID_RUNS} and pay_date >= :since order by period_start"),
            {"c": str(ctx.company_id), "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all()
        found: list[Candidate] = []
        for run in runs:
            slips = session.execute(text(
                "select p.employee_id, p.gross_pay, p.net_pay, p.branch_id, e.full_name, e.employee_no, "
                "  exists (select 1 from people.attendance a where a.employee_id = p.employee_id "
                "          and a.work_date between :s and :e) as has_attendance, "
                "  exists (select 1 from people.leave_request l where l.employee_id = p.employee_id "
                "          and l.status = 'approved' and l.start_date <= :e and l.end_date >= :s) as has_leave "
                "from people.payslip p join people.employee e on e.id = p.employee_id "
                "where p.run_id = :r and p.net_pay > 0 order by e.full_name"),
                {"r": str(run.id), "s": run.period_start, "e": run.period_end}).all()
            if not slips:
                continue
            with_records = sum(1 for s in slips if s.has_attendance or s.has_leave)
            if Decimal(with_records) * 100 / len(slips) < ctx.number("usage_pct"):
                continue                                # the business does not seem to record attendance
            for s in slips:
                if s.has_attendance or s.has_leave:
                    continue
                found.append(Candidate(
                    fingerprint=fingerprint(self.code, run.id, s.employee_id), severity="medium",
                    summary=(f"{s.full_name} was paid {money(currency, s.gross_pay)} gross for {run.period_start} to "
                             f"{run.period_end}, but has no attendance and no approved leave for those dates, while "
                             f"{with_records} of {len(slips)} people paid in the same run do."),
                    recommended_action="Check that this person worked in the period, and add the missing attendance.",
                    company_id=ctx.company_id, branch_id=s.branch_id, entity_type="people.employee",
                    entity_id=s.employee_id, period_start=run.period_start, period_end=run.period_end,
                    amount=s.gross_pay, value=Decimal(0), expected_value=None,
                    records=(Record("people.payroll_run", run.id, f"Payroll {run.period_start} to {run.period_end}"),
                             Record("people.employee", s.employee_id, f"{s.full_name} ({s.employee_no})")),
                    figures={"gross_pay": str(s.gross_pay), "paid_with_records": f"{with_records} of {len(slips)}"}))
        return found


# --------------------------------------------------------------------------- unusual overtime
OVERTIME_METRIC = "people.overtime_hours"


@provides(INTEL_BASELINE_METRIC)
class OvertimeHoursMetric(BaselineMetric):
    """Overtime hours per day: each employee (key `e:<id>`) and each branch's total (key `b:<id>`)."""

    code = OVERTIME_METRIC
    title = "Daily overtime hours"

    def samples(self, session: Session, company_id: UUID, date_from: date, date_to: date) -> list[Sample]:
        params = {"c": str(company_id), "a": date_from, "b": date_to}
        people = session.execute(text(
            "select a.employee_id, a.work_date, sum(a.overtime_hours) as hours from people.attendance a "
            "join people.employee e on e.id = a.employee_id where e.company_id = :c "
            "and a.work_date between :a and :b group by a.employee_id, a.work_date"), params).all()
        branches = session.execute(text(
            "select a.branch_id, a.work_date, sum(a.overtime_hours) as hours from people.attendance a "
            "join people.employee e on e.id = a.employee_id where e.company_id = :c and a.branch_id is not null "
            "and a.work_date between :a and :b group by a.branch_id, a.work_date"), params).all()
        return ([Sample(f"e:{r.employee_id}", Decimal(r.hours)) for r in people]
                + [Sample(f"b:{r.branch_id}", Decimal(r.hours)) for r in branches])


@provides(INTEL_CHECK)
class UnusualOvertime(IntelCheck):
    """Overtime far above what the person (or the branch) normally works."""

    code = "people.unusual_overtime"
    title = "Unusual overtime"
    area = "people"
    description = "Overtime hours on a recent day that are far above the employee's or the branch's own normal."
    default_severity = "medium"
    params: dict[str, Any] = {"recent_days": 3, "min_hours": "2.0"}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("recent_days")) - 1)
        floor = ctx.number("min_hours")
        found: list[Candidate] = []
        for r in session.execute(text(
                "select a.id, a.employee_id, a.work_date, a.overtime_hours, a.branch_id, e.full_name, e.employee_no "
                "from people.attendance a join people.employee e on e.id = a.employee_id "
                "where e.company_id = :c and a.work_date between :a and :b and a.overtime_hours >= :m "
                "order by a.work_date, e.full_name"),
                {"c": str(ctx.company_id), "a": since, "b": ctx.today, "m": floor}).all():
            base = ctx.baseline(OVERTIME_METRIC, f"e:{r.employee_id}")
            if base is None or not is_unusual(r.overtime_hours, base):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, "employee", r.employee_id, r.work_date), severity="medium",
                summary=(f"{r.full_name} worked {r.overtime_hours} hours of overtime on {r.work_date}; their usual "
                         f"is about {base.mean:.1f} hours a day."),
                recommended_action="Ask the manager whether this overtime was needed and approved.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="people.employee",
                entity_id=r.employee_id, period_start=r.work_date, period_end=r.work_date, value=r.overtime_hours,
                expected_value=base.mean.quantize(Decimal("0.01")),
                records=(Record("people.attendance", r.id, f"Attendance of {r.full_name} on {r.work_date}"),
                         Record("people.employee", r.employee_id, f"{r.full_name} ({r.employee_no})")),
                figures={"overtime_hours": str(r.overtime_hours), "usual_hours": f"{base.mean:.1f}"}))
        for b in session.execute(text(
                "select a.branch_id, a.work_date, sum(a.overtime_hours) as hours, max(br.name) as branch_name "
                "from people.attendance a join people.employee e on e.id = a.employee_id "
                "join kernel.branch br on br.id = a.branch_id "
                "where e.company_id = :c and a.work_date between :a and :b "
                "group by a.branch_id, a.work_date order by a.work_date"),
                {"c": str(ctx.company_id), "a": since, "b": ctx.today}).all():
            base = ctx.baseline(OVERTIME_METRIC, f"b:{b.branch_id}")
            if b.hours < floor or base is None or not is_unusual(Decimal(b.hours), base):
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, "branch", b.branch_id, b.work_date), severity="medium",
                summary=(f"{b.branch_name} recorded {b.hours} hours of overtime on {b.work_date}; its usual is about "
                         f"{base.mean:.1f} hours a day."),
                recommended_action="Ask the branch manager why so much overtime was needed.",
                company_id=ctx.company_id, branch_id=b.branch_id, entity_type="kernel.branch", entity_id=b.branch_id,
                period_start=b.work_date, period_end=b.work_date, value=Decimal(b.hours),
                expected_value=base.mean.quantize(Decimal("0.01")),
                figures={"overtime_hours": str(b.hours), "usual_hours": f"{base.mean:.1f}"}))
        return found


# --------------------------------------------------------------------------- pay approved by the person who proposed it
@provides(INTEL_CHECK)
class PayApprovedBySameUser(IntelCheck):
    """Pay terms or payment details proposed and approved by one person (the app refuses it, the data may show it)."""

    code = "people.pay_self_approved"
    title = "Pay changes approved by the person who proposed them"
    area = "controls"
    description = "Pay terms or salary payment details where the person who proposed them is also the one who approved."
    default_severity = "high"
    params: dict[str, Any] = {"lookback_days": 90}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        since = ctx.today - timedelta(days=int(ctx.number("lookback_days")))
        currency = currency_of(session, ctx.company_id)
        found: list[Candidate] = []
        for t in session.execute(text(
                "select t.id, t.employee_id, t.basic_pay, t.created_at, e.full_name, e.branch_id, u.full_name as who "
                "from people.employment_terms t join people.employee e on e.id = t.employee_id "
                "join kernel.app_user u on u.id = t.approved_by "
                "where e.company_id = :c and t.approved_by is not null and t.approved_by = t.created_by "
                "and t.created_at::date >= :s order by t.created_at"), {"c": str(ctx.company_id), "s": since}).all():
            found.append(Candidate(
                fingerprint=fingerprint(self.code, "terms", t.id), severity="high",
                summary=(f"Basic pay of {money(currency, t.basic_pay)} for {t.full_name} was proposed and approved by "
                         f"the same person, {t.who}, on {t.created_at.date()}."),
                recommended_action="Have a second person review this pay change.",
                company_id=ctx.company_id, branch_id=t.branch_id, entity_type="people.employee",
                entity_id=t.employee_id,
                amount=t.basic_pay, records=(Record("people.employment_terms", t.id, f"Pay terms of {t.full_name}"),),
                figures={"approver": t.who, "basic_pay": str(t.basic_pay)}))
        for b in session.execute(text(
                "select b.id, b.employee_id, b.created_at, e.full_name, e.branch_id, u.full_name as who "
                "from people.employee_bank_account b join people.employee e on e.id = b.employee_id "
                "join kernel.app_user u on u.id = b.approved_by "
                "where e.company_id = :c and b.approved_by is not null and b.approved_by = b.created_by "
                "and b.created_at::date >= :s order by b.created_at"), {"c": str(ctx.company_id), "s": since}).all():
            found.append(Candidate(
                fingerprint=fingerprint(self.code, "bank", b.id), severity="high",
                summary=(f"Salary payment details for {b.full_name} were proposed and approved by the same person, "
                         f"{b.who}, on {b.created_at.date()}."),
                recommended_action="Have a second person confirm these payment details with the employee.",
                company_id=ctx.company_id, branch_id=b.branch_id, entity_type="people.employee",
                entity_id=b.employee_id,
                records=(Record("people.employee_bank_account", b.id, f"Payment details of {b.full_name}"),),
                figures={"approver": b.who}))
        return found


# --------------------------------------------------------------------------- pay jumps without a recorded reason
@provides(INTEL_CHECK)
class PayJumpWithoutChange(IntelCheck):
    """Gross pay moved a lot since the previous run, and no pay change, pay item, absence or overtime explains it."""

    code = "people.pay_jump_unexplained"

    value_kind = "money"
    title = "Pay changed with no recorded reason"
    area = "people"
    description = ("An employee's gross pay changed by more than the set percentage from the previous run, with no "
                   "pay-terms change, pay-item change, part-month, unpaid leave or overtime recorded to explain it.")
    default_severity = "medium"
    params: dict[str, Any] = {"percent": "20.0", "lookback_days": 90}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = currency_of(session, ctx.company_id)
        limit = ctx.number("percent")
        rows = session.execute(text(
            "select r.id as run_id, r.period_start, r.period_end, p.id as slip_id, p.employee_id, p.gross_pay, "
            "  p.branch_id, p.detail, e.full_name, e.employee_no, "
            "  q.gross_pay as prev_gross, q.detail as prev_detail, q.period_start as prev_start "
            "from people.payroll_run r join people.payslip p on p.run_id = r.id "
            "join people.employee e on e.id = p.employee_id "
            "join lateral (select ps.gross_pay, ps.detail, pr.period_start from people.payslip ps "
            "  join people.payroll_run pr on pr.id = ps.run_id where ps.employee_id = p.employee_id "
            f"  and pr.status in {PAID_RUNS} and pr.period_start < r.period_start order by pr.period_start desc "
            "  limit 1) q on true "
            f"where r.company_id = :c and r.status in {PAID_RUNS} and r.pay_date >= :since and q.gross_pay > 0 "
            "order by r.period_start, e.full_name"),
            {"c": str(ctx.company_id), "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all()
        found: list[Candidate] = []
        for r in rows:
            change = (r.gross_pay - r.prev_gross) * 100 / r.prev_gross
            if abs(change) <= limit or _explained_by_detail(r.detail, r.prev_detail):
                continue
            recorded = session.execute(text(
                "select exists (select 1 from people.employment_terms t where t.employee_id = :e "
                "  and t.approved_by is not null and not t.rejected and t.valid_from > :a and t.valid_from <= :b) "
                "or exists (select 1 from people.employee_pay_item i where i.employee_id = :e "
                "  and ((i.valid_from > :a and i.valid_from <= :b) or (i.valid_to >= :a and i.valid_to < :b) "
                "       or (i.created_at::date > :a and i.created_at::date <= :b)))"),
                {"e": str(r.employee_id), "a": r.prev_start, "b": r.period_end}).scalar_one()
            if recorded:
                continue
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.run_id, r.employee_id), severity="medium",
                summary=(f"Gross pay for {r.full_name} was {money(currency, r.gross_pay)} for {r.period_start} to "
                         f"{r.period_end}, {abs(change):.1f}% {'up' if change > 0 else 'down'} on "
                         f"{money(currency, r.prev_gross)} last time, and no pay change is recorded."),
                recommended_action="Check why the pay differs and record the change if it is genuine.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="people.employee",
                entity_id=r.employee_id, period_start=r.period_start, period_end=r.period_end, value=r.gross_pay,
                expected_value=r.prev_gross, amount=abs(r.gross_pay - r.prev_gross),
                records=(Record("people.payslip", r.slip_id, f"Payslip of {r.full_name}, {r.period_start}"),
                         Record("people.payroll_run", r.run_id, f"Payroll {r.period_start} to {r.period_end}"),
                         Record("people.employee", r.employee_id, f"{r.full_name} ({r.employee_no})")),
                figures={"gross_pay": str(r.gross_pay), "previous_gross_pay": str(r.prev_gross),
                         "change_percent": f"{change:.1f}"}))
        return found


def _explained_by_detail(*details: dict[str, Any] | None) -> bool:
    """True when a payslip's own detail shows a part month, unpaid leave or overtime (so pay should differ)."""
    for d in details:
        d = d or {}
        if int(d.get("days_worked", 0) or 0) < int(d.get("days_in_period", 0) or 0):
            return True
        if Decimal(str(d.get("unpaid_leave_days", 0) or 0)) > 0 or Decimal(str(d.get("overtime_hours", 0) or 0)) > 0:
            return True
    return False


# --------------------------------------------------------------------------- leave waiting for a decision
@provides(INTEL_CHECK)
class LeaveWaiting(IntelCheck):
    """Leave requests left undecided for days."""

    code = "people.leave_waiting"

    value_kind = "days"
    title = "Leave requests waiting too long"
    area = "people"
    description = "A leave request that has been waiting for a decision for more days than the limit."
    default_severity = "low"
    params: dict[str, Any] = {"days": 5, "lookback_days": 180}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        waited = int(ctx.number("days"))
        found: list[Candidate] = []
        for r in session.execute(text(
                "select l.id, l.start_date, l.end_date, l.days, (l.created_at at time zone :tz)::date as asked_on, "
                "  e.id as employee_id, e.full_name, "
                "  e.branch_id, t.name as leave_type "
                "from people.leave_request l join people.employee e on e.id = l.employee_id "
                "join people.leave_type t on t.id = l.leave_type_id "
                "where e.company_id = :c and l.status = 'pending' and (l.created_at at time zone :tz)::date <= :cut "
                "and (l.created_at at time zone :tz)::date >= :since order by l.created_at"),
                {"c": str(ctx.company_id), "tz": ctx.timezone, "cut": ctx.today - timedelta(days=waited),
                 "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all():
            asked = (ctx.today - r.asked_on).days
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id), severity="low",
                summary=(f"{r.full_name} asked for {r.days} days of {r.leave_type} leave ({r.start_date} to "
                         f"{r.end_date}) {asked} days ago and nobody has decided."),
                recommended_action="Approve or reject the leave request.",
                company_id=ctx.company_id, branch_id=r.branch_id, entity_type="people.leave_request", entity_id=r.id,
                period_start=r.start_date, period_end=r.end_date, value=Decimal(asked), expected_value=Decimal(waited),
                records=(Record("people.leave_request", r.id, f"Leave of {r.full_name}, {r.start_date}"),),
                figures={"days_waiting": str(asked), "leave_days": str(r.days)}))
        return found


# --------------------------------------------------------------------------- runs left behind
@provides(INTEL_CHECK)
class PayrollOverdue(IntelCheck):
    """A payroll run still not approved, or approved but not paid, days after its pay date."""

    code = "people.payroll_overdue"

    value_kind = "days"
    title = "Payroll not finished after the pay date"
    area = "people"
    description = "A payroll run that is still unapproved, or approved but unpaid, several days after its pay date."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 3, "lookback_days": 120}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        limit = int(ctx.number("days"))
        currency = currency_of(session, ctx.company_id)
        found: list[Candidate] = []
        for r in session.execute(text(
                "select id, period_start, period_end, pay_date, status, "
                "  coalesce(nullif(totals->>'net_pay', '')::numeric, 0) as net "
                "from people.payroll_run where company_id = :c "
                "and status in ('draft', 'calculated', 'pending_approval', 'approved', 'posted') "
                "and pay_date < :cut and pay_date >= :since order by pay_date"),
                {"c": str(ctx.company_id), "cut": ctx.today - timedelta(days=limit),
                 "since": ctx.today - timedelta(days=int(ctx.number("lookback_days")))}).all():
            late = (ctx.today - r.pay_date).days
            unpaid = r.status in ("approved", "posted")
            what = "approved but not paid" if unpaid else f"not yet approved (it is {r.status.replace('_', ' ')})"
            found.append(Candidate(
                fingerprint=fingerprint(self.code, r.id, "unpaid" if unpaid else "unapproved"),
                severity="high" if unpaid else "medium",
                summary=(f"The payroll run for {r.period_start} to {r.period_end} was due on {r.pay_date} and is "
                         f"still {what}, {late} days late. Net pay of {money(currency, Decimal(r.net))} is waiting."),
                recommended_action="Approve and pay the run, or cancel it if it is no longer needed.",
                company_id=ctx.company_id, entity_type="people.payroll_run", entity_id=r.id,
                period_start=r.period_start, period_end=r.period_end, value=Decimal(late),
                expected_value=Decimal(limit), amount=Decimal(r.net) if r.net else None,
                records=(Record("people.payroll_run", r.id, f"Payroll {r.period_start} to {r.period_end}"),),
                figures={"status": r.status, "pay_date": str(r.pay_date), "days_late": str(late)}))
        return found
