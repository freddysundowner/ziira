"""Use cases: members (a customer on a plan).

A membership copies the plan's price, interval, credits and discount when it starts, so changing the plan later never
rewrites what a member agreed to (a price change from a date is the one way to move members, and it is explicit). Each
period is invoiced once (billing.py) and grants the plan's credits once. Holds are in holds.py."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.memberships.domain import periods
from ziira.modules.memberships.permissions import CREDITS, MANAGE
from ziira.modules.memberships.repository import memberships_repo as repo
from ziira.modules.memberships.services import (
    billing,
    common,
    credits,
    holds,
    invoicing,
    plans,
    profiles,
)
from ziira.modules.memberships.services import values as values_service
from ziira.sdk import (
    Conflict,
    Event,
    Session,
    ValidationFailed,
    audit_record,
    check_company,
    check_reason,
    current_context,
    next_document_number,
    publish,
)

LIVE = ("active", "paused", "frozen")
MEMBERSHIP = credits.MEMBERSHIP


def _event(session: Session, name: str, member: repo.Row, **extra: Any) -> None:
    publish(session, Event(name, "memberships.member", member["id"], {
        "company_id": member["company_id"], "branch_id": member["branch_id"], "customer_id": member["customer_id"],
        "member_id": member["id"], "plan_id": member["plan_id"], "number": member["number"], **extra}))


def note(session: Session, member: repo.Row, action: str, to_status: str | None, text: str | None = None,
         day: date | None = None) -> None:
    """Write a line in the membership's history."""
    ctx = current_context()
    repo.history(session, member["id"], tenant_id=ctx.tenant_id, user_id=ctx.user_id, action=action,
                 from_status=member["status"], to_status=to_status or member["status"], note=text,
                 day=day or common.today(session, member["company_id"]))


_note = note


def with_balance(session: Session, rows: list[repo.Row]) -> list[repo.Row]:
    """Memberships with their credit balance, plan kind, the pending plan change, days late and who is billed."""
    if not rows:
        return []
    balance = repo.balances(session, [r["id"] for r in rows])
    plan_ids = {r["plan_id"] for r in rows} | {r["pending_plan_id"] for r in rows if r.get("pending_plan_id")}
    plan_rows = {p["id"]: p for p in repo.many(
        session, "select id, name, kind from memberships.plan where id = any(cast(:ids as uuid[]))",
        ids=[str(i) for i in plan_ids])}
    payers = common.customer_names(session, {r["billing_customer_id"] for r in rows if r.get("billing_customer_id")})
    today = common.today(session, rows[0]["company_id"])
    out: list[repo.Row] = []
    for r in rows:
        plan = plan_rows.get(r["plan_id"], {})
        pending = plan_rows.get(r.get("pending_plan_id"), {}) if r.get("pending_plan_id") else {}
        payer = payers.get(r["billing_customer_id"]) if r.get("billing_customer_id") else None
        late = (today - r["past_due_since"]).days if r.get("past_due_since") and r["arrears"] > 0 else 0
        out.append({**r, "balance": balance[r["id"]], "plan_kind": plan.get("kind", "recurring"),
                    "pending_plan_name": pending.get("name"), "days_late": max(late, 0),
                    "billing_customer_name": payer.name if payer else None})
    return out


def _fee_lines(member: repo.Row, amount: Decimal, start: date, end: date,
               extra: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    lines = [{"product_id": str(member["service_product_id"]),
              "description": f"{member['plan_name']} membership, {start} to {end - timedelta(days=1)}",
              "quantity": "1", "unit_price": str(amount), "discount": "0"}]
    return lines + (extra or [])


def _grant(session: Session, member: repo.Row, amount: Decimal, period_start: date) -> None:
    exists = repo.one(session, "select 1 as x from memberships.credit_entry where holder_id = :h "
                               "and entry_type = 'grant' and period_start = :p", h=member["id"], p=period_start)
    if amount > 0 and exists is None:
        credits.add_unchecked(session, member, MEMBERSHIP, "grant", amount, period_start=period_start,
                              note=f"Credits for the period starting {period_start}")


def _billing_customer(member: repo.Row) -> UUID:
    payer: UUID = member["billing_customer_id"] or member["customer_id"]
    return payer


def sign_up(session: Session, *, plan_id: UUID, customer_id: UUID, branch_id: UUID, start_date: date | None = None,
            end_date: date | None = None, auto_invoice: bool | None = None, notes: str | None = None,
            billing_customer_id: UUID | None = None, waive_joining_fee: bool = False,
            price: Decimal | None = None, voucher_code: str | None = None) -> repo.Row:
    """Start a customer on a plan: the first period's fee (and the joining fee) is invoiced when invoices are available
    and its credits granted. `auto_invoice` None: invoice when the plan has a fee, a service item to invoice it as, and
    invoices are on. A household or company payer is invoiced instead of the member. `price` overrides the plan's fee
    for this member (needs 'memberships.credits'). Needs 'memberships.manage' at the branch."""
    plan = common.get_row(session, "plan", plan_id, "Plan")
    company_id = plan["company_id"]
    common.require(MANAGE, company_id, branch_id)
    check_company(session, company_id, branch_id)
    if plan["status"] != "active":
        raise ValidationFailed("This plan is retired and cannot take new members")
    common.customer_of(session, company_id, customer_id)
    if plan["branch_ids"] and str(branch_id) not in plan["branch_ids"]:
        raise ValidationFailed("This plan is not sold at that branch")
    if repo.one(session, "select 1 as x from memberships.member where customer_id = :c and plan_id = :p "
                         "and status in ('active', 'paused', 'frozen')", c=customer_id, p=plan_id) is not None:
        raise Conflict("This customer already has a membership on this plan")
    today = common.today(session, company_id)
    start = start_date or today
    settings = repo.get_settings(session, company_id)
    pass_plan = plan["kind"] == "pass"
    if pass_plan:
        end_date = start + timedelta(days=int(plan["valid_days"] or 1))
        first = periods.FirstPeriod(start, end_date, Decimal(1))
    else:
        if end_date is not None and end_date <= start:
            raise ValidationFailed("The end date must be after the start date")
        prorate = settings["prorate_first_period"] if plan["prorate"] is None else plan["prorate"]
        first = periods.first_period(start, plan["billing_interval"], prorate=bool(prorate))
    list_fee = plans.fee_at(session, plan, start)
    if price is not None:
        common.require(CREDITS, company_id, branch_id)
        if price < 0:
            raise ValidationFailed("The price cannot be negative")
    agreed = list_fee if price is None else price
    fee = periods.prorated_amount(agreed, first.fraction)
    joining = Decimal(0) if (waive_joining_fee or pass_plan) else Decimal(plan["joining_fee"])
    if waive_joining_fee:
        common.require(CREDITS, company_id, branch_id)
    owed = fee + joining
    can_bill = owed > 0 and plan["service_product_id"] is not None and invoicing.available(session)
    if auto_invoice and owed > 0 and not can_bill:
        raise ValidationFailed("The fee cannot be invoiced: the plan needs a service item to invoice it as, and "
                               "Point of Sale and Invoices must be on")
    bill = can_bill if auto_invoice is None else (auto_invoice and can_bill)
    payer = billing_customer_id or profiles.billing_customer_of(session, customer_id)
    if payer is not None and payer != customer_id:
        common.customer_of(session, company_id, payer)
    else:
        payer = None
    ctx = current_context()
    term_end = (periods.shift(start, plan["billing_interval"], int(plan["term_periods"]))
                if plan["kind"] == "fixed_term" and plan["term_periods"] else None)
    member = repo.insert(session, "member", {
        "tenant_id": ctx.tenant_id, "created_by": ctx.user_id, "company_id": company_id, "branch_id": branch_id,
        "number": next_document_number(session, company_id=company_id, branch_id=None, doc_type="membership",
                                       prefix="MEM"),
        "customer_id": customer_id, "plan_id": plan_id, "plan_name": plan["name"], "status": "active",
        "start_date": start, "current_period_start": start, "next_renewal_date": first.end,
        "anchor_day": first.end.day if first.fraction != 1 else start.day, "end_date": end_date,
        "price": agreed, "billing_interval": plan["billing_interval"],
        "credits_per_period": plan["credits_per_period"], "discount_percent": plan["discount_percent"],
        "covered_services": plan["covered_services"], "rollover": plan["rollover"],
        "service_product_id": plan["service_product_id"], "auto_invoice": bill and not pass_plan,
        "notes": (notes or "").strip() or None, "billing_customer_id": payer, "term_end": term_end,
        "is_trial": bool(plan["is_trial"]), "price_locked": price is not None,
        "joining_fee_charged": joining if bill else 0})
    profile = profiles.ensure_profile(session, company_id, customer_id, branch_id=branch_id)
    if bill:
        extra: list[dict[str, str]] = []
        if joining > 0:
            product = plan["joining_fee_product_id"] or plan["service_product_id"]
            extra.append({"product_id": str(product), "description": f"Joining fee, {plan['name']}", "quantity": "1",
                          "unit_price": str(joining), "discount": "0"})
        lines = _fee_lines(member, fee, start, first.end, extra) if fee > 0 else extra
        billing.bill_period(
            session, owner_type="member", owner_id=member["id"], company_id=company_id, branch_id=branch_id,
            customer_id=_billing_customer(member), period_start=start, period_end=first.end, lines=lines,
            due_days=None, memo=f"Membership {member['number']}", raise_on_error=True, voucher_code=voucher_code)
    _grant(session, member, periods.prorated_credits(plan["credits_per_period"], first.fraction), start)
    _note(session, {**member, "status": "new"}, "started", "active", day=start)
    if plan["is_trial"]:
        profiles.set_lifecycle(session, profile["id"], "trial", trial_ends_on=end_date)
    profiles.refresh_lifecycle(session, customer_id)
    audit_record(session, "create", "memberships.member", member["id"],
                 {"plan": plan["code"], "customer": str(customer_id)})
    _event(session, "membership.activated", member, start_date=start, next_renewal_date=first.end,
           plan_kind=plan["kind"], trial=bool(plan["is_trial"]))
    if not plan["is_trial"]:
        values_service.reward_referrer(session, profile)
    return with_balance(session, [member])[0]


def get_member(session: Session, member_id: UUID) -> repo.Row:
    return with_balance(session, [common.get_row(session, "member", member_id, "Membership")])[0]


def list_members(session: Session, *, company_id: UUID | None = None, branch_id: UUID | None = None,
                 status: str | None = None, plan_id: UUID | None = None, customer_id: UUID | None = None,
                 renewing_from: date | None = None, renewing_to: date | None = None, past_due: bool | None = None,
                 limit: int = 50, offset: int = 0) -> list[repo.Row]:
    clause, params = repo.scope_sql(common.view_scopes())
    rows = repo.many(
        session,
        f"select * from memberships.member where {clause} and (cast(:c as uuid) is null or company_id = :c) "
        "and (cast(:b as uuid) is null or branch_id = :b) and (cast(:s as text) is null or status = :s) "
        "and (cast(:p as uuid) is null or plan_id = :p) and (cast(:cu as uuid) is null or customer_id = :cu) "
        "and (cast(:rf as date) is null or (status = 'active' and next_renewal_date >= :rf)) "
        "and (cast(:rt as date) is null or (status = 'active' and next_renewal_date <= :rt)) "
        "and (cast(:pd as boolean) is null or (past_due_since is not null and arrears > 0) = :pd) "
        "order by case status when 'active' then 0 when 'paused' then 1 when 'frozen' then 1 else 2 end, "
        "next_renewal_date, number limit :l offset :o",
        c=company_id, b=branch_id, s=status, p=plan_id, cu=customer_id, rf=renewing_from, rt=renewing_to,
        pd=past_due, l=min(limit, 200), o=offset, **params)
    return with_balance(session, rows)


def history(session: Session, member_id: UUID) -> list[repo.Row]:
    common.get_row(session, "member", member_id, "Membership")
    return repo.many(session, "select * from memberships.member_history where member_id = :m "
                              "order by seq desc", m=member_id)


def update_member(session: Session, member_id: UUID, *, notes: str | None = None, auto_invoice: bool | None = None,
                  price_locked: bool | None = None, billing_customer_id: UUID | None = None,
                  clear_billing_customer: bool = False) -> repo.Row:
    """Change a member's notes, whether renewals are invoiced automatically, whether a later price change applies to
    them,
    or who is invoiced. Needs 'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    values: repo.Row = {}
    if notes is not None:
        values["notes"] = notes.strip() or None
    if auto_invoice is not None:
        values["auto_invoice"] = auto_invoice
    if price_locked is not None:
        values["price_locked"] = price_locked
    if billing_customer_id is not None:
        common.customer_of(session, member["company_id"], billing_customer_id)
        values["billing_customer_id"] = None if billing_customer_id == member["customer_id"] else billing_customer_id
    elif clear_billing_customer:
        values["billing_customer_id"] = None
    saved = repo.update(session, "member", member_id, {**values, "updated_by": current_context().user_id})
    audit_record(session, "update", "memberships.member", member_id, {k: str(v) for k, v in values.items()})
    return with_balance(session, [saved])[0]


# --------------------------------------------------------------------------- cancel
def earliest_end(session: Session, member: repo.Row, plan: repo.Row, today: date) -> date:
    """The first renewal date a cancellation can take effect: after the plan's notice period and any minimum term."""
    when = member["next_renewal_date"]
    notice = int(plan.get("notice_days") or 0)
    guard = 0
    while ((notice > 0 and when < today + timedelta(days=notice))
           or (member["term_end"] is not None and when < member["term_end"])) and guard < 200:
        when = periods.shift(when, member["billing_interval"], 1, member["anchor_day"])
        guard += 1
    result: date = when
    return result


def cancel(session: Session, member_id: UUID, *, reason_code_id: UUID | None, note: str | None = None,
           at_period_end: bool = True, waive_exit_fee: bool = False) -> repo.Row:
    """End a membership: at the end of the period already paid for (default; later if the plan has a notice period or a
    minimum term that is not over) or now. Ending now inside a minimum term charges the plan's early-exit fee unless
    it is
    waived (needs 'memberships.credits'). A reason is required. Needs 'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    if member["status"] not in LIVE:
        raise Conflict("This membership has already ended")
    check_reason(session, "membership_cancel", reason_code_id, note)
    plan = repo.get(session, "plan", member["plan_id"]) or {}
    today = common.today(session, member["company_id"])
    values: repo.Row = {"cancel_reason_code_id": reason_code_id, "cancel_note": (note or "").strip()[:300] or None}
    if at_period_end and member["status"] == "active":
        when = earliest_end(session, member, plan, today)
        saved = repo.update(session, "member", member_id, {**values, "cancel_at": when})
        _note(session, member, "cancel_requested", None, note)
        audit_record(session, "cancel_requested", "memberships.member", member_id,
                     {"cancel_at": str(saved["cancel_at"])})
        profiles.refresh_lifecycle(session, member["customer_id"])
        return with_balance(session, [saved])[0]
    exit_fee = Decimal(plan.get("early_exit_fee") or 0)
    if member["term_end"] is not None and member["term_end"] > today and exit_fee > 0:
        if waive_exit_fee:
            common.require(CREDITS, member["company_id"], member["branch_id"])
        elif plan.get("service_product_id") is None or not invoicing.available(session):
            raise ValidationFailed("The early-exit fee cannot be invoiced: the plan needs a service item to invoice "
                                   "it as, and Point of Sale and Invoices must be on")
        else:
            billing.bill_period(
                session, owner_type="exit", owner_id=member_id, company_id=member["company_id"],
                branch_id=member["branch_id"], customer_id=_billing_customer(member), period_start=today,
                period_end=None, lines=[{"product_id": str(plan["service_product_id"]),
                                         "description": f"Early exit, {member['plan_name']}", "quantity": "1",
                                         "unit_price": str(exit_fee), "discount": "0"}],
                due_days=None, memo=f"Early exit {member['number']}", raise_on_error=True)
    if member["status"] != "active":
        holds.end(session, member, today)
        member = repo.get(session, "member", member_id, lock=True) or member
    return with_balance(session, [_end(session, member, "cancelled", values, note)])[0]


def undo_cancel(session: Session, member_id: UUID) -> repo.Row:
    """Take back a cancellation that has not happened yet. Needs 'memberships.manage'."""
    member = common.get_row(session, "member", member_id, "Membership", lock=True)
    common.require(MANAGE, member["company_id"], member["branch_id"])
    if member["cancel_at"] is None or member["status"] not in LIVE:
        raise Conflict("This membership is not due to be cancelled")
    saved = repo.update(session, "member", member_id, {"cancel_at": None, "cancel_reason_code_id": None,
                                                       "cancel_note": None})
    _note(session, member, "cancel_withdrawn", None)
    profiles.refresh_lifecycle(session, member["customer_id"])
    return with_balance(session, [saved])[0]


def _end(session: Session, member: repo.Row, status: str, values: repo.Row, note_text: str | None) -> repo.Row:
    """Move a membership to cancelled or expired and write off the credits left."""
    today = common.today(session, member["company_id"])
    saved = repo.update(session, "member", member["id"], {
        **values, "status": status, "paused_from": None, "resume_on": None, "cancelled_on": today, "hold_kind": None,
        "pending_plan_id": None, "pending_from": None})
    left = credits.expire_leftover(session, saved, MEMBERSHIP, note=f"Membership {status}")
    _note(session, member, status, status, note_text)
    audit_record(session, status, "memberships.member", member["id"], {"credits_written_off": str(left)})
    _event(session, f"membership.{status}", saved, credits_written_off=left)
    profiles.refresh_lifecycle(session, member["customer_id"])
    return saved


# --------------------------------------------------------------------------- the recurring task's work
def _apply_pending_plan(session: Session, member: repo.Row, start: date) -> repo.Row:
    """A plan change booked for this renewal takes effect now: the member's snapshot becomes the new plan's."""
    plan = repo.get(session, "plan", member["pending_plan_id"])
    if plan is None or plan["status"] != "active":
        return repo.update(session, "member", member["id"], {"pending_plan_id": None, "pending_from": None})
    saved = repo.update(session, "member", member["id"], {
        "plan_id": plan["id"], "plan_name": plan["name"], "price": plans.fee_at(session, plan, start),
        "billing_interval": plan["billing_interval"], "credits_per_period": plan["credits_per_period"],
        "discount_percent": plan["discount_percent"], "covered_services": plan["covered_services"],
        "rollover": plan["rollover"], "service_product_id": plan["service_product_id"], "price_locked": False,
        "pending_plan_id": None, "pending_from": None, "is_trial": bool(plan["is_trial"])})
    _note(session, member, "plan_changed", None, f"Changed to {plan['name']}", start)
    _event(session, "membership.plan_changed", saved, from_plan_id=member["plan_id"], to_plan_id=plan["id"])
    return saved


def _scheduled_price(session: Session, member: repo.Row, start: date) -> Decimal | None:
    """The price a scheduled change (applying to existing members) sets for the period starting `start`, if it differs
    from what the member pays. Price-locked members keep theirs."""
    if member["price_locked"]:
        return None
    found = repo.one(session, "select fee from memberships.plan_price_change where plan_id = :p and status = 'scheduled' "  # noqa: E501
                              "and apply_to_existing and effective_from <= :d order by effective_from desc limit 1",
                     p=member["plan_id"], d=start)
    if found is None or Decimal(found["fee"]) == Decimal(member["price"]):
        return None
    return Decimal(found["fee"])


def process_member(session: Session, member_id: UUID, today: date | None = None) -> str:
    """Do what is due for a membership today: resume it, end it, or renew it (invoice the new period, write off unused
    credits, grant the new ones). Each period happens once. Returns what was done: 'none', 'resumed', 'renewed',
    'cancelled', 'expired' or 'blocked' (a renewal invoice failed; it is tried again at the next run)."""
    member = repo.get(session, "member", member_id, lock=True)
    if member is None:
        return "none"
    day = today or common.today(session, member["company_id"])
    if member["status"] in ("paused", "frozen"):
        if member["resume_on"] is not None and member["resume_on"] <= day:
            holds.end(session, member, member["resume_on"])
            return "resumed"
        return "none"
    if member["status"] != "active":
        return "none"
    settings = repo.get_settings(session, member["company_id"])
    result, skipped, guard = "none", 0, 0
    while member["status"] == "active" and member["next_renewal_date"] <= day and guard < 60:
        guard += 1
        start = member["next_renewal_date"]
        if member["cancel_at"] is not None and member["cancel_at"] <= start:
            member = _end(session, member, "cancelled", {}, member["cancel_note"])
            return "cancelled"
        if member["end_date"] is not None and start >= member["end_date"]:
            member = _end(session, member, "expired", {}, "The membership reached its end date")
            return "expired"
        if member["pending_plan_id"] is not None and member["pending_from"] is not None \
                and member["pending_from"] <= start:
            member = _apply_pending_plan(session, member, start)
        new_price = _scheduled_price(session, member, start)
        if new_price is not None:
            member = repo.update(session, "member", member["id"], {"price": new_price})
            _note(session, member, "price_changed", None, f"New price {new_price} from {start}", start)
        end = periods.shift(start, member["billing_interval"], 1, member["anchor_day"])
        behind = _periods_behind(member, day)
        if behind > int(settings["catch_up_max_periods"]):
            skipped += 1
            billing.skip_period(
                session, owner_type="member", owner_id=member["id"], company_id=member["company_id"],
                branch_id=member["branch_id"], customer_id=_billing_customer(member), period_start=start,
                period_end=end, message=f"Membership {member['number']}: the period starting {start} was not renewed "
                                        "because more periods were missed than the company allows catching up")
        else:
            if member["auto_invoice"] and member["price"] > 0:
                run = billing.bill_period(
                    session, owner_type="member", owner_id=member["id"], company_id=member["company_id"],
                    branch_id=member["branch_id"], customer_id=_billing_customer(member), period_start=start,
                    period_end=end, lines=_fee_lines(member, member["price"], start, end), due_days=None,
                    memo=f"Membership {member['number']}")
                if run["status"] == "failed":
                    return "blocked"
            if not member["rollover"]:
                credits.expire_leftover(session, member, MEMBERSHIP, note="Unused credits at the end of the period",
                                        day=start)
            _grant(session, member, member["credits_per_period"], start)
            result = "renewed"
            _event(session, "membership.renewed", member, period_start=start, period_end=end)
        _note(session, member, "renewed" if result == "renewed" else "skipped_period", None, None, start)
        member = repo.update(session, "member", member["id"], {"current_period_start": start, "next_renewal_date": end})
    if member["status"] == "active" and member["end_date"] is not None and member["end_date"] <= day:
        _end(session, member, "expired", {}, "The membership reached its end date")
        return "expired"
    if skipped:
        result = "renewed" if result == "renewed" else "skipped"
    return result


def _periods_behind(member: repo.Row, day: date) -> int:
    """How many periods, counting the one about to be renewed, have started on or before `day`."""
    count, start = 0, member["next_renewal_date"]
    while start <= day and count < 1000:
        count += 1
        start = periods.shift(start, member["billing_interval"], 1, member["anchor_day"])
    return count
