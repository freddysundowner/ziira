"""Public interface of the Purchasing and Suppliers module.

Other units normally talk to Purchasing through events (`goods.received`, `bill.posted`, `supplier.paid`).
"""

from decimal import Decimal
from uuid import UUID

from ziira.modules.purchasing.repository import purchasing_repo
from ziira.sdk import Session


def supplier_balance(session: Session, supplier_id: UUID) -> Decimal:
    """What the business still owes a supplier on posted bills."""
    total = Decimal(0)
    for bill in purchasing_repo.list_bills(session, None, supplier_id=supplier_id, status=None, due_before=None,
                                           limit=500, offset=0):
        if bill.status in ("posted", "part_paid"):
            total += bill.total - bill.amount_paid
    return total
