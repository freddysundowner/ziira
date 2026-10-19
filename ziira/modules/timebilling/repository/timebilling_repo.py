"""Database access for the timebilling schema. Row-level security scopes every query to the tenant."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, or_, select, true
from sqlalchemy.orm import Session

from ziira.modules.timebilling.repository.models import (
    Entry,
    Expense,
    InvoiceBatch,
    InvoiceBatchLine,
    Project,
    Rate,
    Retainer,
    Setting,
    Timer,
    Week,
)

Scopes = list[tuple[UUID | None, UUID | None]] | None


def in_scope(scopes: Scopes, company_col: Any, branch_col: Any) -> ColumnElement[bool]:
    """Rows of the companies and branches the user may see (None means everywhere). A row with no branch belongs to
    the whole company."""
    if scopes is None:
        return true()
    if branch_col is None:
        return or_(false(), *(company_col == c for c, _ in scopes if c is not None), *(
            true() for c, _ in scopes if c is None))
    return or_(false(), *(and_(company_col == c, true() if b is None else or_(branch_col == b, branch_col.is_(None)))
                          for c, b in scopes))


def add(session: Session, record: Any) -> None:
    session.add(record)
    session.flush()
    session.refresh(record)


def get[M](session: Session, model: type[M], record_id: UUID, *, lock: bool = False) -> M | None:
    if lock:
        return session.scalars(select(model).where(model.id == record_id)  # type: ignore[attr-defined]
                               .with_for_update().execution_options(populate_existing=True)).first()
    return session.get(model, record_id)


def settings_of(session: Session, company_id: UUID) -> Setting | None:
    return session.scalar(select(Setting).where(Setting.company_id == company_id))


def project_by_code(session: Session, company_id: UUID, code: str) -> Project | None:
    return session.scalar(select(Project).where(Project.company_id == company_id, Project.code == code))


def projects_by_ids(session: Session, ids: set[UUID]) -> dict[UUID, Project]:
    if not ids:
        return {}
    return {p.id: p for p in session.scalars(select(Project).where(Project.id.in_(ids)))}


def rates_for(session: Session, company_id: UUID, kind: str, day: date) -> list[Rate]:
    return list(session.scalars(select(Rate).where(
        Rate.company_id == company_id, Rate.kind == kind, Rate.effective_from <= day,
        or_(Rate.effective_to.is_(None), Rate.effective_to >= day))))


def week_of(session: Session, company_id: UUID, user_id: UUID, week_start: date, *,
            lock: bool = False) -> Week | None:
    q = select(Week).where(Week.company_id == company_id, Week.user_id == user_id, Week.week_start == week_start)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return session.scalar(q)


def timer_of(session: Session, user_id: UUID, *, lock: bool = False) -> Timer | None:
    q = select(Timer).where(Timer.user_id == user_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return session.scalar(q)


def entries_of_week(session: Session, company_id: UUID, user_id: UUID, start: date, end: date) -> list[Entry]:
    return list(session.scalars(select(Entry).where(
        Entry.company_id == company_id, Entry.user_id == user_id, Entry.work_date >= start, Entry.work_date <= end)
        .order_by(Entry.work_date, Entry.created_at)))


def expenses_of_week(session: Session, company_id: UUID, user_id: UUID, start: date, end: date) -> list[Expense]:
    return list(session.scalars(select(Expense).where(
        Expense.company_id == company_id, Expense.user_id == user_id, Expense.expense_date >= start,
        Expense.expense_date <= end)
        .order_by(Expense.expense_date, Expense.created_at)))


def active_retainer(session: Session, project_id: UUID, *, lock: bool = False) -> Retainer | None:
    q = select(Retainer).where(Retainer.project_id == project_id, Retainer.status == "active")
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return session.scalar(q)


def batch_lines(session: Session, batch_id: UUID) -> list[InvoiceBatchLine]:
    return list(session.scalars(select(InvoiceBatchLine).where(InvoiceBatchLine.batch_id == batch_id)
                                .order_by(InvoiceBatchLine.line_no)))


def batch_for_invoice(session: Session, invoice_id: UUID) -> InvoiceBatch | None:
    return session.scalar(select(InvoiceBatch).where(InvoiceBatch.invoice_id == invoice_id))
