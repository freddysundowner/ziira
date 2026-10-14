"""The business date: "today" and the day a moment belongs to, in the company's own time zone.

The zone is the company setting `timezone` (an IANA name, default "UTC"); nothing here assumes a country. The
setting is already read once per transaction and company (`company_settings._stored`), so a hot path such as a sale
adds no query per call. Use these helpers wherever a record gets a date from the clock.
"""

from datetime import UTC, date, datetime, tzinfo
from functools import lru_cache
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ziira.kernel import company_settings


@lru_cache(maxsize=64)
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def company_zone(session: Session, company_id: UUID) -> tzinfo:
    """The company's time zone."""
    return _zone(str(company_settings.get_setting(session, company_id, "timezone")))


def company_today(session: Session, company_id: UUID, now: datetime | None = None) -> date:
    """Today's date where the company is (`now` is for tests: an aware moment, default the real clock)."""
    return (now or datetime.now(UTC)).astimezone(company_zone(session, company_id)).date()


def company_date_of(session: Session, company_id: UUID, moment: datetime) -> date:
    """The company's calendar date of an aware moment (a naive one is read as UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(company_zone(session, company_id)).date()
