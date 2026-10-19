"""Next-service reminders: the items (vehicles, devices) whose next service date is near or past, and the message that
reminds their owner. Messages are queued through the notification layer (never sent in a request), once per due date.
The odometer part of 'next service' is shown on the intake screen when the item comes in; only dates can be reminded
by message because nobody knows the reading between visits."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from ziira.modules.jobs.repository.models import Asset, Job, JobSetting
from ziira.modules.jobs.services import access, notify
from ziira.modules.jobs.services.common import unit_enabled
from ziira.sdk import Session, company_today, format_day, send_templated


def due_items(session: Session, company_id: UUID, *, within_days: int = 30, limit: int = 200) -> list[Asset]:
    """Active items whose next service date is within `within_days` days or already past, soonest first."""
    if not access.can_see_company(company_id):
        return []
    until = company_today(session, company_id) + timedelta(days=within_days)
    rows = session.scalars(select(Asset).where(
        Asset.company_id == company_id, Asset.is_active, Asset.next_service_date.is_not(None),
        Asset.next_service_date <= until).order_by(Asset.next_service_date).limit(limit))
    return list(rows)


def odometer_due(asset: Asset) -> Decimal | None:
    """How far the item is from its service reading (negative: past it), or None when there is nothing to compare."""
    if asset.next_service_odometer is None or asset.odometer is None:
        return None
    return asset.next_service_odometer - asset.odometer


def _contact(session: Session, asset: Asset) -> tuple[str | None, str | None, str]:
    phone = email = None
    name = ""
    if asset.customer_id is not None and unit_enabled(session, "crm"):
        from ziira.modules.crm.public import find_customer

        found = find_customer(session, asset.customer_id)
        if found is not None:
            phone, email, name = found.phone, found.email, found.name
    if phone is None and email is None:
        last = session.scalar(select(Job).where(Job.asset_id == asset.id).order_by(Job.received_at.desc()))
        if last is not None:
            phone, name = last.customer_phone, last.customer_name or name
    return phone, email, name


def send_due_reminders(session: Session) -> int:
    """Queue the service reminders that are due: for businesses that switched them on, items whose next service date
    is within the reminder lead time and not yet reminded for that date. Returns how many were queued."""
    queued = 0
    for setting in session.scalars(select(JobSetting).where(JobSetting.remind_service_due)):
        today = company_today(session, setting.company_id)
        horizon = today + timedelta(days=setting.service_reminder_days)
        for asset in session.scalars(select(Asset).where(
                Asset.company_id == setting.company_id, Asset.is_active, Asset.next_service_date.is_not(None),
                Asset.next_service_date <= horizon,
                (Asset.service_reminded_for.is_(None)) | (Asset.service_reminded_for != Asset.next_service_date),
                Asset.next_service_date >= today - timedelta(days=60)).limit(500)):
            phone, email, name = _contact(session, asset)
            route = notify._route(session, asset.company_id, phone, email)
            if route is None or asset.next_service_date is None:
                continue
            channel, recipient = route
            made = send_templated(
                session, company_id=asset.company_id, channel=channel, recipient=recipient, template="job_service_due",
                variables={"customer": name, "item": asset.label,
                           "business": notify.business_name(session, asset.company_id),
                           "when": format_day(asset.next_service_date)},
                ref_type="jobs.asset", ref_id=asset.id, dedupe_key=f"service_due:{asset.id}:{asset.next_service_date}")
            asset.service_reminded_for = asset.next_service_date
            if made is not None:
                queued += 1
    session.flush()
    return queued
