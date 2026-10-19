"""Checkout: the centre of the front-desk day. One screen from a visit that has happened to an invoice that is paid.

A checkout is a draft bill for one client: the services done (from appointments, or sold at the desk), retail products,
fees owed from earlier no-shows, a discount with a reason, credit that pays a service (a package, a membership), a
co-pay for an insurer, then, on completion, the invoice, the payments (split as needed, a deposit already held, a
voucher), the tips for the staff and the commission each person earned. Completion is one transaction: if any step fails
(a card payment more than is owed, an over-limit client) nothing is kept.

Point of Sale makes the invoice and takes the payment; Memberships spends the credit; Inventory moves the stock (through
the invoice); this module only decides what the bill says. It lends the front desk the right to bill for the length of
the call (`delegate.front_desk_rights`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.bookings.domain import checkout as dom
from ziira.modules.bookings.domain import lifecycle as life
from ziira.modules.bookings.permissions import BOOKINGS_CHECKOUT, BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Appointment, BookingSettings
from ziira.modules.bookings.services import (
    access,
    appointments,
    claims_seam,
    commission,
    delegate,
    fees,
    tenders,
)
from ziira.modules.bookings.services.common import now, unit_enabled, user_id
from ziira.sdk import (
    Event,
    Forbidden,
    NotFound,
    Session,
    ValidationFailed,
    audit_record,
    check_reason,
    current_context,
    next_document_number,
    publish,
)

SOURCE = "bookings.checkout"
PAYER_SOURCE = "bookings.checkout.payer"
BILLABLE = (life.CHECKED_IN, life.IN_SERVICE, life.COMPLETED)
METHODS = ("cash", "mobile_money", "card", "bank", "cheque", "other")
TIP_METHODS = ("cash", "mobile_money", "card", "other")


# --------------------------------------------------------------------------- input
@dataclass
class LineIn:
    """A line as the desk sends it. `kind` is service, product or fee. A service line names an appointment, or an offer
    sold at the desk; a product line names a product. A price left out is the list price."""

    kind: str
    quantity: Decimal = Decimal(1)
    appointment_id: UUID | None = None
    offer_id: UUID | None = None
    product_id: UUID | None = None
    fee_id: UUID | None = None
    description: str | None = None
    unit_price: Decimal | None = None
    discount: Decimal = Decimal(0)
    resource_id: UUID | None = None
    variant: str | None = None
    use_credit: bool = False


@dataclass
class PaymentIn:
    method: str
    amount: Decimal
    reference: str | None = None


@dataclass
class TipIn:
    resource_id: UUID
    amount: Decimal
    method: str = "cash"
    held: bool | None = None


@dataclass
class TenderIn:
    kind: str
    amount: Decimal
    code: str | None = None


# --------------------------------------------------------------------------- reading
def _row(session: Session, checkout_id: UUID, *, lock: bool = False) -> dict[str, Any]:
    found = raw.one(session, f"select * from bookings.checkout where id = :i{' for update' if lock else ''}",
                    i=checkout_id)
    if found is None or not access.can_view(found["company_id"], found["branch_id"]):
        raise NotFound("Checkout not found")
    return found


def _require(co: dict[str, Any]) -> None:
    current_context().require(BOOKINGS_CHECKOUT, company_id=co["company_id"], branch_id=co["branch_id"])


def lines_of(session: Session, checkout_id: UUID) -> list[dict[str, Any]]:
    return raw.many(session, "select * from bookings.checkout_line where checkout_id = :c order by line_no",
                    c=checkout_id)


def payments_of(session: Session, checkout_id: UUID) -> list[dict[str, Any]]:
    return raw.many(session, "select * from bookings.checkout_payment where checkout_id = :c order by created_at, id",
                    c=checkout_id)


def tips_of(session: Session, checkout_id: UUID) -> list[dict[str, Any]]:
    return raw.many(session, "select * from bookings.checkout_tip where checkout_id = :c order by created_at, id",
                    c=checkout_id)


def _dom_lines(rows: list[dict[str, Any]]) -> list[dom.Line]:
    return [dom.Line(r["quantity"], r["unit_price"], r["discount"], r["credit_quantity"]) for r in rows]


def _order_discount(co: dict[str, Any], rows: list[dict[str, Any]]) -> Decimal:
    return dom.order_discount_amount(_dom_lines(rows), co["discount_kind"], co["discount_value"])


def get_checkout(session: Session, checkout_id: UUID) -> dict[str, Any]:
    """The checkout with its lines, payments, tips, totals and the things the desk should know (warnings, what the
    client could pay with)."""
    co = _row(session, checkout_id)
    rows = lines_of(session, checkout_id)
    order = _order_discount(co, rows) if co["status"] == "open" else co["discount_total"] - sum(
        (r["discount"] for r in rows), Decimal(0))
    t = dom.totals(_dom_lines(rows), max(order, Decimal(0)))
    view: dict[str, Any] = {**co, "lines": rows, "payments": payments_of(session, checkout_id),
                            "tips": tips_of(session, checkout_id), "order_discount": t.order_discount,
                            "totals": t, "warnings": [], "deposit_held": Decimal(0),
                            "credit_on_account": Decimal(0), "line_shares": list(t.shares)}
    if co["status"] == "open":
        view["warnings"] = _warnings(session, co, rows)
        view["credit_on_account"] = _account_credit(session, co["customer_id"])
        view["deposit_held"] = sum((p["amount"] for p in view["payments"] if p["kind"] == "deposit"), Decimal(0))
    return view


def _account_credit(session: Session, customer_id: UUID | None) -> Decimal:
    if customer_id is None or not unit_enabled(session, "pos"):
        return Decimal(0)
    import ziira.modules.pos.public as pos_public

    return pos_public.customer_credit(session, customer_id)


def _warnings(session: Session, co: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in rows:
        if r["kind"] in ("service", "fee") and r["product_id"] is None:
            out.append(f"{r['description']}: link this service to a service item in Products so it can be invoiced")
    if co["customer_id"] is None:
        out.append("No client is named: the sale will be made to the walk-in client account")
    return out


def list_checkouts(session: Session, *, branch_id: UUID | None = None, status: str | None = None,
                   customer_id: UUID | None = None, owing: bool = False, day: Any = None, limit: int = 100,
                   offset: int = 0) -> list[dict[str, Any]]:
    """Checkouts the user may see, newest first. `owing` keeps those completed with something still to pay."""
    scopes = access.view_scopes()
    where: list[str] = ["true"]
    params: dict[str, Any] = {"lim": min(limit, 300), "off": offset}
    if scopes is not None:
        clauses = []
        for i, (c, b) in enumerate(scopes):
            params[f"c{i}"], params[f"b{i}"] = c, b
            clauses.append(f"(company_id = :c{i} and (cast(:b{i} as uuid) is null or branch_id = :b{i}))")
        where.append("(" + " or ".join(clauses or ["false"]) + ")")
    if branch_id:
        where.append("branch_id = :branch")
        params["branch"] = branch_id
    if status:
        where.append("status = :status")
        params["status"] = status
    if customer_id:
        where.append("customer_id = :cust")
        params["cust"] = customer_id
    if owing:
        where.append("status = 'done' and total - paid_total - credit_total > 0")
    if day:
        where.append("((completed_at at time zone 'UTC')::date = :day or "
                     "(completed_at is null and (created_at at time zone 'UTC')::date = :day))")
        params["day"] = day
    return raw.many(session, f"select * from bookings.checkout where {' and '.join(where)} "
                             "order by created_at desc, id limit :lim offset :off", **params)


# --------------------------------------------------------------------------- opening
def _branch_company(session: Session, branch_id: UUID) -> UUID:
    found = raw.one(session, "select company_id from kernel.branch where id = :b", b=branch_id)
    if found is None:
        raise ValidationFailed("Branch not found")
    return UUID(str(found["company_id"]))


def _staff_resource(session: Session, appt_id: UUID) -> UUID | None:
    ids = repo.appointment_resources(session, {appt_id}).get(appt_id, [])
    if not ids:
        return None
    found = repo.resources_by_ids(session, set(ids))
    staff = [i for i in ids if i in found and found[i].kind == "staff"]
    return (staff or ids)[0]


def _checkout_of_appointment(session: Session, appointment_id: UUID) -> dict[str, Any] | None:
    return raw.one(session, "select c.* from bookings.checkout c join bookings.checkout_line l on l.checkout_id = c.id "
                            "where l.appointment_id = :a and c.status in ('open', 'done') limit 1", a=appointment_id)


def open_checkout(session: Session, *, appointment_ids: list[UUID] | None = None, visit_id: UUID | None = None,
                  customer_id: UUID | None = None, branch_id: UUID | None = None,
                  local_id: str | None = None) -> dict[str, Any]:
    """Start a checkout for the appointments of a visit (or one appointment, or nothing at all for a sale of products
    over the desk). Asking again for the same appointments returns the open checkout. Needs 'bookings.checkout'."""
    ids = list(dict.fromkeys(appointment_ids or []))
    appts: list[Appointment] = []
    if visit_id is not None:
        appts += [a for a in repo.list_appointments(session, access.view_scopes(), visit_id=visit_id, limit=50)
                  if a.id not in ids]
    for i in ids:
        a = repo.get_appointment(session, i, lock=True)
        if a is None or not access.can_view(a.company_id, a.branch_id):
            raise NotFound("Appointment not found")
        appts.append(a)
    if not appts and branch_id is None:
        raise ValidationFailed("Say which branch, or which appointments, to check out")
    if appts:
        branch_id = appts[0].branch_id
        company_id = appts[0].company_id
        if any(a.branch_id != branch_id for a in appts):
            raise ValidationFailed("Appointments from different branches cannot be billed together")
    else:
        assert branch_id is not None
        company_id = _branch_company(session, branch_id)
    current_context().require(BOOKINGS_CHECKOUT, company_id=company_id, branch_id=branch_id)
    if local_id:
        again = raw.one(session, "select id from bookings.checkout where company_id = :c and local_id = :l",
                        c=company_id, l=local_id)
        if again is not None:
            return get_checkout(session, again["id"])
    existing = [_checkout_of_appointment(session, a.id) for a in appts]
    found = [e for e in existing if e is not None]
    if found:
        if any(e["status"] == "done" for e in found):
            raise ValidationFailed(f"That visit was already billed ({found[0]['number']})")
        return get_checkout(session, found[0]["id"])
    for a in appts:
        if a.status not in BILLABLE:
            raise ValidationFailed(f"{a.number} is {a.status.replace('_', ' ')}: check the client in first")
        if a.invoice_id is not None:
            raise ValidationFailed(f"{a.number} already has an invoice ({a.invoice_number})")
        if a.kind == "class":
            raise ValidationFailed("A class is billed per person, not as a visit")
    customers = {a.customer_id for a in appts if a.customer_id}
    if len(customers) > 1:
        raise ValidationFailed("These appointments are for different clients: check them out one at a time")
    customer_id = customer_id or (next(iter(customers)) if customers else None)
    if customer_id is not None:
        _check_customer(session, company_id, customer_id)
    settings = repo.ensure_settings(session, company_id)
    ctx = current_context()
    co = raw.insert(session, "checkout", {
        "company_id": company_id, "branch_id": branch_id,
        "number": next_document_number(session, company_id=company_id, branch_id=branch_id, doc_type="checkout",
                                       prefix="CO"),
        "customer_id": customer_id, "client_name": next((a.client_name for a in appts if a.client_name), None),
        "visit_id": visit_id or next((a.visit_id for a in appts if a.visit_id), None), "local_id": local_id,
        "payer_customer_id": next((a.payer_customer_id for a in appts if a.payer_customer_id), None),
        "copay_amount": next((a.copay_amount for a in appts if a.copay_amount is not None), None),
        "preauth_ref": next((a.preauth_ref for a in appts if a.preauth_ref), None)}, user_id=ctx.user_id)
    number = 0
    for a in appts:
        offer = repo.get_offer(session, a.offer_id)
        assert offer is not None
        number += 1
        claim = claims_seam.claim_label(session, a.id)
        raw.insert(session, "checkout_line", {
            "checkout_id": co["id"], "line_no": number, "kind": "service", "appointment_id": a.id,
            "offer_id": offer.id, "product_id": offer.product_id, "description": offer.name, "quantity": 1,
            "unit_price": a.price, "resource_id": _staff_resource(session, a.id), "variant": a.price_variant,
            **({"credit_quantity": 1, "credit_ref": claims_seam.CLAIM_PREFIX + claim} if claim else {})},
            user_id=ctx.user_id)
        if a.deposit_paid > 0:
            raw.insert(session, "checkout_payment", {
                "checkout_id": co["id"], "kind": "deposit", "method": "deposit", "amount": a.deposit_paid,
                "reference": a.number}, user_id=ctx.user_id)
    if customer_id is not None:
        number = fees.add_fee_lines(session, co, settings, customer_id, number)
        _auto_credit_and_member_discount(session, co, settings, customer_id)
    audit_record(session, "create", "bookings.checkout", co["id"], {"number": co["number"]})
    return get_checkout(session, co["id"])


def _check_customer(session: Session, company_id: UUID, customer_id: UUID) -> None:
    if not unit_enabled(session, "crm"):
        raise ValidationFailed("Customers are not switched on for this business")
    from ziira.modules.crm.public import find_customer

    found = find_customer(session, customer_id)
    if found is None or found.company_id != company_id:
        raise ValidationFailed("The client was not found in this company")


def _service_refs(session: Session, line: dict[str, Any]) -> list[str]:
    """The names a plan may list a service under: its SKU, its id, the service's name."""
    refs: list[str] = []
    if line["product_id"] is not None:
        from ziira.modules.products.public import find_product

        product = find_product(session, line["product_id"])
        if product is not None:
            refs.append(product.sku)
        refs.append(str(line["product_id"]))
    if line["offer_id"] is not None:
        refs.append(str(line["offer_id"]))
    refs.append(line["description"])
    return list(dict.fromkeys(refs))


def _credit_ref(session: Session, customer_id: UUID, line: dict[str, Any]) -> tuple[str | None, Decimal]:
    """The first name of the service under which the client has credit, and how much."""
    if not unit_enabled(session, "memberships"):
        return None, Decimal(0)
    import ziira.modules.memberships.public as memberships

    for ref in _service_refs(session, line):
        balance = memberships.member_credit_balance(session, customer_id, ref)
        if balance > 0:
            return ref, balance
    return None, Decimal(0)


def _apply_credit_flags(session: Session, co: dict[str, Any], customer_id: UUID, wanted: set[UUID] | None) -> None:
    """Set how many units of each service line are paid with credit (never more than the client's balance, and a
    balance is shared over the lines in order). `wanted` limits it to those line ids; None means every service line."""
    left: dict[str, Decimal] = {}
    for line in lines_of(session, co["id"]):
        if line["kind"] != "service" or (wanted is not None and line["id"] not in wanted):
            continue
        if (line["credit_ref"] or "").startswith(claims_seam.CLAIM_PREFIX):
            continue
        ref, balance = _credit_ref(session, customer_id, line)
        if ref is None:
            raw.update(session, "checkout_line", line["id"], {"credit_quantity": 0, "credit_ref": None})
            continue
        available = left.setdefault(ref, balance)
        use = min(line["quantity"], available)
        left[ref] = available - use
        raw.update(session, "checkout_line", line["id"], {"credit_quantity": use, "credit_ref": ref if use else None})


def _auto_credit_and_member_discount(session: Session, co: dict[str, Any], settings: BookingSettings,
                                     customer_id: UUID) -> None:
    if not unit_enabled(session, "memberships"):
        return
    import ziira.modules.memberships.public as memberships

    _apply_credit_flags(session, co, customer_id, None)
    pct = memberships.member_discount_percent(session, customer_id)
    if pct > 0:
        for line in lines_of(session, co["id"]):
            if line["kind"] == "service" and line["discount"] == 0 and line["credit_quantity"] < line["quantity"]:
                charged = dom.charged_gross(dom.Line(line["quantity"], line["unit_price"], Decimal(0),
                                                     line["credit_quantity"]))
                raw.update(session, "checkout_line", line["id"], {"discount": dom.percent_of(charged, pct)})
        reason = raw.one(session, "select id from kernel.reason_code where category = 'checkout_discount' and "
                                  "code = 'MEMBER'")
        if reason is not None:
            raw.update(session, "checkout", co["id"], {"discount_reason_id": reason["id"],
                                                       "discount_note": f"Member discount {pct}%"})


# --------------------------------------------------------------------------- the draft
def set_customer(session: Session, checkout_id: UUID, customer_id: UUID | None) -> dict[str, Any]:
    """Name (or change) the client of an open checkout. Credits and fees are looked at again."""
    co = _row(session, checkout_id, lock=True)
    _require(co)
    if co["status"] != "open":
        raise ValidationFailed("This checkout is closed")
    if customer_id is not None:
        _check_customer(session, co["company_id"], customer_id)
    raw.update(session, "checkout", checkout_id, {"customer_id": customer_id}, user_id=user_id())
    if customer_id is not None:
        settings = repo.ensure_settings(session, co["company_id"])
        co = _row(session, checkout_id)
        rows = lines_of(session, checkout_id)
        fees.add_fee_lines(session, co, settings, customer_id, max((r["line_no"] for r in rows), default=0))
        _apply_credit_flags(session, co, customer_id, None)
    return get_checkout(session, checkout_id)


def _list_price(session: Session, company_id: UUID, branch_id: UUID, product_id: UUID) -> Decimal | None:
    from ziira.modules.products.public import selling_prices

    return selling_prices(session, company_id, branch_id, {product_id}).get(product_id)


def save_draft(session: Session, checkout_id: UUID, *, lines: list[LineIn], discount_kind: str = "amount",
               discount_value: Decimal = Decimal(0), discount_reason_id: UUID | None = None,
               discount_note: str | None = None, note: str | None = None,
               payer_customer_id: UUID | None = None, copay_amount: Decimal | None = None,
               preauth_ref: str | None = None) -> dict[str, Any]:
    """Replace the lines and the discount of an open checkout with what is on the desk's screen. Appointment lines
    keep their link; a price left out is the list price; credit is looked at again for the lines that ask for it."""
    co = _row(session, checkout_id, lock=True)
    _require(co)
    if co["status"] != "open":
        raise ValidationFailed("This checkout is closed")
    if discount_kind not in ("amount", "percent"):
        raise ValidationFailed("A discount is an amount or a percent")
    if discount_value < 0 or (discount_kind == "percent" and discount_value > 100):
        raise ValidationFailed("A discount cannot be negative, and a percent is at most 100")
    if not lines or len(lines) > 60:
        raise ValidationFailed("A checkout has between 1 and 60 lines")
    company_id, branch_id = co["company_id"], co["branch_id"]
    ctx = current_context()
    prepared: list[dict[str, Any]] = []
    seen_appts: set[UUID] = set()
    for item in lines:
        if item.kind not in ("service", "product", "fee"):
            raise ValidationFailed("A line is a service, a product or a fee")
        if item.quantity <= 0 or item.quantity > 1000:
            raise ValidationFailed("A quantity is more than zero")
        if item.discount < 0:
            raise ValidationFailed("A discount cannot be negative")
        row: dict[str, Any] = {"kind": item.kind, "quantity": item.quantity, "discount": item.discount,
                               "resource_id": item.resource_id, "variant": item.variant,
                               "appointment_id": None, "offer_id": None, "product_id": None, "fee_id": None}
        price = item.unit_price
        if item.kind == "service":
            if item.appointment_id is not None:
                appt = repo.get_appointment(session, item.appointment_id)
                if appt is None or appt.company_id != company_id or appt.branch_id != branch_id:
                    raise ValidationFailed("An appointment on the checkout was not found here")
                if appt.id in seen_appts:
                    raise ValidationFailed("An appointment is on the bill once")
                seen_appts.add(appt.id)
                other = _checkout_of_appointment(session, appt.id)
                if other is not None and other["id"] != checkout_id:
                    raise ValidationFailed(f"{appt.number} is already on checkout {other['number']}")
                row["appointment_id"], item.offer_id = appt.id, appt.offer_id
                price = appt.price if price is None else price
            offer = repo.get_offer(session, item.offer_id) if item.offer_id else None
            if offer is None or offer.company_id != company_id:
                raise ValidationFailed("Pick the service for each service line")
            row.update(offer_id=offer.id, product_id=offer.product_id,
                       description=(item.description or offer.name))
            price = offer.price if price is None else price
        elif item.kind == "product":
            if item.product_id is None:
                raise ValidationFailed("Pick the product for each product line")
            from ziira.modules.products.public import find_product

            product = find_product(session, item.product_id)
            if product is None or product.company_id != company_id or not product.is_active:
                raise ValidationFailed("A product on the checkout was not found in this company")
            row.update(product_id=product.id, description=(item.description or product.name))
            if price is None:
                price = _list_price(session, company_id, branch_id, product.id)
                if price is None:
                    raise ValidationFailed(f"{product.name} has no price: ask a manager to set one")
        else:
            fee = raw.one(session, "select * from bookings.client_fee where id = :i", i=item.fee_id) \
                if item.fee_id else None
            if fee is None or fee["company_id"] != company_id or fee["status"] == "waived":
                raise ValidationFailed("A fee on the checkout was not found")
            row.update(fee_id=fee["id"], product_id=repo.ensure_settings(session, company_id).fee_product_id,
                       description=(item.description or f"{fee['kind'].replace('_', ' ').capitalize()} fee"))
            price = fee["amount"] if price is None else price
        if price is None or price < 0:
            raise ValidationFailed("Every line needs a price")
        row["unit_price"] = price
        row["use_credit"] = item.use_credit
        row["claim"] = claims_seam.claim_label(session, row["appointment_id"]) if row["appointment_id"] else None
        prepared.append(row)
    raw.run(session, "delete from bookings.checkout_line where checkout_id = :c", c=checkout_id)
    wanted: set[UUID] = set()
    for number, row in enumerate(prepared, start=1):
        use = row.pop("use_credit")
        claim = row.pop("claim")
        if claim:
            row["credit_quantity"], row["credit_ref"] = row["quantity"], claims_seam.CLAIM_PREFIX + claim
        made = raw.insert(session, "checkout_line", {"checkout_id": checkout_id, "line_no": number, **row},
                          user_id=ctx.user_id)
        if use:
            wanted.add(made["id"])
    if co["customer_id"] is not None:
        _apply_credit_flags(session, co, co["customer_id"], wanted)
    if payer_customer_id is not None:
        _check_customer(session, company_id, payer_customer_id)
    if copay_amount is not None and copay_amount < 0:
        raise ValidationFailed("A co-pay cannot be negative")
    raw.update(session, "checkout", checkout_id, {
        "discount_kind": discount_kind, "discount_value": discount_value, "discount_reason_id": discount_reason_id,
        "discount_note": (discount_note or "").strip()[:300] or None, "note": (note or "").strip()[:500] or None,
        "payer_customer_id": payer_customer_id, "copay_amount": copay_amount if payer_customer_id else None,
        "preauth_ref": (preauth_ref or "").strip()[:80] or None}, user_id=ctx.user_id)
    return get_checkout(session, checkout_id)


def discard(session: Session, checkout_id: UUID, reason: str) -> dict[str, Any]:
    """Throw away an open checkout (the client left, it was opened by mistake). A completed one is reversed in Sales
    (a credit note), not here."""
    co = _row(session, checkout_id, lock=True)
    _require(co)
    if co["status"] != "open":
        raise ValidationFailed(
            "Only an open checkout can be thrown away: a billed visit is reversed with a credit note")
    if not reason.strip():
        raise ValidationFailed("Say why")
    raw.update(session, "checkout", checkout_id, {"status": "void", "voided_at": now(),
                                                "void_reason": reason.strip()[:300]},
               user_id=user_id())
    audit_record(session, "void", "bookings.checkout", checkout_id, {"reason": reason.strip()[:300]})
    publish(session, Event("checkout.voided", "bookings.checkout", checkout_id, {
        "company_id": co["company_id"], "branch_id": co["branch_id"], "checkout_id": checkout_id}))
    return get_checkout(session, checkout_id)


# --------------------------------------------------------------------------- completing
def _walkin_customer(session: Session, company_id: UUID, settings: BookingSettings) -> UUID:
    if settings.walkin_customer_id is not None:
        return UUID(str(settings.walkin_customer_id))
    from ziira.modules.crm.public import match_or_create_customer

    customer, _ = match_or_create_customer(session, company_id, name="Walk-in client",
                                           email="walk-in@client.invalid")
    settings.walkin_customer_id = customer.id
    session.flush()
    return customer.id


def _location(session: Session, company_id: UUID, branch_id: UUID) -> UUID | None:
    if not unit_enabled(session, "inventory"):
        return None
    from ziira.modules.inventory.public import locations_for_branch

    found = locations_for_branch(session, company_id, branch_id)
    return found[0].id if found else None


def _check_discount(session: Session, co: dict[str, Any], rows: list[dict[str, Any]], settings: BookingSettings,
                    order: Decimal) -> None:
    line_total = sum((dom.line_discount(x) for x in _dom_lines(rows)), Decimal(0))
    given = line_total + order
    if given <= 0:
        return
    check_reason(session, "checkout_discount", co["discount_reason_id"], co["discount_note"])
    base = sum((dom.charged_gross(x) for x in _dom_lines(rows)), Decimal(0))
    limit = settings.discount_limit_percent
    if limit is not None and base > 0 and given * 100 > base * limit:
        ctx = current_context()
        if not ctx.can(BOOKINGS_SETUP, company_id=co["company_id"], branch_id=co["branch_id"]):
            raise Forbidden(f"A discount above {limit}% needs a manager")


def complete(session: Session, checkout_id: UUID, *, payments: list[PaymentIn] | None = None,
             tips: list[TipIn] | None = None, tender_uses: list[TenderIn] | None = None,
             use_deposit: bool = True) -> dict[str, Any]:
    """Bill the visit: spend the credit, issue the invoice, apply the deposit, take the payments and tenders, record
    the tips and commission, and finish the appointments. All or nothing. Doing it again returns the finished
    checkout and changes nothing. Needs 'bookings.checkout' at the branch."""
    co = _row(session, checkout_id, lock=True)
    _require(co)
    if co["status"] == "done":
        return get_checkout(session, checkout_id)
    if co["status"] != "open":
        raise ValidationFailed("This checkout was thrown away")
    payments, tips, tender_uses = payments or [], tips or [], tender_uses or []
    company_id, branch_id = co["company_id"], co["branch_id"]
    with delegate.front_desk_rights(company_id, branch_id):
        return _complete(session, co, payments, tips, tender_uses, use_deposit)


def _complete(session: Session, co: dict[str, Any], payments: list[PaymentIn], tips: list[TipIn],
              tender_uses: list[TenderIn], use_deposit: bool) -> dict[str, Any]:
    import ziira.modules.pos.public as pos_public

    checkout_id, company_id, branch_id = co["id"], co["company_id"], co["branch_id"]
    ctx = current_context()
    settings = repo.ensure_settings(session, company_id)
    if not unit_enabled(session, "pos") or not unit_enabled(session, "crm"):
        raise ValidationFailed("Invoicing is not available: switch on Point of Sale and Customers to check clients out")
    rows = lines_of(session, checkout_id)
    if not rows:
        raise ValidationFailed("There is nothing on the bill")
    for p in payments:
        if p.method not in METHODS or p.amount <= 0 or p.amount != p.amount.quantize(Decimal("0.01")):
            raise ValidationFailed(f"A payment is more than zero with two decimals, by one of: {', '.join(METHODS)}")
    for tip in tips:
        if tip.amount <= 0 or tip.method not in TIP_METHODS:
            raise ValidationFailed("A tip is more than zero, by cash, mobile money, card or other")
    customer_id = co["customer_id"] or _walkin_customer(session, company_id, settings)
    if customer_id != co["customer_id"]:
        raw.update(session, "checkout", checkout_id, {"customer_id": customer_id})
    # 1. credit: really spend what the draft promised (idempotent per line)
    spend = [r for r in rows if r["credit_quantity"] > 0 and not (r["credit_ref"] or "").startswith(
        claims_seam.CLAIM_PREFIX)]
    if unit_enabled(session, "memberships") and spend:
        import ziira.modules.memberships.public as memberships

        for r in spend:
            use = memberships.consume_credit(session, customer_id=customer_id, service_ref=r["credit_ref"],
                                             quantity=r["credit_quantity"], source_type="bookings.checkout_line",
                                             source_id=r["id"])
            raw.update(session, "checkout_line", r["id"], {"credit_quantity": use.covered})
        rows = lines_of(session, checkout_id)
    elif spend:
        raise ValidationFailed("Credit cannot be used: Memberships is not switched on")
    # 2. the bill
    lines = _dom_lines(rows)
    order = _order_discount(co, rows)
    _check_discount(session, co, rows, settings, order)
    t = dom.totals(lines, order)
    discounts = dom.invoice_discounts(lines, order)
    charged = [(r, ln, d) for r, ln, d in zip(rows, lines, discounts, strict=True) if dom.charged_quantity(ln) > 0]
    for r, _, _ in charged:
        if r["product_id"] is None:
            raise ValidationFailed(f"{r['description']}: link this service to a service item in Products first")
    # 3. who pays what
    copay = co["copay_amount"] if co["payer_customer_id"] is not None else None
    amounts = [dom.charged_gross(ln) - d for _, ln, d in charged]
    if copay is not None and co["payer_customer_id"] is not None:
        split = dom.split_payer(amounts, copay)
    else:
        split = [(a, Decimal(0)) for a in amounts]
    patient_total = sum((p for p, _ in split), Decimal(0))
    payer_total = sum((q for _, q in split), Decimal(0))
    deposit_held = sum((p["amount"] for p in payments_of(session, checkout_id) if p["kind"] == "deposit"), Decimal(0))
    deposit_use = min(deposit_held, patient_total) if use_deposit else Decimal(0)
    paid_now = sum((p.amount for p in payments), Decimal(0))
    tender_total = sum((x.amount for x in tender_uses), Decimal(0))
    settled = deposit_use + paid_now + tender_total
    if settled > patient_total:
        raise ValidationFailed(f"The payments come to {settled} but the client owes {patient_total}")
    invoice = payer_invoice = None
    if patient_total > 0:
        invoice = pos_public.issue_invoice_from_lines(
            session, company_id=company_id, branch_id=branch_id, customer_id=customer_id,
            lines=_invoice_lines(charged, [p for p, _ in split]),
            source_type=SOURCE, source_id=checkout_id, due_days=settings.invoice_due_days, memo=co["number"],
            location_id=_location(session, company_id, branch_id), settled_now=settled)
    if payer_total > 0:
        payer_invoice = pos_public.issue_invoice_from_lines(
            session, company_id=company_id, branch_id=branch_id, customer_id=co["payer_customer_id"],
            lines=_invoice_lines(charged, [q for _, q in split]),
            source_type=PAYER_SOURCE, source_id=checkout_id, due_days=settings.invoice_due_days,
            memo=f"{co['number']} {co['preauth_ref'] or ''}".strip(),
            location_id=None)
    # 4. money
    if invoice is not None and deposit_use > 0:
        pos_public.apply_account_credit(session, customer_id, [(invoice.id, deposit_use)])
    for p in payments:
        assert invoice is not None
        made = pos_public.take_payment(session, customer_id=customer_id, branch_id=branch_id, amount=p.amount,
                                       method=p.method, allocations=[(invoice.id, p.amount)],
                                       external_ref=(p.reference or None))
        raw.insert(session, "checkout_payment", {
            "checkout_id": checkout_id, "kind": "payment", "method": p.method, "amount": p.amount,
            "reference": p.reference, "receipt_id": made.id, "receipt_number": made.number}, user_id=ctx.user_id)
    for use_t in tender_uses:
        assert invoice is not None
        done = tenders.redeem(session, kind=use_t.kind, code=use_t.code, amount=use_t.amount, customer_id=customer_id,
                              invoice_id=invoice.id, checkout_id=checkout_id)
        raw.insert(session, "checkout_payment", {
            "checkout_id": checkout_id, "kind": "tender", "method": use_t.kind, "amount": done.applied,
            "reference": done.reference, "provider": use_t.kind}, user_id=ctx.user_id)
    left = pos_public.invoice_balance(session, invoice.id) if invoice is not None else Decimal(0)
    expected = (patient_total - settled) if invoice is not None else Decimal(0)
    if invoice is not None and left is not None and left != expected:
        raise ValidationFailed("The payments did not settle the invoice as expected: nothing was saved")
    # 5. tips and commission
    for tip in tips:
        _save_tip(session, co, tip)
    commission.record_for_checkout(session, co, rows, lines, order, t.shares, settings)
    fees.mark_charged(session, checkout_id, rows)
    # 6. the visit
    for r in rows:
        if r["appointment_id"] is not None:
            appt = repo.get_appointment(session, r["appointment_id"], lock=True)
            assert appt is not None
            appointments.finish_for_checkout(session, appt, invoice)
    paid_total = sum((p.amount for p in payments), Decimal(0)) + deposit_use + tender_total
    raw.update(session, "checkout", checkout_id, {
        "status": "done", "subtotal": t.subtotal, "discount_total": t.line_discounts + t.order_discount,
        "credit_total": t.credit_value, "total": patient_total, "paid_total": paid_total,
        "tip_total": sum((x.amount for x in tips), Decimal(0)),
        "invoice_id": invoice.id if invoice else None, "invoice_number": invoice.number if invoice else None,
        "payer_invoice_id": payer_invoice.id if payer_invoice else None,
        "payer_invoice_number": payer_invoice.number if payer_invoice else None,
        "completed_at": now(), "completed_by": ctx.user_id}, user_id=ctx.user_id)
    audit_record(session, "complete", "bookings.checkout", checkout_id, {
        "number": co["number"], "total": patient_total, "paid": paid_total, "payer": payer_total})
    publish(session, Event("checkout.completed", "bookings.checkout", checkout_id, {
        "company_id": company_id, "branch_id": branch_id, "checkout_id": checkout_id, "number": co["number"],
        "customer_id": customer_id, "total": patient_total, "paid": paid_total, "tips": sum(
            (x.amount for x in tips), Decimal(0)),
        "invoice_id": invoice.id if invoice else None, "payer_invoice_id": payer_invoice.id if payer_invoice else None,
        "appointment_ids": [r["appointment_id"] for r in rows if r["appointment_id"]],
        "completed_at": datetime.now(UTC).isoformat()}))
    return get_checkout(session, checkout_id)


def _invoice_lines(charged: list[tuple[dict[str, Any], dom.Line, Decimal]], parts: list[Decimal]) -> list[Any]:
    """Invoice lines for one party: each line at its price with the discount that makes it come to that party's part."""
    import ziira.modules.pos.public as pos_public

    out = []
    for (r, ln, _), part in zip(charged, parts, strict=True):
        if part <= 0:
            continue
        qty = dom.charged_quantity(ln)
        out.append(pos_public.InvoiceLineIn(
            product_id=r["product_id"], description=r["description"], quantity=qty, unit_price=r["unit_price"],
            discount=dom.cents(qty * r["unit_price"]) - part))
    return out


def _save_tip(session: Session, co: dict[str, Any], tip: TipIn) -> None:
    resource = repo.get_resource(session, tip.resource_id)
    if resource is None or resource.company_id != co["company_id"]:
        raise ValidationFailed("A tip goes to a person set up in Staff and rooms")
    held = tip.held if tip.held is not None else tip.method != "cash"
    raw.insert(session, "checkout_tip", {
        "checkout_id": co["id"], "company_id": co["company_id"], "branch_id": co["branch_id"],
        "resource_id": tip.resource_id, "amount": tip.amount, "method": tip.method, "held": held},
        user_id=user_id())


def add_tip_later(session: Session, checkout_id: UUID, tip: TipIn) -> dict[str, Any]:
    """A tip added after the bill was paid (the client left it on the card). Needs 'bookings.checkout'."""
    co = _row(session, checkout_id, lock=True)
    _require(co)
    if co["status"] != "done":
        raise ValidationFailed("Tips are added when the checkout is done")
    if tip.amount <= 0 or tip.method not in TIP_METHODS:
        raise ValidationFailed("A tip is more than zero, by cash, mobile money, card or other")
    _save_tip(session, co, tip)
    raw.update(session, "checkout", checkout_id, {"tip_total": co["tip_total"] + tip.amount})
    audit_record(session, "tip", "bookings.checkout", checkout_id, {"amount": tip.amount})
    return get_checkout(session, checkout_id)
