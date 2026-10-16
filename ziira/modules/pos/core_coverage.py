"""What POS tells Connectors about the business running on Ziira: sales and customer invoices, by branch."""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import CoreCoverage
from ziira.sdk import Session


class PosCoverage(CoreCoverage):
    """Posted sales and issued customer invoices since a date. Opening balances brought in at go-live do not count."""

    def active(self, session: Session, company_id: UUID | None, since: date) -> dict[str, set[UUID | None]]:
        scope = "" if company_id is None else " and company_id = :c"
        params = {"s": since, "c": str(company_id) if company_id else None}
        sales = {r.branch_id for r in session.execute(text(
            f"select distinct branch_id from pos.sale where status = 'posted' and business_date >= :s{scope}"), params)}
        invoices = {r.branch_id for r in session.execute(text(
            "select distinct branch_id from pos.sales_invoice where kind <> 'opening_balance' "
            f"and status <> 'cancelled' and issue_date >= :s{scope}"), params)}
        return {"sales": sales, "receivables": invoices}
