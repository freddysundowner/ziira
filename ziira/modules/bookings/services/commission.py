"""Staff commission: rules (a percent or a fixed amount per service or product, per person, per level), the lines earned
at each checkout, a report for a period, and a figure Payroll can read.

Commission is *information*: it never posts a payment or an entry. Lines are never edited (the database refuses); a
checkout that is reversed adds negative lines. Tips are kept apart: they are not commission and not revenue.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.bookings.domain import checkout as dom
from ziira.modules.bookings.permissions import BOOKINGS_REPORTS, BOOKINGS_SETUP
from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import BookingSettings
from ziira.modules.bookings.services import access
from ziira.modules.bookings.services.common import now, user_id, zone
from ziira.sdk import NotFound, Session, ValidationFailed, audit_record, check_company, current_context


# --------------------------------------------------------------------------- rules
def list_rules(session: Session, company_id: UUID, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    if not access.can_see_company(company_id):
        raise NotFound("Company not found")
    return raw.many(session, "select * from bookings.commission_rule where company_id = :c "
                             f"{'' if include_inactive else 'and is_active '}order by applies_to, created_at",
                    c=company_id)


def _check_rule(session: Session, company_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
    if values["applies_to"] not in ("service", "product"):
        raise ValidationFailed("A rule is for a service or a product")
    if values["kind"] not in ("percent", "fixed"):
        raise ValidationFailed("Commission is a percent or a fixed amount")
    if values["value"] < 0 or (values["kind"] == "percent" and values["value"] > 100):
        raise ValidationFailed("A percent is between 0 and 100")
    if values.get("offer_id"):
        offer = repo.get_offer(session, values["offer_id"])
        if offer is None or offer.company_id != company_id or values["applies_to"] != "service":
            raise ValidationFailed("That service was not found")
    if values.get("resource_id"):
        res = repo.get_resource(session, values["resource_id"])
        if res is None or res.company_id != company_id:
            raise ValidationFailed("That person was not found")
    if values["applies_to"] == "service":
        values["product_id"] = None
    else:
        values["offer_id"] = None
    values["level"] = (values.get("level") or "").strip() or None
    return values


def create_rule(session: Session, company_id: UUID, **values: Any) -> dict[str, Any]:
    """Add a commission rule. Needs 'bookings.setup'. A field left out matches anything; the most specific rule wins."""
    current_context().require(BOOKINGS_SETUP, company_id=company_id)
    check_company(session, company_id)
    data = _check_rule(session, company_id, {
        "applies_to": values.get("applies_to", "service"), "kind": values.get("kind", "percent"),
        "value": Decimal(values.get("value", 0)), "offer_id": values.get("offer_id"),
        "product_id": values.get("product_id"), "resource_id": values.get("resource_id"),
        "level": values.get("level")})
    made = raw.insert(session, "commission_rule", {"company_id": company_id, **data}, user_id=user_id())
    audit_record(session, "create", "bookings.commission_rule", made["id"], {"kind": data["kind"],
                                                                         "value": data["value"]})
    return made


def update_rule(session: Session, rule_id: UUID, **values: Any) -> dict[str, Any]:
    rule = raw.one(session, "select * from bookings.commission_rule where id = :i", i=rule_id)
    if rule is None or not access.can_see_company(rule["company_id"]):
        raise NotFound("Rule not found")
    current_context().require(BOOKINGS_SETUP, company_id=rule["company_id"])
    merged = {k: rule[k] for k in ("applies_to", "kind", "value", "offer_id", "product_id", "resource_id", "level")}
    merged.update({k: v for k, v in values.items() if k in merged and v is not None})
    data = _check_rule(session, rule["company_id"], merged)
    if "is_active" in values and values["is_active"] is not None:
        data["is_active"] = bool(values["is_active"])
    row = raw.update(session, "commission_rule", rule_id, data, user_id=user_id())
    audit_record(session, "update", "bookings.commission_rule", rule_id, {"value": row["value"]})
    return row


def _rules(session: Session, company_id: UUID) -> list[dom.Rule]:
    return [dom.Rule(r["id"], r["applies_to"], r["kind"], r["value"], r["resource_id"], r["level"], r["offer_id"],
                     r["product_id"]) for r in raw.many(session, "select * from bookings.commission_rule where "
                                                                 "company_id = :c and is_active", c=company_id)]


# --------------------------------------------------------------------------- earning
def record_for_checkout(session: Session, co: dict[str, Any], rows: list[dict[str, Any]], lines: list[dom.Line],
                        order_discount: Decimal, shares: tuple[Decimal, ...], settings: BookingSettings) -> int:
    """Write the commission each line earned for the person who did it. Base is what the client paid for the line after
    discounts, plus the worth of units paid with credit (the work was done), without tax when the business says so.
    Returns how many lines were written."""
    rules = _rules(session, co["company_id"])
    if not rules:
        return 0
    day = now().astimezone(zone(session, co["company_id"])).date()
    written = 0
    resources = repo.resources_by_ids(session, {r["resource_id"] for r in rows if r["resource_id"]})
    for r, ln, share in zip(rows, lines, shares, strict=True):
        if r["kind"] == "fee" or r["resource_id"] is None:
            continue
        resource = resources.get(r["resource_id"])
        if resource is None:
            continue
        base = dom.line_net(ln) - share + dom.cents((ln.quantity - dom.charged_quantity(ln)) * ln.unit_price)
        if settings.commission_excludes_tax and r["product_id"] is not None and base > 0:
            from ziira.modules.products.public import find_product

            product = find_product(session, r["product_id"])
            if product is not None:
                base = dom.net_of_tax(base, product.vat_rate)
        applies = "service" if r["kind"] == "service" else "product"
        rule = dom.pick_rule(rules, applies_to=applies, resource_id=resource.id, level=resource.level,
                             offer_id=r["offer_id"], product_id=r["product_id"])
        if rule is None:
            continue
        amount = dom.commission_amount(rule, base, ln.quantity)
        raw.insert(session, "commission_line", {
            "company_id": co["company_id"], "branch_id": co["branch_id"], "checkout_id": co["id"],
            "checkout_line_id": r["id"], "resource_id": resource.id, "user_id": resource.user_id,
            "applies_to": applies, "base": base, "kind": rule.kind, "rate": rule.value, "amount": amount,
            "earned_on": day}, user_id=user_id())
        written += 1
    return written


def reverse_checkout(session: Session, checkout_id: UUID, reason: str) -> int:
    """Take back the commission of a checkout whose bill was reversed (a credit note in Sales). Adds negative lines;
    nothing is edited. Doing it twice adds nothing more. Needs 'bookings.reports'."""
    co = raw.one(session, "select * from bookings.checkout where id = :i", i=checkout_id)
    if co is None or not access.can_view(co["company_id"], co["branch_id"]):
        raise NotFound("Checkout not found")
    current_context().require(BOOKINGS_REPORTS, company_id=co["company_id"], branch_id=co["branch_id"])
    if not reason.strip():
        raise ValidationFailed("Say why")
    day = now().astimezone(zone(session, co["company_id"])).date()
    done = 0
    for line in raw.many(session, "select * from bookings.commission_line l where l.checkout_id = :c and "
                                  "l.reverses_id is null and not exists (select 1 from bookings.commission_line x "
                                  "where x.reverses_id = l.id)", c=checkout_id):
        raw.insert(session, "commission_line", {
            "company_id": line["company_id"], "branch_id": line["branch_id"], "checkout_id": checkout_id,
            "checkout_line_id": line["checkout_line_id"], "resource_id": line["resource_id"],
            "user_id": line["user_id"], "applies_to": line["applies_to"], "base": -line["base"],
            "kind": line["kind"], "rate": line["rate"], "amount": -line["amount"], "earned_on": day,
            "reverses_id": line["id"]}, user_id=user_id())
        done += 1
    audit_record(session, "commission_reversed", "bookings.checkout", checkout_id, {"lines": done,
                                                                                     "reason": reason.strip()[:200]})
    return done


# --------------------------------------------------------------------------- reporting
def report(session: Session, company_id: UUID, start: date, end: date, *,
           branch_id: UUID | None = None) -> list[dict[str, Any]]:
    """Per person for a period (both days included): services done and their commission, products sold and their
    commission, the total, and tips (kept apart: received in the period, and still owed to the person). Needs
    'bookings.reports'."""
    current_context().require(BOOKINGS_REPORTS, company_id=company_id, branch_id=branch_id)
    if end < start:
        raise ValidationFailed("The end is before the start")
    params: dict[str, Any] = {"c": company_id, "s": start, "e": end, "b": branch_id}
    people = raw.many(session, """
        select r.id as resource_id, r.name, r.level, r.user_id,
          coalesce(sum(l.base) filter (where l.applies_to = 'service'), 0) as service_sales,
          coalesce(sum(l.amount) filter (where l.applies_to = 'service'), 0) as service_commission,
          coalesce(sum(l.base) filter (where l.applies_to = 'product'), 0) as product_sales,
          coalesce(sum(l.amount) filter (where l.applies_to = 'product'), 0) as product_commission,
          coalesce(sum(l.amount), 0) as commission
        from bookings.resource r
        left join bookings.commission_line l on l.resource_id = r.id and l.earned_on between :s and :e
        where r.company_id = :c and (cast(:b as uuid) is null or r.branch_id = :b) and r.kind in ('staff', 'chair')
        group by r.id, r.name, r.level, r.user_id order by r.name""", **params)
    tips = {t["resource_id"]: t for t in raw.many(session, """
        select resource_id, sum(amount) as received,
          coalesce(sum(amount) filter (where held and paid_out_at is null), 0) as owed
        from bookings.checkout_tip where company_id = :c and (created_at at time zone 'UTC')::date between :s and :e
        group by resource_id""", **params)}
    owed_all = {t["resource_id"]: t["owed"] for t in raw.many(session, """
        select resource_id, sum(amount) as owed from bookings.checkout_tip
        where company_id = :c and held and paid_out_at is null group by resource_id""", c=company_id)}
    for p in people:
        t = tips.get(p["resource_id"])
        p["tips_received"] = t["received"] if t else Decimal(0)
        p["tips_owed"] = owed_all.get(p["resource_id"], Decimal(0))
    return people


def commission_figure(session: Session, *, company_id: UUID, start: date, end: date, resource_id: UUID | None = None,
                      user_id_: UUID | None = None) -> Decimal:
    """What a person earned in commission in a period (one number, for Payroll to read). Name the person by resource or
    by the user the resource is linked to. Not permission-checked: the caller has checked its own."""
    row = raw.one(session, """
        select coalesce(sum(amount), 0) as total from bookings.commission_line
        where company_id = :c and earned_on between :s and :e
        and (cast(:r as uuid) is null or resource_id = :r) and (cast(:u as uuid) is null or user_id = :u)""",
                  c=company_id, s=start, e=end, r=resource_id, u=user_id_)
    return Decimal(row["total"]) if row else Decimal(0)


def tips_owed(session: Session, company_id: UUID, branch_id: UUID | None = None) -> list[dict[str, Any]]:
    """Tips the business holds for each person (card and mobile-money tips not yet paid out)."""
    current_context().require(BOOKINGS_REPORTS, company_id=company_id, branch_id=branch_id)
    return raw.many(session, """
        select t.resource_id, r.name, sum(t.amount) as owed, count(*) as tips from bookings.checkout_tip t
        join bookings.resource r on r.id = t.resource_id
        where t.company_id = :c and t.held and t.paid_out_at is null and (cast(:b as uuid) is null or t.branch_id = :b)
        group by t.resource_id, r.name order by r.name""", c=company_id, b=branch_id)


def pay_out_tips(session: Session, company_id: UUID, resource_id: UUID, branch_id: UUID | None = None) -> Decimal:
    """Record that the tips held for a person were handed over. Returns the amount. No ledger entry is made (tips are
    not revenue and the business only holds them for a short while); the record is the proof. Needs
    'bookings.reports'."""
    current_context().require(BOOKINGS_REPORTS, company_id=company_id, branch_id=branch_id)
    rows = raw.many(session, "update bookings.checkout_tip set paid_out_at = now(), paid_out_by = :u, "
                             "updated_at = now() "
                             "where company_id = :c and resource_id = :r and held and paid_out_at is null "
                             "and (cast(:b as uuid) is null or branch_id = :b) returning amount",
                    u=user_id(), c=company_id, r=resource_id, b=branch_id)
    total = sum((Decimal(r["amount"]) for r in rows), Decimal(0))
    if total <= 0:
        raise ValidationFailed("There are no tips owed to that person")
    audit_record(session, "tips_paid_out", "bookings.resource", resource_id, {"amount": total, "tips": len(rows)})
    return total
