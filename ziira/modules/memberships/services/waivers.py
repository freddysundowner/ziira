"""The terms or waiver a member accepts: versions (never edited) and who accepted which one, when and how.

No health data is asked for or kept: this is the business's own terms text (and any liability wording the owner
writes). A change of wording is a new version; members who accepted an older one are asked again."""

from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.memberships.permissions import MANAGE, PLANS
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import common, profiles
from ziira.sdk import Session, ValidationFailed, audit_record, check_company, current_context

METHODS = ("desk", "kiosk", "online")


def current_version(session: Session, company_id: UUID) -> repo.Row | None:
    return repo.one(session, "select * from memberships.waiver_version where company_id = :c "
                             "order by version desc limit 1", c=company_id)


def list_versions(session: Session, company_id: UUID) -> list[repo.Row]:
    common.check_visible(company_id, None, "Company")
    return repo.many(session, "select * from memberships.waiver_version where company_id = :c order by version desc",
                     c=company_id)


def publish_version(session: Session, *, company_id: UUID, title: str, body: str) -> repo.Row:
    """Make new wording the current terms. Everyone is asked to accept it again. Needs 'memberships.plans'."""
    common.require(PLANS, company_id)
    check_company(session, company_id)
    if not title.strip() or not body.strip():
        raise ValidationFailed("The terms need a title and some wording")
    session.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"waiver:{company_id}"})
    latest = current_version(session, company_id)
    ctx = current_context()
    version = repo.insert(session, "waiver_version", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id,
        "version": (latest["version"] + 1) if latest else 1, "title": title.strip()[:200], "body": body.strip()})
    audit_record(session, "publish", "memberships.waiver_version", version["id"], {"version": version["version"]})
    return version


def status_of(session: Session, customer_id: UUID) -> dict[str, Any]:
    """What the customer has accepted: the current version, whether they accepted it, and when."""
    customer = common.customer_of_any(session, customer_id)
    common.check_visible(customer.company_id, None, "Member")
    current = current_version(session, customer.company_id)
    accepted = repo.many(session, "select a.*, (select u.full_name from kernel.app_user u where u.id = a.created_by) "
                                  "as recorded_by_name from memberships.waiver_acceptance a where a.customer_id = :c "
                                  "order by a.accepted_at desc", c=customer_id)
    return {"customer_id": customer_id, "current_version": current["version"] if current else None,
            "current_title": current["title"] if current else None,
            "accepted_current": current is not None and any(a["version_id"] == current["id"] for a in accepted),
            "acceptances": accepted}


def accept(session: Session, customer_id: UUID, *, accepted_name: str, method: str = "desk",
           note: str | None = None, version: int | None = None) -> repo.Row:
    """Record that the person accepted the terms (the current version unless one is named): the name they typed, when,
    how, and who recorded it. Accepting twice records nothing new. Needs 'memberships.manage'."""
    customer = common.customer_of_any(session, customer_id)
    common.require_in_company(MANAGE, customer.company_id)
    if method not in METHODS:
        raise ValidationFailed("Accepted at the desk, the kiosk or online")
    name = " ".join(accepted_name.split())[:200]
    if not name:
        raise ValidationFailed("Type the name of the person who accepts")
    chosen = (current_version(session, customer.company_id) if version is None else repo.one(
        session, "select * from memberships.waiver_version where company_id = :c and version = :v",
        c=customer.company_id, v=version))
    if chosen is None:
        raise ValidationFailed("There are no terms to accept yet")
    found = repo.one(session, "select * from memberships.waiver_acceptance where customer_id = :c and version_id = :v",
                     c=customer_id, v=chosen["id"])
    if found is not None:
        return found
    profiles.ensure_profile(session, customer.company_id, customer_id)
    ctx = current_context()
    made = repo.insert(session, "waiver_acceptance", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": customer.company_id,
        "customer_id": customer_id, "version_id": chosen["id"], "version": chosen["version"], "accepted_name": name,
        "method": method, "note": (note or "").strip()[:300] or None})
    audit_record(session, "accept", "memberships.waiver_acceptance", made["id"],
                 {"customer": str(customer_id), "version": chosen["version"], "method": method})
    return made


def accepted_current(session: Session, company_id: UUID, customer_id: UUID) -> bool:
    """True when there are no terms, or the customer accepted the current ones."""
    current = current_version(session, company_id)
    if current is None:
        return True
    return repo.one(session, "select 1 as x from memberships.waiver_acceptance where customer_id = :c "
                             "and version_id = :v", c=customer_id, v=current["id"]) is not None
