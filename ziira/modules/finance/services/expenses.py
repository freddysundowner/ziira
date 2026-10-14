"""Use cases: expenses (a cost paid at once from cash, bank, M-Pesa or card, with a receipt reference).

    draft --submit--> pending_approval --approved--> posted --reverse--> reversed
      |                      '--rejected--> rejected
      '--submit (no approval rule applies)--> posted

Posting is Dr the expense account and Dr VAT input, Cr cash / bank / M-Pesa / card. Costs bought on credit go through
Purchasing's supplier bills, so what is owed to suppliers always equals what the supplier ledger says.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from ziira.modules.finance.domain import recipes
from ziira.modules.finance.permissions import EXPENSES_APPROVE, EXPENSES_SUBMIT, REPORTS_VIEW
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import Expense
from ziira.modules.finance.services.books import ensure_books
from ziira.modules.finance.services.posting import post_from_recipe
from ziira.sdk import (
    Conflict,
    Event,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    current_context,
    next_document_number,
    publish,
    submit_for_approval,
)

DOC_TYPE = "expense"
METHODS = ("cash", "bank", "mobile_money", "card", "other")


def _scopes() -> list[tuple[UUID | None, UUID | None]] | None:
    ctx = current_context()
    found: set[tuple[UUID | None, UUID | None]] = set()
    for permission in (EXPENSES_SUBMIT, EXPENSES_APPROVE, REPORTS_VIEW):
        scopes = ctx.scopes_with(permission)
        if scopes is None:
            return None
        found.update(scopes)
    return sorted(found, key=str)


def _can_see(expense: Expense) -> bool:
    scopes = _scopes()
    return scopes is None or any((c is None or c == expense.company_id) and (b is None or b == expense.branch_id)
                                 for c, b in scopes)


def _load(session: Session, expense_id: UUID, *, lock: bool = False) -> Expense:
    expense = finance_repo.get_expense(session, expense_id, lock=lock)
    if expense is None or not _can_see(expense):
        raise NotFound("Expense not found")
    return expense


def get_expense(session: Session, expense_id: UUID) -> Expense:
    return _load(session, expense_id)


def list_expenses(session: Session, *, company_id: UUID | None = None, status: str | None = None,
                  date_from: date | None = None, date_to: date | None = None, limit: int = 50,
                  offset: int = 0) -> list[Expense]:
    """Expenses of the companies and branches the user may see, newest first."""
    return finance_repo.list_expenses(session, _scopes(), company_id=company_id, status=status, date_from=date_from,
                                      date_to=date_to, limit=min(limit, 200), offset=offset)


def create_expense(session: Session, *, company_id: UUID, branch_id: UUID | None, expense_date: date, description: str,
                   account_id: UUID, amount: Decimal, tax_amount: Decimal, paid_from: str, payee: str | None = None,
                   receipt_ref: str | None = None) -> Expense:
    """Write a draft expense (`amount` is everything paid, `tax_amount` the VAT inside it). It changes nothing until it
    is submitted. Needs 'expenses.submit' for the company and branch."""
    ctx = current_context()
    check_company(session, company_id, branch_id)
    ctx.require(EXPENSES_SUBMIT, company_id=company_id, branch_id=branch_id)
    description = description.strip()
    if not description or len(description) > 500:
        raise ValidationFailed("A description is required (at most 500 characters)")
    if paid_from not in METHODS:
        raise ValidationFailed(f"Paid from must be one of: {', '.join(METHODS)}")
    if amount <= 0 or tax_amount < 0 or tax_amount >= amount:
        raise ValidationFailed("The amount must be more than nothing and the VAT in it less than the amount")
    payee, receipt_ref = (payee or "").strip() or None, (receipt_ref or "").strip() or None
    if (payee and len(payee) > 200) or (receipt_ref and len(receipt_ref) > 100):
        raise ValidationFailed("The payee is at most 200 characters and the receipt reference at most 100")
    ensure_books(session, company_id)
    account = finance_repo.get_account(session, account_id)
    if account is None or account.company_id != company_id:
        raise ValidationFailed("Account not found in this company")
    if account.type != "expense" or account.is_control or not account.is_active:
        raise ValidationFailed(f"Account {account.code} {account.name} cannot take an expense: choose an active "
                               "expense account")
    expense = Expense(
        tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
        number=next_document_number(session, company_id=company_id, branch_id=None, doc_type=DOC_TYPE, prefix="EXP"),
        expense_date=expense_date, payee=payee, description=description, account_id=account_id, amount=amount,
        tax_amount=tax_amount, paid_from=paid_from, receipt_ref=receipt_ref)
    finance_repo.add(session, expense)
    audit_record(session, "create", "finance.expense", expense.id,
                 {"number": expense.number, "amount": amount, "account": account.code})
    return expense


def submit_expense(session: Session, expense_id: UUID) -> Expense:
    """Send a draft for approval; it posts at once if no approval rule applies to its size. Needs 'expenses.submit'."""
    expense = _load(session, expense_id, lock=True)
    current_context().require(EXPENSES_SUBMIT, company_id=expense.company_id, branch_id=expense.branch_id)
    if expense.status != "draft":
        raise Conflict(f"This expense is {expense.status.replace('_', ' ')}, so it cannot be submitted")
    audit_record(session, "submit", "finance.expense", expense.id, {"amount": expense.amount})
    if submit_for_approval(session, company_id=expense.company_id, doc_type=DOC_TYPE, doc_id=expense.id,
                           amount=expense.amount) == "approved":
        _post(session, expense, approved_by=None)
    else:
        expense.status = "pending_approval"
        session.flush()
    return expense


def apply_decision(session: Session, expense_id: UUID, *, approved: bool, decided_by: UUID | None) -> None:
    """Post or reject an expense once its approval has been decided (from `approval.decided`)."""
    expense = finance_repo.get_expense(session, expense_id, lock=True)
    if expense is None:
        return
    if expense.status != "pending_approval":
        raise Conflict(f"This expense is {expense.status.replace('_', ' ')}, so it cannot be decided")
    current_context().require(EXPENSES_APPROVE, company_id=expense.company_id, branch_id=expense.branch_id)
    if approved:
        _post(session, expense, approved_by=decided_by)
    else:
        expense.status = "rejected"
        session.flush()
        audit_record(session, "reject", "finance.expense", expense.id, {"number": expense.number})


def reverse_expense(session: Session, expense_id: UUID, reason: str) -> Expense:
    """Cancel a posted expense (entered wrongly, or the money came back) by posting its mirror image. Needs
    'expenses.approve'."""
    expense = _load(session, expense_id, lock=True)
    current_context().require(EXPENSES_APPROVE, company_id=expense.company_id, branch_id=expense.branch_id)
    if not reason.strip():
        raise ValidationFailed("A reason is required")
    if expense.status != "posted":
        raise Conflict(f"This expense is {expense.status.replace('_', ' ')}, so it cannot be reversed")
    post_from_recipe(
        session, company_id=expense.company_id, doc_type=DOC_TYPE, journal_code="CSH", entry_date=date.today(),
        recipe=recipes.expense(expense.paid_from, expense.amount, expense.tax_amount, expense.account_id,
                               description=f"Reversal of expense {expense.number}", reverse=True),
        context={}, branch_id=expense.branch_id, source_type="expense_reversal", source_id=expense.id,
        description=f"Reversal of expense {expense.number}: {reason.strip()}"[:500])
    expense.status = "reversed"
    expense.reverse_reason = reason.strip()
    from datetime import UTC, datetime

    expense.reversed_at = datetime.now(UTC)
    session.flush()
    audit_record(session, "reverse", "finance.expense", expense.id, {"number": expense.number, "reason": reason})
    return expense


def _post(session: Session, expense: Expense, *, approved_by: UUID | None) -> None:
    entry = post_from_recipe(
        session, company_id=expense.company_id, doc_type=DOC_TYPE, journal_code="CSH", entry_date=expense.expense_date,
        recipe=recipes.expense(expense.paid_from, expense.amount, expense.tax_amount, expense.account_id,
                               description=f"{expense.number}: {expense.description}"[:500]),
        context={}, branch_id=expense.branch_id, source_type=DOC_TYPE, source_id=expense.id,
        description=f"Expense {expense.number}: {expense.description}"[:500])
    expense.status = "posted"
    expense.entry_id = entry.id if entry else None
    expense.approved_by = approved_by
    session.flush()
    publish(session, Event("expense.approved", "finance.expense", expense.id, {
        "company_id": expense.company_id, "branch_id": expense.branch_id, "number": expense.number,
        "amount": expense.amount, "tax_amount": expense.tax_amount, "account_id": expense.account_id,
        "paid_from": expense.paid_from, "expense_date": expense.expense_date}))
