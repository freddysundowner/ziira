"""What Purchasing tells Connectors about the business running on Ziira: supplier bills, by branch."""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import CoreCoverage
from ziira.sdk import Session


class PurchasingCoverage(CoreCoverage):
    """Supplier bills entered since a date, other than the opening balances brought in at go-live."""

    def active(self, session: Session, company_id: UUID | None, since: date) -> dict[str, set[UUID | None]]:
        scope = "" if company_id is None else " and company_id = :c"
        found = session.execute(text(
            "select distinct branch_id from purchasing.supplier_bill where kind <> 'opening_balance' "
            f"and status <> 'cancelled' and bill_date >= :s{scope}"),
            {"s": since, "c": str(company_id) if company_id else None})
        return {"payables": {r.branch_id for r in found}}
