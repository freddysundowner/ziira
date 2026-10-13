"""Use cases: the chart of accounts."""

import re
from uuid import UUID

from ziira.modules.finance.domain.entries import ACCOUNT_TYPES
from ziira.modules.finance.permissions import ACCOUNTS_MANAGE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import Account
from ziira.modules.finance.services.access import require_visible, visible_companies
from ziira.modules.finance.services.books import ensure_books
from ziira.sdk import Conflict, NotFound, Session, ValidationFailed, audit_record, current_context

CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")


def setup_books(session: Session, company_id: UUID) -> list[Account]:
    """Create the company's chart of accounts, journals and default posting rules (nothing happens if it has them).
    Needs 'accounts.manage' for the company."""
    current_context().require(ACCOUNTS_MANAGE, company_id=company_id)
    ensure_books(session, company_id)
    return finance_repo.list_accounts(session, {company_id}, company_id)


def list_accounts(session: Session, company_id: UUID | None = None, include_inactive: bool = False) -> list[Account]:
    """The chart of accounts of the companies the user may see."""
    if company_id is not None:
        require_visible(company_id)
    return finance_repo.list_accounts(session, visible_companies(), company_id, include_inactive)


def create_account(session: Session, *, company_id: UUID, code: str, name: str, type: str, subtype: str | None = None,
                   parent_id: UUID | None = None) -> Account:
    """Add an account to a company's chart. Control accounts (kept by stock, customers or suppliers) are not created by
    hand. Needs 'accounts.manage' for the company."""
    ctx = current_context()
    ctx.require(ACCOUNTS_MANAGE, company_id=company_id)
    ensure_books(session, company_id)
    code = code.strip().upper()
    name = name.strip()
    if not CODE_PATTERN.match(code):
        raise ValidationFailed("Account code must be 1-20 letters, digits, '.', '_' or '-'")
    if not name or len(name) > 200:
        raise ValidationFailed("Account name is required (at most 200 characters)")
    if type not in ACCOUNT_TYPES:
        raise ValidationFailed(f"Account type must be one of: {', '.join(ACCOUNT_TYPES)}")
    if finance_repo.account_by_code(session, company_id, code) is not None:
        raise Conflict(f"Account {code} already exists in this company")
    if parent_id is not None:
        parent = finance_repo.get_account(session, parent_id)
        if parent is None or parent.company_id != company_id:
            raise ValidationFailed("Parent account not found in this company")
        if parent.type != type:
            raise ValidationFailed("An account must be of the same type as its parent")
    account = Account(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, code=code, name=name,
                      type=type, subtype=(subtype or "").strip() or None, parent_id=parent_id)
    finance_repo.add(session, account)
    audit_record(session, "create", "finance.account", account.id, {"code": code, "name": name, "type": type})
    return account


def update_account(session: Session, account_id: UUID, *, name: str | None = None,
                   is_active: bool | None = None) -> Account:
    """Rename an account or switch it off. An account cannot be switched off while a posting rule uses it, while it is
    a control account, or while it has a balance. Needs 'accounts.manage' for the company."""
    account = finance_repo.get_account(session, account_id)
    if account is None:
        raise NotFound("Account not found")
    current_context().require(ACCOUNTS_MANAGE, company_id=account.company_id)
    changes: dict[str, object] = {}
    if name is not None:
        name = name.strip()
        if not name or len(name) > 200:
            raise ValidationFailed("Account name is required (at most 200 characters)")
        changes["name"] = name
        account.name = name
    if is_active is not None and is_active != account.is_active:
        if not is_active:
            if account.is_control:
                raise ValidationFailed("A control account cannot be switched off")
            if finance_repo.account_in_rules(session, account.id):
                raise ValidationFailed("A posting rule uses this account: point the rule at another account first")
            debit, credit = finance_repo.account_balance(session, account.id)
            if debit != credit:
                raise ValidationFailed("The account still has a balance")
        account.is_active = is_active
        changes["is_active"] = is_active
    if changes:
        session.flush()
        audit_record(session, "update", "finance.account", account.id, changes)
    return account
