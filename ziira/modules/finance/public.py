"""Public interface of the Finance and Accounting module.

Other units do not call Finance: they publish documents (`sale.posted`, `sale.returned`, and the stock movements
Inventory already publishes) and Finance turns them into journal entries. Only reads are exposed here.
"""

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



def party_balances(session: Session, company_id: UUID, account_code: str) -> dict[UUID | None, Decimal]:
    """What each party (customer or supplier) owes or is owed on a control account, from the journal: debits less
    credits. A key of None holds lines with no party. Used by the sub-ledger checks."""
    rows = session.execute(text(
        "select l.party_id, coalesce(sum(l.debit - l.credit), 0) as balance from finance.journal_line l join "
        "finance.account a on a.id = l.account_id where a.company_id = :c and a.code = :code group by l.party_id"),
        {"c": str(company_id), "code": account_code}).all()
    return {r.party_id: Decimal(r.balance) for r in rows if Decimal(r.balance) != 0}
