"""Selling one add-on (a module or plugin) for one payment (docs/subscription-payments.md, "Add-ons").

A business may use its plan's units **plus** the add-ons it has bought. Nothing here is a plan change: buying an add-on
never touches the subscription, and a purchase survives upgrades, downgrades and renewals.

- **The price list** reuses `master.addon` (kind `unit`, `is_public` = offered for sale) and `master.addon_price`
  (interval `one_time`, one row per currency, append-only). The plan editor writes it through `set_unit_sale`.
- **Buying** makes a platform invoice with one line ("Add-on: <title> (one-time)", the usual tax lines) and a *pending*
  `master.subscription_addon` row. The business pays that invoice through the same payment machinery as a plan
  (`payments.py`: provider plugins, confirm-before-credit). Only when the invoice is credited
  (`billing._mark_paid` calls `on_invoice_paid`) does the row become *active*. A browser return or a webhook
  alone never grants anything.
- **Operators** may grant (comp, with a reason) or revoke an add-on on the subscriber page.
- While the platform switch `access.all_units_free` is on, every unit is included and nothing can be bought.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.platform import behaviour, billing, plans, subscriptions
from ziira.kernel.platform import entitlements as ent
from ziira.kernel.registry import discover

log = logging.getLogger("ziira.unit_addons")
FOR_SALE, NOT_FOR_SALE, BOUGHT, INCLUDED = "for_sale", "not_for_sale", "bought", "included"


def _now() -> datetime:
    return datetime.now(UTC)


def _sellable_units() -> dict[str, Any]:
    """The units that can be sold: modules and plugins (not the kernel, not platform-level provider plugins)."""
    return {n: m for n, m in discover().items() if not m.core and not m.platform_scope}


def _known(unit: str) -> Any:
    found = _sellable_units().get(unit)
    if found is None:
        raise NotFound("No such add-on")
    return found


# --------------------------------------------------------------------------- the price list (Super Admin)
def _addon_row(unit: str) -> Any:
    with master_session() as m:
        return m.execute(
            text("select * from master.addon where kind = 'unit' and unit_name = :u order by created_at limit 1"),
            {"u": unit},
        ).first()


def sale_currencies() -> list[str]:
    """The currencies the platform sells in: every currency it has a plan or add-on price, or a subscription, in."""
    with master_session() as m:
        rows = m.execute(
            text(
                "select currency from master.plan_price union select currency from master.addon_price "
                "union select currency from master.subscription"
            )
        )
        return sorted({str(r.currency).strip() for r in rows})


def sales_overview(*, at: datetime | None = None) -> dict[str, Any]:
    """Every unit's selling state: offered or not, and the one-time price in each currency."""
    out: dict[str, dict[str, Any]] = {}
    with master_session() as m:
        addons = list(m.execute(text("select * from master.addon where kind = 'unit' and status = 'active'")))
    for a in addons:
        live = [p for p in plans.current_prices("addon", a.id, at) if p.interval == "one_time"]
        out[a.unit_name] = {
            "unit": a.unit_name,
            "offered": bool(a.is_public),
            "prices": {p.currency: p.amount for p in live},
            "tax_inclusive": any(p.tax_inclusive for p in live),
        }
    for name in _sellable_units():
        out.setdefault(name, {"unit": name, "offered": False, "prices": {}, "tax_inclusive": False})
    return {"currencies": sale_currencies(), "units": sorted(out.values(), key=lambda u: u["unit"])}


def _addon_code(unit: str) -> str:
    code = unit.lower().replace(".", "-")
    if plans.CODE.match(code) and not _code_taken(code):
        return code
    return f"u-{code}"[:40]


def _code_taken(code: str) -> bool:
    with master_session() as m:
        return m.execute(text("select 1 from master.addon where code = :c"), {"c": code}).first() is not None


def set_unit_sale(
    unit: str,
    *,
    offered: bool,
    prices: dict[str, Any],
    tax_inclusive: bool = False,
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Offer a unit for sale (or stop), with its one-time price per currency. A blank price in a currency withdraws it.
    Prices are append-only like all prices: a changed amount adds a row, the old one stays for the record."""
    manifest = _known(unit)
    wanted: dict[str, Decimal | None] = {}
    for cur, amount in prices.items():
        code = plans._currency(cur)
        value = None if amount in (None, "") else plans.money(amount, f"The {code} price")
        if value is not None and value <= 0:
            raise ValidationFailed(f"The {code} price must be more than zero")
        wanted[code] = value
    row = _addon_row(unit)
    if row is None:
        row = _create_unit_addon(unit, manifest.title, manifest.description)
    with master_session() as m:
        m.execute(
            text("update master.addon set is_public = :p, status = 'active', updated_at = now() where id = :i"),
            {"p": offered, "i": str(row.id)},
        )
    for cur, amount in wanted.items():
        current = plans.price_at("addon", row.id, cur, "one_time", now)
        if amount is None:
            if current is not None:
                plans.set_price(
                    "addon", row.id, currency=cur, interval="one_time", amount=current.amount,
                    tax_inclusive=current.tax_inclusive, withdrawn=True, by=by, now=now,
                )
        elif current is None or current.amount != amount or current.tax_inclusive != tax_inclusive:
            plans.set_price(
                "addon", row.id, currency=cur, interval="one_time", amount=amount, tax_inclusive=tax_inclusive,
                by=by, now=now,
            )
    live = [p for p in plans.current_prices("addon", row.id, now) if p.interval == "one_time"]
    if offered and not live:
        with master_session() as m:
            m.execute(text("update master.addon set is_public = false where id = :i"), {"i": str(row.id)})
        raise ValidationFailed("Set a price in at least one currency before offering this for sale")
    return next(u for u in sales_overview(at=now)["units"] if u["unit"] == unit)


def _create_unit_addon(unit: str, title: str, description: str) -> Any:
    created = plans.create_addon(
        {
            "code": _addon_code(unit),
            "name": title[:80],
            "description": description[:500],
            "kind": "unit",
            "unit_name": unit,
            "is_public": False,
        }
    )
    return _addon_row(created["unit_name"])


def offer_for(unit: str, currency: str, at: datetime | None = None) -> dict[str, Any] | None:
    """The one-time offer for a unit in a currency: {"price", "tax_inclusive", "currency"}, or None when it is not for
    sale (not offered, retired, or no price in that currency)."""
    row = _addon_row(unit)
    if row is None or not row.is_public or row.status != "active":
        return None
    price = plans.price_at("addon", row.id, currency.strip().upper(), "one_time", at)
    if price is None or price.amount <= 0:
        return None
    return {"price": price.amount, "tax_inclusive": price.tax_inclusive, "currency": price.currency}


def _offers(currency: str, at: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Every unit offered for sale in a currency (unit -> offer), in one pass."""
    with master_session() as m:
        rows = list(
            m.execute(
                text(
                    "select id, unit_name from master.addon where kind = 'unit' and is_public and status = 'active'"
                )
            )
        )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        price = plans.price_at("addon", r.id, currency.strip().upper(), "one_time", at)
        if price is not None and price.amount > 0:
            out[r.unit_name] = {"price": price.amount, "tax_inclusive": price.tax_inclusive, "currency": price.currency}
    return out


# --------------------------------------------------------------------------- what a business has bought
_COLUMNS = (
    "a.id, a.tenant_id, a.unit_name, a.status, a.price, a.currency, a.invoice_id, a.payment_reference, a.granted_by, "
    "a.granted_by_name, a.reason, a.purchased_at, a.revoked_at, a.revoked_by, a.revoke_reason, a.created_at, "
    "i.number as invoice_number"
)


def _view(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    d["currency"] = str(d["currency"]).strip() if d["currency"] else None
    unit = discover().get(d["unit_name"])
    d["title"] = unit.title if unit else d["unit_name"]
    return d


def list_for_tenant(tenant_id: UUID, *, include_closed: bool = True) -> list[dict[str, Any]]:
    """The business's add-on records, newest first (pending, active, revoked)."""
    with master_session() as m:
        rows = m.execute(
            text(
                f"select {_COLUMNS} from master.subscription_addon a left join master.billing_invoice i "
                "on i.id = a.invoice_id where a.tenant_id = :t and (:c or a.status in ('pending', 'active')) "
                "order by a.created_at desc"
            ),
            {"t": str(tenant_id), "c": include_closed},
        )
        return [_view(r) for r in rows]


def purchased_units(tenant_id: UUID) -> frozenset[str]:
    with master_session() as m:
        return frozenset(
            m.execute(
                text("select unit_name from master.subscription_addon where tenant_id = :t and status = 'active'"),
                {"t": str(tenant_id)},
            ).scalars()
        )


def shop(tenant_id: UUID, *, can_buy: bool, now: datetime | None = None) -> dict[str, Any]:
    """What this business can buy, with prices in its billing currency, and what it has bought.

    `state` per unit: `included` (in the plan, or everything is free right now), `bought`, `for_sale` or `not_for_sale`.
    """
    moment = now or _now()
    free = behaviour.all_units_free()
    entitled = ent.for_tenant(tenant_id, use_cache=False)
    sub = subscriptions.get(tenant_id) if ent.mode() == "saas" else None
    currency = sub["currency"].strip() if sub else None
    purchases = list_for_tenant(tenant_id)
    bought = {r["unit_name"]: r for r in purchases if r["status"] == "active"}
    offers = _offers(currency, moment) if currency and sub is not None else {}
    units: list[dict[str, Any]] = []
    for name, manifest in sorted(_sellable_units().items(), key=lambda kv: kv[1].title):
        offer = offers.get(name)
        if name in bought:
            state = BOUGHT
        elif free or entitled.units is None or name in entitled.units:
            state = INCLUDED
        else:
            state = FOR_SALE if offer else NOT_FOR_SALE
        units.append(
            {
                "unit": name,
                "title": manifest.title,
                "state": state,
                "price": offer["price"] if offer and state == FOR_SALE else None,
                "currency": offer["currency"] if offer and state == FOR_SALE else None,
                "tax_inclusive": bool(offer and offer["tax_inclusive"]),
                "purchase": bought.get(name),
            }
        )
    can = bool(sub is not None and not free and ent.mode() == "saas" and sub["status"] in subscriptions.LIVE)
    return {
        "free_for_all": free,
        "currency": currency,
        "can_buy": can_buy and can,
        "units": units,
        "purchases": purchases,
    }


# --------------------------------------------------------------------------- buying
def _line(title: str, price: Decimal) -> dict[str, Any]:
    return {"description": f"Add-on: {title} (one-time)", "quantity": 1, "unit_amount": price}


def _reusable(purchase: Any, price: Decimal) -> dict[str, Any] | None:
    """The invoice of a pending purchase, if it can still be paid as it is (issued, same price, nothing paid yet)."""
    if purchase.invoice_id is None:
        return None
    invoice = billing.get_invoice(purchase.invoice_id)
    lines = invoice.get("lines") or []
    same_price = len(lines) == 1 and Decimal(str(lines[0].get("unit_amount"))) == price
    if invoice["status"] == "issued" and same_price:
        return invoice
    return None


def buy(
    tenant_id: UUID,
    unit: str,
    *,
    by_name: str,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start buying an add-on: an issued invoice with one line, ready to pay, and a pending purchase.

    Safe to repeat: the same `idempotency_key`, or a second request while a purchase of that unit is waiting for
    payment, returns the same invoice. Nothing is granted here; see `on_invoice_paid`."""
    moment = now or _now()
    if behaviour.all_units_free():
        raise Conflict("Every add-on is included for now, so there is nothing to buy.")
    if ent.mode() != "saas":
        raise Conflict("This copy of Ziira is self-hosted: add-ons come with your licence.")
    manifest = _known(unit)
    sub = subscriptions.get(tenant_id)
    if sub is None:
        raise Conflict("Your account has no subscription, so every add-on is already available.")
    if sub["status"] not in subscriptions.LIVE:
        raise Conflict("Your account needs attention first: pay your outstanding invoice or choose a plan.")
    entitled = ent.for_tenant(tenant_id, use_cache=False)
    if entitled.units is None or unit in entitled.units:
        raise Conflict(f"{manifest.title} is already available to you.")
    offer = offer_for(unit, sub["currency"], moment)
    if offer is None:
        raise Conflict(f"{manifest.title} is not for sale. Ask us if you need it.")
    price: Decimal = offer["price"]

    with master_session() as m:
        if idempotency_key:
            same = m.execute(
                text("select * from master.subscription_addon where tenant_id = :t and idempotency_key = :k"),
                {"t": str(tenant_id), "k": idempotency_key},
            ).first()
            if same is not None:
                if same.unit_name != unit:
                    raise Conflict("That Idempotency-Key was used for a different add-on")
                return _result(same.id)
        waiting = m.execute(
            text(
                "select * from master.subscription_addon where tenant_id = :t and unit_name = :u and status = 'pending'"
            ),
            {"t": str(tenant_id), "u": unit},
        ).first()
    if waiting is not None:
        if _reusable(waiting, price) is not None:
            return _result(waiting.id)
        _close_pending(waiting, "replaced by a new purchase", by_name, moment)

    invoice = billing.create_invoice(
        tenant_id=tenant_id,
        currency=sub["currency"].strip(),
        lines=[_line(manifest.title, price)],
        kind="addon",
        tax_inclusive=offer["tax_inclusive"],
        created_by=by_name,
        issue=True,                         # the price is above zero, so issuing never marks it paid on the spot
        now=moment,
    )
    try:
        with master_session() as m:
            row = m.execute(
                text(
                    "insert into master.subscription_addon (tenant_id, unit_name, status, price, currency, invoice_id, "
                    "idempotency_key, granted_by, created_by) values (:t, :u, 'pending', :p, :c, :i, :k, 'payment', "
                    ":b) returning id"
                ),
                {
                    "t": str(tenant_id), "u": unit, "p": price, "c": sub["currency"].strip(),
                    "i": str(invoice["id"]), "k": idempotency_key, "b": by_name,
                },
            ).one()
    except IntegrityError:                                         # a parallel click won: use its purchase
        billing.void_invoice(invoice["id"], "duplicate add-on purchase", by=by_name, now=moment)
        with master_session() as m:
            other = m.execute(
                text(
                    "select id from master.subscription_addon where tenant_id = :t and unit_name = :u "
                    "and status in ('pending', 'active')"
                ),
                {"t": str(tenant_id), "u": unit},
            ).first()
        if other is None:
            raise
        return _result(other.id)
    subscriptions.record_event(tenant_id, "addon.buy_started", {"unit": unit, "price": str(price)}, by_name)
    return _result(row.id)


def _result(purchase_id: UUID) -> dict[str, Any]:
    with master_session() as m:
        row = m.execute(
            text(
                f"select {_COLUMNS} from master.subscription_addon a left join master.billing_invoice i "
                "on i.id = a.invoice_id where a.id = :i"
            ),
            {"i": str(purchase_id)},
        ).one()
    invoice = billing.get_invoice(row.invoice_id) if row.invoice_id else None
    return {"purchase": _view(row), "invoice": invoice}


def _close_pending(row: Any, why: str, by: str | None, moment: datetime) -> None:
    """Withdraw a purchase nobody paid for (its unpaid invoice is voided; one with money against it is left alone)."""
    if row.invoice_id is not None:
        invoice = billing.get_invoice(row.invoice_id)
        if invoice["amount_paid"] > 0:
            raise Conflict("A payment for this add-on is being processed: wait a moment")
        if invoice["status"] in ("draft", "issued"):
            billing.void_invoice(row.invoice_id, why, by=by, now=moment)
    with master_session() as m:
        m.execute(
            text("update master.subscription_addon set status = 'void', idempotency_key = null where id = :i"),
            {"i": str(row.id)},
        )


# --------------------------------------------------------------------------- granting (called by billing, operators)
def on_invoice_paid(invoice: dict[str, Any], *, now: datetime | None = None, by: str | None = None) -> None:
    """An add-on invoice is fully paid (credited): the purchase becomes active. Repeating it changes nothing."""
    moment = now or _now()
    granted: tuple[UUID, str] | None = None
    with master_session() as m:
        row = m.execute(
            text("select * from master.subscription_addon where invoice_id = :i for update"), {"i": str(invoice["id"])}
        ).first()
        if row is None:
            log.warning("Add-on invoice %s was paid but has no purchase record", invoice.get("number"))
            return
        if row.status in ("pending", "void"):
            reference = m.execute(
                text(
                    "select reference from master.billing_payment where invoice_id = :i and reversed_at is null "
                    "order by created_at desc limit 1"
                ),
                {"i": str(invoice["id"])},
            ).scalar()
            taken = m.execute(
                text(
                    "select 1 from master.subscription_addon where tenant_id = :t and unit_name = :u and status = "
                    "'active' and id <> :i"
                ),
                {"t": str(row.tenant_id), "u": row.unit_name, "i": str(row.id)},
            ).first()
            if taken is not None:
                log.warning("Add-on %s paid for %s, which already has it", row.unit_name, row.tenant_id)
                return
            m.execute(
                text(
                    "update master.subscription_addon set status = 'active', purchased_at = :at, "
                    "payment_reference = :r, granted_by = 'payment' where id = :i"
                ),
                {"at": moment, "r": reference or None, "i": str(row.id)},
            )
            granted = (row.tenant_id, row.unit_name)
    if granted is not None:
        ent.invalidate(granted[0])
        subscriptions.record_event(
            granted[0], "addon.purchased", {"unit": granted[1], "invoice": invoice.get("number")}, by
        )


def on_payment_reversed(invoice: dict[str, Any], *, by: str | None = None) -> None:
    """A payment for an add-on was reversed and the invoice is open again: the add-on is taken back (data kept)."""
    if invoice.get("kind") != "addon" or invoice["status"] == "paid":
        return
    with master_session() as m:
        row = m.execute(
            text("select * from master.subscription_addon where invoice_id = :i and status = 'active'"),
            {"i": str(invoice["id"])},
        ).first()
    if row is not None:
        _revoke_row(row, "the payment was reversed", by or "system", _now())


def grant(tenant_id: UUID, unit: str, reason: str, *, by: str, now: datetime | None = None) -> dict[str, Any]:
    """An operator gives a business an add-on (a comp). Needs a reason; no payment, no invoice."""
    moment = now or _now()
    manifest = _known(unit)
    if len(reason.strip()) < 5:
        raise ValidationFailed("Say why (at least 5 characters)")
    sub = subscriptions.get(tenant_id)
    if sub is None:
        raise Conflict("This business has no subscription, so every add-on is already available")
    entitled = ent.for_tenant(tenant_id, use_cache=False)
    if purchased_units(tenant_id) & {unit}:
        raise Conflict(f"This business already has {manifest.title}")
    if entitled.units is None or unit in entitled.units:
        raise Conflict(f"{manifest.title} is already in this business's plan")
    with master_session() as m:
        waiting = m.execute(
            text(
                "select * from master.subscription_addon where tenant_id = :t and unit_name = :u "
                "and status = 'pending'"
            ),
            {"t": str(tenant_id), "u": unit},
        ).first()
    if waiting is not None:
        _close_pending(waiting, "the add-on was given by the vendor", by, moment)
    with master_session() as m:
        row = m.execute(
            text(
                "insert into master.subscription_addon (tenant_id, unit_name, status, price, granted_by, "
                "granted_by_name, reason, purchased_at, created_by) values (:t, :u, 'active', 0, 'operator', :b, :r, "
                ":at, :b) returning id"
            ),
            {"t": str(tenant_id), "u": unit, "b": by, "r": reason.strip()[:500], "at": moment},
        ).one()
    ent.invalidate(tenant_id)
    subscriptions.record_event(tenant_id, "addon.granted", {"unit": unit, "reason": reason.strip()[:200]}, by)
    purchase: dict[str, Any] = _result(row.id)["purchase"]
    return purchase


def revoke(tenant_id: UUID, unit: str, reason: str, *, by: str, now: datetime | None = None) -> dict[str, Any]:
    """An operator takes an add-on back. The unit is switched off for the business, its data is kept. No refund is
    made here: reverse the payment on the invoice if one is due."""
    moment = now or _now()
    _known(unit)
    if len(reason.strip()) < 5:
        raise ValidationFailed("Say why (at least 5 characters)")
    with master_session() as m:
        row = m.execute(
            text(
                "select * from master.subscription_addon where tenant_id = :t and unit_name = :u "
                "and status in ('pending', 'active')"
            ),
            {"t": str(tenant_id), "u": unit},
        ).first()
    if row is None:
        raise NotFound("This business does not have that add-on")
    if row.status == "pending":
        _close_pending(row, reason.strip(), by, moment)
    else:
        _revoke_row(row, reason.strip()[:500], by, moment)
    return next(p for p in list_for_tenant(tenant_id) if p["id"] == row.id)


def _revoke_row(row: Any, reason: str, by: str, moment: datetime) -> None:
    with master_session() as m:
        m.execute(
            text(
                "update master.subscription_addon set status = 'revoked', revoked_at = :at, revoked_by = :b, "
                "revoke_reason = :r where id = :i and status = 'active'"
            ),
            {"at": moment, "b": by, "r": reason, "i": str(row.id)},
        )
    ent.invalidate(row.tenant_id)
    subscriptions.enforce_units(row.tenant_id)
    subscriptions.record_event(row.tenant_id, "addon.revoked", {"unit": row.unit_name, "reason": reason[:200]}, by)
