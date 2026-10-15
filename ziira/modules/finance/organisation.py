"""Finance's part of "kernel.branch_usage": a company with journal entries keeps its currency."""

from uuid import UUID

from sqlalchemy import text

from ziira.sdk import BranchUsageProvider, Session, provides


@provides("kernel.branch_usage")
class FinanceBranchUsage(BranchUsageProvider):
    name = "finance"

    def branch_blockers(self, session: Session, branch_id: UUID) -> list[str]:
        return []

    def currency_locks(self, session: Session, company_id: UUID) -> list[str]:
        posted = session.execute(text("select 1 from finance.journal_entry where company_id = :c limit 1"),
                                 {"c": str(company_id)}).first()
        return ["journal entries posted"] if posted else []
