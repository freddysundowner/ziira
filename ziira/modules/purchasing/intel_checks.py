"""Intelligence checks over buying: what suppliers charge, what is owed and paid, and who changed what.

Each check reads Purchasing's own tables (and, for payments, Payments' public view of a bill's payments) and reports
questions with their evidence; none of them writes anything.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from ziira.modules.intel.public import Candidate, CheckContext, IntelCheck, Record, fingerprint
from ziira.modules.payments.public import payments_for_document
from ziira.modules.products.public import find_product, product_labels, selling_prices
from ziira.modules.purchasing.domain import watch
from ziira.modules.purchasing.services.common import unit_enabled
from ziira.sdk import Session

CENT = Decimal("0.01")
OPEN_ORDER_STATES = ("pending_approval", "approved", "sent", "part_received")
LIVE_BILL_STATES = ("pending_approval", "posted", "part_paid", "paid")


def money(amount: Decimal, currency: str) -> str:
    """An amount with its currency code, to two places: "KES 1,250.00"."""
    return f"{currency} {amount.quantize(CENT):,.2f}"


def pct(value: Decimal) -> str:
    """A percentage with one decimal place."""
    return f"{value.quantize(Decimal('0.1'))}%"


def _currency(session: Session, company_id: UUID) -> str:
    found = session.execute(text("select base_currency from kernel.company where id = :c"), {"c": company_id}).scalar()
    return str(found or "")


def _supplier_names(session: Session, company_id: UUID) -> dict[UUID, str]:
    rows = session.execute(text("select id, name from purchasing.supplier where company_id = :c"), {"c": company_id})
    return {r.id: str(r.name) for r in rows}


def _price_series(session: Session, company_id: UUID, since: date,
                  until: date) -> dict[tuple[UUID, UUID], list[Row[Any]]]:
    """Each supplier's costs per product, oldest first, from the receipts in the window."""
    rows = session.execute(text(
        "select sp.supplier_id, sp.product_id, sp.unit_cost, sp.effective_date, sp.source_id "
        "from purchasing.supplier_price sp "
        "join purchasing.supplier s on s.id = sp.supplier_id where s.company_id = :c and sp.effective_date >= :since "
        "and sp.effective_date <= :until order by sp.supplier_id, sp.product_id, sp.effective_date, sp.created_at"),
        {"c": company_id, "since": since, "until": until}).all()
    series: dict[tuple[UUID, UUID], list[Row[Any]]] = defaultdict(list)
    for row in rows:
        series[(row.supplier_id, row.product_id)].append(row)
    return series


@dataclass(frozen=True)
class _Rise:
    supplier_id: UUID
    product_id: UUID
    latest: Decimal
    average: Decimal
    percent: Decimal
    receipt_id: UUID
    day: date


def _rises(session: Session, ctx: CheckContext, days: int, min_percent: Decimal, min_earlier: int) -> list[_Rise]:
    found = []
    for (supplier_id, product_id), rows in _price_series(session, ctx.company_id, ctx.today - timedelta(days=days),
                                                          ctx.today).items():
        result = watch.price_rise([r.unit_cost for r in rows], min_earlier)
        if result is not None and result[2] > min_percent:
            found.append(_Rise(supplier_id, product_id, result[0], result[1], result[2], rows[-1].source_id,
                               rows[-1].effective_date))
    return found


def _receipt(session: Session, receipt_id: UUID, product_id: UUID) -> Row[Any] | None:
    return session.execute(text(
        "select r.id, r.number, r.branch_id, coalesce(sum(l.quantity), 0) as quantity from purchasing.goods_receipt r "
        "left join purchasing.goods_receipt_line l on l.receipt_id = r.id and l.product_id = :p "
        "where r.id = :r group by r.id, r.number, r.branch_id"), {"r": receipt_id, "p": product_id}).first()


class SupplierPriceRise(IntelCheck):
    """A supplier charging noticeably more than their usual price for a product."""

    code = "purchasing.supplier_price_rise"
    title = "Supplier price went up"
    area = "suppliers"
    description = "A supplier's latest price for a product is well above what they charged in earlier deliveries."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 90, "rise_percent": "10.0", "min_earlier": 2}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        rises = _rises(session, ctx, int(ctx.number("days")), ctx.number("rise_percent"),
                       int(ctx.number("min_earlier")))
        labels = product_labels(session, {r.product_id for r in rises})
        limit = ctx.number("rise_percent")
        out = []
        for r in rises:
            receipt = _receipt(session, r.receipt_id, r.product_id)
            quantity = Decimal(receipt.quantity) if receipt else Decimal(0)
            sku, name = labels.get(r.product_id, ("", "a product"))
            extra = ((r.latest - r.average) * quantity).quantize(CENT)
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.supplier_id, r.product_id, r.receipt_id),
                severity="high" if r.percent >= limit * 3 else "medium",
                summary=(f"{names.get(r.supplier_id, 'A supplier')} charged {money(r.latest, currency)} per unit for "
                         f"{name} on {r.day.isoformat()}, {pct(r.percent)} above the {money(r.average, currency)} "
                         f"they charged before. On the {quantity.normalize():f} units delivered that is "
                         f"{money(extra, currency)} more."),
                recommended_action="Ask the supplier why the price went up and update the selling price if it stays.",
                company_id=ctx.company_id, branch_id=receipt.branch_id if receipt else None,
                entity_type="purchasing.supplier", entity_id=r.supplier_id, period_end=r.day, value=r.latest,
                expected_value=r.average.quantize(Decimal("0.000001")), amount=extra,
                records=(Record("purchasing.supplier", r.supplier_id, names.get(r.supplier_id, "Supplier")),
                         Record("purchasing.goods_receipt", r.receipt_id,
                                f"Receipt {receipt.number}" if receipt else "Receipt"),
                         Record("products.product", r.product_id, f"{sku} {name}".strip())),
                figures={"latest_cost": str(r.latest.normalize()),
                         "usual_cost": str(r.average.quantize(Decimal('0.01'))),
                         "rise_percent": str(r.percent.quantize(Decimal('0.1'))), "currency": currency}))
        return out


class OrderAboveUsualPrice(IntelCheck):
    """An open purchase order priced above what the supplier usually charges."""

    code = "purchasing.order_above_usual_price"
    title = "Purchase order priced above usual"
    area = "suppliers"
    description = "An open purchase order has a unit price well above what this supplier charged for the product."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 30, "history_days": 180, "above_percent": "10.0", "min_earlier": 2}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        history = _price_series(session, ctx.company_id, ctx.today - timedelta(days=int(ctx.number("history_days"))),
                                ctx.today)
        lines = session.execute(text(
            "select l.id as line_id, l.product_id, l.quantity, l.unit_cost, o.id as order_id, o.number, o.branch_id, "
            "o.supplier_id, o.order_date from purchasing.purchase_order_line l "
            "join purchasing.purchase_order o on o.id = l.order_id where o.company_id = :c and o.status = any(:st) "
            "and o.order_date >= :since order by o.order_date, l.id"),
            {"c": ctx.company_id, "st": list(OPEN_ORDER_STATES),
             "since": ctx.today - timedelta(days=int(ctx.number("days")))}).all()
        labels = product_labels(session, {x.product_id for x in lines})
        limit, minimum = ctx.number("above_percent"), int(ctx.number("min_earlier"))
        out = []
        for x in lines:
            earlier = [r.unit_cost for r in history.get((x.supplier_id, x.product_id), [])
                       if r.effective_date < x.order_date]
            if len(earlier) < minimum:
                continue
            usual = sum(earlier, Decimal(0)) / len(earlier)
            if usual <= 0:
                continue
            over = (x.unit_cost - usual) / usual * 100
            if over <= limit:
                continue
            extra = ((x.unit_cost - usual) * x.quantity).quantize(CENT)
            sku, name = labels.get(x.product_id, ("", "a product"))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, x.line_id),
                severity="high" if over >= limit * 3 else "medium",
                summary=(f"Order {x.number} to {names.get(x.supplier_id, 'a supplier')} prices {name} at "
                         f"{money(x.unit_cost, currency)} per unit, {pct(over)} above the usual "
                         f"{money(usual, currency)}. Over {x.quantity.normalize():f} units that is "
                         f"{money(extra, currency)} more than usual."),
                recommended_action="Check the price with the supplier before the order is approved or received.",
                company_id=ctx.company_id, branch_id=x.branch_id, entity_type="purchasing.purchase_order",
                entity_id=x.order_id, period_end=x.order_date, value=x.unit_cost,
                expected_value=usual.quantize(Decimal("0.000001")), amount=extra,
                records=(Record("purchasing.purchase_order", x.order_id, f"Order {x.number}"),
                         Record("purchasing.supplier", x.supplier_id, names.get(x.supplier_id, "Supplier")),
                         Record("products.product", x.product_id, f"{sku} {name}".strip())),
                figures={"order_cost": str(x.unit_cost.normalize()), "usual_cost": str(usual.quantize(Decimal("0.01"))),
                         "above_percent": str(over.quantize(Decimal("0.1"))), "currency": currency}))
        return out


class MarginSqueeze(IntelCheck):
    """A cost rise that leaves a product with a thin or negative margin at today's selling price."""

    code = "purchasing.margin_squeeze"
    title = "Cost rise squeezes the margin"
    area = "suppliers"
    description = "A product's cost went up and its selling price now leaves very little profit."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 60, "cost_rise_percent": "5.0", "min_margin_percent": "10.0", "min_earlier": 1}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        rises = _rises(session, ctx, int(ctx.number("days")), ctx.number("cost_rise_percent"),
                       int(ctx.number("min_earlier")))
        if not rises:
            return []
        prices = selling_prices(session, ctx.company_id, None, {r.product_id for r in rises}, ctx.today)
        labels = product_labels(session, {r.product_id for r in rises})
        floor = ctx.number("min_margin_percent")
        out = []
        for r in rises:
            price, product = prices.get(r.product_id), find_product(session, r.product_id)
            if price is None or product is None:
                continue
            net = price / (1 + product.vat_rate / 100)            # the selling price is tax-inclusive
            if net <= 0:
                continue
            margin = (net - r.latest) / net * 100
            if margin >= floor:
                continue
            sku, name = labels.get(r.product_id, ("", "a product"))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, r.supplier_id, r.product_id),
                severity="high" if margin < 0 else "medium",
                summary=(f"The cost of {name} from {names.get(r.supplier_id, 'a supplier')} rose {pct(r.percent)} to "
                         f"{money(r.latest, currency)}. At the selling price of {money(price, currency)} (before tax "
                         f"{money(net, currency)}) the margin is {pct(margin)}."),
                recommended_action="Update the selling price or negotiate the cost.",
                company_id=ctx.company_id, entity_type="products.product", entity_id=r.product_id, period_end=r.day,
                value=margin.quantize(Decimal("0.01")), expected_value=floor,
                records=(Record("products.product", r.product_id, f"{sku} {name}".strip()),
                         Record("purchasing.supplier", r.supplier_id, names.get(r.supplier_id, "Supplier"))),
                figures={"cost": str(r.latest.normalize()), "selling_price": str(price.normalize()),
                         "margin_percent": str(margin.quantize(Decimal("0.1"))), "currency": currency}))
        return out


class DuplicateSupplierBill(IntelCheck):
    """The same supplier bill possibly entered twice."""

    code = "purchasing.duplicate_supplier_bill"
    title = "Possible duplicate supplier bill"
    area = "controls"
    description = "Two bills from one supplier have the same amount close together, or the same invoice number."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 60, "within_days": 7}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        rows = session.execute(text(
            "select id, number, branch_id, supplier_id, supplier_invoice_no, bill_date, total, amount_paid "
            "from purchasing.supplier_bill where company_id = :c and status = any(:st) and bill_date >= :since"),
            {"c": ctx.company_id, "st": ["draft", *LIVE_BILL_STATES],
             "since": ctx.today - timedelta(days=int(ctx.number("days")))}).all()
        by_id = {r.id: r for r in rows}
        stubs = [watch.BillStub(r.id, r.supplier_id, r.supplier_invoice_no, r.bill_date, r.total) for r in rows]
        out = []
        for first, second, why in watch.duplicate_bills(stubs, int(ctx.number("within_days"))):
            a, b = by_id[first.id], by_id[second.id]
            paid = b.amount_paid > 0 or a.amount_paid > 0
            out.append(Candidate(
                fingerprint=fingerprint(self.code, *sorted([str(a.id), str(b.id)])),
                severity="high" if paid else "medium",
                summary=(f"Bills {a.number} ({a.supplier_invoice_no}, {a.bill_date.isoformat()}) and {b.number} "
                         f"({b.supplier_invoice_no}, {b.bill_date.isoformat()}) from "
                         f"{names.get(a.supplier_id, 'a supplier')} have {why}: {money(b.total, currency)} "
                         f"{'and one has already been paid' if paid else 'and neither is paid yet'}."),
                recommended_action="Check whether the supplier billed twice and cancel the extra bill.",
                company_id=ctx.company_id, branch_id=b.branch_id, entity_type="purchasing.supplier_bill",
                entity_id=b.id, period_start=a.bill_date, period_end=b.bill_date, value=b.total, amount=b.total,
                records=(Record("purchasing.supplier_bill", a.id, f"Bill {a.number}"),
                         Record("purchasing.supplier_bill", b.id, f"Bill {b.number}")),
                figures={"reason": why, "currency": currency}))
        return out


class DuplicateSupplierPayment(IntelCheck):
    """The same supplier possibly paid twice."""

    code = "purchasing.duplicate_supplier_payment"
    title = "Possible duplicate supplier payment"
    area = "controls"
    description = "A supplier was paid the same amount twice within a few days, or two payments share a reference."
    default_severity = "high"
    params: dict[str, Any] = {"days": 60, "within_days": 3}
    auto_resolves = False

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        if not unit_enabled(session, "payments"):
            return []
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        bills = session.execute(text(
            "select id, number, branch_id, supplier_id from purchasing.supplier_bill where company_id = :c "
            "and amount_paid > 0 and bill_date >= :since"),
            {"c": ctx.company_id, "since": ctx.today - timedelta(days=int(ctx.number("days")))}).all()
        by_bill = {b.id: b for b in bills}
        stubs = []
        for bill in bills:
            for p in payments_for_document(session, "supplier_bill", bill.id):
                if p.direction == "out" and p.status == "posted":
                    stubs.append(watch.PaymentStub(p.payment_id, bill.id, bill.supplier_id, p.number, p.business_date,
                                                   p.amount, p.reference))
        out = []
        for first, second, why in watch.duplicate_payments(stubs, int(ctx.number("within_days"))):
            bill = by_bill[second.bill_id]
            out.append(Candidate(
                fingerprint=fingerprint(self.code, *sorted([str(first.payment_id), str(second.payment_id)])),
                severity="high",
                summary=(f"{names.get(first.supplier_id, 'A supplier')} received payments {first.number} "
                         f"({first.day.isoformat()}) and {second.number} ({second.day.isoformat()}) with {why}: "
                         f"{money(second.amount, currency)}."),
                recommended_action="Check whether the supplier was paid twice and ask for a refund if so.",
                company_id=ctx.company_id, branch_id=bill.branch_id, entity_type="purchasing.supplier",
                entity_id=first.supplier_id, period_start=first.day, period_end=second.day, value=second.amount,
                amount=second.amount,
                records=(Record("payments.payment", first.payment_id, f"Payment {first.number}"),
                         Record("payments.payment", second.payment_id, f"Payment {second.number}"),
                         Record("purchasing.supplier_bill", second.bill_id, f"Bill {bill.number}")),
                figures={"reason": why, "currency": currency}))
        return out


class SupplierBankChanged(IntelCheck):
    """A supplier's bank or mobile money details changed recently."""

    code = "purchasing.supplier_bank_changed"
    title = "Supplier payment details changed"
    area = "controls"
    description = "A supplier's bank or mobile money details were replaced recently."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 14}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        names = _supplier_names(session, ctx.company_id)
        currency = _currency(session, ctx.company_id)
        since = ctx.today - timedelta(days=int(ctx.number("days")))
        rows = session.execute(text(
            "select a.id, a.supplier_id, a.method, a.bank_name, a.account_no_masked, "
            "(a.valid_from at time zone :tz)::date as changed_on from purchasing.supplier_bank_account a "
            "join purchasing.supplier s on s.id = a.supplier_id where s.company_id = :c and a.status = 'active' "
            "and (a.valid_from at time zone :tz)::date >= :since and exists "
            "(select 1 from purchasing.supplier_bank_account o "
            "where o.supplier_id = a.supplier_id and o.id <> a.id and o.status = 'superseded')"),
            {"c": ctx.company_id, "tz": ctx.timezone, "since": since}).all()
        paying = unit_enabled(session, "payments")
        out = []
        for a in rows:
            paid_after: list[tuple[str, date, Decimal, UUID]] = []
            if paying:
                bills = session.execute(text(
                    "select id from purchasing.supplier_bill where supplier_id = :s and amount_paid > 0 "
                    "and bill_date >= :since"), {"s": a.supplier_id, "since": since - timedelta(days=365)}).all()
                for bill in bills:
                    for p in payments_for_document(session, "supplier_bill", bill.id):
                        if p.direction == "out" and p.status == "posted" and p.business_date >= a.changed_on:
                            paid_after.append((p.number, p.business_date, p.amount, p.payment_id))
            total = sum((x[2] for x in paid_after), Decimal(0))
            supplier = names.get(a.supplier_id, "A supplier")
            detail = (f"{supplier}'s {'bank' if a.method == 'bank' else 'mobile money'} details were replaced on "
                      f"{a.changed_on.isoformat()}")
            summary = (f"{detail}, and {len(paid_after)} payment(s) worth {money(total, currency)} have gone out since."
                       if paid_after else f"{detail}. No payment has gone to the new details yet.")
            out.append(Candidate(
                fingerprint=fingerprint(self.code, a.id),
                severity="high" if paid_after else "medium", summary=summary,
                recommended_action="Call the supplier on a number you already know to confirm the new details.",
                company_id=ctx.company_id, entity_type="purchasing.supplier", entity_id=a.supplier_id,
                period_start=a.changed_on, period_end=ctx.today, amount=total if paid_after else None,
                records=(Record("purchasing.supplier", a.supplier_id, supplier),
                         Record("purchasing.supplier_bank_account", a.id,
                                f"Details {a.account_no_masked or ''}".strip()),
                         *(Record("payments.payment", x[3], f"Payment {x[0]}") for x in paid_after[:5])),
                figures={"changed_on": a.changed_on.isoformat(), "payments_since": str(len(paid_after)),
                         "currency": currency}))
        return out


class PaidWithoutReceipt(IntelCheck):
    """A bill that was paid for goods that did not arrive, or for more than arrived."""

    code = "purchasing.paid_without_receipt"
    title = "Paid for goods not received"
    area = "suppliers"
    description = "A paid supplier bill charges for goods that were not received, were sent back, or arrived short."
    default_severity = "medium"
    params: dict[str, Any] = {"days": 60}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        rows = session.execute(text(
            "select b.id, b.number, b.branch_id, b.supplier_id, b.amount_paid, b.bill_date, l.id as line_id, "
            "l.product_id, l.quantity, l.unit_cost, "
            "case when gr.status = 'posted' then rl.quantity else 0 end as received, "
            "coalesce((select sum(r.quantity) from purchasing.purchase_return_line r "
            "where r.receipt_line_id = rl.id), 0) "
            "as returned, coalesce((select sum(l2.quantity) from purchasing.supplier_bill_line l2 "
            "join purchasing.supplier_bill b2 on b2.id = l2.bill_id where l2.receipt_line_id = rl.id "
            "and b2.status = any(:live)), 0) as billed from purchasing.supplier_bill b "
            "join purchasing.supplier_bill_line l on l.bill_id = b.id "
            "join purchasing.goods_receipt_line rl on rl.id = l.receipt_line_id "
            "join purchasing.goods_receipt gr on gr.id = rl.receipt_id "
            "where b.company_id = :c and b.status in ('part_paid', 'paid') and b.amount_paid > 0 "
            "and b.bill_date >= :since order by b.bill_date, b.id, l.id"),
            {"c": ctx.company_id, "live": list(LIVE_BILL_STATES),
             "since": ctx.today - timedelta(days=int(ctx.number("days")))}).all()
        labels = product_labels(session, {r.product_id for r in rows})
        grouped: dict[UUID, list[Row[Any]]] = defaultdict(list)
        for r in rows:
            grouped[r.id].append(r)
        out = []
        for bill_id, lines in grouped.items():
            head = lines[0]
            worth = Decimal(0)
            details = []
            for r in lines:
                usable = max(Decimal(0), r.received - r.returned)
                excess = min(r.quantity, max(Decimal(0), r.billed - usable))
                if excess > 0:
                    worth += excess * r.unit_cost
                    details.append(f"{labels.get(r.product_id, ('', 'goods'))[1]}: {excess.normalize():f} unit(s) "
                                   f"billed beyond the {usable.normalize():f} received")
            if not details:
                continue
            at_stake = min(head.amount_paid, worth.quantize(CENT))
            out.append(Candidate(
                fingerprint=fingerprint(self.code, bill_id),
                severity="high" if at_stake >= head.amount_paid else "medium",
                summary=(f"Bill {head.number} from {names.get(head.supplier_id, 'a supplier')} has been paid "
                         f"({money(head.amount_paid, currency)}) but " + "; ".join(details[:3])
                         + f", worth about {money(at_stake, currency)}."),
                recommended_action="Check the delivery with the storekeeper and ask the supplier to deliver or credit.",
                company_id=ctx.company_id, branch_id=head.branch_id, entity_type="purchasing.supplier_bill",
                entity_id=bill_id, period_end=head.bill_date, amount=at_stake,
                records=(Record("purchasing.supplier_bill", bill_id, f"Bill {head.number}"),),
                figures={"paid": str(head.amount_paid), "unreceived_value": str(at_stake), "currency": currency}))
        return out


class OverdueSupplierBills(IntelCheck):
    """Money owed to a supplier past its due date."""

    code = "purchasing.overdue_supplier_bills"
    title = "Overdue supplier bills"
    area = "suppliers"
    description = "A supplier has bills that are still unpaid well after their due date."
    default_severity = "medium"
    params: dict[str, Any] = {"overdue_days": 14, "serious_days": 60}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        limit = ctx.today - timedelta(days=int(ctx.number("overdue_days")))
        rows = session.execute(text(
            "select id, number, supplier_id, due_date, total - amount_paid - credited as owed "
            "from purchasing.supplier_bill where company_id = :c and status in ('posted', 'part_paid') "
            "and due_date < :limit and total - amount_paid - credited > 0 order by due_date, id"),
            {"c": ctx.company_id, "limit": limit}).all()
        grouped: dict[UUID, list[Row[Any]]] = defaultdict(list)
        for r in rows:
            grouped[r.supplier_id].append(r)
        out = []
        for supplier_id, bills in grouped.items():
            total = sum((b.owed for b in bills), Decimal(0))
            oldest = (ctx.today - bills[0].due_date).days
            out.append(Candidate(
                fingerprint=fingerprint(self.code, supplier_id),
                severity="high" if oldest >= int(ctx.number("serious_days")) else "medium",
                summary=(f"{names.get(supplier_id, 'A supplier')} is owed {money(total, currency)} on {len(bills)} "
                         f"bill(s) past their due date; the oldest is {oldest} days overdue."),
                recommended_action="Pay the overdue bills or agree a new date with the supplier.",
                company_id=ctx.company_id, entity_type="purchasing.supplier", entity_id=supplier_id,
                period_start=bills[0].due_date, period_end=ctx.today, value=Decimal(oldest), amount=total,
                records=tuple(Record("purchasing.supplier_bill", b.id, f"Bill {b.number}") for b in bills[:10]),
                figures={"bills": str(len(bills)), "oldest_days": str(oldest), "currency": currency}))
        return out


class BillMismatchWaiting(IntelCheck):
    """A supplier bill that does not match its order or receipt and has been waiting for a decision."""

    code = "purchasing.bill_mismatch_waiting"
    title = "Supplier bill waiting on a mismatch"
    area = "suppliers"
    description = "A supplier bill differs from its order or receipt and nobody has decided yet."
    default_severity = "medium"
    params: dict[str, Any] = {"waiting_days": 3}
    auto_resolves = True

    def run(self, session: Session, ctx: CheckContext) -> list[Candidate]:
        currency = _currency(session, ctx.company_id)
        names = _supplier_names(session, ctx.company_id)
        rows = session.execute(text(
            "select id, number, branch_id, supplier_id, total, match_notes, (created_at at time zone :tz)::date as day "
            "from purchasing.supplier_bill where company_id = :c and status = 'pending_approval' "
            "and match_status = 'exception' and (created_at at time zone :tz)::date <= :limit order by created_at"),
            {"c": ctx.company_id, "tz": ctx.timezone,
             "limit": ctx.today - timedelta(days=int(ctx.number("waiting_days")))}).all()
        out = []
        for b in rows:
            notes = list(b.match_notes or [])
            first = f" {notes[0]}." if notes else ""
            out.append(Candidate(
                fingerprint=fingerprint(self.code, b.id),
                severity="medium",
                summary=(f"Bill {b.number} from {names.get(b.supplier_id, 'a supplier')} for "
                         f"{money(b.total, currency)} "
                         f"has not matched its order and receipt since {b.day.isoformat()}.{first}"),
                recommended_action="Approve the difference with a reason, or reject the bill and ask for a new one.",
                company_id=ctx.company_id, branch_id=b.branch_id, entity_type="purchasing.supplier_bill",
                entity_id=b.id, period_start=b.day, period_end=ctx.today, amount=b.total,
                records=(Record("purchasing.supplier_bill", b.id, f"Bill {b.number}"),),
                figures={"problems": str(len(notes)), "currency": currency}))
        return out
