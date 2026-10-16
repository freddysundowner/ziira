"""Plans, prices, add-ons and coupons: the vendor's price list, kept as data (docs/platform-admin.md).

A **plan** names what is included (an edition and/or units, plugin add-ons, limits) and which billing intervals are
offered. A **price** is a row per plan, currency and interval with an effective date. Prices are append-only: changing a
price adds a row that starts at a moment (now or later), withdrawing one adds a "withdrawn" row; rows already in force
are never edited, so an old invoice can always be explained. A subscription copies the price and limits it was sold at.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import editions
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.registry import discover

INTERVALS = ("month", "year", "one_time")
CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")
COUPON_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,39}$")
CENT = Decimal("0.01")
LIMIT_FIELDS = ("max_users", "max_branches", "max_companies")
# plan.limits (informational caps a vendor may state; shown to subscribers, enforced only where the platform can count)
KNOWN_EXTRA_LIMITS = ("storage_mb", "documents_per_month", "api_requests_per_day")


def _now() -> datetime:
    return datetime.now(UTC)


def money(value: Any, what: str = "Amount") -> Decimal:
    """A non-negative amount with at most two decimals."""
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValidationFailed(f"{what} must be a number") from None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(CENT):
        raise ValidationFailed(f"{what} must be zero or more, with at most two decimals")
    return amount.quantize(CENT)


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _currency(value: Any) -> str:
    code = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValidationFailed("Currency is a three-letter code such as USD")
    return code


def _interval(value: Any) -> str:
    if value not in INTERVALS:
        raise ValidationFailed("Interval is month, year or one_time")
    return str(value)


# --------------------------------------------------------------------------- plans
def _plan_dict(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    d["id"] = r.id
    return d


def _limit(value: Any, what: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationFailed(f"{what} must be a whole number (or empty for no limit)") from None
    if number < 1 or number > 10_000_000:
        raise ValidationFailed(f"{what} must be at least 1 (or empty for no limit)")
    return number


def _known_units(names: Any, what: str) -> list[str]:
    if not isinstance(names, list):
        raise ValidationFailed(f"{what} must be a list of unit names")
    known = discover()
    clean = sorted({str(n).strip() for n in names if str(n).strip()})
    unknown = [n for n in clean if n not in known]
    if unknown:
        raise ValidationFailed(f"Unknown unit(s) in {what}: {', '.join(unknown)}")
    return clean


def _plan_values(data: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    """Validate the fields given (all of them when not `partial`) and return the columns to store."""
    out: dict[str, Any] = {}
    present = data.keys()
    if "name" in present or not partial:
        name = " ".join(str(data.get("name") or "").split())
        if not 2 <= len(name) <= 80:
            raise ValidationFailed("A plan name is 2 to 80 characters")
        out["name"] = name
    if "description" in present:
        out["description"] = str(data["description"] or "").strip()[:1000]
    if "edition" in present:
        edition = data["edition"] or None
        if edition is not None and edition not in editions.load_editions():
            raise ValidationFailed("Edition is one of: " + ", ".join(editions.load_editions()))
        out["edition"] = edition
    if "units" in present:
        out["units"] = _known_units(data["units"], "units")
    if "addon_units" in present:
        out["addon_units"] = _known_units(data["addon_units"], "plugin add-ons")
    for field in LIMIT_FIELDS:
        if field in present:
            out[field] = _limit(data[field], field.replace("_", " "))
    if "limits" in present:
        limits = data["limits"] or {}
        if not isinstance(limits, dict) or set(limits) - set(KNOWN_EXTRA_LIMITS):
            raise ValidationFailed("Other limits can be: " + ", ".join(KNOWN_EXTRA_LIMITS))
        out["limits"] = json.dumps({k: _limit(v, k) for k, v in limits.items() if v not in (None, "")})
    if "highlights" in present:
        items = [str(h).strip() for h in (data["highlights"] or []) if str(h).strip()]
        if len(items) > 12 or any(len(h) > 140 for h in items):
            raise ValidationFailed("Highlights: at most 12, each up to 140 characters")
        out["highlights"] = items
    if "trial_days" in present:
        try:
            days = int(data["trial_days"])
        except (TypeError, ValueError):
            raise ValidationFailed("Trial days must be a whole number") from None
        if not 0 <= days <= 365:
            raise ValidationFailed("Trial days are from 0 to 365")
        out["trial_days"] = days
    if "intervals" in present:
        intervals = sorted({_interval(i) for i in data["intervals"] or []})
        if not intervals:
            raise ValidationFailed("Offer at least one billing interval")
        out["intervals"] = intervals
    if "sort_order" in present:
        out["sort_order"] = int(data["sort_order"])
    if "is_public" in present:
        out["is_public"] = bool(data["is_public"])
    if "status" in present:
        if data["status"] not in ("active", "retired"):
            raise ValidationFailed("Status is active or retired")
        out["status"] = data["status"]
    return out


def create_plan(data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("code") or "").strip().lower()
    if not CODE.match(code):
        raise ValidationFailed("A plan code is 2-40 lowercase letters, digits, '-' or '_'")
    values = _plan_values(data, partial=False)
    values.setdefault("units", [])
    if not data.get("edition") and not values["units"]:
        raise ValidationFailed("Give an edition or a list of units: a plan must include something")
    with master_session() as m:
        if m.execute(text("select 1 from master.plan where code = :c"), {"c": code}).first():
            raise Conflict(f"There is already a plan with the code '{code}'")
        cols = ["code", *values]
        placeholders = [f"cast(:{c} as jsonb)" if c == "limits" else f":{c}" for c in cols]
        row = m.execute(
            text(f"insert into master.plan ({', '.join(cols)}) values ({', '.join(placeholders)}) returning *"),
            {"code": code, **values},
        ).one()
    return _plan_dict(row)


def update_plan(code: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Change a plan. Subscribers keep the limits and units they were sold; use `sync_subscription` to move one over."""
    if "code" in changes and changes["code"] != code:
        raise ValidationFailed("A plan's code cannot change")
    values = _plan_values({k: v for k, v in changes.items() if k != "code"}, partial=True)
    if not values:
        return get_plan(code)
    sets = ", ".join(f"{c} = cast(:{c} as jsonb)" if c == "limits" else f"{c} = :{c}" for c in values)
    with master_session() as m:
        row = m.execute(
            text(f"update master.plan set {sets}, updated_at = now() where code = :code returning *"),
            {"code": code, **values},
        ).first()
        if row is None:
            raise NotFound("No such plan")
        if not row.edition and not row.units:
            raise ValidationFailed("A plan must include an edition or some units")
    return _plan_dict(row)


def get_plan(code: str) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text("select * from master.plan where code = :c"), {"c": code.strip().lower()}).first()
    if row is None:
        raise NotFound("No such plan")
    return _plan_dict(row)


def plan_by_id(plan_id: UUID) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text("select * from master.plan where id = :i"), {"i": str(plan_id)}).first()
    if row is None:
        raise NotFound("No such plan")
    return _plan_dict(row)


def list_plans(*, include_retired: bool = True) -> list[dict[str, Any]]:
    with master_session() as m:
        rows = m.execute(
            text(
                "select p.*, (select count(*) from master.subscription s where s.plan_id = p.id) "
                "as subscribers from master.plan p where (:r or p.status = 'active') "
                "order by p.sort_order, p.name"
            ),
            {"r": include_retired},
        )
        return [_plan_dict(r) for r in rows]


def plan_units(plan: dict[str, Any]) -> list[str]:
    """Every unit a plan includes: its edition's, its own list and its plugin add-ons."""
    names = set(plan["units"]) | set(plan["addon_units"])
    if plan.get("edition"):
        names |= set(editions.get(plan["edition"]).units)
    return sorted(names)


def plan_limits(plan: dict[str, Any]) -> dict[str, Any]:
    """The limits a subscription copies: users, branches, companies (None = unlimited) and the extra caps."""
    return {
        "max_users": plan["max_users"],
        "max_branches": plan["max_branches"],
        "max_companies": plan["max_companies"],
        **{f"limit_{k}": v for k, v in (plan["limits"] or {}).items()},
    }


# --------------------------------------------------------------------------- prices (plans and add-ons)
_OWNERS = {"plan": ("master.plan_price", "plan_id"), "addon": ("master.addon_price", "addon_id")}


@dataclass(frozen=True)
class Price:
    currency: str
    interval: str
    amount: Decimal
    tax_inclusive: bool
    effective_from: datetime


def set_price(
    owner: str,
    owner_id: UUID,
    *,
    currency: str,
    interval: str,
    amount: Any,
    tax_inclusive: bool,
    effective_from: datetime | None = None,
    withdrawn: bool = False,
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Add a price row. It starts at `effective_from` (default now); it may not start before the newest row for the same
    plan, currency and interval, so history is never rewritten."""
    table, column = _OWNERS[owner]
    moment = now or _now()
    start = effective_from or moment
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    cur, itv = _currency(currency), _interval(interval)
    value = money(amount)
    with master_session() as m:
        newest = m.execute(
            text(f"select max(effective_from) from {table} where {column} = :o and currency = :c and interval = :i"),
            {"o": str(owner_id), "c": cur, "i": itv},
        ).scalar()
        if newest is not None and start <= newest:
            raise ValidationFailed(
                "A new price must start after the latest one for this plan, currency and interval "
                f"({newest:%Y-%m-%d %H:%M} UTC). Remove the scheduled change first to replace it."
            )
        if start < moment - timedelta(minutes=5):
            raise ValidationFailed("A price cannot start in the past")
        row = m.execute(
            text(
                f"insert into {table} ({column}, currency, interval, amount, tax_inclusive, withdrawn, effective_from, "
                "created_by) values (:o, :c, :i, :a, :t, :w, :f, :b) returning *"
            ),
            {
                "o": str(owner_id),
                "c": cur,
                "i": itv,
                "a": value,
                "t": tax_inclusive,
                "w": withdrawn,
                "f": start,
                "b": by,
            },
        ).one()
    return dict(row._mapping)


def remove_scheduled_price(owner: str, price_id: UUID, *, now: datetime | None = None) -> None:
    """Take back a price that has not started yet (one already in force can only be superseded or withdrawn)."""
    table, _ = _OWNERS[owner]
    with master_session() as m:
        row = m.execute(text(f"select effective_from from {table} where id = :i"), {"i": str(price_id)}).first()
        if row is None:
            raise NotFound("No such price")
        if row.effective_from <= (now or _now()):
            raise ValidationFailed("This price is already in force; add a newer one or withdraw it instead")
        m.execute(text(f"delete from {table} where id = :i"), {"i": str(price_id)})


def price_at(owner: str, owner_id: UUID, currency: str, interval: str, at: datetime | None = None) -> Price | None:
    """The price in force at a moment, or None when none was set yet or it was withdrawn."""
    table, column = _OWNERS[owner]
    with master_session() as m:
        row = m.execute(
            text(
                f"select currency, interval, amount, tax_inclusive, withdrawn, effective_from from {table} "
                f"where {column} = :o and currency = :c and interval = :i and effective_from <= :t "
                "order by effective_from desc limit 1"
            ),
            {"o": str(owner_id), "c": currency.upper(), "i": interval, "t": at or _now()},
        ).first()
    if row is None or row.withdrawn:
        return None
    return Price(row.currency.strip(), row.interval, row.amount, row.tax_inclusive, row.effective_from)


def current_prices(owner: str, owner_id: UUID, at: datetime | None = None) -> list[Price]:
    """Every price in force (one per currency and interval)."""
    table, column = _OWNERS[owner]
    with master_session() as m:
        keys = m.execute(
            text(f"select distinct currency, interval from {table} where {column} = :o"), {"o": str(owner_id)}
        ).all()
    found = [price_at(owner, owner_id, k.currency.strip(), k.interval, at) for k in keys]
    return sorted((p for p in found if p is not None), key=lambda p: (p.currency, p.interval))


def price_history(owner: str, owner_id: UUID) -> list[dict[str, Any]]:
    table, column = _OWNERS[owner]
    with master_session() as m:
        return [
            dict(r._mapping)
            for r in m.execute(
                text(
                    f"select id, currency, interval, amount, tax_inclusive, withdrawn, effective_from, created_by "
                    f"from {table} "
                    f"where {column} = :o order by currency, interval, effective_from desc"
                ),
                {"o": str(owner_id)},
            )
        ]


# --------------------------------------------------------------------------- add-ons
def create_addon(data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("code") or "").strip().lower()
    if not CODE.match(code):
        raise ValidationFailed("An add-on code is 2-40 lowercase letters, digits, '-' or '_'")
    kind = data.get("kind")
    if kind not in ("unit", "users", "branches", "companies"):
        raise ValidationFailed("An add-on adds a unit, users, branches or companies")
    unit = data.get("unit_name") or None
    if (kind == "unit") != (unit is not None):
        raise ValidationFailed("Name the unit for a unit add-on, and only then")
    if unit is not None and unit not in discover():
        raise ValidationFailed(f"Unknown unit {unit}")
    name = " ".join(str(data.get("name") or "").split())
    if not 2 <= len(name) <= 80:
        raise ValidationFailed("An add-on name is 2 to 80 characters")
    quantity = int(data.get("quantity") or 1)
    if quantity < 1:
        raise ValidationFailed("Quantity is at least 1")
    with master_session() as m:
        if m.execute(text("select 1 from master.addon where code = :c"), {"c": code}).first():
            raise Conflict(f"There is already an add-on with the code '{code}'")
        row = m.execute(
            text(
                "insert into master.addon (code, name, description, kind, unit_name, quantity, is_public, sort_order) "
                "values (:c, :n, :d, :k, :u, :q, :p, :s) returning *"
            ),
            {
                "c": code,
                "n": name,
                "d": str(data.get("description") or "")[:500],
                "k": kind,
                "u": unit,
                "q": quantity,
                "p": bool(data.get("is_public")),
                "s": int(data.get("sort_order") or 100),
            },
        ).one()
    return dict(row._mapping)


def update_addon(code: str, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "description", "is_public", "status", "sort_order", "quantity"}
    bad = set(changes) - allowed
    if bad:
        raise ValidationFailed("An add-on's kind and unit cannot change; editable: " + ", ".join(sorted(allowed)))
    if "status" in changes and changes["status"] not in ("active", "retired"):
        raise ValidationFailed("Status is active or retired")
    if "quantity" in changes and int(changes["quantity"]) < 1:
        raise ValidationFailed("Quantity is at least 1")
    if not changes:
        return get_addon(code)
    sets = ", ".join(f"{c} = :{c}" for c in changes)
    with master_session() as m:
        row = m.execute(
            text(f"update master.addon set {sets}, updated_at = now() where code = :code returning *"),
            {"code": code, **changes},
        ).first()
    if row is None:
        raise NotFound("No such add-on")
    return dict(row._mapping)


def get_addon(code: str) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text("select * from master.addon where code = :c"), {"c": code.strip().lower()}).first()
    if row is None:
        raise NotFound("No such add-on")
    return dict(row._mapping)


def list_addons() -> list[dict[str, Any]]:
    with master_session() as m:
        return [dict(r._mapping) for r in m.execute(text("select * from master.addon order by sort_order, name"))]


# --------------------------------------------------------------------------- coupons
def create_coupon(data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("code") or "").strip().upper()
    if not COUPON_CODE.match(code):
        raise ValidationFailed("A coupon code is 3-40 letters, digits, '-' or '_'")
    percent = data.get("percent_off")
    amounts = data.get("amounts") or {}
    if (percent in (None, "")) == (not amounts):
        raise ValidationFailed("Give a percentage or fixed amounts per currency, not both and not neither")
    pct: Decimal | None = None
    if percent not in (None, ""):
        try:
            pct = Decimal(str(percent))
        except InvalidOperation:
            raise ValidationFailed("Percent must be a number") from None
        if not Decimal(0) < pct <= Decimal(100):
            raise ValidationFailed("Percent is above 0 and at most 100")
    fixed = {_currency(k): money(v) for k, v in amounts.items()}
    if any(v <= 0 for v in fixed.values()):
        raise ValidationFailed("A fixed discount must be more than zero")
    duration = data.get("duration", "once")
    periods = data.get("duration_periods")
    if duration not in ("once", "repeating", "forever"):
        raise ValidationFailed("Duration is once, repeating or forever")
    if (duration == "repeating") != (periods not in (None, "")):
        raise ValidationFailed("Give the number of invoices for a repeating coupon, and only then")
    maximum = data.get("max_redemptions")
    plans = sorted({str(p).strip().lower() for p in data.get("plan_codes") or [] if str(p).strip()})
    with master_session() as m:
        if plans:
            known = set(m.execute(text("select code from master.plan where code = any(:c)"), {"c": plans}).scalars())
            if known != set(plans):
                raise ValidationFailed("Unknown plan(s): " + ", ".join(sorted(set(plans) - known)))
        if m.execute(text("select 1 from master.coupon where code = :c"), {"c": code}).first():
            raise Conflict(f"There is already a coupon '{code}'")
        row = m.execute(
            text(
                "insert into master.coupon (code, description, percent_off, duration, duration_periods, "
                "max_redemptions, "
                "expires_at, plan_codes) values (:c, :d, :p, :du, :n, :m, :e, :pl) returning *"
            ),
            {
                "c": code,
                "d": str(data.get("description") or "")[:300],
                "p": pct,
                "du": duration,
                "n": int(periods) if periods not in (None, "") else None,
                "m": int(maximum) if maximum not in (None, "") else None,
                "e": data.get("expires_at"),
                "pl": plans,
            },
        ).one()
        for cur, amount in fixed.items():
            m.execute(
                text("insert into master.coupon_amount (coupon_id, currency, amount_off) values (:i, :c, :a)"),
                {"i": str(row.id), "c": cur, "a": amount},
            )
    return get_coupon(code)


def get_coupon(code: str) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(text("select * from master.coupon where code = :c"), {"c": code.strip().upper()}).first()
        if row is None:
            raise NotFound("No such coupon")
        amounts = {
            r.currency.strip(): r.amount_off
            for r in m.execute(
                text("select currency, amount_off from master.coupon_amount where coupon_id = :i"), {"i": str(row.id)}
            )
        }
    return {**dict(row._mapping), "amounts": amounts}


def list_coupons() -> list[dict[str, Any]]:
    with master_session() as m:
        codes = list(m.execute(text("select code from master.coupon order by created_at desc")).scalars())
    return [get_coupon(c) for c in codes]


def set_coupon_status(code: str, status: str) -> dict[str, Any]:
    if status not in ("active", "disabled"):
        raise ValidationFailed("Status is active or disabled")
    with master_session() as m:
        if (
            m.execute(
                text("update master.coupon set status = :s where code = :c returning id"),
                {"s": status, "c": code.strip().upper()},
            ).first()
            is None
        ):
            raise NotFound("No such coupon")
    return get_coupon(code)


def check_coupon(coupon: dict[str, Any], plan_code: str, currency: str, now: datetime | None = None) -> None:
    """Raise ValidationFailed unless the coupon may be used now on this plan and currency."""
    if coupon["status"] != "active":
        raise ValidationFailed("This coupon is not active")
    if coupon["expires_at"] is not None and coupon["expires_at"] <= (now or _now()):
        raise ValidationFailed("This coupon has expired")
    if coupon["max_redemptions"] is not None and coupon["redeemed"] >= coupon["max_redemptions"]:
        raise ValidationFailed("This coupon has been used up")
    if coupon["plan_codes"] and plan_code not in coupon["plan_codes"]:
        raise ValidationFailed("This coupon is not valid for this plan")
    if coupon["percent_off"] is None and currency not in coupon["amounts"]:
        raise ValidationFailed(f"This coupon has no amount in {currency}")


def discount_for(coupon: dict[str, Any], currency: str, base: Decimal) -> Decimal:
    """The discount on `base`: a percentage (rounded half up to the cent) or the fixed amount, never more than
    `base`."""
    if coupon["percent_off"] is not None:
        return min(base, round_money(base * Decimal(coupon["percent_off"]) / 100))
    return min(base, Decimal(coupon["amounts"][currency]))


# --------------------------------------------------------------------------- the public price list
_PUBLIC_CACHE: dict[str, Any] = {"at": 0.0, "value": None}
PUBLIC_CACHE_SECONDS = 60


def invalidate_public_cache() -> None:
    _PUBLIC_CACHE["value"] = None


def public_plans(*, at: datetime | None = None, use_cache: bool = True) -> dict[str, Any]:
    """What the website and the in-app plan page show: public, active plans with the prices in force now, and public
    add-ons. Nothing else leaves the platform (no subscriber, no hidden plan, no retired price)."""
    import time

    if (
        use_cache
        and at is None
        and _PUBLIC_CACHE["value"] is not None
        and time.monotonic() - _PUBLIC_CACHE["at"] < PUBLIC_CACHE_SECONDS
    ):
        value: dict[str, Any] = _PUBLIC_CACHE["value"]
        return value
    plans: list[dict[str, Any]] = []
    stamps: list[datetime] = []
    with master_session() as m:
        plan_rows = list(
            m.execute(text("select * from master.plan where is_public and status = 'active' order by sort_order, name"))
        )
        addon_rows = list(
            m.execute(
                text("select * from master.addon where is_public and status = 'active' order by sort_order, name")
            )
        )
        newest = m.execute(
            text(
                "select greatest((select max(created_at) from master.plan_price), "
                "(select max(created_at) from master.addon_price))"
            )
        ).scalar()
    for p in plan_rows:
        stamps.append(p.updated_at)
        prices = [pr for pr in current_prices("plan", p.id, at) if pr.interval in p.intervals]
        limits = {
            "max_users": p.max_users,
            "max_branches": p.max_branches,
            "max_companies": p.max_companies,
            **(p.limits or {}),
        }
        plans.append(
            {
                "code": p.code,
                "name": p.name,
                "description": p.description,
                "edition": p.edition,
                "highlights": list(p.highlights),
                "limits": limits,
                "trial_days": p.trial_days,
                "prices": [_public_price(x) for x in prices],
            }
        )
    addons = []
    for a in addon_rows:
        stamps.append(a.updated_at)
        addons.append(
            {
                "code": a.code,
                "name": a.name,
                "description": a.description,
                "kind": a.kind,
                "unit": a.unit_name,
                "quantity": a.quantity,
                "prices": [_public_price(x) for x in current_prices("addon", a.id, at)],
            }
        )
    if newest is not None:
        stamps.append(newest)
    stamp = max(stamps) if stamps else datetime(1970, 1, 1, tzinfo=UTC)
    value = {"plans": plans, "addons": addons, "updated_at": stamp.isoformat()}
    if at is None:
        _PUBLIC_CACHE.update({"at": time.monotonic(), "value": value})
    return value


def _public_price(p: Price) -> dict[str, Any]:
    return {
        "currency": p.currency,
        "interval": p.interval,
        "amount": format(p.amount, "f"),
        "tax_inclusive": p.tax_inclusive,
    }
