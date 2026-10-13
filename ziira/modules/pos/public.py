"""Public interface of the Point of Sale and Sales module.

Other units use these; they normally talk to POS through events (`sale.posted`, `sale.returned`, `till.closed`).
"""

from datetime import date
from uuid import UUID

from sqlalchemy import text

from ziira.sdk import Session


def open_till_sessions(session: Session, branch_id: UUID, day: date) -> int:
    """How many till sessions of a branch and business date are still open (a day cannot be closed while any is)."""
    return int(session.execute(text(
        "select count(*) from pos.till_session where branch_id = :b and business_date = :d and status = 'open'"),
        {"b": str(branch_id), "d": day}).scalar_one())
