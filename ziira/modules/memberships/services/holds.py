"""Putting a membership on hold and taking it off: a member's freeze (injury, travel) under the plan's rules, a hold the
business puts on, and the automatic hold for unpaid fees.

A held membership is not invoiced, its credits cannot be spent and it does not let anyone in. The days it was held are
added to the period when it resumes, so nothing is lost. Every hold is a row in `memberships.freeze`."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from ziira.modules.memberships.permissions import CREDITS, MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import billing, common, invoicing
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    publish,
)

KINDS = ("member", "business", "arrears")
WINDOW_DAYS = 365


def days_used(session: Session, member_id: UUID, today: date) -> int:
    """Days the member has been frozen at their own request in the last 12 months (a hold still running counts to
    today)."""
    closed = repo.scalar(session, "select coalesce(sum(days), 0) from memberships.freeze where member_id = :m "
                                  "and kind = 'member' and ended_on is not null and ended_on >= :s",
                         m=member_id, s=today - timedelta(days=WINDOW_DAYS))
    running = repo.one(session, "select started_on from memberships.freeze where member_id = :m and kind = 'member' "
                                "and ended_on is null", m=member_id)
    return int(closed) + ((today - running["started_on"]).days if running else 0)


def allowance(session: Session, member: repo.Row, today: date) -> dict[str, Any]:
    """The freeze allowance of a member's plan: the limit (None: no limit, 0: none allowed), used and left."""
    plan = repo.get(session, "plan", member["plan_id"]) or {}
    limit = plan.get("freeze_max_days")
    used = days_used(session, member["id"], today)
    return {"limit": limit, "used": used, "left": None if limit is None else max(limit - used, 0),
            "fee": plan.get("freeze_fee", 0), "allowed": plan.get("kind", "recurring") != "pass" and limit != 0}


def _event(session: Session, name: str, member: repo.Row, **extra: Any) -> None:
    publish(session, Event(name, "memberships.member", member["id"], {
        "company_id": member["company_id"], "branch_id": member["branch_id"], "customer_id": member["customer_id"],
        "member_id": member["id"], "plan_id": member["plan_id"], "number": member["number"], **extra}))


def start(session: Session, member: repo.Row, *, kind: str, resume_on: date | None, note: str | None,
          waive_fee: bool = False, enforce_rules: bool = True) -> repo.Row:
    """Hold an active membership (the caller has locked it and checked access). `member` kind follows the plan's freeze
    rules: a limit of days a year, and a fee invoiced at once. Returns the saved membership."""
    from ziira.modules.memberships.services import members

    today = common.today(session, member["company_id"])
    if member["status"] != "active":
        raise Conflict("Only an active membership can be paused")
    if resume_on is not None and resume_on <= today:
        raise ValidationFailed("The resume date must be in the future")
    plan = repo.get(session, "plan", member["plan_id"]) or {}
    fee = 0
    if kind == "member" and enforce_rules:
        if plan.get("kind") == "pass":
            raise ValidationFailed("A pass cannot be put on hold")
        limit = plan.get("freeze_max_days")
        if limit is not None:
            if limit == 0:
                raise ValidationFailed("This plan cannot be frozen")
            left = limit - days_used(session, member["id"], today)
            if left <= 0:
                raise ValidationFailed(f"All {limit} freeze days of the last 12 months are used")
            if resume_on is None:
                resume_on = today + timedelta(days=left)
            elif (resume_on - today).days > left:
                raise ValidationFailed(f"This plan allows {left} more freeze days (of {limit} a year)")
        fee = plan.get("freeze_fee", 0) or 0
    fee_charged = 0
    if fee and fee > 0:
        if waive_fee:
            common.require(CREDITS, member["company_id"], member["branch_id"])
        else:
            product = plan.get("service_product_id")
            if product is None or not invoicing.available(session):
                raise ValidationFailed("The freeze fee cannot be invoiced: the plan needs a service item to invoice "
                                       "it as, and Point of Sale and Invoices must be on")
            billing.bill_period(
                session, owner_type="freeze", owner_id=member["id"], company_id=member["company_id"],
                branch_id=member["branch_id"], customer_id=member["billing_customer_id"] or member["customer_id"],
                period_start=today, period_end=None,
                lines=[{"product_id": str(product), "description": f"Freeze fee, {member['plan_name']}",
                        "quantity": "1", "unit_price": str(fee), "discount": "0"}],
                due_days=None, memo=f"Freeze fee {member['number']}", raise_on_error=True)
            fee_charged = fee
    status = "paused" if kind == "member" else "frozen"
    saved = repo.update(session, "member", member["id"], {
        "status": status, "paused_from": today, "resume_on": resume_on, "hold_kind": kind})
    ctx = current_context()
    repo.insert(session, "freeze", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": member["company_id"],
        "member_id": member["id"], "kind": kind, "started_on": today, "planned_resume_on": resume_on,
        "fee": fee_charged, "reason": (note or "").strip()[:300] or None})
    members.note(session, member, {"member": "paused", "business": "frozen", "arrears": "frozen"}[kind], status, note)
    audit_record(session, "pause", "memberships.member", member["id"],
                 {"status": status, "kind": kind, "resume_on": str(resume_on), "fee": str(fee_charged)})
    _event(session, "membership.paused", saved, resume_on=resume_on, frozen=kind != "member", hold_kind=kind)
    return saved


def end(session: Session, member: repo.Row, day: date, note: str | None = None) -> repo.Row:
    """Take a held membership off hold on `day`: the days held are added to the renewal date, a fixed term and an end
    date."""
    from ziira.modules.memberships.services import members

    held = timedelta(days=max((day - (member["paused_from"] or day)).days, 0))
    values: repo.Row = {"status": "active", "paused_from": None, "resume_on": None, "hold_kind": None,
                        "next_renewal_date": member["next_renewal_date"] + held}
    for column in ("cancel_at", "term_end", "end_date"):
        if member[column] is not None:
            values[column] = member[column] + held
    saved = repo.update(session, "member", member["id"], values)
    repo.run(session, "update memberships.freeze set ended_on = :d, days = greatest(:n, 0) where member_id = :m "
                      "and ended_on is null", d=day, n=held.days, m=member["id"])
    members.note(session, member, "resumed", "active", note, day)
    audit_record(session, "resume", "memberships.member", member["id"], {"held_days": held.days})
    _event(session, "membership.resumed", saved, held_days=held.days)
    return saved


# --------------------------------------------------------------------------- with permission checks
def pause(session: Session, member_id: UUID, *, resume_on: date | None = None, frozen: bool = False,
          note: str | None = None, waive_fee: bool = False) -> repo.Row:
    """Hold a membership: no renewals and no credits can be spent until it resumes. `frozen` marks a hold the business
    put on (for example for unpaid fees); otherwise the member asked for it and the plan's freeze rules apply (days a
    year, a fee). Needs 'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    return start(session, member, kind="business" if frozen else "member", resume_on=resume_on, note=note,
                 waive_fee=waive_fee)


def resume(session: Session, member_id: UUID, *, today: date | None = None, note: str | None = None) -> repo.Row:
    """Start a held membership again. The days it was held are added to the period, so nothing is lost. Needs
    'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    if member["status"] not in ("paused", "frozen"):
        raise Conflict("This membership is not on hold")
    return end(session, member, today or common.today(session, member["company_id"]), note)


def history(session: Session, member_id: UUID) -> list[repo.Row]:
    common.get_row(session, "member", member_id, "Membership")
    return repo.many(session, "select * from memberships.freeze where member_id = :m order by started_on desc",
                     m=member_id)
