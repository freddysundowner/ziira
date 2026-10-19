"""The customer's own page for an estimate: opened from a link, without signing in.

The link holds `<business id>.<secret>`; only a hash of the secret is stored, it works for one answer, and it shows
nothing but the estimate (no customer details, no costs). Every use is rate limited. A wrong, used or replaced link is
answered the same way as one that never existed.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.jobs.repository import jobs_repo as repo
from ziira.modules.jobs.repository.models import Estimate, Job
from ziira.modules.jobs.services import estimates, notify
from ziira.sdk import (
    NotFound,
    Session,
    ValidationFailed,
    company_today,
    files,
    hash_secret,
    rate_limit,
    system_session,
)


def _enabled(session: Session) -> bool:
    return session.execute(text(
        "select 1 from kernel.tenant_unit where unit_name = 'jobs' and status = 'enabled' "
        "and tenant_id = kernel.current_tenant()")).first() is not None


def _tenant_of(token: str) -> UUID:
    try:
        return UUID(hex=token.partition(".")[0])
    except ValueError:
        raise NotFound("This link is not valid") from None


def _find(session: Session, token: str) -> tuple[Estimate, Job]:
    found = repo.estimate_by_link(session, hash_secret(token)) if _enabled(session) else None
    if found is None:
        raise NotFound("This link is not valid or has already been used")
    job = repo.get(session, Job, found.job_id)
    assert job is not None
    return found, job


def _state(session: Session, estimate: Estimate, job: Job) -> str:
    if estimate.status == "sent":
        return "expired" if estimate.valid_until and estimate.valid_until < company_today(session, job.company_id) \
            else "open"
    return estimate.status


def view(token: str, ip_address: str | None) -> dict[str, Any]:
    """What the customer sees: the estimate, its lines and totals, and whether it can still be answered."""
    rate_limit("job-approval", token, ip_address, per_subject=40, per_ip=200)
    with system_session(_tenant_of(token)) as session:
        estimate, job = _find(session, token)
        currency = session.execute(text("select base_currency from kernel.company where id = :c"),
                                   {"c": str(job.company_id)}).scalar_one()
        shown = [{"id": f.id, "category": f.category, "caption": f.caption, "kind": f.kind, "name": f.name,
                  "thumb_path": f.thumb.path if f.thumb else None, "web_path": f.web.path if f.web else None,
                  "original_path": f.original.path}
                 for f in files.public_links(session, "jobs.job", job.id, label=f"approval {job.number}")]
        return {
            "photos": shown,
            "business": notify.business_name(session, job.company_id), "currency": currency, "job_number": job.number,
            "item": notify.item_name(session, job), "title": job.title, "version": estimate.version,
            "kind": estimate.kind,
            "state": _state(session, estimate, job), "notes": estimate.notes, "valid_until": estimate.valid_until,
            "net": estimate.net, "tax": estimate.tax, "total": estimate.total,
            "lines": [{"description": x.description, "quantity": x.quantity, "unit_price": x.unit_price,
                       "total": x.net + x.tax, "part_class": x.part_class}
                      for x in repo.estimate_lines(session, estimate.id)]}


def answer(token: str, ip_address: str | None, *, approve: bool, name: str, note: str | None) -> dict[str, Any]:
    """The customer approves or declines. One answer per link."""
    rate_limit("job-approval", token, ip_address, per_subject=40, per_ip=200)
    if not name.strip():
        raise ValidationFailed("Please type your name")
    with system_session(_tenant_of(token)) as session:
        estimate, job = _find(session, token)
        if _state(session, estimate, job) != "open":
            raise ValidationFailed("This estimate can no longer be answered. Please contact the business")
        estimates.apply_decision(session, job, estimate, approved=approve, channel="link", by_user=None,
                                 by_name=name.strip()[:160], note=note)
        files.revoke_links_for_entity(session, "jobs.job", job.id)       # the link is used: its photo addresses stop
        return {"state": estimate.status}
