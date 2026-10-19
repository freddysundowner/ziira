"""Use cases: retainers (prepaid hours or a monthly fee) and drawing time down from them.

    hours retainer       balance in minutes; approved billable time on the project uses the balance first and only the
                         overage is billed; a top-up is billed with an invoice review line and adds to the balance when
                         the invoice is issued; unused minutes expire on the expiry date.
    monthly-fee retainer all the project's billable time is covered; the fee is billed once per month (review screen).

Every change to a balance is a row in `retainer_txn` (never edited), so the balance can be re-added from its history.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from ziira.modules.timebilling.domain import retainer as rules
from ziira.modules.timebilling.permissions import PROJECTS_MANAGE
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Entry, Project, Retainer, RetainerTxn
from ziira.modules.timebilling.services import access, common
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, current_context


def _txn(session: Session, retainer: Retainer, kind: str, minutes: int, day: date, *, amount: Decimal | None = None,
         entry_id: UUID | None = None, batch_id: UUID | None = None, period: str | None = None,
         note: str | None = None) -> RetainerTxn:
    row = RetainerTxn(tenant_id=current_context().tenant_id, created_by=current_context().user_id,
                      retainer_id=retainer.id, kind=kind, minutes=minutes, amount=amount, entry_id=entry_id,
                      batch_id=batch_id, period=period, occurred_on=day, note=note)
    repo.add(session, row)
    return row


def create_retainer(session: Session, project_id: UUID, *, kind: str, monthly_fee: Decimal | None = None,
                    expires_on: date | None = None, alert_percent: int = 80, opening_minutes: int = 0,
                    note: str | None = None, bill_day: int = 1, auto_draft: bool = True) -> Retainer:
    """Start a retainer on a project whose billing is 'retainer'. `opening_minutes` is a prepaid balance already paid
    for outside Ziira. Needs 'projects.manage'."""
    project = repo.get(session, Project, project_id)
    if project is None or not access.can_see_company(project.company_id):
        raise NotFound("Project not found")
    ctx = current_context()
    ctx.require(PROJECTS_MANAGE, company_id=project.company_id, branch_id=project.branch_id)
    if project.billing_mode != "retainer":
        raise ValidationFailed("Set the project's billing to retainer first")
    if kind not in ("hours", "monthly_fee"):
        raise ValidationFailed("A retainer is prepaid hours or a monthly fee")
    if kind == "monthly_fee" and (monthly_fee is None or monthly_fee <= 0):
        raise ValidationFailed("Give the monthly fee")
    if opening_minutes < 0 or (kind == "monthly_fee" and opening_minutes):
        raise ValidationFailed("Only an hours retainer has a prepaid balance")
    if repo.active_retainer(session, project.id) is not None:
        raise Conflict("This project already has an active retainer: close it first")
    row = Retainer(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=project.company_id,
                   project_id=project.id, kind=kind, monthly_fee=monthly_fee if kind == "monthly_fee" else None,
                   expires_on=expires_on, alert_percent=alert_percent, note=(note or "").strip()[:500] or None,
                   bill_day=bill_day, auto_draft=auto_draft)
    repo.add(session, row)
    if opening_minutes:
        add_minutes(session, row, opening_minutes, common.today(session, project.company_id), note="Opening balance")
    audit_record(session, "create", "timebilling.retainer", row.id, {"project": project.code, "kind": kind})
    return row


def add_minutes(session: Session, retainer: Retainer, minutes: int, day: date, *, amount: Decimal | None = None,
                batch_id: UUID | None = None, note: str | None = None) -> None:
    """Add prepaid minutes to an hours retainer (a paid top-up, or an opening balance)."""
    if retainer.kind != "hours" or minutes <= 0:
        raise ValidationFailed("Only an hours retainer takes prepaid hours, and it must be more than none")
    retainer.balance_minutes += minutes
    retainer.topped_up_minutes += minutes
    session.flush()
    _txn(session, retainer, "topup", minutes, day, amount=amount, batch_id=batch_id, note=note)


def update_retainer(session: Session, retainer_id: UUID, **changes: Any) -> Retainer:
    """Change expiry, alert level, fee or note, or close the retainer (`status = closed`). Needs 'projects.manage'."""
    row = repo.get(session, Retainer, retainer_id, lock=True)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Retainer not found")
    current_context().require(PROJECTS_MANAGE, company_id=row.company_id)
    if changes.get("status") not in (None, "active", "closed"):
        raise ValidationFailed("A retainer is active or closed")
    if changes.get("status") == "active" and row.status == "closed" and repo.active_retainer(
            session, row.project_id) is not None:
        raise Conflict("This project already has an active retainer")
    for key in ("expires_on", "alert_percent", "monthly_fee", "note", "status", "bill_day", "auto_draft"):
        if key in changes and (changes[key] is not None or key in ("expires_on", "note")):
            setattr(row, key, changes[key])
    row.updated_by = current_context().user_id
    session.flush()
    audit_record(session, "update", "timebilling.retainer", row.id, {k: str(v) for k, v in changes.items()})
    return row


def get_retainer(session: Session, retainer_id: UUID) -> Retainer:
    row = repo.get(session, Retainer, retainer_id)
    if row is None or not access.can_see_company(row.company_id):
        raise NotFound("Retainer not found")
    return row


def list_retainers(session: Session, *, company_id: UUID | None = None, project_id: UUID | None = None,
                   status: str | None = None) -> list[Retainer]:
    from ziira.modules.timebilling.permissions import ALL

    q = select(Retainer).where(repo.in_scope(access.scopes_for(*ALL), Retainer.company_id, None))
    if company_id:
        q = q.where(Retainer.company_id == company_id)
    if project_id:
        q = q.where(Retainer.project_id == project_id)
    if status:
        q = q.where(Retainer.status == status)
    return list(session.scalars(q.order_by(Retainer.status, Retainer.created_at.desc())))


def list_txns(session: Session, retainer_id: UUID) -> list[RetainerTxn]:
    get_retainer(session, retainer_id)
    return list(session.scalars(select(RetainerTxn).where(RetainerTxn.retainer_id == retainer_id)
                                .order_by(RetainerTxn.occurred_on.desc(), RetainerTxn.created_at.desc())))


# --------------------------------------------------------------------------- drawing time down
def apply_to_entry(session: Session, entry: Entry) -> None:
    """Called when an entry is approved: billable time on a retainer project is covered by the retainer."""
    if not entry.billable:
        return
    retainer = repo.active_retainer(session, entry.project_id, lock=True)
    if retainer is None:
        return
    if retainer.kind == "monthly_fee":
        entry.retainer_minutes = entry.minutes
        return
    if rules.is_expired(retainer.expires_on, entry.work_date):
        return
    taken = rules.draw_down(retainer.balance_minutes, entry.minutes)
    if taken.covered == 0:
        return
    retainer.balance_minutes = taken.balance_after
    entry.retainer_minutes = taken.covered
    session.flush()
    _txn(session, retainer, "drawdown", -taken.covered, entry.work_date, entry_id=entry.id)


def release_entry(session: Session, entry: Entry) -> None:
    """Called when an approved entry goes back to draft: the minutes it used return to the balance."""
    if entry.retainer_minutes <= 0:
        return
    retainer = repo.active_retainer(session, entry.project_id, lock=True)
    if retainer is not None and retainer.kind == "hours":
        retainer.balance_minutes += entry.retainer_minutes
        session.flush()
        _txn(session, retainer, "release", entry.retainer_minutes, common.today(session, entry.company_id),
             entry_id=entry.id)
    entry.retainer_minutes = 0


def expire_due(session: Session, company_id: UUID, day: date) -> int:
    """Unused prepaid minutes of retainers past their expiry date are written off (a row in the history). Returns how
    many retainers expired."""
    count = 0
    for retainer in session.scalars(select(Retainer).where(
            Retainer.company_id == company_id, Retainer.kind == "hours", Retainer.status == "active",
            Retainer.expires_on < day, Retainer.balance_minutes > 0).with_for_update()):
        _txn(session, retainer, "expire", -retainer.balance_minutes, day, note="Expired unused")
        retainer.balance_minutes = 0
        count += 1
    return count


def used_percent(retainer: Retainer) -> int:
    return rules.share_used(retainer.topped_up_minutes, retainer.balance_minutes)


def history_balance(session: Session, retainer_id: UUID) -> int:
    """The balance as the history adds up (equals `balance_minutes`; the integrity check compares them)."""
    return int(session.scalar(select(func.coalesce(func.sum(RetainerTxn.minutes), 0)).where(
        RetainerTxn.retainer_id == retainer_id)) or 0)
