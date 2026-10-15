"""Public interface of the Finance and Accounting module.

Other units do not call Finance: they publish documents (`sale.posted`, `sale.returned`, and the stock movements
Inventory already publishes) and Finance turns them into journal entries. Only reads are exposed here.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.finance.repository import finance_repo
from ziira.sdk import Session


def is_expense_account(session: Session, company_id: UUID, account_id: UUID) -> bool:
    """True when the account is an active expense account of the company that people may post to."""
    account = finance_repo.get_account(session, account_id)
    return (account is not None and account.company_id == company_id and account.type == "expense"
            and account.is_active and not account.is_control)



def is_payable_account(session: Session, company_id: UUID, account_id: UUID) -> bool:
    """True when the account is an active liability account of the company (somewhere an amount can be owed)."""
    account = finance_repo.get_account(session, account_id)
    return (account is not None and account.company_id == company_id and account.type == "liability"
            and account.is_active)


def entry_for_source(session: Session, company_id: UUID, source_type: str, source_id: UUID) -> UUID | None:
    """The journal entry a document made, if it has been posted."""
    entry = finance_repo.entry_by_source(session, company_id, source_type, source_id)
    return entry.id if entry is not None else None


def party_balances(session: Session, company_id: UUID, account_code: str) -> dict[UUID | None, Decimal]:
    """What each party (customer or supplier) owes or is owed on a control account, from the journal: debits less
    credits. A key of None holds lines with no party. Used by the sub-ledger checks."""
    rows = session.execute(text(
        "select l.party_id, coalesce(sum(l.debit - l.credit), 0) as balance from finance.journal_line l join "
        "finance.account a on a.id = l.account_id where a.company_id = :c and a.code = :code group by l.party_id"),
        {"c": str(company_id), "code": account_code}).all()
    return {r.party_id: Decimal(r.balance) for r in rows if Decimal(r.balance) != 0}


def opening_balance_posted(session: Session, company_id: UUID) -> bool:
    """True when the company has an opening balance entry that has not been reversed. Customers' and suppliers' opening
    balances are brought in before it, never after."""
    return finance_repo.live_opening_balance(session, company_id) is not None


def books_are_on(session: Session, company_id: UUID) -> bool:
    """True when the company's books exist (accounts have been set up), so documents can be posted to them."""
    return finance_repo.has_accounts(session, company_id)


def posted_for_sources(session: Session, company_id: UUID, source_type: str, source_ids: set[UUID]) -> set[UUID]:
    """Which of these documents already have a journal entry of the given source type."""
    return finance_repo.posted_sources(session, source_type, source_ids)


def party_amount_by_source(session: Session, company_id: UUID, source_type: str, source_ids: set[UUID],
                           party_type: str) -> Decimal:
    """Debits less credits on the customer (or supplier) lines of the entries these documents made: what the books hold
    for them, to compare with what the documents say."""
    return finance_repo.party_net_by_source(session, company_id, source_type, source_ids, party_type)


def period_is_open(session: Session, company_id: UUID, day: date) -> bool:
    """True when the accounting period containing the day is open (or not created yet, which makes it open)."""
    period = finance_repo.period_for(session, company_id, day)
    return period is None or period.status == "open"
