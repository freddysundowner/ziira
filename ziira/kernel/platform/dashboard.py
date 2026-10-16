"""The Super Admin dashboard: recurring revenue, trials, churn, money overdue, and where attention is needed.

Figures are computed per currency and never converted (no exchange rates are assumed). MRR is the monthly value of
subscriptions that are paying (active, past due or in grace; not comps, trials or one-time purchases), after any running
coupon: a yearly price counts as a twelfth.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ziira.kernel import operator_console as console
from ziira.kernel.db import master_session
from ziira.kernel.platform import entitlements, plans

PERIOD_DAYS = 30
HOT_RATIO = Decimal("0.8")
ZERO = Decimal("0.00")


def _now() -> datetime:
    return datetime.now(UTC)


def monthly_value(sub: dict[str, Any], coupons: dict[Any, dict[str, Any]]) -> Decimal:
    """What one paying subscription is worth per month (zero for a comp or a one-time purchase)."""
    if sub["is_comp"] or sub["interval"] == "one_time":
        return ZERO
    amount: Decimal = sub["unit_amount"]
    coupon = coupons.get(sub["coupon_id"])
    running = coupon is not None and sub["coupon_periods_left"] != 0
    if coupon is not None and running and (coupon["percent_off"] is not None or sub["currency"] in coupon["amounts"]):
        amount -= plans.discount_for(coupon, sub["currency"], amount)
    return plans.round_money(amount / 12) if sub["interval"] == "year" else plans.round_money(amount)


def overview(*, now: datetime | None = None, scans: list[console.BusinessScan] | None = None) -> dict[str, Any]:
    moment = now or _now()
    since = moment - timedelta(days=PERIOD_DAYS)
    with master_session() as m:
        subs = [
            dict(r._mapping)
            for r in m.execute(
                text("select s.*, t.code, t.name from master.subscription s join master.tenant t on t.id = s.tenant_id")
            )
        ]
        coupons = {
            c["id"]: plans.get_coupon(c["code"])
            for c in [dict(r._mapping) for r in m.execute(text("select id, code from master.coupon"))]
        }
        events = [
            dict(r._mapping)
            for r in m.execute(
                text("select tenant_id, kind, detail from master.subscription_event where occurred_at >= :s"),
                {"s": since},
            )
        ]
        overdue = [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select currency, count(*) as invoices, sum(total - amount_paid) as owed from "
                    "master.billing_invoice "
                    "where status = 'issued' and due_date < :d group by currency order by currency"
                ),
                {"d": moment.date()},
            )
        ]
        requests = m.execute(text("select count(*) from master.plan_request where status = 'pending'")).scalar_one()
        drafts = m.execute(text("select count(*) from master.billing_invoice where status = 'draft'")).scalar_one()
    paying = [s for s in subs if s["status"] in ("active", "past_due", "grace")]
    mrr: dict[str, Decimal] = {}
    for s in paying:
        mrr[s["currency"].strip()] = mrr.get(s["currency"].strip(), ZERO) + monthly_value(s, coupons)
    mrr_rows = [
        {
            "currency": c,
            "mrr": v,
            "arr": v * 12,
            "subscribers": sum(1 for s in paying if s["currency"].strip() == c and monthly_value(s, coupons) > 0),
        }
        for c, v in sorted(mrr.items())
    ]
    started = [e for e in events if e["kind"] == "created"]
    ended = {e["tenant_id"] for e in events if e["kind"] in ("status.cancelled", "status.expired")}
    from_trial = [e for e in events if (e["detail"] or {}).get("from") == "trialing"]
    converted = len({e["tenant_id"] for e in from_trial if e["kind"] == "status.active"})
    lapsed = len(
        {
            e["tenant_id"]
            for e in from_trial
            if e["kind"] in ("status.past_due", "status.suspended", "status.expired", "status.cancelled")
        }
    )
    found = scans if scans is not None else console.scan_businesses()
    by_id = {sc.id: sc for sc in found}
    hot, failed = [], []
    for s in subs:
        sc = by_id.get(s["tenant_id"])
        if sc is None:
            continue
        e = s["entitlements"] or {}
        for kind, used, limit in (
            ("users", sc.users, e.get("max_users")),
            ("branches", sc.branches, e.get("max_branches")),
            ("companies", sc.companies, e.get("max_companies")),
        ):
            if limit and Decimal(used) / Decimal(limit) >= HOT_RATIO:
                hot.append({"code": s["code"], "name": s["name"], "kind": kind, "used": used, "limit": limit})
    for sc in found:
        if sc.failed_jobs:
            failed.append({"code": sc.code, "name": sc.name, "failed_jobs": sc.failed_jobs})
    renewals = sorted(
        (
            s
            for s in subs
            if s["status"] == "active"
            and not s["is_comp"]
            and s["period_end"]
            and not s["cancel_at_period_end"]
            and moment <= s["period_end"] <= moment + timedelta(days=14)
        ),
        key=lambda s: s["period_end"],
    )
    return {
        "generated_at": moment,
        "period_days": PERIOD_DAYS,
        "mrr": mrr_rows,
        "new_subscribers": len(started),
        "churned": len(ended),
        "trials": {
            "in_progress": sum(1 for s in subs if s["status"] == "trialing"),
            "ending_soon": sum(
                1
                for s in subs
                if s["status"] == "trialing" and s["trial_end"] and s["trial_end"] <= moment + timedelta(days=7)
            ),
            "converted": converted,
            "lapsed": lapsed,
            "conversion_percent": (round(100 * converted / (converted + lapsed)) if converted + lapsed else None),
        },
        "past_due": [
            {"currency": r["currency"].strip(), "invoices": r["invoices"], "owed": r["owed"]} for r in overdue
        ],
        "by_status": dict(Counter(s["status"] for s in subs)),
        "by_plan": dict(Counter(s["plan_code"] for s in subs)),
        "by_edition": dict(
            Counter(by_id[s["tenant_id"]].edition or "unknown" for s in subs if s["tenant_id"] in by_id)
        ),
        "by_country": dict(
            Counter(by_id[s["tenant_id"]].country or "unknown" for s in subs if s["tenant_id"] in by_id)
        ),
        "unmanaged": sum(1 for sc in found if sc.id not in {s["tenant_id"] for s in subs} and sc.status == "active"),
        "usage_hot_spots": hot,
        "upcoming_renewals": [
            {
                "code": s["code"],
                "name": s["name"],
                "plan": s["plan_name"],
                "period_end": s["period_end"],
                "amount": s["unit_amount"],
                "currency": s["currency"].strip(),
            }
            for s in renewals
        ][:20],
        "failed_jobs": failed,
        "pending_requests": int(requests),
        "draft_invoices": int(drafts),
        "mode": entitlements.mode(),
    }
