"""What Payments tells Connectors about the business running on Ziira: money received and paid, by branch."""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import CoreCoverage
from ziira.sdk import Session


class PaymentsCoverage(CoreCoverage):
    """Payments posted since a date."""

    def active(self, session: Session, company_id: UUID | None, since: date) -> dict[str, set[UUID | None]]:
        scope = "" if company_id is None else " and company_id = :c"
        found = session.execute(text(
            f"select distinct branch_id from payments.payment where status = 'posted' and business_date >= :s{scope}"),
            {"s": since, "c": str(company_id) if company_id else None})
        return {"payments": {r.branch_id for r in found}}
