"""Billing records: invoices, payments, renewals and dunning (docs/platform-admin.md, "Billing").

The vendor bills subscribers (and licence customers) here. Rules:

- An invoice is built from lines; tax lines come from the vendor's settings (`billing.tax_lines`, never code) and are
  copied onto the invoice. A price is either tax-inclusive (the tax is part of it) or exclusive (tax is added).
- A draft has no number. Issuing gives the next number from a counter inside the same transaction, fixes the dates and
  the vendor and customer details. An issued invoice is never edited: it is paid or voided.
- Payments are recorded by hand (`manual` provider) or reported by a provider's webhook; a payment can be reversed.
- `run_due` (the worker, hourly) creates renewal invoices ahead of the period end, sends reminders and moves a
  subscription past due -> grace -> suspended -> expired by the dunning schedule in settings. It is safe to run again.
"""

import html
import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.kernel import platform_mail
from ziira.kernel.db import master_session
from ziira.kernel.errors import Conflict, NotFound, ValidationFailed
from ziira.kernel.platform import contacts, plans, providers, settings, subscriptions

log = logging.getLogger("ziira.billing")
ZERO = Decimal("0.00")
STATUS_RANK = {"trialing": 0, "active": 0, "past_due": 1, "grace": 2, "suspended": 3, "expired": 4}


def _now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- amounts
def _line(description: str, quantity: Any, unit_amount: Any, *, discount: bool = False) -> dict[str, Any]:
    qty = Decimal(str(quantity))
    unit = Decimal(str(unit_amount))
    if qty <= 0:
        raise ValidationFailed("A line's quantity must be more than zero")
    if not description.strip():
        raise ValidationFailed("Every line needs a description")
    return {
        "description": description.strip()[:300],
        "quantity": format(qty.normalize(), "f"),
        "unit_amount": format(unit, "f"),
        "amount": format(plans.round_money(qty * unit), "f"),
        "discount": discount,
    }


def compute_totals(lines: list[dict[str, Any]], tax_lines: list[dict[str, str]], tax_inclusive: bool) -> dict[str, Any]:
    """The invoice's money, hand-checkable: subtotal (charges), discount, tax per line and total.

    Exclusive: tax_i = round(net x rate_i / 100); total = net + taxes.
    Inclusive: the net already holds the tax; tax_i = round(net x rate_i / (100 + sum of rates)), the last line takes
    any
    rounding difference so that the taxes add up to net - net / (1 + rates), and total = net."""
    charges = sum((Decimal(x["amount"]) for x in lines if Decimal(x["amount"]) > 0), ZERO)
    discount = -sum((Decimal(x["amount"]) for x in lines if Decimal(x["amount"]) < 0), ZERO)
    if discount > charges:
        raise ValidationFailed("The discounts are more than the charges")
    net = charges - discount
    rates = [Decimal(t["rate_percent"]) for t in tax_lines]
    taxes: list[Decimal] = []
    if rates and net > 0:
        if tax_inclusive:
            combined = sum(rates)
            total_tax = net - plans.round_money(net * 100 / (100 + combined))
            taxes = [plans.round_money(net * r / (100 + combined)) for r in rates]
            taxes[-1] += total_tax - sum(taxes, ZERO)
        else:
            taxes = [plans.round_money(net * r / 100) for r in rates]
    tax_total = sum(taxes, ZERO)
    total = net if tax_inclusive else net + tax_total
    return {
        "subtotal": charges,
        "discount_total": discount,
        "tax_total": tax_total,
        "total": total,
        "tax_lines": [
            {"name": t["name"], "rate_percent": t["rate_percent"], "amount": format(a, "f")}
            for t, a in zip(tax_lines, taxes, strict=False)
        ],
    }


# --------------------------------------------------------------------------- invoices
def _public(row: Any) -> dict[str, Any]:
    d = dict(row._mapping)
    d["balance"] = d["total"] - d["amount_paid"]
    return d


def get_invoice(invoice_id: UUID, *, tenant_id: UUID | None = None) -> dict[str, Any]:
    """One invoice; with `tenant_id` only if it is that business's (a business can never read another's)."""
    with master_session() as m:
        row = m.execute(text("select * from master.billing_invoice where id = :i"), {"i": str(invoice_id)}).first()
    if row is None or (tenant_id is not None and row.tenant_id != tenant_id):
        raise NotFound("No such invoice")
    return _public(row)


def list_invoices(
    *,
    tenant_id: UUID | None = None,
    status: str | None = None,
    include_drafts: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with master_session() as m:
        rows = m.execute(
            text(
                "select i.*, t.code as tenant_code, t.name as tenant_name from master.billing_invoice i "
                "left join master.tenant t on t.id = i.tenant_id "
                "where (cast(:t as uuid) is null or i.tenant_id = :t) and (cast(:s as text) is null or i.status = :s) "
                "and (:d or i.status <> 'draft') order by i.created_at desc limit :l offset :o"
            ),
            {"t": str(tenant_id) if tenant_id else None, "s": status, "d": include_drafts, "l": limit, "o": offset},
        )
        return [_public(r) for r in rows]


def _bill_to(tenant_id: UUID | None, licence: dict[str, Any] | None) -> dict[str, Any]:
    if tenant_id is not None:
        with master_session() as m:
            tenant = m.execute(
                text("select code, name from master.tenant where id = :i"), {"i": str(tenant_id)}
            ).first()
        owners = contacts.owner_contacts(tenant_id)
        return {
            "name": tenant.name if tenant else "",
            "code": tenant.code if tenant else "",
            "contact": owners[0]["name"] if owners else "",
            "email": owners[0]["email"] if owners else "",
        }
    if licence is not None:
        return {
            "name": licence["customer"],
            "code": licence["licence_no"],
            "contact": "",
            "email": licence["contact_email"] or "",
        }
    return {}


def create_invoice(
    *,
    currency: str,
    lines: list[dict[str, Any]],
    tenant_id: UUID | None = None,
    licence_id: UUID | None = None,
    kind: str = "manual",
    tax_inclusive: bool = False,
    notes: str = "",
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    plan_change: dict[str, Any] | None = None,
    coupon_id: UUID | None = None,
    due_date: date | None = None,
    created_by: str | None = None,
    issue: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Make a draft invoice (or issue it at once). Lines are {description, quantity, unit_amount}; a negative unit
    amount is
    a discount."""
    if (tenant_id is None) == (licence_id is None):
        raise ValidationFailed("An invoice is for a subscriber or for a licence customer")
    cur = currency.strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise ValidationFailed("Currency is a three-letter code such as USD")
    if not lines:
        raise ValidationFailed("An invoice needs at least one line")
    built = [
        _line(x["description"], x.get("quantity", 1), x["unit_amount"], discount=Decimal(str(x["unit_amount"])) < 0)
        for x in lines
    ]
    totals = compute_totals(built, settings.get("billing.tax_lines"), tax_inclusive)
    licence = None
    if licence_id is not None:
        from ziira.kernel.platform import licences

        licence = licences.get_licence(licence_id)
    bill_to = _bill_to(tenant_id, licence)
    with master_session() as m:
        row = m.execute(
            text(
                "insert into master.billing_invoice (tenant_id, licence_id, bill_to, kind, currency, lines, tax_lines, "
                "tax_inclusive, subtotal, discount_total, tax_total, total, period_start, period_end, due_date, "
                "plan_change, coupon_id, notes, created_by) values (:t, :l, cast(:b as jsonb), :k, :c, cast(:li as "
                "jsonb), "
                "cast(:tl as jsonb), :ti, :s, :d, :tt, :to, :ps, :pe, :due, cast(:pc as jsonb), :co, :n, :by) "
                "returning id"
            ),
            {
                "t": str(tenant_id) if tenant_id else None,
                "l": str(licence_id) if licence_id else None,
                "b": json.dumps(bill_to),
                "k": kind,
                "c": cur,
                "li": json.dumps(built),
                "tl": json.dumps(totals["tax_lines"]),
                "ti": tax_inclusive,
                "s": totals["subtotal"],
                "d": totals["discount_total"],
                "tt": totals["tax_total"],
                "to": totals["total"],
                "ps": period_start,
                "pe": period_end,
                "due": due_date,
                "pc": json.dumps(plan_change) if plan_change else None,
                "co": str(coupon_id) if coupon_id else None,
                "n": notes.strip()[:2000],
                "by": created_by,
            },
        ).one()
    if issue:
        return issue_invoice(row.id, by=created_by, now=now)
    return get_invoice(row.id)


def update_draft(
    invoice_id: UUID,
    *,
    lines: list[dict[str, Any]] | None = None,
    notes: str | None = None,
    due_date: date | None = None,
    tax_inclusive: bool | None = None,
) -> dict[str, Any]:
    """Change a draft (an issued invoice cannot be edited: void it and make a new one)."""
    inv = get_invoice(invoice_id)
    if inv["status"] != "draft":
        raise Conflict("Only a draft can be edited: void an issued invoice and make a new one")
    built = (
        inv["lines"]
        if lines is None
        else [
            _line(x["description"], x.get("quantity", 1), x["unit_amount"], discount=Decimal(str(x["unit_amount"])) < 0)
            for x in lines
        ]
    )
    inclusive = inv["tax_inclusive"] if tax_inclusive is None else tax_inclusive
    totals = compute_totals(built, settings.get("billing.tax_lines"), inclusive)
    with master_session() as m:
        m.execute(
            text(
                "update master.billing_invoice set lines = cast(:li as jsonb), tax_lines = cast(:tl as jsonb), "
                "tax_inclusive = :ti, subtotal = :s, discount_total = :d, tax_total = :tt, total = :to, "
                "notes = coalesce(:n, notes), due_date = coalesce(:due, due_date) where id = :i"
            ),
            {
                "li": json.dumps(built),
                "tl": json.dumps(totals["tax_lines"]),
                "ti": inclusive,
                "s": totals["subtotal"],
                "d": totals["discount_total"],
                "tt": totals["tax_total"],
                "to": totals["total"],
                "n": notes.strip()[:2000] if notes is not None else None,
                "due": due_date,
                "i": str(invoice_id),
            },
        )
    return get_invoice(invoice_id)


def _next_number() -> str:
    prefix = settings.get("billing.invoice_prefix")
    with master_session() as m:
        m.execute(
            text(
                "insert into master.billing_counter (name, last_value) values ('invoice', 0) "
                "on conflict (name) do nothing"
            )
        )
        n = m.execute(
            text(
                "update master.billing_counter set last_value = last_value + 1 where name = 'invoice' "
                "returning last_value"
            )
        ).scalar_one()
    return f"{prefix}{n:06d}"


def issue_invoice(invoice_id: UUID, *, by: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Number and issue a draft. A zero invoice is paid at once."""
    moment = now or _now()
    inv = get_invoice(invoice_id)
    if inv["status"] != "draft":
        raise Conflict("This invoice is already issued")
    number = _next_number()
    due = inv["due_date"] or (moment.date() + timedelta(days=int(settings.get("billing.due_days"))))
    with master_session() as m:
        m.execute(
            text(
                "update master.billing_invoice set status = 'issued', number = :n, issue_date = :d, due_date = :due, "
                "issued_at = :at, vendor = cast(:v as jsonb) where id = :i"
            ),
            {
                "n": number,
                "d": moment.date(),
                "due": due,
                "at": moment,
                "v": json.dumps(settings.get("vendor")),
                "i": str(invoice_id),
            },
        )
    out = get_invoice(invoice_id)
    if out["total"] <= 0:
        out = _mark_paid(out, moment, by)
    return out


def void_invoice(
    invoice_id: UUID, reason: str, *, by: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Cancel a draft or an issued invoice that has no live payment. The number stays used (and shows as void)."""
    inv = get_invoice(invoice_id)
    if inv["status"] in ("paid", "void") or inv["amount_paid"] > 0:
        raise Conflict("Reverse the payments first: an invoice with money against it cannot be voided")
    if len(reason.strip()) < 3:
        raise ValidationFailed("Say why")
    with master_session() as m:
        m.execute(
            text("update master.billing_invoice set status = 'void', voided_at = :at, void_reason = :r where id = :i"),
            {"at": now or _now(), "r": reason.strip(), "i": str(invoice_id)},
        )
        m.execute(
            text("update master.plan_request set status = 'cancelled' where invoice_id = :i and status = 'pending'"),
            {"i": str(invoice_id)},
        )
    return get_invoice(invoice_id)


# --------------------------------------------------------------------------- payments
def _mark_paid(inv: dict[str, Any], moment: datetime, by: str | None) -> dict[str, Any]:
    with master_session() as m:
        m.execute(
            text("update master.billing_invoice set status = 'paid', paid_at = :at where id = :i"),
            {"at": moment, "i": str(inv["id"])},
        )
    paid = get_invoice(inv["id"])
    if paid["tenant_id"] is not None:
        subscriptions.on_invoice_paid(paid, now=moment, by=by)
    return paid


def record_payment(
    invoice_id: UUID,
    *,
    method: str,
    amount: Any,
    paid_on: date | None = None,
    reference: str = "",
    provider: str = "manual",
    by: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record money received against an issued invoice. Paying it in full marks it paid and, for a subscriber, moves the
    subscription on (see `subscriptions.on_invoice_paid`)."""
    moment = now or _now()
    inv = get_invoice(invoice_id)
    if inv["status"] != "issued":
        raise Conflict("Payments are recorded against issued invoices")
    value = plans.money(amount)
    if value <= 0:
        raise ValidationFailed("The amount must be more than zero")
    if value > inv["balance"]:
        raise ValidationFailed(f"The amount is more than the {inv['balance']} still owed")
    if not method.strip():
        raise ValidationFailed("Say how it was paid (bank transfer, cash, ...)")
    with master_session() as m:
        m.execute(
            text(
                "insert into master.billing_payment (invoice_id, tenant_id, method, reference, amount, currency, "
                "paid_on, "
                "provider, recorded_by) values (:i, :t, :m, :r, :a, :c, :d, :p, :b)"
            ),
            {
                "i": str(invoice_id),
                "t": str(inv["tenant_id"]) if inv["tenant_id"] else None,
                "m": method.strip()[:60],
                "r": reference.strip()[:120],
                "a": value,
                "c": inv["currency"],
                "d": paid_on or moment.date(),
                "p": provider,
                "b": by,
            },
        )
        m.execute(
            text("update master.billing_invoice set amount_paid = amount_paid + :a where id = :i"),
            {"a": value, "i": str(invoice_id)},
        )
    fresh = get_invoice(invoice_id)
    if fresh["balance"] <= 0:
        fresh = _mark_paid(fresh, moment, by)
    return fresh


def reverse_payment(payment_id: UUID, reason: str, *, by: str | None = None) -> dict[str, Any]:
    """Undo a recorded payment (it stays in the list, marked reversed). A paid invoice goes back to issued. A
    subscription
    already moved on is not moved back: dunning will see the unpaid invoice and act on its schedule."""
    if len(reason.strip()) < 3:
        raise ValidationFailed("Say why")
    with master_session() as m:
        pay = m.execute(
            text("select * from master.billing_payment where id = :i for update"), {"i": str(payment_id)}
        ).first()
        if pay is None:
            raise NotFound("No such payment")
        if pay.reversed_at is not None:
            raise Conflict("This payment is already reversed")
        m.execute(
            text(
                "update master.billing_payment set reversed_at = now(), reversed_by = :b, reversal_reason = :r "
                "where id = :i"
            ),
            {"b": by, "r": reason.strip(), "i": str(payment_id)},
        )
        m.execute(
            text(
                "update master.billing_invoice set amount_paid = amount_paid - :a, "
                "status = case when status = 'paid' then 'issued' else status end, "
                "paid_at = case when status = 'paid' then null else paid_at end where id = :i"
            ),
            {"a": pay.amount, "i": str(pay.invoice_id)},
        )
    return get_invoice(pay.invoice_id)


def list_payments(invoice_id: UUID) -> list[dict[str, Any]]:
    with master_session() as m:
        return [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select id, method, reference, amount, currency, paid_on, provider, recorded_by, created_at, "
                    "reversed_at, "
                    "reversal_reason from master.billing_payment where invoice_id = :i order by created_at"
                ),
                {"i": str(invoice_id)},
            )
        ]


def record_provider_payments(provider_name: str, headers: dict[str, str], body: bytes) -> int:
    """A provider's webhook: check it, then record each payment it reports against the named invoice."""
    recorded = 0
    for p in providers.get(provider_name).parse_webhook(headers, body):
        with master_session() as m:
            row = m.execute(
                text("select id from master.billing_invoice where number = :n"), {"n": p.invoice_number}
            ).first()
        if row is None:
            log.warning("Provider %s reported a payment for unknown invoice %s", provider_name, p.invoice_number)
            continue
        record_payment(
            row.id,
            method=provider_name,
            amount=p.amount,
            reference=p.reference,
            provider=provider_name,
            paid_on=p.paid_on,
            by=f"provider:{provider_name}",
        )
        recorded += 1
    return recorded


# --------------------------------------------------------------------------- printable view
def invoice_html(inv: dict[str, Any], *, payment_instructions: str | None = None) -> str:
    """A self-contained printable page for an invoice (escaped; no scripts)."""
    e = html.escape
    vendor, bill = inv.get("vendor") or settings.get("vendor"), inv["bill_to"]
    rows = "".join(
        f"<tr><td>{e(x['description'])}</td><td class=n>{e(x['quantity'])}</td><td class=n>{e(x['unit_amount'])}</td>"
        f"<td class=n>{e(x['amount'])}</td></tr>"
        for x in inv["lines"]
    )
    taxes = "".join(
        f"<tr><td colspan=3>{e(t['name'])} ({e(t['rate_percent'])}%)"
        f"{' included' if inv['tax_inclusive'] else ''}</td><td class=n>{e(t['amount'])}</td></tr>"
        for t in inv["tax_lines"]
    )
    discount = (
        f"<tr><td colspan=3>Discount</td><td class=n>-{inv['discount_total']}</td></tr>"
        if inv["discount_total"] > 0
        else ""
    )
    instructions = (
        payment_instructions if payment_instructions is not None else settings.get("billing.payment_instructions")
    )
    title = inv["number"] or "Draft invoice"
    return (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        f"<title>{e(title)}</title><style>body{{font:14px/1.45 system-ui,sans-serif;margin:2rem;color:#111}}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{padding:.4rem .5rem;border-bottom:1px solid "
        "#ddd;"
        "text-align:left}.n{text-align:right}h1{margin:0}.muted{color:#555}.total td{font-weight:700}"
        ".stamp{float:right;border:2px solid #555;padding:.2rem .6rem;text-transform:uppercase}</style>"
        f"<span class=stamp>{e(inv['status'])}</span><h1>Invoice {e(title)}</h1>"
        f"<p class=muted>Issued {e(str(inv['issue_date'] or '-'))} · Due {e(str(inv['due_date'] or '-'))}</p>"
        f"<p><b>{e(str(vendor.get('name', '')))}</b><br>{e(str(vendor.get('address', ''))).replace(chr(10), '<br>')}"
        f"<br>{e(str(vendor.get('tax_id', '')))}</p>"
        f"<p><b>Bill to</b><br>{e(str(bill.get('name', '')))}<br>{e(str(bill.get('contact', '')))}"
        f"<br>{e(str(bill.get('email', '')))}</p>"
        f"<table><tr><th>Description</th><th class=n>Qty</th><th class=n>Unit ({e(inv['currency'])})</th>"
        f"<th class=n>Amount</th></tr>{rows}{discount}{taxes}"
        f"<tr class=total><td colspan=3>Total {e(inv['currency'])}</td><td class=n>{inv['total']}</td></tr>"
        f"<tr><td colspan=3>Paid</td><td class=n>{inv['amount_paid']}</td></tr>"
        f"<tr class=total><td colspan=3>Balance</td><td class=n>{inv['balance']}</td></tr></table>"
        f"<p class=muted>{e(inv['notes'])}</p><p>{e(instructions).replace(chr(10), '<br>')}</p></html>"
    )


# --------------------------------------------------------------------------- renewals
def _coupon_line(sub: dict[str, Any], base: Decimal, moment: datetime) -> tuple[dict[str, Any] | None, UUID | None]:
    if sub["coupon_id"] is None or sub["coupon_periods_left"] == 0:
        return None, None
    with master_session() as m:
        row = m.execute(text("select code from master.coupon where id = :i"), {"i": str(sub["coupon_id"])}).first()
    if row is None:
        return None, None
    coupon = plans.get_coupon(row.code)
    if sub["currency"] not in coupon["amounts"] and coupon["percent_off"] is None:
        return None, None
    amount = plans.discount_for(coupon, sub["currency"], base)
    if amount <= 0:
        return None, None
    return _line(f"Coupon {coupon['code']}", 1, -amount, discount=True), sub["coupon_id"]


def renewal_invoice(
    sub: dict[str, Any], *, now: datetime | None = None, by: str | None = None
) -> dict[str, Any] | None:
    """The invoice for the period after the current one (None when nothing is to be billed or it already exists)."""
    moment = now or _now()
    tenant_id: UUID = sub["tenant_id"]
    boundary = sub["trial_end"] if sub["status"] == "trialing" and sub["trial_end"] else sub["period_end"]
    if boundary is None or sub["is_comp"] or sub["cancel_at_period_end"] or sub["interval"] == "one_time":
        return None
    plan_name, amount, currency, interval, inclusive = (
        sub["plan_name"],
        sub["unit_amount"],
        sub["currency"],
        sub["interval"],
        sub["tax_inclusive"],
    )
    if sub["pending_plan_id"] is not None:
        plan = plans.plan_by_id(sub["pending_plan_id"])
        price = subscriptions.pick_price(plan, sub["pending_currency"], sub["pending_interval"], boundary)
        if price is not None:
            plan_name, amount, currency, interval, inclusive = (
                plan["name"],
                price.amount,
                price.currency,
                price.interval,
                price.tax_inclusive,
            )
    end = subscriptions.add_interval(boundary, interval)
    with master_session() as m:
        exists = m.execute(
            text(
                "select 1 from master.billing_invoice where tenant_id = :t and kind in ('renewal', 'first') "
                "and status <> 'void' and period_start = :p"
            ),
            {"t": str(tenant_id), "p": boundary},
        ).first()
    if exists or end is None:
        return None
    if amount <= 0:
        # A free plan has nothing to bill: its period simply rolls on.
        if sub["pending_plan_id"] is not None:
            subscriptions.apply_pending(tenant_id, by)
        subscriptions._update(tenant_id, period_start=boundary, period_end=end, trial_end=None)
        if sub["status"] in ("trialing", "past_due", "grace"):
            subscriptions._set_status(tenant_id, "active", None, by, moment)
        return None
    lines = [_line(f"{plan_name} ({interval}) {boundary:%Y-%m-%d} to {end:%Y-%m-%d}", 1, amount)]
    coupon_line, coupon_id = _coupon_line(sub, plans.round_money(amount), moment)
    if coupon_line is not None:
        lines.append(coupon_line)
    kind = "first" if sub["status"] == "trialing" else "renewal"
    invoice = create_invoice(
        tenant_id=tenant_id,
        currency=currency,
        lines=lines,
        kind=kind,
        tax_inclusive=inclusive,
        period_start=boundary,
        period_end=end,
        coupon_id=coupon_id,
        due_date=boundary.date(),
        created_by=by or "system",
        issue=True,
        now=moment,
    )
    if coupon_id is not None and sub["coupon_periods_left"] is not None:
        left = sub["coupon_periods_left"] - 1
        subscriptions._update(tenant_id, coupon_periods_left=left, **({"coupon_id": None} if left <= 0 else {}))
    subscriptions.record_event(
        tenant_id,
        "invoice.created",
        {"number": invoice["number"], "total": str(invoice["total"]), "kind": kind},
        by or "system",
    )
    _email_owners(
        tenant_id,
        f"Invoice {invoice['number']} from Ziira",
        f"Your invoice {invoice['number']} for {invoice['total']} {invoice['currency']} is ready. It is due on "
        f"{invoice['due_date']}.\n\n{settings.get('billing.payment_instructions')}\n{_pay_link()}",
    )
    return invoice


def _pay_link() -> str:
    """Where an owner pays by themselves (sign-in needed): added to invoice and reminder emails."""
    from ziira.kernel.config import get_settings

    return f"\nPay online or print the invoice: {get_settings().public_web_url.rstrip('/')}/billing (sign in first)\n"


def _email_owners(tenant_id: UUID, subject: str, body: str) -> int:
    sent = 0
    for owner in contacts.owner_contacts(tenant_id):
        try:
            platform_mail.send(owner["email"], subject, f"Hello {owner['name']},\n\n{body}")
            sent += 1
        except Exception:  # noqa: BLE001 - one undeliverable address must not stop the billing run
            log.warning("Could not email %s", owner["email"], exc_info=True)
    return sent


def _target_status(days: int, cfg: dict[str, Any]) -> str | None:
    if days >= cfg["expire_after_days"]:
        return "expired"
    if days >= cfg["suspend_after_days"]:
        return "suspended"
    if days >= cfg["grace_after_days"]:
        return "grace"
    if days >= cfg["past_due_after_days"]:
        return "past_due"
    return None


def dunning_status(days_overdue: int) -> str | None:
    """The status the dunning schedule gives an invoice `days_overdue` days after its due date (None: still fine)."""
    return _target_status(days_overdue, settings.get("billing.dunning"))


def run_due(*, now: datetime | None = None) -> dict[str, int]:
    """One pass of the platform's recurring billing work: renewal invoices, cancellations that fall due, reminders,
    status
    changes. Safe to repeat (each step checks what it has already done). Returns counts for the log."""
    moment = now or _now()
    counts = {"invoices": 0, "cancelled": 0, "reminders": 0, "moved": 0, "deletions": 0}
    lead = timedelta(days=int(settings.get("billing.renewal_lead_days")))
    with master_session() as m:
        subs = [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select s.* from master.subscription s join master.tenant t on t.id = s.tenant_id "
                    "where t.status = 'active' and s.status in ('trialing', 'active', 'past_due', 'grace')"
                )
            )
        ]
    for sub in subs:
        try:
            boundary = sub["trial_end"] if sub["status"] == "trialing" and sub["trial_end"] else sub["period_end"]
            if boundary is None:
                continue
            if sub["cancel_at_period_end"] and boundary <= moment:
                subscriptions._update(sub["tenant_id"], cancel_at_period_end=False)
                subscriptions._set_status(
                    sub["tenant_id"], "cancelled", "ended at the end of the period", "system", moment
                )
                counts["cancelled"] += 1
            elif boundary - lead <= moment and renewal_invoice(sub, now=moment) is not None:
                counts["invoices"] += 1
        except Exception:  # noqa: BLE001 - one business must not stop the others
            log.exception("Renewal failed for %s", sub["tenant_id"])
    reminders, moved = _dunning(moment)
    counts["reminders"], counts["moved"] = reminders, moved
    from ziira.kernel.platform import subscribers

    counts["deletions"] = subscribers.run_due_deletions(now=moment)
    return counts


def _dunning(moment: datetime) -> tuple[int, int]:
    cfg = settings.get("billing.dunning")
    today = moment.date()
    reminders = moved = 0
    with master_session() as m:
        due = [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select i.id, i.tenant_id, i.number, i.total, i.amount_paid, i.currency, i.due_date, s.status "
                    "from master.billing_invoice i join master.subscription s on s.tenant_id = i.tenant_id "
                    "where i.status = 'issued' and i.due_date is not null and i.tenant_id is not null "
                    "order by i.due_date"
                )
            )
        ]
    worst: dict[UUID, tuple[int, str]] = {}
    for inv in due:
        days = (today - inv["due_date"]).days
        if inv["tenant_id"] not in worst:
            worst[inv["tenant_id"]] = (days, inv["status"])
        reminders += _remind(inv, days, cfg)
    for tenant_id, (days, _) in worst.items():
        target = _target_status(days, cfg)
        sub = subscriptions.get(tenant_id)
        if target is None or sub is None or sub["is_comp"] or sub["status"] not in STATUS_RANK:
            continue
        if STATUS_RANK[target] > STATUS_RANK[sub["status"]]:
            subscriptions._set_status(tenant_id, target, f"invoice {days} days overdue", "system", moment)
            moved += 1
    return reminders, moved


def _remind(inv: dict[str, Any], days: int, cfg: dict[str, Any]) -> int:
    """Send the most recent due reminder of the schedule that has not gone yet (earlier unsent ones are marked as
    done)."""
    with master_session() as m:
        sent = set(
            m.execute(
                text("select offset_days from master.billing_reminder where invoice_id = :i"), {"i": str(inv["id"])}
            ).scalars()
        )
    pending = [o for o in cfg["reminders"] if o <= days and o not in sent]
    if not pending:
        return 0
    with master_session() as m:
        for offset in pending:
            m.execute(
                text(
                    "insert into master.billing_reminder (invoice_id, offset_days) values (:i, :o) "
                    "on conflict do nothing"
                ),
                {"i": str(inv["id"]), "o": offset},
            )
    owed = inv["total"] - inv["amount_paid"]
    when = f"is due in {-days} day(s)" if days < 0 else "is due today" if days == 0 else f"is {days} day(s) overdue"
    sent_to = _email_owners(
        inv["tenant_id"],
        f"Invoice {inv['number']}: {when}",
        f"Invoice {inv['number']} for {owed} {inv['currency']} {when} (due {inv['due_date']}).\n\n"
        f"{settings.get('billing.payment_instructions')}\n{_pay_link()}",
    )
    return 1 if sent_to else 0


# --------------------------------------------------------------------------- plan requests (self-serve upgrade)
def request_plan_change(
    tenant_id: UUID,
    plan_code: str,
    *,
    interval: str | None,
    currency: str | None,
    coupon_code: str | None,
    note: str,
    by_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A business asks for another plan. A draft invoice is made where money is due now (a new paid period, or the pro
    rata difference of an upgrade); the vendor's billing operators are emailed and decide. Nothing changes until the
    invoice is issued and paid, or an operator applies the change."""
    moment = now or _now()
    sub = subscriptions.require(tenant_id)
    plan = subscriptions._plan_for_sale(plan_code)
    price = subscriptions.pick_price(plan, currency or sub["currency"], interval or sub["interval"], moment)
    if price is None:
        raise ValidationFailed(f"{plan['name']} has no price to buy: choose another plan or ask the vendor")
    if plan["code"] == sub["plan_code"] and sub["status"] in subscriptions.LIVE and not sub["cancel_at_period_end"]:
        raise ValidationFailed("You are already on this plan")
    coupon = None
    if coupon_code and coupon_code.strip():
        coupon = plans.get_coupon(coupon_code)
        plans.check_coupon(coupon, plan["code"], price.currency, moment)
    with master_session() as m:
        if m.execute(
            text("select 1 from master.plan_request where tenant_id = :t and status = 'pending'"), {"t": str(tenant_id)}
        ).first():
            raise Conflict("You already have a plan request waiting for the vendor: wait for it or cancel it")
    change = {"plan_code": plan["code"], "interval": price.interval, "currency": price.currency}
    paying_now = (
        sub["is_comp"]
        or sub["status"] in ("trialing", "suspended", "cancelled", "expired", "past_due", "grace")
        or sub["period_end"] is None
    )
    invoice: dict[str, Any] | None = None
    if paying_now:
        end = subscriptions.add_interval(moment, price.interval)
        lines = [
            _line(
                f"{plan['name']} ({price.interval}) {moment:%Y-%m-%d} to {end:%Y-%m-%d}"
                if end
                else f"{plan['name']} (one-time)",
                1,
                price.amount,
            )
        ]
        if coupon is not None:
            discount = plans.discount_for(coupon, price.currency, price.amount)
            if discount > 0:
                lines.append(_line(f"Coupon {coupon['code']}", 1, -discount, discount=True))
        invoice = create_invoice(
            tenant_id=tenant_id,
            currency=price.currency,
            lines=lines,
            kind="first",
            tax_inclusive=price.tax_inclusive,
            period_start=moment,
            period_end=end,
            plan_change=change,
            created_by=by_name,
            now=moment,
        )
    elif price.currency == sub["currency"] and price.interval == sub["interval"] and price.amount > sub["unit_amount"]:
        due = subscriptions.prorate_due(
            sub["unit_amount"], price.amount, sub["period_start"], sub["period_end"], moment
        )
        if due > 0:
            invoice = create_invoice(
                tenant_id=tenant_id,
                currency=price.currency,
                kind="upgrade",
                tax_inclusive=price.tax_inclusive,
                lines=[
                    _line(
                        f"Upgrade to {plan['name']}: rest of period to {sub['period_end']:%Y-%m-%d}, pro rata", 1, due
                    )
                ],
                plan_change=change,
                created_by=by_name,
                now=moment,
            )
    with master_session() as m:
        request = m.execute(
            text(
                "insert into master.plan_request (tenant_id, plan_id, interval, currency, coupon_code, note, "
                "invoice_id, "
                "requested_by) values (:t, :p, :i, :c, :co, :n, :inv, :by) returning *"
            ),
            {
                "t": str(tenant_id),
                "p": str(plan["id"]),
                "i": price.interval,
                "c": price.currency,
                "co": coupon["code"] if coupon else None,
                "n": note.strip()[:1000],
                "inv": str(invoice["id"]) if invoice else None,
                "by": by_name,
            },
        ).one()
    subscriptions.record_event(tenant_id, "plan.requested", {"plan": plan["code"], "request": str(request.id)}, by_name)
    _tell_billing_operators(tenant_id, plan, by_name, note)
    return {**dict(request._mapping), "plan_code": plan["code"], "plan_name": plan["name"], "invoice": invoice}


def _tell_billing_operators(tenant_id: UUID, plan: dict[str, Any], by_name: str, note: str) -> None:
    with master_session() as m:
        tenant = m.execute(text("select name, code from master.tenant where id = :i"), {"i": str(tenant_id)}).first()
        emails = list(
            m.execute(
                text(
                    "select email from master.operator where status = 'active' and role in "
                    "('superadmin', 'billing') order by email"
                )
            ).scalars()
        )
    extra = [x.strip() for x in str(settings.get("billing.notify_emails")).split(",") if x.strip()]
    for address in sorted({*emails, *extra}):
        try:
            platform_mail.send(
                address,
                f"Plan request: {tenant.name if tenant else tenant_id}",
                f"{by_name} asked to move {tenant.name if tenant else ''} ({tenant.code if tenant else ''}) to "
                f"{plan['name']}.\n\n{note}\n\nOpen the Super Admin > Billing to review.",
            )
        except Exception:  # noqa: BLE001
            log.warning("Could not tell %s about a plan request", address, exc_info=True)


def list_requests(*, tenant_id: UUID | None = None, status: str | None = None) -> list[dict[str, Any]]:
    with master_session() as m:
        return [
            dict(r._mapping)
            for r in m.execute(
                text(
                    "select r.*, p.code as plan_code, p.name as plan_name, t.code as tenant_code, t.name as "
                    "tenant_name "
                    "from master.plan_request r join master.plan p on p.id = r.plan_id join master.tenant t on "
                    "t.id = r.tenant_id "
                    "where (cast(:t as uuid) is null or r.tenant_id = :t) and (cast(:s as text) is null or "
                    "r.status = :s) "
                    "order by r.created_at desc"
                ),
                {"t": str(tenant_id) if tenant_id else None, "s": status},
            )
        ]


def decide_request(request_id: UUID, approve: bool, *, by: str, now: datetime | None = None) -> dict[str, Any]:
    """Approve a plan request (issue its invoice, or apply the change when no money is due now) or decline it."""
    moment = now or _now()
    with master_session() as m:
        row = m.execute(
            text(
                "select r.*, p.code as plan_code from master.plan_request r join master.plan p on "
                "p.id = r.plan_id where r.id = :i for update of r"
            ),
            {"i": str(request_id)},
        ).first()
        if row is None:
            raise NotFound("No such request")
        if row.status != "pending":
            raise Conflict("This request has already been decided")
        m.execute(
            text("update master.plan_request set status = :s, decided_at = :at, decided_by = :b where id = :i"),
            {"s": "approved" if approve else "declined", "at": moment, "b": by, "i": str(request_id)},
        )
    invoice = get_invoice(row.invoice_id) if row.invoice_id else None
    if not approve:
        if invoice and invoice["status"] == "draft":
            void_invoice(invoice["id"], "request declined", by=by, now=moment)
        subscriptions.record_event(row.tenant_id, "plan.declined", {"plan": row.plan_code}, by)
        return {"status": "declined", "invoice": None}
    if invoice is not None:
        invoice = issue_invoice(invoice["id"], by=by, now=moment)
        _email_owners(
            row.tenant_id,
            f"Invoice {invoice['number']} for your plan change",
            f"Your plan change is ready once invoice {invoice['number']} ({invoice['total']} "
            f"{invoice['currency']}) is paid by {invoice['due_date']}.\n\n"
            f"{settings.get('billing.payment_instructions')}\n{_pay_link()}",
        )
    else:
        subscriptions.change_plan(
            row.tenant_id, row.plan_code, interval=row.interval, currency=row.currency, by=by, now=moment
        )
    return {"status": "approved", "invoice": invoice}


def cancel_request(tenant_id: UUID, request_id: UUID) -> None:
    """The business withdraws its own pending request (and a draft invoice made for it is voided)."""
    with master_session() as m:
        row = m.execute(
            text(
                "update master.plan_request set status = 'cancelled' where id = :i and tenant_id = :t "
                "and status = 'pending' returning invoice_id"
            ),
            {"i": str(request_id), "t": str(tenant_id)},
        ).first()
    if row is None:
        raise NotFound("No such pending request")
    if row.invoice_id:
        inv = get_invoice(row.invoice_id)
        if inv["status"] == "draft":
            void_invoice(inv["id"], "request withdrawn")
