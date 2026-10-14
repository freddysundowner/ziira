"""Events published and handled by the People, HR and Payroll module.

Publishes: employee.pay_changed, employee.bank_changed, payroll.approved, payroll.paid
Subscribes: till.opened, till.closed (a cashier opening and closing their till clocks in and out)
"""

import logging
from datetime import UTC, date, datetime
from uuid import UUID

from ziira.modules.people.services import attendance
from ziira.sdk import Event, Session, subscribe

log = logging.getLogger("ziira.people")


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@subscribe("till.opened")
def on_till_opened(session: Session, event: Event) -> None:
    """Clock the cashier in. Never allowed to stop a till opening: a problem here is logged and skipped."""
    p = event.payload
    day = _day(p.get("business_date"))
    if day is None:
        return
    try:
        with session.begin_nested():
            attendance.clock_in_from_till(session, user_id=_uuid(p.get("cashier_id")),
                                          branch_id=_uuid(p.get("branch_id")), day=day, at=datetime.now(UTC))
    except Exception:
        log.exception("Could not record attendance from till.opened")


@subscribe("till.closed")
def on_till_closed(session: Session, event: Event) -> None:
    """Clock the cashier out."""
    p = event.payload
    day = _day(p.get("business_date"))
    if day is None:
        return
    try:
        with session.begin_nested():
            attendance.clock_out_from_till(session, user_id=_uuid(p.get("cashier_id")), day=day,
                                           at=datetime.now(UTC))
    except Exception:
        log.exception("Could not record attendance from till.closed")
