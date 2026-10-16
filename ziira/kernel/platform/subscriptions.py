"""Subscriptions: a business's plan, price and status (docs/platform-admin.md, "Subscriptions").

A subscription copies the plan's units and limits and the price it was sold at, so later edits of the plan or price list
do not change what a subscriber has agreed (use `sync_to_plan` to move one over on purpose). Its life:

    trialing -> active -> past_due -> grace -> suspended -> expired       (money not received, by the dunning schedule)
    active -> cancelled                                                    (cancel at period end, or now)
    any -> active                                                          (an invoice is paid, or an operator
    reactivates)

Nothing here deletes a business's data. Enforcement of the status is `entitlements.py`; invoices are `billing.py`.
"""

import calendar
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import audit, editions
from ziira.kernel.config import get_settings
from ziira.kernel.context import system_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.errors import Conflict, DependencyError, NotFound, ValidationFailed
from ziira.kernel.platform import entitlements, plans, settings
from ziira.kernel.registry import Registry, discover, install_order

log = logging.getLogger("ziira.subscriptions")

STATUSES = ("trialing", "active", "past_due", "grace", "suspended", "cancelled", "expired")
LIVE = ("trialing", "active", "past_due", "grace")


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- pure helpers
def add_interval(start: datetime, interval: str) -> datetime | None:
    """The end of a billing period that starts at `start`: one calendar month or year later (a 31st becomes the month's
    last day). None for a one-time purchase, which does not renew."""
    if interval == "one_time":
        return None
    months = 1 if interval == "month" else 12
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _ceil_days(delta: timedelta) -> int:
    seconds = delta.total_seconds()
    return int(-(-seconds // 86400)) if seconds > 0 else 0


def prorate_due(
    old_amount: Decimal, new_amount: Decimal, period_start: datetime, period_end: datetime, now: datetime
) -> Decimal:
    """What to charge now for moving to a plan that costs `new_amount` per period from one that cost `old_amount`, for
    the
    rest of the current period: (new - old) x days left / days in the period, days counted up (a part day counts as a
    whole), rounded to the cent. Never negative: a cheaper plan gives no credit here (it starts at the next period)."""
    total = _ceil_days(period_end - period_start)
    left = min(_ceil_days(period_end - now), total)
    if total == 0 or left == 0:
        return Decimal("0.00")
    return max(Decimal("0.00"), plans.round_money((new_amount - old_amount) * left / total))


# --------------------------------------------------------------------------- reading and recording
def get(tenant_id: UUID) -> dict[str, Any] | None:
    with master_session() as m:
        row = m.execute(text("select * from master.subscription where tenant_id = :t"), {"t": str(tenant_id)}).first()
    return dict(row._mapping) if row is not None else None


def require(tenant_id: UUID) -> dict[str, Any]:
    sub = get(tenant_id)
    if sub is None:
        raise NotFound("This business has no subscription")
    return sub


def record_event(tenant_id: UUID, kind: str, detail: dict[str, Any] | None = None, by: str | None = None) -> None:
    with master_session() as m:
        m.execute(
            text(
                "insert into master.subscription_event (tenant_id, kind, detail, by_name) "
                "values (:t, :k, cast(:d as jsonb), :b)"
            ),
            {"t": str(tenant_id), "k": kind, "d": json.dumps(detail, default=str) if detail else None, "b": by},
        )


def timeline(tenant_id: UUID, limit: int = 100) -> list[dict[str, Any]]:
    with master_session() as m:
        return [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select occurred_at, kind, detail, by_name from master.subscription_event where tenant_id = :t "
                    "order by id desc limit :n"
                ),
                {"t": str(tenant_id), "n": limit},
            )
        ]


def _update(tenant_id: UUID, **columns: Any) -> dict[str, Any]:
    assignments = ", ".join(f"{k} = :{k}" for k in columns)
    with master_session() as m:
        row = m.execute(
            text(
                f"update master.subscription set {assignments}, updated_at = now() "
                "where tenant_id = :tenant_id returning *"
            ),
            {**columns, "tenant_id": str(tenant_id)},
        ).first()
    entitlements.invalidate(tenant_id)
    if row is None:
        raise NotFound("This business has no subscription")
    return dict(row._mapping)


def _set_status(tenant_id: UUID, status: str, reason: str | None, by: str | None, now: datetime) -> dict[str, Any]:
    before = require(tenant_id)["status"]
    row = _update(tenant_id, status=status, status_reason=reason, status_changed_at=now)
    if before != status:
        record_event(tenant_id, f"status.{status}", {"from": before, "reason": reason}, by)
    return row


# --------------------------------------------------------------------------- choosing plan and price
def _plan_for_sale(code: str) -> dict[str, Any]:
    plan = plans.get_plan(code)
    if plan["status"] != "active":
        raise ValidationFailed("This plan has been retired and cannot be chosen")
    return plan


def pick_price(plan: dict[str, Any], currency: str | None, interval: str | None, now: datetime) -> plans.Price | None:
    """The price to sell at: the business's currency and the wanted interval when the plan has them, else the nearest
    the plan does offer (same interval in another currency, then another interval). None when the plan is unpriced."""
    available = [p for p in plans.current_prices("plan", plan["id"], now) if p.interval in plan["intervals"]]
    if not available:
        return None
    wanted_interval = interval if interval in plan["intervals"] else None
    order = [p for p in available if p.currency == (currency or "").upper() and p.interval == wanted_interval]
    order += [p for p in available if p.interval == wanted_interval]
    order += [p for p in available if p.currency == (currency or "").upper()]
    order += available
    return order[0]


def _units_of(plan: dict[str, Any]) -> list[str]:
    return plans.plan_units(plan)


def default_plan_code(edition: str | None = None) -> str | None:
    """The plan a new business starts on: the platform setting, then the environment, then the edition's own default."""
    for candidate in (settings.get("billing.default_plan_code"), get_settings().default_plan_code):
        if candidate:
            return str(candidate)
    if edition:
        code = editions.get(edition).default_plan
        if code:
            return code
    return None


# --------------------------------------------------------------------------- starting
def start(
    tenant_id: UUID,
    plan_code: str,
    *,
    currency: str | None = None,
    interval: str | None = None,
    mode: str = "trial",
    comp_until: datetime | None = None,
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Give a business a subscription. mode: 'trial' (the plan's trial days, then it must be paid), 'active' (a paid
    period starts now) or 'comp' (free, for as long as an operator says)."""
    moment = now or _now()
    if mode not in ("trial", "active", "comp"):
        raise ValidationFailed("Mode is trial, active or comp")
    if get(tenant_id) is not None:
        raise Conflict("This business already has a subscription: change its plan instead")
    plan = _plan_for_sale(plan_code)
    price = pick_price(plan, currency, interval, moment)
    chosen_interval = (
        price.interval
        if price
        else (interval if interval and interval in plan["intervals"] else str(plan["intervals"][0]))
    )
    chosen_currency = price.currency if price else (currency or "").strip().upper()
    if not chosen_currency:
        raise ValidationFailed("This plan has no price yet: give the currency the business is billed in")
    amount = Decimal("0.00") if price is None or mode == "comp" else price.amount
    trial_end = moment + timedelta(days=plan["trial_days"]) if mode == "trial" else None
    status = "trialing" if mode == "trial" else "active"
    period_start = moment
    if mode == "trial":
        period_end: datetime | None = trial_end
    elif mode == "comp":
        period_end = comp_until
    else:
        period_end = add_interval(moment, chosen_interval)
    snap = entitlements.snapshot(plan, _units_of(plan))
    with master_session() as m:
        m.execute(
            text(
                "insert into master.subscription (tenant_id, plan_id, plan_code, plan_name, status, interval, "
                "currency, "
                "unit_amount, tax_inclusive, entitlements, period_start, period_end, trial_end, is_comp) "
                "values (:t, :p, :pc, :pn, :s, :i, :c, :a, :ti, cast(:e as jsonb), :ps, :pe, :te, :comp)"
            ),
            {
                "t": str(tenant_id),
                "p": str(plan["id"]),
                "pc": plan["code"],
                "pn": plan["name"],
                "s": status,
                "i": chosen_interval,
                "c": chosen_currency,
                "a": amount,
                "ti": bool(price and price.tax_inclusive),
                "e": entitlements.dumps(snap),
                "ps": period_start,
                "pe": period_end,
                "te": trial_end,
                "comp": mode == "comp",
            },
        )
    entitlements.invalidate(tenant_id)
    record_event(
        tenant_id,
        "created",
        {
            "plan": plan["code"],
            "mode": mode,
            "interval": chosen_interval,
            "currency": chosen_currency,
            "amount": str(amount),
        },
        by,
    )
    return require(tenant_id)


def start_for_registration(
    tenant_id: UUID, edition: str | None, currency: str, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """The trial a self-registered business starts on (none when no default plan is set: the business is unmanaged)."""
    if get_settings().deployment_mode == "selfhosted":
        return None
    code = default_plan_code(edition)
    if not code:
        return None
    sub = start(tenant_id, code, currency=currency, mode="trial", now=now)
    enforce_units(tenant_id)                    # the edition's units that the plan does not include are switched off
    return sub


# --------------------------------------------------------------------------- changing plan
def _apply_plan(
    tenant_id: UUID,
    plan: dict[str, Any],
    price: plans.Price | None,
    interval: str,
    currency: str,
    keep_amount: bool = False,
) -> dict[str, Any]:
    """Copy a plan's units, limits and (unless kept) price into the subscription."""
    snap = entitlements.snapshot(plan, _units_of(plan))
    columns: dict[str, Any] = {
        "plan_id": plan["id"],
        "plan_code": plan["code"],
        "plan_name": plan["name"],
        "entitlements": entitlements.dumps(snap),
        "pending_plan_id": None,
        "pending_interval": None,
        "pending_currency": None,
    }
    if not keep_amount:
        columns.update(
            interval=interval,
            currency=currency,
            unit_amount=price.amount if price else Decimal("0.00"),
            tax_inclusive=bool(price and price.tax_inclusive),
        )
    with master_session() as m:
        m.execute(
            text("update master.subscription set entitlements = cast(:e as jsonb) where tenant_id = :t"),
            {"e": columns.pop("entitlements"), "t": str(tenant_id)},
        )
    return _update(tenant_id, **columns)


def change_plan(
    tenant_id: UUID,
    plan_code: str,
    *,
    interval: str | None = None,
    currency: str | None = None,
    effective: str = "auto",
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Move a business to another plan. Returns {"subscription", "effective", "prorated_due", "disabled_units"}.

    Rules (docs/platform-admin.md, "Plan changes"): during a trial or on a comp the new plan applies at once. On a paid
    subscription, a dearer plan in the same currency and interval applies at once and the rest of the period is charged
    pro rata by days (`prorate_due`, the caller bills it); a cheaper plan, another interval or another currency starts
    at
    the end of the period (or at once, with no credit, when the platform setting says downgrades are immediate)."""
    moment = now or _now()
    sub = require(tenant_id)
    if effective not in ("auto", "now", "period_end"):
        raise ValidationFailed("Effective is auto, now or period_end")
    plan = _plan_for_sale(plan_code)
    new_interval = interval or sub["interval"]
    new_currency = (currency or sub["currency"]).upper()
    price = pick_price(plan, new_currency, new_interval, moment)
    if (
        price is not None
        and (price.currency != new_currency or price.interval != new_interval)
        and (currency or interval)
    ):
        raise ValidationFailed(f"{plan['name']} has no price for {new_interval} in {new_currency}")
    if price is not None:
        new_interval, new_currency = price.interval, price.currency
    new_amount = price.amount if price else Decimal("0.00")
    result: dict[str, Any] = {"effective": "now", "prorated_due": Decimal("0.00"), "disabled_units": []}

    paid = not sub["is_comp"] and sub["status"] != "trialing" and sub["period_end"] is not None
    same_terms = new_interval == sub["interval"] and new_currency == sub["currency"]
    dearer = same_terms and new_amount > sub["unit_amount"]
    if not paid:
        timing = "now"
    elif effective != "auto":
        timing = effective
    elif dearer or same_terms and settings.get("billing.proration")["downgrade"] == "now":
        timing = "now"
    else:
        timing = "period_end"
    if timing == "now" and paid and not same_terms:
        raise ValidationFailed("A change of billing interval or currency starts at the end of the period")

    if timing == "period_end":
        result["effective"] = "period_end"
        row = _update(
            tenant_id, pending_plan_id=plan["id"], pending_interval=new_interval, pending_currency=new_currency
        )
        record_event(
            tenant_id,
            "plan.scheduled",
            {"plan": plan["code"], "interval": new_interval, "currency": new_currency, "at": sub["period_end"]},
            by,
        )
    else:
        if paid and dearer and sub["period_start"] and sub["period_end"]:
            result["prorated_due"] = prorate_due(
                sub["unit_amount"], new_amount, sub["period_start"], sub["period_end"], moment
            )
        row = _apply_plan(tenant_id, plan, price, new_interval, new_currency)
        record_event(
            tenant_id,
            "plan.changed",
            {"from": sub["plan_code"], "to": plan["code"], "prorated_due": str(result["prorated_due"])},
            by,
        )
        result["disabled_units"] = enforce_units(tenant_id)
    result["subscription"] = row
    return result


def apply_pending(tenant_id: UUID, by: str | None = None) -> dict[str, Any]:
    """Make a scheduled plan change take effect (called when the period it waited for is paid)."""
    sub = require(tenant_id)
    if sub["pending_plan_id"] is None:
        return sub
    plan = plans.plan_by_id(sub["pending_plan_id"])
    price = pick_price(plan, sub["pending_currency"], sub["pending_interval"], _now())
    row = _apply_plan(
        tenant_id, plan, price, sub["pending_interval"] or sub["interval"], sub["pending_currency"] or sub["currency"]
    )
    record_event(tenant_id, "plan.changed", {"from": sub["plan_code"], "to": plan["code"], "scheduled": True}, by)
    enforce_units(tenant_id)
    return row


def sync_to_plan(tenant_id: UUID, *, by: str | None = None) -> dict[str, Any]:
    """Copy the plan's current units and limits (not the price) into the subscription."""
    sub = require(tenant_id)
    if sub["plan_id"] is None:
        raise ValidationFailed("This subscription has no plan to sync to")
    plan = plans.plan_by_id(sub["plan_id"])
    row = _apply_plan(tenant_id, plan, None, sub["interval"], sub["currency"], keep_amount=True)
    record_event(tenant_id, "plan.synced", {"plan": plan["code"]}, by)
    enforce_units(tenant_id)
    return row


def enforce_units(tenant_id: UUID) -> list[str]:
    """Switch off (data kept) units the subscription's plan no longer includes. Returns the units switched off."""
    ent = entitlements.for_tenant(tenant_id, use_cache=False)
    if ent.units is None:
        return []
    units = discover()
    reg = Registry(units)
    switched: list[str] = []
    try:
        with tenant_session(tenant_id, admin=True) as s:
            enabled = reg.enabled_for(s)
        for name in reversed(install_order(units, [u for u in enabled if u in units])):
            if name in ent.units or units[name].core:
                continue
            try:
                reg.disable(tenant_id, name)
                switched.append(name)
            except DependencyError:
                log.info("Unit %s stays on for %s: another unit needs it", name, tenant_id)
        if switched:
            system_context(tenant_id)
            with tenant_session(tenant_id) as s:
                audit.record(s, "plan_units_disabled", "kernel.unit", None, {"units": switched})
    except Exception:  # noqa: BLE001 - never let a business database problem undo the plan change
        log.warning("Could not switch off units outside the plan for %s", tenant_id, exc_info=True)
    if switched:
        record_event(tenant_id, "units.disabled", {"units": switched})
    return switched


# --------------------------------------------------------------------------- trial, comp, coupon, notes
def extend_trial(tenant_id: UUID, days: int, *, by: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Add days to a trial (or restart one that has ended: the business comes back to `trialing`)."""
    moment = now or _now()
    if not 1 <= days <= 365:
        raise ValidationFailed("Extend by 1 to 365 days")
    sub = require(tenant_id)
    if sub["status"] in ("active", "cancelled") and not sub["trial_end"]:
        raise ValidationFailed("Only a business that is (or was) on a trial can have it extended")
    base = max(moment, sub["trial_end"] or moment)
    end = base + timedelta(days=days)
    row = _update(
        tenant_id,
        trial_end=end,
        period_end=end,
        status="trialing",
        status_reason=None,
        status_changed_at=moment,
        cancel_at_period_end=False,
    )
    record_event(tenant_id, "trial.extended", {"days": days, "trial_end": end}, by)
    return row


def make_comp(
    tenant_id: UUID,
    plan_code: str | None,
    *,
    until: datetime | None,
    reason: str,
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Give the business the plan free of charge (until a date, or without end)."""
    moment = now or _now()
    if len(reason.strip()) < 5:
        raise ValidationFailed("Say why (at least a few words)")
    if until is not None and until <= moment:
        raise ValidationFailed("A comp must end in the future (or not at all)")
    sub = require(tenant_id)
    if plan_code and plan_code != sub["plan_code"]:
        plan = _plan_for_sale(plan_code)
        _apply_plan(tenant_id, plan, None, sub["interval"], sub["currency"], keep_amount=True)
        enforce_units(tenant_id)
    row = _update(
        tenant_id,
        is_comp=True,
        unit_amount=Decimal("0.00"),
        status="active",
        period_start=moment,
        period_end=until,
        trial_end=None,
        cancel_at_period_end=False,
        status_reason=reason.strip(),
        status_changed_at=moment,
    )
    record_event(tenant_id, "comp", {"until": until, "reason": reason.strip()}, by)
    return row


def apply_coupon(tenant_id: UUID, code: str, *, by: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    sub = require(tenant_id)
    coupon = plans.get_coupon(code)
    plans.check_coupon(coupon, sub["plan_code"], sub["currency"], now)
    periods = {"once": 1, "repeating": coupon["duration_periods"], "forever": None}[coupon["duration"]]
    with master_session() as m:
        taken = m.execute(
            text(
                "update master.coupon set redeemed = redeemed + 1 where id = :i and "
                "(max_redemptions is null or redeemed < max_redemptions) returning id"
            ),
            {"i": str(coupon["id"])},
        ).first()
    if taken is None:
        raise ValidationFailed("This coupon has been used up")
    row = _update(tenant_id, coupon_id=coupon["id"], coupon_periods_left=periods)
    record_event(tenant_id, "coupon.applied", {"coupon": coupon["code"]}, by)
    return row


def set_notes(tenant_id: UUID, notes: str | None, tags: list[str] | None, by: str | None = None) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    if notes is not None:
        columns["notes"] = notes.strip()[:4000]
    if tags is not None:
        clean = sorted({t.strip().lower() for t in tags if t.strip()})
        if len(clean) > 12 or any(len(t) > 30 for t in clean):
            raise ValidationFailed("At most 12 tags, each up to 30 characters")
        columns["tags"] = clean
    if not columns:
        return require(tenant_id)
    row = _update(tenant_id, **columns)
    record_event(tenant_id, "notes.changed", None, by)
    return row


# --------------------------------------------------------------------------- suspend, reactivate, cancel
def suspend(tenant_id: UUID, reason: str, *, by: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    if len(reason.strip()) < 5:
        raise ValidationFailed("Say why (at least a few words)")
    return _set_status(tenant_id, "suspended", "manual: " + reason.strip(), by, now or _now())


def reactivate(
    tenant_id: UUID, *, reason: str | None = None, by: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Back to normal: `trialing` while a trial is still running, else `active`. A cancelled or expired subscription
    whose period has run out is given a new period starting now (the operator decides to; no invoice is made)."""
    moment = now or _now()
    sub = require(tenant_id)
    if sub["status"] in LIVE and not sub["cancel_at_period_end"]:
        return sub
    trial_running = bool(sub["trial_end"] and sub["trial_end"] > moment and not sub["is_comp"])
    status = "trialing" if trial_running else "active"
    columns: dict[str, Any] = {"cancel_at_period_end": False}
    if (
        status == "active"
        and not sub["is_comp"]
        and (sub["period_end"] is None or sub["period_end"] <= moment)
        and sub["interval"] != "one_time"
    ):
        columns.update(period_start=moment, period_end=add_interval(moment, sub["interval"]))
    _update(tenant_id, **columns)
    return _set_status(tenant_id, status, reason, by, moment)


def cancel(
    tenant_id: UUID,
    *,
    at_period_end: bool = True,
    reason: str | None = None,
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """End the subscription: at the end of the period paid for (default) or now. The business turns read-only; its
    data is
    kept for the retention period and deleted only by an operator's confirmed, cooled-off request."""
    moment = now or _now()
    sub = require(tenant_id)
    if sub["status"] in ("cancelled", "expired"):
        raise ValidationFailed("This subscription has already ended")
    if at_period_end and sub["period_end"] is not None and sub["period_end"] > moment:
        row = _update(tenant_id, cancel_at_period_end=True)
        record_event(tenant_id, "cancel.scheduled", {"at": sub["period_end"], "reason": reason}, by)
        return row
    _update(tenant_id, cancel_at_period_end=False, period_end=moment)
    return _set_status(tenant_id, "cancelled", reason, by, moment)


def uncancel(tenant_id: UUID, *, by: str | None = None) -> dict[str, Any]:
    """Take back a cancellation that has not happened yet."""
    sub = require(tenant_id)
    if not sub["cancel_at_period_end"]:
        raise ValidationFailed("This subscription is not set to cancel")
    row = _update(tenant_id, cancel_at_period_end=False)
    record_event(tenant_id, "cancel.withdrawn", None, by)
    return row


# --------------------------------------------------------------------------- when money arrives
def on_invoice_paid(invoice: dict[str, Any], *, now: datetime | None = None, by: str | None = None) -> None:
    """A subscriber's invoice is fully paid: apply the plan change it carried; for a first or renewal invoice move the
    period on (from the end of the last one, or from now if it is paid very late); put the business back to normal."""
    tenant_id = invoice["tenant_id"]
    if tenant_id is None or get(tenant_id) is None:
        return
    moment = now or _now()
    change = invoice.get("plan_change")
    if change:
        plan = _plan_for_sale(change["plan_code"])
        price = pick_price(plan, change.get("currency"), change.get("interval"), moment)
        sub = require(tenant_id)
        _apply_plan(
            tenant_id, plan, price, change.get("interval") or sub["interval"], change.get("currency") or sub["currency"]
        )
        record_event(tenant_id, "plan.changed", {"to": plan["code"], "paid_invoice": invoice["number"]}, by)
        enforce_units(tenant_id)
    if invoice["kind"] in ("renewal", "first") and invoice["period_start"] is not None:
        if not change and require(tenant_id)["pending_plan_id"] is not None:
            apply_pending(tenant_id, by)
        sub = require(tenant_id)
        start = invoice["period_start"]
        end = add_interval(start, sub["interval"])
        if end is not None and end <= moment:
            start, end = moment, add_interval(moment, sub["interval"])  # paid very late: the period starts now
        _update(tenant_id, period_start=start, period_end=end, trial_end=None, is_comp=False)
    fresh = require(tenant_id)
    if fresh["is_comp"]:
        return
    came_back = fresh["status"] == "cancelled" and (bool(change) or invoice["kind"] == "first")
    if fresh["status"] in ("trialing", "past_due", "grace", "suspended", "expired") or came_back:
        _update(tenant_id, cancel_at_period_end=False)
        _set_status(tenant_id, "active", None, by, moment)
    elif fresh["trial_end"] is not None:
        _update(tenant_id, trial_end=None)
