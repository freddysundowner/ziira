"""Messages to the customer about a job. Always queued through the notification layer, never sent in the request, and
nothing goes to someone on the do-not-contact list (the kernel checks)."""

from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Asset, Job
from ziira.modules.jobs.services.common import add_event, unit_enabled
from ziira.sdk import Session, company_setting, configured_channels, send_templated


def _contact(session: Session, job: Job) -> tuple[str | None, str | None]:
    """(phone, email) of the customer: the customer record's when there is one, else what the job kept."""
    phone, email = job.customer_phone, None
    if job.customer_id is not None and unit_enabled(session, "crm"):
        from ziira.modules.crm.public import find_customer

        record = find_customer(session, job.customer_id)
        if record is not None:
            phone, email = record.phone or phone, record.email
    return phone, email


def _route(session: Session, company_id: UUID, phone: str | None, email: str | None) -> tuple[str, str] | None:
    """The channel and address to use: the business's reminder channel when it is set up, else SMS, else email."""
    ready = configured_channels(session, company_id)
    wanted = str(company_setting(session, company_id, "reminder_channel"))
    if wanted != "off" and wanted in ready and wanted != "email" and phone:
        return wanted, phone
    if phone and "sms" in ready:
        return "sms", phone
    if email and "email" in ready:
        return "email", email
    return None


def item_name(session: Session, job: Job) -> str:
    asset = repo.get(session, Asset, job.asset_id) if job.asset_id else None
    return asset.label if asset is not None else job.title


def business_name(session: Session, company_id: UUID) -> str:
    return str(session.execute(text("select name from kernel.company where id = :c"),
                               {"c": str(company_id)}).scalar_one())


def tell_customer_ready(session: Session, job: Job) -> bool:
    """Queue the 'your item is ready' message if the business wants it and can reach the customer. True when queued."""
    from ziira.modules.jobs.services.settings import get_settings

    if not get_settings(session, job.company_id).tell_customer_when_ready:
        return False
    stamp = int(job.status_changed_at.timestamp())
    return send_to_customer(session, job, "job_ready", {}, key=f"job_ready:{job.id}:{stamp}")


def send_to_customer(session: Session, job: Job, template: str, extra: dict[str, str], *, key: str) -> bool:
    """Queue a shipped template to the job's customer. Notes on the timeline when there was no way to reach them."""
    phone, email = _contact(session, job)
    route = _route(session, job.company_id, phone, email)
    if route is None:
        add_event(session, job, "note", "The customer could not be messaged: no phone or email, or no message "
                                        "channel is set up")
        return False
    channel, recipient = route
    fallbacks = [{"channel": "email", "recipient": email}] if email and channel != "email" \
        and "email" in configured_channels(session, job.company_id) else []
    queued = send_templated(
        session, company_id=job.company_id, channel=channel, recipient=recipient, template=template,
        variables={"customer": job.customer_name or "", "job": job.number, "item": item_name(session, job),
                   "business": business_name(session, job.company_id), **extra},
        fallbacks=fallbacks, ref_type="job", ref_id=job.id, dedupe_key=key)
    return queued is not None


def send_ready_reminders(session: Session) -> int:
    """Remind customers whose finished item is still waiting: for businesses that switched it on, jobs that have been
    in the ready stage for the set number of days. Queued once per job and ready spell (the notification layer drops a
    repeat). Returns how many were queued."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from ziira.modules.jobs.repository.models import JobSetting

    queued = 0
    for setting in session.scalars(select(JobSetting).where(JobSetting.ready_reminder_days > 0)):
        cutoff = datetime.now(UTC) - timedelta(days=setting.ready_reminder_days)
        for job in session.scalars(select(Job).where(
                Job.company_id == setting.company_id, Job.ready_at.is_not(None), Job.ready_at <= cutoff,
                Job.collected_at.is_(None), Job.closed_at.is_(None)).limit(300)):
            stamp = int(job.ready_at.timestamp()) if job.ready_at else 0
            if send_to_customer(session, job, "job_pickup_reminder", {}, key=f"job_pickup:{job.id}:{stamp}"):
                queued += 1
    return queued
