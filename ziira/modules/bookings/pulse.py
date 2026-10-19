"""Bookings' figures for the Command Center: today's appointments, finished ones, no-shows and
requests waiting."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from ziira.modules.command.public import COMMAND_PULSE_SOURCE, Figure, PulseSource
from ziira.sdk import Session, company_zone, provides


@provides(COMMAND_PULSE_SOURCE)
class BookingsPulse(PulseSource):
    """Appointment numbers for a company and a day."""

    code = "bookings"

    def figures(self, session: Session, company_id: UUID, day: date) -> list[Figure]:
        zone = company_zone(session, company_id)
        start = datetime.combine(day, time(0, 0), tzinfo=zone)
        params = {"c": str(company_id), "s": start, "e": start + timedelta(days=1)}

        def count(extra: str) -> Decimal:
            return Decimal(session.execute(text(
                "select count(*) from bookings.appointment where company_id = :c and starts_at >= :s "
                "and starts_at < :e " + extra), params).scalar_one())

        booked = count("and status not in ('cancelled')")
        done = count("and status = 'completed'")
        missed = count("and status = 'no_show'")
        waiting = Decimal(session.execute(text(
            "select count(*) from bookings.appointment where company_id = :c and status = 'requested'"),
            params).scalar_one())
        return [Figure("bookings.appointments", "Appointments", "count", booked, None, None),
                Figure("bookings.completed", "Appointments finished", "count", done, None, True),
                Figure("bookings.no_shows", "Clients who did not come", "count", missed, None, False),
                Figure("bookings.requests_waiting", "Booking requests waiting for an answer", "count", waiting, None,
                       False)]
