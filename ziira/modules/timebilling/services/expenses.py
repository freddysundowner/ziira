"""Use cases: expenses billed to a client. Entered here with an amount and an optional markup; nothing is posted to the
books by this module (the business records the spending itself): it only bills.

They travel with the week like time does: the person's week is submitted, someone else approves it, and then they can be
invoiced.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from ziira.modules.timebilling.permissions import TIME_LOG, TIME_VIEW
from ziira.modules.timebilling.repository import timebilling_repo as repo
from ziira.modules.timebilling.repository.models import Expense
from ziira.modules.timebilling.services import access, common, weeks
from ziira.modules.timebilling.services import settings as settings_service
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, current_context, files


def default_markup(session: Session, company_id: UUID, client_id: UUID) -> Decimal:
    """The markup new expenses start with: the client's own, else the company's (0 when neither says)."""
    terms = settings_service.get_client_terms(session, company_id, client_id)
    if terms is not None and terms.expense_markup_percent is not None:
        return Decimal(terms.expense_markup_percent)
    return Decimal(common.settings(session, company_id).default_markup_percent)


def create_expense(session: Session, *, project_id: UUID, expense_date: date, description: str, amount: Decimal,
                   markup_percent: Decimal | None = None, billable: bool = True,
                   reference: str | None = None, category: str | None = None) -> Expense:
    """Record an expense (a disbursement) for a client's project. Needs 'time.log'. Without a `markup_percent` the
    client's usual markup (else the company's) applies; 0 bills it at cost."""
    ctx = current_context()
    me = access.user_id()
    project = common.usable_project(session, project_id)
    ctx.require(TIME_LOG, company_id=project.company_id, branch_id=project.branch_id)
    if amount <= 0:
        raise ValidationFailed("An expense must be more than nothing")
    if not description.strip():
        raise ValidationFailed("Say what the expense was for")
    if expense_date > common.today(session, project.company_id):
        raise ValidationFailed("An expense cannot be dated in the future")
    setting = common.settings(session, project.company_id)
    weeks.ensure_open(session, project.company_id, me, expense_date, setting.week_starts_on)
    markup = markup_percent if markup_percent is not None else default_markup(
        session, project.company_id, project.client_id)
    expense = Expense(tenant_id=ctx.tenant_id, created_by=me, company_id=project.company_id,
                      branch_id=project.branch_id, user_id=me, project_id=project.id, expense_date=expense_date,
                      description=description.strip()[:300], reference=(reference or "").strip()[:60] or None,
                      amount=amount, markup_percent=markup, billable=billable,
                      category=(category or "").strip()[:60] or None)
    repo.add(session, expense)
    audit_record(session, "create", "timebilling.expense", expense.id, {"project": project.code, "amount": amount})
    return expense


def get_expense(session: Session, expense_id: UUID, *, lock: bool = False) -> Expense:
    expense = repo.get(session, Expense, expense_id, lock=lock)
    ctx = current_context()
    if expense is None or not (expense.user_id == ctx.user_id or ctx.can(
            TIME_VIEW, company_id=expense.company_id, branch_id=expense.branch_id)):
        raise NotFound("Expense not found")
    return expense


def _own_open(session: Session, expense_id: UUID) -> Expense:
    expense = get_expense(session, expense_id, lock=True)
    if expense.user_id != access.user_id():
        raise ValidationFailed("You can only change your own expenses")
    if expense.status != "draft" or expense.invoice_id is not None:
        raise Conflict("This expense has been submitted: ask for the week to be sent back first")
    return expense


def update_expense(session: Session, expense_id: UUID, **changes: Any) -> Expense:
    expense = _own_open(session, expense_id)
    for key in ("description", "amount", "markup_percent", "billable", "reference", "expense_date", "category"):
        if key in changes and changes[key] is not None:
            setattr(expense, key, changes[key])
    if expense.amount <= 0 or not expense.description.strip():
        raise ValidationFailed("An expense needs an amount and a description")
    if "expense_date" in changes:
        setting = common.settings(session, expense.company_id)
        weeks.ensure_open(session, expense.company_id, expense.user_id, expense.expense_date, setting.week_starts_on)
    expense.updated_by = expense.user_id
    session.flush()
    audit_record(session, "update", "timebilling.expense", expense.id, {k: str(v) for k, v in changes.items()})
    return expense


def delete_expense(session: Session, expense_id: UUID) -> None:
    expense = _own_open(session, expense_id)
    files.remove_for_entity(session, "timebilling.expense", expense_id, "The expense was deleted")
    session.delete(expense)
    session.flush()
    audit_record(session, "delete", "timebilling.expense", expense_id, {"amount": expense.amount})


def list_expenses(session: Session, *, user_id: UUID | None = None, project_id: UUID | None = None,
                  status: str | None = None, date_from: date | None = None, date_to: date | None = None,
                  limit: int = 100, offset: int = 0) -> list[Expense]:
    me = access.user_id()
    q = select(Expense).where(or_(Expense.user_id == me, repo.in_scope(
        access.scopes_for(TIME_VIEW), Expense.company_id, Expense.branch_id)))
    if user_id:
        q = q.where(Expense.user_id == user_id)
    if project_id:
        q = q.where(Expense.project_id == project_id)
    if status:
        q = q.where(Expense.status == status)
    if date_from:
        q = q.where(Expense.expense_date >= date_from)
    if date_to:
        q = q.where(Expense.expense_date <= date_to)
    return list(session.scalars(q.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
                                .limit(min(limit, 500)).offset(offset)))
