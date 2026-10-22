"""Use case: add the catalogue an industry pack supplies (`data/products.toml`): product categories, units of measure,
and example stock products with their other pack units and custom-field values.

`data/products.toml` shape (next to the `[[service]]` tables `seed_industry.py` reads):

    [[category]]                       # name
    [[unit]]                           # code, name   (a unit the business already has is left alone)
    [[product]]                        # sku, name, category (name), unit (the base unit code), batch_tracked,
                                       # reorder_level, pack_units = [{unit = "STRIP", factor = 10}],
                                       # fields = {key = value}  (custom fields of "products.product")

A pack gives no prices: a price is money the business sets itself. Products are examples the business edits (the
pack names them so); a SKU the business already has is skipped, so running it again adds nothing and a product the
business changed or removed is never brought back or overwritten. Other units of a product (a strip, a box) are
recorded with their factor to the base unit; no screen sells in them yet.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from ziira.modules.products.domain import rules
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Uom
from ziira.modules.products.services.create_product import create_product
from ziira.modules.products.services.seed_industry import _uom_and_tax
from ziira.sdk import (
    PackData,
    SeededItem,
    SeedReport,
    Session,
    ValidationFailed,
    audit_record,
    current_context,
    custom_fields,
)

ENTITY = "products.product"


def _ensure_fields(session: Session, pack: PackData) -> None:
    """Make sure the product fields the pack ships exist before values are written (the kernel seeder adds the same
    fields, in whichever order the seeders run; a field that exists is left alone)."""
    for spec in pack.unit_data("custom_fields").get("field", []):
        if spec["entity_type"] == ENTITY:
            custom_fields.seed_definition(
                session, pack=pack.name, entity_type=ENTITY, key=spec["key"], label=spec["label"], kind=spec["kind"],
                choices=list(spec.get("choices", [])), required=bool(spec.get("required", False)),
                searchable=bool(spec.get("searchable", False)))


def _categories(session: Session, specs: list[dict[str, Any]], report: SeedReport) -> dict[str, UUID]:
    ctx = current_context()
    found = {str(r.name).lower(): r.id for r in session.execute(text("select id, name from products.category"))}
    for spec in specs:
        name = rules.check_name(str(spec["name"]), "Category")
        if name.lower() in found:
            report.skipped += 1
            continue
        made = session.execute(text(
            "insert into products.category (tenant_id, created_by, name) values (:t, :u, :n) returning id"),
            {"t": str(ctx.tenant_id), "u": str(ctx.user_id) if ctx.user_id else None, "n": name}).scalar_one()
        found[name.lower()] = made
        report.added.append(SeededItem("category", made, name))
    return found


def _units(session: Session, specs: list[dict[str, Any]], report: SeedReport) -> dict[str, UUID]:
    ctx = current_context()
    have = {u.code: u.id for u in products_repo.list_uoms(session)}
    for spec in specs:
        code = rules.normalise_uom_code(str(spec["code"]))
        if code in have:
            report.skipped += 1
            continue
        uom = Uom(tenant_id=ctx.tenant_id, created_by=ctx.user_id, code=code, name=rules.check_name(str(spec["name"])))
        products_repo.add(session, uom)
        have[code] = uom.id
        report.added.append(SeededItem("uom", uom.id, code))
    return have


def _pack_units(session: Session, product_id: UUID, specs: list[dict[str, Any]], units: dict[str, UUID]) -> None:
    for spec in specs:
        uom_id = units.get(rules.normalise_uom_code(str(spec["unit"])))
        factor = Decimal(str(spec["factor"]))
        if uom_id is None or factor <= 0:
            continue
        session.execute(text(
            "insert into products.product_uom (tenant_id, product_id, uom_id, factor_to_base) "
            "values (kernel.current_tenant(), :p, :u, :f) on conflict (product_id, uom_id) do nothing"),
            {"p": str(product_id), "u": str(uom_id), "f": str(factor)})


def seed_catalogue(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    """Add the pack's categories, units and example products the company lacks."""
    report = SeedReport()
    data = pack.unit_data("products")
    if not (data.get("category") or data.get("unit") or data.get("product")):
        return report
    categories = _categories(session, data.get("category", []), report)
    units = _units(session, data.get("unit", []), report)
    products = data.get("product", [])
    if not products:
        return report
    _, tax_id = _uom_and_tax(session, data)
    if tax_id is None:
        report.notes.append("products: no tax code yet, so no example products were added")
        report.skipped += len(products)
        return report
    _ensure_fields(session, pack)
    for row in products:
        sku = rules.normalise_sku(str(row["sku"]))
        base = units.get(rules.normalise_uom_code(str(row["unit"])))
        if base is None:
            report.notes.append(f"{sku}: unit {row['unit']} is not available")
            report.skipped += 1
            continue
        if products_repo.sku_exists(session, company_id, sku):
            report.skipped += 1
            continue
        level = Decimal(str(row["reorder_level"])) if row.get("reorder_level") is not None else None
        product = create_product(session, company_id=company_id, sku=sku, name=str(row["name"]), base_uom_id=base,
                                 tax_code_id=tax_id, product_type="stock",
                                 is_batch_tracked=bool(row.get("batch_tracked", False)), reorder_level=level)
        category = categories.get(str(row.get("category", "")).lower())
        if category is not None:
            product.category_id = category
        session.flush()
        _pack_units(session, product.id, row.get("pack_units", []), units)
        if row.get("fields"):
            try:
                custom_fields.write_values(session, ENTITY, product.id, dict(row["fields"]), company_id=company_id,
                                           check_required=False)
            except ValidationFailed as problem:
                report.notes.append(f"{sku}: fields not saved ({problem.message})")
        report.added.append(SeededItem("product", product.id, product.name))
    if report.added:
        audit_record(session, "seed_catalogue", "products.product", None,
                     {"pack": pack.name, "added": [i.label for i in report.added]})
    return report
