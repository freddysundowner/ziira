"""Use cases: handing the books to the accountant (journal export) and what the accountant calls each account."""

from datetime import date
from uuid import UUID

from ziira.modules.finance.domain import exports
from ziira.modules.finance.permissions import ACCOUNTS_MANAGE
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import AccountMapping
from ziira.modules.finance.services.access import require_visible
from ziira.modules.finance.services.reports import _scopes
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, check_company, current_context

MAX_NAME = 100


def journal_export(session: Session, company_id: UUID, date_from: date, date_to: date, fmt: str, *,
                   branch_id: UUID | None = None) -> str:
    """Every journal line dated between two dates as CSV (generic, quickbooks or sage), with each account under the
    code and name its mapping gives it. Needs 'reports.view'."""
    if fmt not in exports.FORMATS:
        raise ValidationFailed(f"Format must be one of: {', '.join(exports.FORMATS)}")
    if date_to < date_from:
        raise ValidationFailed("The end date is before the start date")
    check_company(session, company_id, branch_id)
    scopes = _scopes(company_id)
    mapped = finance_repo.mappings(session, company_id)
    names = finance_repo.branch_names(session, company_id)
    rows = [exports.JournalRow(
        r.entry_number, r.entry_date, r.source_type, r.description, r.account_code, r.account_name,
        names.get(r.branch_id) if r.branch_id else None, r.debit, r.credit,
        mapped[r.account_id].external_code if r.account_id in mapped else None,
        mapped[r.account_id].external_name if r.account_id in mapped else None)
        for r in finance_repo.journal_rows(session, scopes, company_id, date_from, date_to, branch_id)]
    return exports.journal_csv(rows, fmt)


def list_mappings(session: Session, company_id: UUID) -> list[AccountMapping]:
    """The account names the accountant uses. Anyone who can see the books may read them."""
    require_visible(company_id)
    return sorted(finance_repo.mappings(session, company_id).values(), key=lambda m: str(m.account_id))


def set_mapping(session: Session, company_id: UUID, account_id: UUID, *, external_code: str | None,
                external_name: str | None) -> AccountMapping:
    """Say what an account is called in the accountant's software (code, name, or both). Needs 'accounts.manage'."""
    ctx = current_context()
    ctx.require(ACCOUNTS_MANAGE, company_id=company_id)
    code, name = (external_code or "").strip() or None, (external_name or "").strip() or None
    if code is None and name is None:
        raise ValidationFailed("Give a code, a name, or both")
    if (code and len(code) > 40) or (name and len(name) > MAX_NAME):
        raise ValidationFailed(f"The code is at most 40 characters and the name at most {MAX_NAME}")
    account = finance_repo.get_account(session, account_id)
    if account is None or account.company_id != company_id:
        raise NotFound("Account not found in this company")
    mapping = finance_repo.get_mapping(session, company_id, account_id)
    if mapping is None:
        mapping = AccountMapping(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id,
                                 account_id=account_id, external_code=code, external_name=name)
        finance_repo.add(session, mapping)
    else:
        mapping.external_code, mapping.external_name, mapping.updated_by = code, name, ctx.user_id
        session.flush()
    audit_record(session, "update", "finance.account_mapping", mapping.id,
                 {"account": account.code, "external_code": code, "external_name": name})
    return mapping


def clear_mapping(session: Session, company_id: UUID, account_id: UUID) -> None:
    """Go back to the account's own code and name in exports. Needs 'accounts.manage'."""
    current_context().require(ACCOUNTS_MANAGE, company_id=company_id)
    mapping = finance_repo.get_mapping(session, company_id, account_id)
    if mapping is None:
        raise NotFound("That account has no mapping")
    session.delete(mapping)
    audit_record(session, "delete", "finance.account_mapping", mapping.id, {"account_id": str(account_id)})
