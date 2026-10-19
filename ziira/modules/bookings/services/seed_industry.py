"""Industry packs for Bookings: what a kind of business starts with, copied from the pack's `data/bookings.toml`.

A pack (salon, clinic ...) may supply: suggested settings, staff and room templates with hours, bookable services
(linked to the matching service items in Products), price variants by staff level, commission rules, a first-run
checklist and Intelligence limits. Everything is data the business can edit; nothing is overwritten once the business
has changed it; and prices in a pack are *examples* (shown as such until the business sets its own).

`data/bookings.toml` shape:

    [settings]                         # applied once, while the business has saved no booking settings of its own
    cancel_window_hours = 24
    [[resource]]                       # name, kind, level, colour,
                                       # hours = [{days = [0,1,2,3,4], start = "09:00", end = "17:00"}]
    [[service]]                        # sku (the Products item), name, minutes, price (an example), buffer_after,
                                       # processing_start, processing, recall_days, deposit_percent,
                                       # needs_patch_test, kind, capacity, resources = [names]
    [[variant]]                        # service (sku), label, level, price
    [[commission]]                     # applies_to, level, kind, value, service (sku, optional)
    [[step]]                           # id, title, hint, to, check
    [intel."bookings.no_show_rate"]    # limits for an Intelligence check
"""

from datetime import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.bookings.repository import bookings_repo as repo
from ziira.modules.bookings.repository import raw
from ziira.modules.bookings.repository.models import Resource, ResourceHours, ServiceOffer, ServiceOfferResource
from ziira.modules.bookings.services.common import unit_enabled
from ziira.sdk import (
    INDUSTRY_SEEDER,
    PackData,
    SeededItem,
    SeedReport,
    Session,
    current_context,
    implementations,
)

SETTING_KEYS: dict[str, type] = {
    "online_enabled": bool, "auto_confirm": bool, "min_notice_minutes": int, "max_days_ahead": int,
    "cancel_window_hours": int, "reminders_enabled": bool, "reminder_hours_before": int,
    "slot_granularity_minutes": int, "default_buffer_minutes": int, "show_resources_publicly": bool,
    "late_cancel_fee_percent": Decimal, "no_show_fee_percent": Decimal, "waitlist_confirm_minutes": int,
    "rebook_prompt_hours": int, "recalls_enabled": bool, "deposit_note": str, "patch_test_valid_days": int,
    "commission_excludes_tax": bool, "reminder_template": str, "recall_template": str, "rebook_template": str,
    "discount_limit_percent": Decimal}


def _was_seeded(session: Session, pack: PackData, company_id: UUID, item_type: str, label: str) -> bool:
    """True when this pack already added a row with this label for the company, so one the business removed on purpose
    is not brought back."""
    return session.execute(text(
        "select 1 from kernel.pack_seed_log where pack = :p and company_id = :c and seeder = 'bookings' "
        "and item_type = :t and item_label = :l limit 1"),
        {"p": pack.name, "c": str(company_id), "t": item_type, "l": label}).first() is not None


def _time(value: str) -> time:
    hour, minute = value.split(":")[:2]
    return time(int(hour), int(minute))


def _main_branch(session: Session, company_id: UUID) -> UUID | None:
    row = session.execute(text("select id from kernel.branch where company_id = :c order by created_at, name limit 1"),
                          {"c": str(company_id)}).first()
    return row.id if row else None


def seed(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    """Copy the pack's booking data for the company. Idempotent: running it again adds what is missing only."""
    report = SeedReport()
    data = pack.unit_data("bookings")
    if not data:
        return report
    _settings(session, pack, company_id, data.get("settings", {}), report)
    branch_id = _main_branch(session, company_id)
    _products_first(session, pack, company_id, report)
    names = _resources(session, pack, company_id, branch_id, data.get("resource", []), report)
    offers = _services(session, pack, company_id, data.get("service", []), names, report)
    _variants(session, pack, company_id, data.get("variant", []), offers, report)
    _commission(session, pack, company_id, data.get("commission", []), offers, report)
    _steps(session, pack, company_id, data.get("step", []), report)
    if data.get("intel") and unit_enabled(session, "intel"):
        from ziira.modules.intel.public import apply_check_defaults

        done = apply_check_defaults(session, {code: dict(p) for code, p in data["intel"].items()})
        if done:
            report.notes.append(f"Intelligence limits suggested for: {', '.join(done)}")
    return report


# --------------------------------------------------------------------------- pieces
def _settings(session: Session, pack: PackData, company_id: UUID, given: dict[str, Any], report: SeedReport) -> None:
    if not given:
        return
    row = repo.ensure_settings(session, company_id)
    if row.updated_at is not None or row.pack_name is not None:
        report.skipped += 1
        return
    for key, value in given.items():
        kind = SETTING_KEYS.get(key)
        if kind is None:
            report.notes.append(f"settings: '{key}' is not a booking setting")
            continue
        setattr(row, key, kind(value) if kind in (int, Decimal) else value)
    row.pack_name = pack.name
    session.flush()
    report.notes.append("Booking settings set to the pack's suggestions")


def _products_first(session: Session, pack: PackData, company_id: UUID, report: SeedReport) -> None:
    """The service items of the pack come from Products' own seeder. Which seeder runs first is not promised, so run it
    now (it only adds what is missing) and report what it added as ours; the kernel's later call finds nothing to do."""
    if not unit_enabled(session, "products"):
        return
    for seeder in implementations(session, INDUSTRY_SEEDER):
        if getattr(seeder, "unit", "") == "products":
            made = seeder.seed(session, pack, company_id)
            report.added.extend(made.added)
            report.notes.extend(made.notes)


def _resources(session: Session, pack: PackData, company_id: UUID, branch_id: UUID | None, specs: list[dict[str, Any]],
               report: SeedReport) -> dict[str, UUID]:
    """Staff and room templates; returns every resource of the company by name (the pack's and the existing)."""
    ctx = current_context()
    found = {r.name.casefold(): r for r in repo.list_resources(session, None, company_id=company_id)}
    names: dict[str, UUID] = {r.name: r.id for r in found.values()}
    if not specs:
        return names
    if branch_id is None:
        report.notes.append("resources: the business has no branch yet")
        return names
    for spec in specs:
        name = str(spec["name"]).strip()
        if name.casefold() in found or _was_seeded(session, pack, company_id, "resource", name):
            report.skipped += 1
            continue
        resource = Resource(tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, branch_id=branch_id,
                            name=name, kind=spec.get("kind", "staff"), colour=spec.get("colour"),
                            level=spec.get("level"), is_template=True, sort_order=int(spec.get("order", 0)),
                            note=spec.get("note"))
        repo.add(session, resource)
        for window in spec.get("hours", []):
            for day in window.get("days", []):
                repo.add(session, ResourceHours(tenant_id=ctx.tenant_id, created_by=ctx.user_id,
                                                resource_id=resource.id, weekday=int(day),
                                                start_time=_time(window["start"]), end_time=_time(window["end"])))
        names[name] = resource.id
        report.added.append(SeededItem("resource", resource.id, name))
    return names


def _offer_for(session: Session, company_id: UUID, sku: str | None,
               name: str) -> tuple[ServiceOffer | None, UUID | None]:
    """(the business's offer for this item, the Products item) - found by the item or, failing that, by name."""
    product_id = None
    if sku and unit_enabled(session, "products"):
        from ziira.modules.products.public import find_product_by_sku

        product = find_product_by_sku(session, company_id, sku)
        product_id = product.id if product else None
    offers = repo.list_offers(session, None, company_id=company_id)
    for o in offers:
        if (product_id is not None and o.product_id == product_id) or o.name.casefold() == name.casefold():
            return o, product_id
    return None, product_id


def _services(session: Session, pack: PackData, company_id: UUID, specs: list[dict[str, Any]], names: dict[str, UUID],
              report: SeedReport) -> dict[str, UUID]:
    """Bookable services. Returns offer ids by item code (and by name)."""
    ctx = current_context()
    out: dict[str, UUID] = {}
    staff_chairs = [rid for n, rid in names.items()
                    if (r := repo.get_resource(session, rid)) is not None and r.kind in ("staff", "chair")]
    rooms = [rid for n, rid in names.items() if (r := repo.get_resource(session, rid)) is not None and r.kind == "room"]
    for spec in specs:
        name = str(spec["name"]).strip()
        existing, product_id = _offer_for(session, company_id, spec.get("sku"), name)
        if existing is None and _was_seeded(session, pack, company_id, "service_offer", name):
            report.skipped += 1                              # removed on purpose: it stays removed
            continue
        if existing is not None:
            if existing.product_id is None and product_id is not None and existing.updated_at is None:
                existing.product_id = product_id             # the item now exists: link what the pack made earlier
                session.flush()
            out[spec.get("sku") or name] = existing.id
            out[name] = existing.id
            report.skipped += 1
            continue
        price = Decimal(str(spec.get("price", 0)))
        if product_id is not None and unit_enabled(session, "products"):
            from ziira.modules.products.public import selling_prices

            real = selling_prices(session, company_id, None, {product_id}).get(product_id)
            if real is not None:
                price = real
        is_class = spec.get("kind", "appointment") == "class"
        offer = ServiceOffer(
            tenant_id=ctx.tenant_id, created_by=ctx.user_id, company_id=company_id, product_id=product_id, name=name,
            description=spec.get("description"), kind="class" if is_class else "appointment",
            duration_minutes=int(spec["minutes"]), buffer_before_minutes=int(spec.get("buffer_before", 0)),
            buffer_after_minutes=int(spec.get("buffer_after", 0)), price=price,
            resource_mode=spec.get("resource_mode", "any"), capacity=int(spec.get("capacity", 1)) if is_class else 1,
            show_publicly=bool(spec.get("show_publicly", True)),
            processing_start_minutes=int(spec.get("processing_start", 0)),
            processing_minutes=int(spec.get("processing", 0)),
            deposit_percent=Decimal(str(spec.get("deposit_percent", 0))),
            deposit_amount=Decimal(str(spec.get("deposit_amount", 0))), recall_days=spec.get("recall_days"),
            needs_patch_test=bool(spec.get("needs_patch_test", False)),
            price_is_example=spec.get("price") is not None and not _has_real_price(session, company_id, product_id))
        repo.add(session, offer)
        wanted = [names[n] for n in spec.get("resources", []) if n in names] or (rooms if spec.get("rooms") else
                                                                                   staff_chairs)
        for rid in dict.fromkeys(wanted):
            repo.add(session, ServiceOfferResource(tenant_id=ctx.tenant_id, created_by=ctx.user_id, offer_id=offer.id,
                                                   resource_id=rid))
        out[spec.get("sku") or name] = offer.id
        out[name] = offer.id
        report.added.append(SeededItem("service_offer", offer.id, name))
    return out


def _has_real_price(session: Session, company_id: UUID, product_id: UUID | None) -> bool:
    if product_id is None or not unit_enabled(session, "products"):
        return False
    from ziira.modules.products.public import selling_prices

    return product_id in selling_prices(session, company_id, None, {product_id})


def _variants(session: Session, pack: PackData, company_id: UUID, specs: list[dict[str, Any]], offers: dict[str, UUID],
              report: SeedReport) -> None:
    for spec in specs:
        offer_id = offers.get(spec["service"])
        if offer_id is None:
            report.notes.append(f"variant '{spec['label']}': no service {spec['service']}")
            continue
        have = raw.one(session, "select id from bookings.price_variant "
                       "where offer_id = :o and lower(label) = lower(:l)",
                       o=offer_id, l=spec["label"])
        label = f"{spec['service']}: {spec['label']}"
        if have is not None or _was_seeded(session, pack, company_id, "price_variant", label):
            report.skipped += 1
            continue
        made = raw.insert(session, "price_variant", {
            "offer_id": offer_id, "label": spec["label"], "level": spec.get("level"),
            "price": Decimal(str(spec["price"])), "sort_order": int(spec.get("order", 0))},
            user_id=current_context().user_id)
        report.added.append(SeededItem("price_variant", made["id"], f"{spec['service']}: {spec['label']}"))


def _commission(session: Session, pack: PackData, company_id: UUID, specs: list[dict[str, Any]],
                offers: dict[str, UUID], report: SeedReport) -> None:
    for spec in specs:
        offer_id = offers.get(spec["service"]) if spec.get("service") else None
        have = raw.one(session, """select id from bookings.commission_rule where company_id = :c and applies_to = :a
            and kind = :k and coalesce(level, '') = coalesce(cast(:l as text), '')
            and coalesce(offer_id, '00000000-0000-0000-0000-000000000000'::uuid) =
                coalesce(cast(:o as uuid), '00000000-0000-0000-0000-000000000000'::uuid) and resource_id is null""",
                       c=company_id, a=spec.get("applies_to", "service"), k=spec.get("kind", "percent"),
                       l=spec.get("level"), o=offer_id)
        label = f"{spec.get('applies_to', 'service')} {spec.get('level') or 'everyone'}: {spec['value']}"
        if have is not None or _was_seeded(session, pack, company_id, "commission_rule", label):
            report.skipped += 1
            continue
        made = raw.insert(session, "commission_rule", {
            "company_id": company_id, "applies_to": spec.get("applies_to", "service"), "offer_id": offer_id,
            "level": spec.get("level"), "kind": spec.get("kind", "percent"), "value": Decimal(str(spec["value"]))},
            user_id=current_context().user_id)
        report.added.append(SeededItem(
            "commission_rule", made["id"],
            f"{spec.get('applies_to', 'service')} {spec.get('level') or 'everyone'}: {spec['value']}"))


def _steps(session: Session, pack: PackData, company_id: UUID, specs: list[dict[str, Any]], report: SeedReport) -> None:
    for order, spec in enumerate(specs):
        if _was_seeded(session, pack, company_id, "pack_step", spec["title"]):
            report.skipped += 1
            continue
        made = raw.one(session, "insert into bookings.pack_step (tenant_id, company_id, pack, step_id, title, hint, "
                                "to_path, check_key, sort_order) values (kernel.current_tenant(), :c, :p, :s, :t, :h, "
                                ":to, :k, :o) on conflict (company_id, pack, step_id) do nothing returning id",
                       c=company_id, p=pack.name, s=spec["id"], t=spec["title"], h=spec.get("hint"),
                       to=spec.get("to"), k=spec.get("check"), o=order)
        if made is None:
            report.skipped += 1
        else:
            report.added.append(SeededItem("pack_step", made["id"], spec["title"]))


# --------------------------------------------------------------------------- switching a pack off
def untouched(session: Session, item_type: str, item_id: UUID) -> bool:
    """A row the pack added that nobody changed or used."""
    if item_type == "resource":
        row = session.execute(text(
            "select r.is_template, "
            "(select count(*) from bookings.appointment_resource a where a.resource_id = r.id) as n "
            "from bookings.resource r where r.id = :i"), {"i": str(item_id)}).first()
        return bool(row and row.is_template and row.n == 0)
    if item_type == "service_offer":
        row = session.execute(text(
            "select o.price_is_example, (select count(*) from bookings.appointment a where a.offer_id = o.id) as n "
            "from bookings.service_offer o where o.id = :i"), {"i": str(item_id)}).first()
        return bool(row and row.price_is_example and row.n == 0)
    if item_type == "product":
        return any(s.untouched(session, item_type, item_id) for s in implementations(session, INDUSTRY_SEEDER)
                   if getattr(s, "unit", "") == "products")
    return item_type in ("pack_step", "commission_rule", "price_variant")


def remove(session: Session, item_type: str, item_id: UUID) -> None:
    if item_type == "product":
        for s in implementations(session, INDUSTRY_SEEDER):
            if getattr(s, "unit", "") == "products":
                s.remove(session, item_type, item_id)
        return
    table = {"resource": "resource", "service_offer": "service_offer", "pack_step": "pack_step",
             "commission_rule": "commission_rule", "price_variant": "price_variant"}[item_type]
    session.execute(text(f"delete from bookings.{table} where id = :i"), {"i": str(item_id)})
