"""What Finance tells Connectors about the business running on Ziira: expenses and hand-made journals."""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.modules.connect.public import CoreCoverage
from ziira.sdk import Session


class FinanceCoverage(CoreCoverage):
    """Posted expenses (by branch) and manual journals (company wide) since a date. Entries the system makes for
    other units' documents, and opening balances, are not counted: they say nothing about who keeps the books."""

    def active(self, session: Session, company_id: UUID | None, since: date) -> dict[str, set[UUID | None]]:
        scope = "" if company_id is None else " and company_id = :c"
        params = {"s": since, "c": str(company_id) if company_id else None}
        expenses = {r.branch_id for r in session.execute(text(
            f"select distinct branch_id from finance.expense where status = 'posted' and expense_date >= :s{scope}"),
            params)}
        manual = session.execute(text(
            f"select 1 from finance.journal_entry where is_manual and entry_date >= :s{scope} limit 1"), params).first()
        return {"expenses": expenses, "journals": {None} if manual else set()}
