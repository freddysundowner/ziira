"""Use cases: reading journal entries, and reversing one."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from ziira.modules.finance.permissions import REPORTS_VIEW
from ziira.modules.finance.repository import finance_repo
from ziira.modules.finance.repository.models import JournalEntry, JournalLine
from ziira.modules.finance.services.access import visible_companies
from ziira.sdk import NotFound, Session, current_context


@dataclass(frozen=True)
class EntryDetail:
    entry: JournalEntry
    lines: list[JournalLine]
    reversed_by: UUID | None


def list_entries(session: Session, *, company_id: UUID | None = None, source_type: str | None = None,
                 source_id: UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                 limit: int = 100, offset: int = 0) -> list[JournalEntry]:
    """Journal entries of the companies the user may see, newest first."""
    return finance_repo.list_entries(session, visible_companies(REPORTS_VIEW), company_id=company_id,
                                     source_type=source_type, source_id=source_id, date_from=date_from,
                                     date_to=date_to, limit=min(limit, 500), offset=offset)


def get_entry(session: Session, entry_id: UUID) -> EntryDetail:
    """One entry with its lines. A user limited to some branches sees only the lines of those branches."""
    entry = finance_repo.get_entry(session, entry_id)
    companies = visible_companies(REPORTS_VIEW)
    if entry is None or (companies is not None and entry.company_id not in companies):
        raise NotFound("Journal entry not found")
    scopes = current_context().scopes_with(REPORTS_VIEW)
    lines = [x for x in finance_repo.entry_lines(session, entry_id)
             if scopes is None or any(c == x.company_id and (b is None or b == x.branch_id) for c, b in scopes)]
    reversal = finance_repo.reversal_of(session, entry_id)
    return EntryDetail(entry, lines, reversal.id if reversal else None)
