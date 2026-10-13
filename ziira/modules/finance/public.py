"""Public interface of the Finance and Accounting module.

Other units do not call Finance: they publish documents (`sale.posted`, `sale.returned`, and the stock movements
Inventory already publishes) and Finance turns them into journal entries. Only reads are exposed here.
"""

from uuid import UUID

from ziira.modules.finance.repository import finance_repo
from ziira.sdk import Session


def is_expense_account(session: Session, company_id: UUID, account_id: UUID) -> bool:
    """True when the account is an active expense account of the company that people may post to."""
    account = finance_repo.get_account(session, account_id)
    return (account is not None and account.company_id == company_id and account.type == "expense"
            and account.is_active and not account.is_control)

