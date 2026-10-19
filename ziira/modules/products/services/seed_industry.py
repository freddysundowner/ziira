"""Use case: add the service items an industry pack supplies (`data/products.toml`, a list of `[[service]]` tables with
`sku`, `name`, optionally `minutes`; optionally `uom` and `tax_code` codes at the top).

Services are `service` products (no stock). The pack gives no prices: a price is money the business sets itself. The
unit of measure and tax code are the pack's named ones when the business has them, else the first unit and the
zero-rate (or first) tax code. Idempotent and non-destructive: a SKU the business already has is left alone.
"""

from decimal import Decimal
from typing import Any
from uuid import UUID

from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Product
from ziira.modules.products.services.create_product import create_product
from ziira.sdk import PackData, SeededItem, SeedReport, Session, audit_record, current_context

MAX_MINUTES = 1440


def _uom_and_tax(session: Session, data: dict[str, Any]) -> tuple[UUID | None, UUID | None]:
    uoms = products_repo.list_uoms(session)
    wanted_uom = str(data.get("uom", "")).upper()
    uom = next((u for u in uoms if u.code == wanted_uom), uoms[0] if uoms else None)
    taxes = [t for t in products_repo.list_tax_codes(session) if t.is_active]
    wanted_tax = str(data.get("tax_code", "")).upper()
    tax = (next((t for t in taxes if t.code == wanted_tax), None)
           or next((t for t in taxes if t.vat_rate == Decimal(0)), None) or (taxes[0] if taxes else None))
    return (uom.id if uom else None), (tax.id if tax else None)


def seed_services(session: Session, pack: PackData, company_id: UUID) -> SeedReport:
    """Add the pack's service items the company lacks."""
    report = SeedReport()
    data = pack.unit_data("products")
    services = data.get("service", [])
    if not services:
        return report
    uom_id, tax_id = _uom_and_tax(session, data)
    if uom_id is None or tax_id is None:
        report.notes.append("products: no unit of measure or tax code yet, so no service items were added")
        report.skipped = len(services)
        return report
    for row in services:
        sku = str(row["sku"]).strip().upper()
        if products_repo.sku_exists(session, company_id, sku):
            report.skipped += 1
            continue
        minutes = row.get("minutes")
        if minutes is not None and not 1 <= int(minutes) <= MAX_MINUTES:
            report.notes.append(f"{sku}: minutes must be 1 to {MAX_MINUTES}")
            report.skipped += 1
            continue
        product = create_product(session, company_id=company_id, sku=sku, name=row["name"], base_uom_id=uom_id,
                                 tax_code_id=tax_id, product_type="service")
        product.service_minutes = int(minutes) if minutes is not None else None
        session.flush()
        report.added.append(SeededItem("product", product.id, product.name))
    if report.added:
        audit_record(session, "seed_services", "products.product", None,
                     {"pack": pack.name, "skus": [i.label for i in report.added]})
    return report


def is_untouched(session: Session, product_id: UUID) -> bool:
    """A pack's service item nobody edited, priced or used in a price list: hiding it loses nothing."""
    product = session.get(Product, product_id)
    return (product is not None and product.is_active and product.updated_at is None
            and not products_repo.has_price(session, product_id))


def hide(session: Session, product_id: UUID) -> None:
    """Hide the service item (products are never deleted: other records may name them)."""
    product = session.get(Product, product_id)
    if product is not None:
        product.is_active = False
        product.updated_by = current_context().user_id
        session.flush()
        audit_record(session, "hide", "products.product", product_id, {"reason": "industry pack switched off"})
