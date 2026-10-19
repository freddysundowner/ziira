"""Days the business (or one branch) is closed: holidays, a staff day, a refit. No class or appointment is booked on
them by clients, and a weekly series skips them."""

from datetime import date
from typing import Any
from uuid import UUID

from ziira.modules.bookings.permissions import BOOKINGS_SETUP
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.services import access
from ziira.sdk import NotFound, Session, audit_record, check_company, current_context


def list_closed(session: Session, company_id: UUID, start: date | None = None,
                end: date | None = None) -> list[dict[str, Any]]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return raw.many(session, "select * from bookings.closed_day where company_id = :c "
                             "and (cast(:s as date) is null or day >= :s) and (cast(:e as date) is null or day <= :e) "
                             "order by day", c=company_id, s=start, e=end)


def close_day(session: Session, company_id: UUID, day: date, *, branch_id: UUID | None = None,
              label: str | None = None) -> dict[str, Any]:
    """Mark a day closed (the whole business, or one branch). Needs 'bookings.setup'. Closing a day that is already
    closed changes nothing."""
    current_context().require(BOOKINGS_SETUP, company_id=company_id)
    check_company(session, company_id, branch_id)
    found = raw.one(session, "select * from bookings.closed_day where company_id = :c and day = :d and "
                             "coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid) = "
                             "coalesce(cast(:b as uuid), '00000000-0000-0000-0000-000000000000'::uuid)",
                    c=company_id, d=day, b=branch_id)
    if found is not None:
        return found
    made = raw.insert(session, "closed_day", {"company_id": company_id, "branch_id": branch_id, "day": day,
                                              "label": (label or "").strip()[:100] or None},
                      user_id=current_context().user_id)
    audit_record(session, "close_day", "bookings.closed_day", made["id"], {"day": day.isoformat()})
    return made


def reopen_day(session: Session, closed_id: UUID) -> None:
    row = raw.one(session, "select * from bookings.closed_day where id = :i", i=closed_id)
    if row is None or not access.can_see_company(row["company_id"]):
        raise NotFound("Closed day not found")
    current_context().require(BOOKINGS_SETUP, company_id=row["company_id"])
    raw.run(session, "delete from bookings.closed_day where id = :i", i=closed_id)
    audit_record(session, "reopen_day", "bookings.closed_day", closed_id, {"day": row["day"].isoformat()})
