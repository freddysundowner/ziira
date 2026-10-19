"""Moving a member to another plan: an upgrade now with the difference charged for the days left, or a change that
starts
at the next renewal (always the case for a cheaper plan: no money goes back mid-period).

The member's snapshot (price, credits, discount, covered services) becomes the new plan's. History keeps the old
plan."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.memberships.domain import periods
from ziira.modules.memberships.permissions import MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import billing, common, credits, invoicing, members, plans
from ziira.sdk import Conflict, Event, Session, ValidationFailed, audit_record, publish


def _fraction_left(member: repo.Row, today: date) -> Decimal:
    total = (member["next_renewal_date"] - member["current_period_start"]).days
    left = (member["next_renewal_date"] - today).days
    if total <= 0 or left <= 0:
        return Decimal(0)
    return min(Decimal(left) / Decimal(total), Decimal(1))


def quote(session: Session, member_id: UUID, new_plan_id: UUID) -> dict[str, Any]:
    """What changing to another plan would mean today: the fraction of the period left, the charge now for an
    upgrade, and
    whether it can start now or only at the next renewal. Changes nothing."""
    member = common.get_row(session, "member", member_id, "Membership")
    new = common.get_row(session, "plan", new_plan_id, "Plan")
    today = common.today(session, member["company_id"])
    fraction = _fraction_left(member, today)
    new_price = plans.fee_at(session, new, today)
    old_price = Decimal(member["price"])
    same_interval = new["billing_interval"] == member["billing_interval"]
    difference = periods.prorated_amount(new_price - old_price, fraction) if same_interval else Decimal(0)
    can_now = (member["status"] == "active" and same_interval and difference >= 0 and new_price >= old_price
               and member["current_period_start"] <= today)
    extra_credits = max(Decimal(new["credits_per_period"]) - Decimal(member["credits_per_period"]), Decimal(0))
    return {"member_id": member_id, "from_plan": member["plan_name"], "to_plan": new["name"],
            "period_fraction_left": fraction, "old_price": old_price, "new_price": new_price,
            "charge_now": difference if can_now else Decimal(0), "can_start_now": can_now,
            "extra_credits_now": periods.prorated_credits(extra_credits, fraction) if can_now else Decimal(0),
            "starts_on": today if can_now else member["next_renewal_date"],
            "reason": None if can_now else (
                "A plan with a different billing period starts at the next renewal" if not same_interval else
                "A cheaper plan starts at the next renewal: nothing is refunded for the current period"
                if new_price < old_price else None)}


def change_plan(session: Session, member_id: UUID, new_plan_id: UUID, *, when: str = "now",
                note: str | None = None) -> repo.Row:
    """Change a member's plan. `when="now"` is an upgrade: the difference for the days left in the period is invoiced
    and
    the extra credits for those days granted. `when="next_renewal"` records the change and applies it at the next
    renewal. Needs 'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    if member["status"] != "active":
        raise Conflict("Only an active membership can change plan")
    new = common.get_row(session, "plan", new_plan_id, "Plan")
    if new["company_id"] != member["company_id"]:
        raise ValidationFailed("That plan belongs to another company")
    if new["status"] != "active":
        raise ValidationFailed("That plan is retired")
    if new["id"] == member["plan_id"]:
        raise ValidationFailed("The member is already on this plan")
    if new["kind"] == "pass":
        raise ValidationFailed("A pass is bought, not switched to")
    if repo.one(session, "select 1 as x from memberships.member where customer_id = :c and plan_id = :p "
                         "and status in ('active', 'paused', 'frozen')", c=member["customer_id"], p=new["id"]):
        raise Conflict("This customer already has a membership on that plan")
    if when not in ("now", "next_renewal"):
        raise ValidationFailed("A plan change starts now or at the next renewal")
    today = common.today(session, member["company_id"])
    if when == "next_renewal":
        saved = repo.update(session, "member", member_id, {"pending_plan_id": new["id"],
                                                           "pending_from": member["next_renewal_date"]})
        members.note(session, member, "plan_change_booked", None,
                     f"{new['name']} from {member['next_renewal_date']}" + (f". {note}" if note else ""))
        audit_record(session, "plan_change_booked", "memberships.member", member_id,
                     {"to": new["code"], "from": str(member["next_renewal_date"])})
        return members.with_balance(session, [saved])[0]
    q = quote(session, member_id, new_plan_id)
    if not q["can_start_now"]:
        raise ValidationFailed(q["reason"] or "This change cannot start now: book it for the next renewal")
    charge = Decimal(q["charge_now"])
    if charge > 0:
        if member["service_product_id"] is None or not invoicing.available(session):
            raise ValidationFailed("The difference cannot be invoiced: the plan needs a service item to invoice it "
                                   "as, and Point of Sale and Invoices must be on")
        billing.bill_period(
            session, owner_type="change", owner_id=member_id, company_id=member["company_id"],
            branch_id=member["branch_id"], customer_id=member["billing_customer_id"] or member["customer_id"],
            period_start=today, period_end=member["next_renewal_date"],
            lines=[{"product_id": str(member["service_product_id"]),
                    "description": f"Change from {member['plan_name']} to {new['name']}, {today} to "
                                   f"{member['next_renewal_date']}", "quantity": "1", "unit_price": str(charge),
                    "discount": "0"}],
            due_days=None, memo=f"Plan change {member['number']}", raise_on_error=True, credit_eligible=False)
    saved = repo.update(session, "member", member_id, {
        "plan_id": new["id"], "plan_name": new["name"], "price": q["new_price"],
        "billing_interval": new["billing_interval"], "credits_per_period": new["credits_per_period"],
        "discount_percent": new["discount_percent"], "covered_services": new["covered_services"],
        "rollover": new["rollover"], "service_product_id": new["service_product_id"], "price_locked": False,
        "is_trial": bool(new["is_trial"]), "pending_plan_id": None, "pending_from": None})
    extra = Decimal(q["extra_credits_now"])
    if extra > 0:
        credits.add_unchecked(session, saved, credits.MEMBERSHIP, "adjustment", extra,
                              note=f"Upgrade to {new['name']}: credits for the days left")
    members.note(session, member, "plan_changed", None,
                 f"{member['plan_name']} to {new['name']}" + (f". {note}" if note else ""))
    audit_record(session, "plan_changed", "memberships.member", member_id,
                 {"from": member["plan_name"], "to": new["name"], "charge": str(charge)})
    publish(session, Event("membership.plan_changed", "memberships.member", member_id, {
        "company_id": member["company_id"], "branch_id": member["branch_id"], "customer_id": member["customer_id"],
        "member_id": member_id, "plan_id": new["id"], "from_plan_id": member["plan_id"], "number": member["number"],
        "charge": charge}))
    return members.with_balance(session, [saved])[0]


def undo_pending(session: Session, member_id: UUID) -> repo.Row:
    """Take back a plan change booked for the next renewal."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    if member["pending_plan_id"] is None:
        raise Conflict("No plan change is booked")
    saved = repo.update(session, "member", member_id, {"pending_plan_id": None, "pending_from": None})
    members.note(session, member, "plan_change_withdrawn", None)
    return members.with_balance(session, [saved])[0]
