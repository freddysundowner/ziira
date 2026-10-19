"""Use cases: the timer. One per person; stopping it saves the time as an entry with its start and end.

    start -> running <-> paused -> stop (an entry, rounded as the company's timer rounding says) or discard
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from ziira.modules.timebilling.domain.timesheet import seconds_to_minutes
from ziira.modules.timebilling.permissions import TIME_LOG
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry, Timer
from ziira.modules.timebilling.services import access, common, entries
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, company_date_of, current_context


@dataclass
class TimerView:
    timer: Timer
    elapsed_seconds: int
    running: bool


def elapsed(timer: Timer, now: datetime | None = None) -> int:
    """Seconds the timer has counted: what was saved when it was paused, plus the current run."""
    now = now or datetime.now(UTC)
    extra = int((now - timer.resumed_at).total_seconds()) if timer.resumed_at else 0
    return timer.accumulated_seconds + max(extra, 0)


def view(timer: Timer) -> TimerView:
    return TimerView(timer, elapsed(timer), timer.resumed_at is not None)


def current(session: Session) -> TimerView | None:
    found = repo.timer_of(session, access.user_id())
    return view(found) if found else None


def start(session: Session, *, project_id: UUID, task: str | None = None, note: str | None = None,
          billable: bool = True, service_product_id: UUID | None = None) -> TimerView:
    """Start the timer on a project. You can run one timer at a time: stop or discard the first before starting another.
    Needs 'time.log'."""
    ctx = current_context()
    me = access.user_id()
    project = common.usable_project(session, project_id)
    ctx.require(TIME_LOG, company_id=project.company_id, branch_id=project.branch_id)
    if repo.timer_of(session, me, lock=True) is not None:
        raise Conflict("You already have a timer: stop or discard it first")
    now = datetime.now(UTC)
    timer = Timer(tenant_id=ctx.tenant_id, created_by=me, company_id=project.company_id, user_id=me,
                  project_id=project.id, task=(task or "").strip()[:120] or None,
                  note=(note or "").strip()[:entries.MAX_NOTE] or None, billable=billable,
                  service_product_id=service_product_id, started_at=now, resumed_at=now)
    repo.add(session, timer)
    audit_record(session, "start", "timebilling.timer", timer.id, {"project": project.code})
    return view(timer)


def _mine(session: Session) -> Timer:
    timer = repo.timer_of(session, access.user_id(), lock=True)
    if timer is None:
        raise NotFound("You have no timer running")
    return timer


def pause(session: Session) -> TimerView:
    timer = _mine(session)
    if timer.resumed_at is None:
        return view(timer)                                       # already paused: asking twice changes nothing
    timer.accumulated_seconds = elapsed(timer)
    timer.resumed_at = None
    session.flush()
    return view(timer)


def resume(session: Session) -> TimerView:
    timer = _mine(session)
    if timer.resumed_at is None:
        timer.resumed_at = datetime.now(UTC)
        session.flush()
    return view(timer)


def update(session: Session, *, task: str | None, note: str | None, billable: bool | None) -> TimerView:
    """Change the label of the running timer (task, note, billable)."""
    timer = _mine(session)
    if task is not None:
        timer.task = task.strip()[:120] or None
    if note is not None:
        timer.note = note.strip()[:entries.MAX_NOTE] or None
    if billable is not None:
        timer.billable = billable
    session.flush()
    return view(timer)


def discard(session: Session) -> None:
    timer = _mine(session)
    session.delete(timer)
    session.flush()
    audit_record(session, "discard", "timebilling.timer", timer.id, {"seconds": elapsed(timer)})


def stop(session: Session, *, minutes: int | None = None) -> Entry:
    """Stop the timer and save the time as an entry, rounded by the company's timer rounding. `minutes` replaces the
    counted time (when the person forgot to stop it). A timer that counted under a few seconds saves nothing."""
    timer = _mine(session)
    setting = common.settings(session, timer.company_id)
    counted = elapsed(timer)
    if minutes is None:
        minutes = seconds_to_minutes(counted, setting.timer_round_minutes, setting.timer_round_mode)
    if minutes <= 0:
        raise ValidationFailed("The timer has hardly run: discard it instead")
    if minutes > 1440:
        raise ValidationFailed("The timer has run for more than a day: give the minutes worked")
    ended = datetime.now(UTC)
    day = company_date_of(session, timer.company_id, timer.started_at)
    entry = entries.create_entry(
        session, project_id=timer.project_id, work_date=day, minutes=minutes, task=timer.task, note=timer.note,
        billable=timer.billable, service_product_id=timer.service_product_id, source="timer",
        started_at=timer.started_at, ended_at=ended)
    session.delete(timer)
    session.flush()
    audit_record(session, "stop", "timebilling.timer", timer.id, {"entry": entry.id, "minutes": minutes})
    return entry
