"""Use cases: a person's week of time, submitted and approved by someone else.

    week: draft -> submitted -> approved          submitted -> rejected (back to the person) -> submitted again
                                                  approved -> draft again if a manager reopens it (nothing invoiced)

Separation of duties: nobody approves their own week. With `approval_required` off in the settings a submitted week is
approved at once. If the company has an approval rule for documents of type `timesheet` the kernel's approval inbox
decides (and `approval.decided` carries out its answer); with no rule, a person with 'time.approve' approves directly.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from ziira.modules.timebilling.domain import timesheet
from ziira.modules.timebilling.permissions import TIME_APPROVE, TIME_LOG, TIME_VIEW
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry, Expense, Week
from ziira.modules.timebilling.services import access, common, rate_cards, retainers
from ziira.sdk import (
    Conflict,
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    files,
    publish,
    submit_for_approval,
)

DOC_TYPE = "timesheet"


@dataclass
class WeekView:
    company_id: UUID
    user_id: UUID
    week_start: date
    week: Week | None
    entries: list[Entry]
    expenses: list[Expense]

    @property
    def status(self) -> str:
        return self.week.status if self.week else "draft"

    @property
    def minutes(self) -> int:
        return sum(e.minutes for e in self.entries)

    @property
    def billable_minutes(self) -> int:
        return sum(e.minutes for e in self.entries if e.billable)


def ensure_open(session: Session, company_id: UUID, user_id: UUID, day: date, starts_on: int) -> None:
    """Refuse to change time in a week that is submitted or approved."""
    start = timesheet.week_start(day, starts_on)
    week = repo.week_of(session, company_id, user_id, start)
    if week is not None and week.status in ("submitted", "approved"):
        raise Conflict(f"The week of {start.isoformat()} has been {week.status}: ask for it to be sent back first")


def view_week(session: Session, company_id: UUID, user_id: UUID, week_start: date) -> WeekView:
    """A person's week: their own, or anyone's where you hold 'time.view'."""
    me = access.user_id()
    ctx = current_context()
    may_see_others = ctx.can(TIME_VIEW, company_id=company_id) or ctx.can(TIME_APPROVE, company_id=company_id)
    if user_id != me and not may_see_others:
        raise NotFound("Week not found")
    if not access.can_see_company(company_id):
        raise NotFound("Week not found")
    setting = common.settings(session, company_id)
    start = timesheet.week_start(week_start, setting.week_starts_on)
    end = start + timedelta(days=6)
    return WeekView(company_id, user_id, start, repo.week_of(session, company_id, user_id, start),
                    repo.entries_of_week(session, company_id, user_id, start, end),
                    repo.expenses_of_week(session, company_id, user_id, start, end))


def _locked_view(session: Session, company_id: UUID, user_id: UUID, start: date) -> WeekView:
    week = repo.week_of(session, company_id, user_id, start, lock=True)
    end = start + timedelta(days=6)
    return WeekView(company_id, user_id, start, week, repo.entries_of_week(session, company_id, user_id, start, end),
                    repo.expenses_of_week(session, company_id, user_id, start, end))


def submit_week(session: Session, company_id: UUID, week_start: date) -> Week:
    """Send your week for approval. Needs 'time.log'. Every entry and expense of the week goes with it."""
    me = access.user_id()
    ctx = current_context()
    setting = common.settings(session, company_id)
    start = timesheet.week_start(week_start, setting.week_starts_on)
    view = _locked_view(session, company_id, me, start)
    for branch in {e.branch_id for e in view.entries} | {x.branch_id for x in view.expenses} or {None}:
        ctx.require(TIME_LOG, company_id=company_id, branch_id=branch)
    week = view.week
    if week is not None and week.status in ("submitted", "approved"):
        raise Conflict(f"This week is already {week.status}")
    if not view.entries and not view.expenses:
        raise ValidationFailed("There is nothing to submit: log some time first")
    _require_receipts(session, setting, view.expenses)
    if start + timedelta(days=6) >= common.today(session, company_id) + timedelta(days=7):
        raise ValidationFailed("That week is too far ahead to submit")
    if week is None:
        week = Week(tenant_id=ctx.tenant_id, created_by=me, company_id=company_id, user_id=me, week_start=start)
        repo.add(session, week)
    week.status, week.submitted_at, week.minutes = "submitted", datetime.now(UTC), view.minutes
    week.decided_by = week.decided_at = week.decision_note = None
    week.approval_pending = False
    for e in view.entries:
        e.status, e.week_id = "submitted", week.id
    for x in view.expenses:
        x.status, x.week_id = "submitted", week.id
    session.flush()
    audit_record(session, "submit", "timebilling.week", week.id, {"week_start": start, "minutes": week.minutes})
    if not setting.approval_required:
        _approve(session, week, None, "No approval needed")
        return week
    outcome = submit_for_approval(session, company_id=company_id, doc_type=DOC_TYPE, doc_id=week.id,
                                  amount=timesheet.hours(week.minutes))
    week.approval_pending = outcome == "pending"
    session.flush()
    return week


def _require_receipts(session: Session, setting: Any, spent: list[Expense]) -> None:
    """Expenses of the amount the company asks a receipt for must have one before the week goes in."""
    limit = setting.receipt_required_above
    if limit is None:
        return
    big = [x for x in spent if x.amount >= limit]
    if not big:
        return
    have = files.counts(session, "timebilling.expense", [x.id for x in big])
    missing = [x.description for x in big if not have.get(x.id)]
    if missing:
        raise ValidationFailed("Add a receipt first for: " + ", ".join(m[:40] for m in missing[:5]))


def _load(session: Session, week_id: UUID) -> Week:
    week = repo.get(session, Week, week_id, lock=True)
    if week is None or not access.can_see_company(week.company_id):
        raise NotFound("Week not found")
    return week


def _check_approver(session: Session, week: Week) -> None:
    ctx = current_context()
    me = access.user_id()
    if me == week.user_id:
        raise Forbidden("You cannot approve your own time: someone else has to")
    branches = set(session.scalars(select(Entry.branch_id).where(Entry.week_id == week.id).distinct()))
    if not branches:
        branches = {None}
    for b in branches:
        ctx.require(TIME_APPROVE, company_id=week.company_id, branch_id=b)


def approve_week(session: Session, week_id: UUID, note: str | None = None) -> Week:
    """Approve a submitted week (not your own). Needs 'time.approve'. Rates are fixed at this moment, billable time on a
    retainer project is drawn down, and the time becomes billable work."""
    week = _load(session, week_id)
    _check_approver(session, week)
    if week.status != "submitted":
        raise Conflict(f"This week is {week.status}")
    if week.approval_pending:
        raise Conflict("This week is waiting for a decision in the approvals inbox")
    _approve(session, week, access.user_id(), note)
    return week


def _approve(session: Session, week: Week, approver: UUID | None, note: str | None) -> None:
    now = datetime.now(UTC)
    pricer = rate_cards.Pricer(session, week.company_id)
    entries = list(session.scalars(select(Entry).where(Entry.week_id == week.id).order_by(Entry.work_date)))
    for e in entries:
        e.bill_rate, e.cost_rate = pricer.bill_rate(e), pricer.cost_rate(e)
        e.status, e.approved_by, e.approved_at = "approved", approver, now
        session.flush()
        retainers.apply_to_entry(session, e)
    for x in session.scalars(select(Expense).where(Expense.week_id == week.id)):
        x.status, x.approved_by, x.approved_at = "approved", approver, now
    week.status, week.decided_by, week.decided_at = "approved", approver, now
    week.decision_note = (note or "").strip()[:500] or None
    week.approval_pending = False
    session.flush()
    audit_record(session, "approve", "timebilling.week", week.id, {"approver": approver, "minutes": week.minutes})
    publish(session, Event("timesheet.approved", "timebilling.week", week.id, {
        "company_id": week.company_id, "user_id": week.user_id, "week_start": week.week_start,
        "minutes": week.minutes, "billable_minutes": sum(e.minutes for e in entries if e.billable)}))


def reject_week(session: Session, week_id: UUID, note: str) -> Week:
    """Send a submitted week back to its person with a reason (not your own). Needs 'time.approve'."""
    week = _load(session, week_id)
    _check_approver(session, week)
    if week.status != "submitted":
        raise Conflict(f"This week is {week.status}")
    if week.approval_pending:
        raise Conflict("This week is waiting for a decision in the approvals inbox")
    if not note.strip():
        raise ValidationFailed("Say what needs changing")
    _reject(session, week, access.user_id(), note)
    return week


def _reject(session: Session, week: Week, decider: UUID | None, note: str | None) -> None:
    for e in session.scalars(select(Entry).where(Entry.week_id == week.id)):
        e.status = "draft"
    for x in session.scalars(select(Expense).where(Expense.week_id == week.id)):
        x.status = "draft"
    week.status, week.decided_by, week.decided_at = "rejected", decider, datetime.now(UTC)
    week.decision_note = (note or "").strip()[:500] or None
    week.approval_pending = False
    session.flush()
    audit_record(session, "reject", "timebilling.week", week.id, {"by": decider, "note": week.decision_note})
    publish(session, Event("timesheet.rejected", "timebilling.week", week.id, {
        "company_id": week.company_id, "user_id": week.user_id, "week_start": week.week_start,
        "note": week.decision_note}))


def recall_week(session: Session, week_id: UUID) -> Week:
    """Take back your own submitted week to change it (not once it is approved)."""
    week = _load(session, week_id)
    if week.user_id != access.user_id():
        raise Forbidden("This is not your week")
    if week.status != "submitted":
        raise Conflict("Only a submitted week can be taken back")
    if week.approval_pending:
        raise Conflict("This week is already with the approvers")
    _reject(session, week, None, "Taken back by the person")
    week.status = "draft"
    return week


def reopen_week(session: Session, week_id: UUID, note: str) -> Week:
    """Reopen an approved week (not your own) that nothing has been invoiced from, so it can be corrected. Needs
    'time.approve'. Retainer minutes used come back."""
    week = _load(session, week_id)
    _check_approver(session, week)
    if week.status != "approved":
        raise Conflict("Only an approved week can be reopened")
    if not note.strip():
        raise ValidationFailed("Say why the week is reopened")
    entries = list(session.scalars(select(Entry).where(Entry.week_id == week.id)))
    expenses = list(session.scalars(select(Expense).where(Expense.week_id == week.id)))
    if any(e.batch_id or e.invoice_id for e in entries) or any(x.batch_id or x.invoice_id for x in expenses):
        raise Conflict("Some of this time is on an invoice or in an invoice review: take it off first")
    for e in entries:
        retainers.release_entry(session, e)
        e.status, e.bill_rate, e.cost_rate, e.approved_by, e.approved_at = "draft", None, None, None, None
    for x in expenses:
        x.status, x.approved_by, x.approved_at = "draft", None, None
    week.status, week.decision_note = "draft", note.strip()[:500]
    session.flush()
    audit_record(session, "reopen", "timebilling.week", week.id, {"note": note.strip()})
    return week


def apply_decision(session: Session, week_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Carry out the answer of the approvals inbox (event `approval.decided` for a timesheet)."""
    week = repo.get(session, Week, week_id, lock=True)
    if week is None or week.status != "submitted":
        return
    if approved:
        if decided_by is not None and decided_by == week.user_id:
            _reject(session, week, decided_by, "A person cannot approve their own time")
            return
        _approve(session, week, decided_by, "Approved in the approvals inbox")
    else:
        _reject(session, week, decided_by, "Not approved in the approvals inbox")


def list_weeks(session: Session, *, status: str | None = None, user_id: UUID | None = None,
               company_id: UUID | None = None, limit: int = 100, offset: int = 0) -> list[Week]:
    """Weeks you may see: your own, and everyone's where you hold 'time.view' or 'time.approve'."""
    me = access.user_id()
    scopes = access.scopes_for(TIME_VIEW, TIME_APPROVE)
    from sqlalchemy import or_

    q = select(Week).where(or_(Week.user_id == me, repo.in_scope(scopes, Week.company_id, None)))
    if status:
        q = q.where(Week.status == status)
    if user_id:
        q = q.where(Week.user_id == user_id)
    if company_id:
        q = q.where(Week.company_id == company_id)
    return list(session.scalars(q.order_by(Week.week_start.desc(), Week.created_at.desc())
                                .limit(min(limit, 200)).offset(offset)))


def week_minutes(session: Session, week_id: UUID) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(Entry.minutes), 0)).where(Entry.week_id == week_id)) or 0)


def hours_of(minutes: int) -> Decimal:
    return timesheet.hours(minutes)

