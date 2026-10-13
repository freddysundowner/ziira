"""Create a demo tenant with sample products and opening stock (development only).

Workspace code: demo-hardware · owner: owner@demo-hardware.test · password: demo-pass-123

Prints the tenant ID. Safe to run more than once: reuses the tenant stored in .demo_tenant.
"""

import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.context import system_context
from ziira.kernel.db import master_session, tenant_session
from ziira.kernel.registry import Registry, load_event_handlers
from ziira.kernel.tenants import create_tenant
from ziira.modules.inventory.services.locations import create_location
from ziira.modules.inventory.services.opening_stock import OpeningLine, post_opening_stock
from ziira.modules.products.services.create_product import create_product
from ziira.modules.products.services.create_tax_code import create_tax_code
from ziira.modules.products.services.create_uom import create_uom

STATE = Path(__file__).resolve().parent.parent / ".demo_tenant"

PRODUCTS = [
    ("CEM-50KG", "Cement 50kg", "BAG", "stock", Decimal("50")),
    ("ROOF-G30", "Roofing sheet gauge 30, 3m", "PCS", "stock", Decimal("40")),
    ("NAIL-4IN", "Wire nails 4 inch, 1kg", "KG", "stock", Decimal("25")),
    ("PAINT-W4L", "White emulsion paint 4L", "PCS", "stock", Decimal("10")),
    ("DELIVERY", "Delivery within Thika", "PCS", "service", None),
]


# Opening stock (SKU -> quantity, unit cost)
STOCK = {"CEM-50KG": (Decimal("120"), Decimal("650")), "ROOF-G30": (Decimal("60"), Decimal("780")),
         "NAIL-4IN": (Decimal("200"), Decimal("140")), "PAINT-W4L": (Decimal("8"), Decimal("1900"))}


def add_stock(tenant_id: UUID) -> None:
    """Give the demo business a shop-floor location with opening stock (skipped if it already has one)."""
    system_context(tenant_id)
    with tenant_session(tenant_id) as s:
        if s.execute(text("select 1 from inventory.location")).first():
            return
        company_id, branch_id = s.execute(text(
            "select c.id, b.id from kernel.company c join kernel.branch b on b.company_id = c.id limit 1")).one()
        location = create_location(s, company_id=company_id, branch_id=branch_id, code="MAIN",
                                   name="Thika shop floor", kind="store")
        products = {sku: pid for pid, sku in s.execute(text("select id, sku from products.product"))}
        post_opening_stock(s, company_id=company_id, location_id=location.id, lines=[
            OpeningLine(products[sku], quantity, cost) for sku, (quantity, cost) in STOCK.items()])


def main() -> None:
    load_event_handlers()
    if STATE.exists():
        tenant_id = UUID(STATE.read_text().strip())
        with master_session() as s:
            found = s.execute(text("select 1 from master.tenant where id = :t and status = 'active'"),
                              {"t": str(tenant_id)}).first()
        if found:
            add_stock(tenant_id)
            print(tenant_id)
            return

    demo = create_tenant(name="Demo Hardware", code="demo-hardware", company="Demo Hardware Ltd",
                         branch_code="THK", branch_name="Thika", owner_name="Demo Owner",
                         owner_email="owner@demo-hardware.test", owner_password="demo-pass-123",
                         vat_registered=True)
    tenant_id, company_id = demo.tenant_id, demo.company_id

    Registry().enable(tenant_id, "pos")             # also enables products, inventory, payments
    Registry().enable(tenant_id, "catalog_stats")

    system_context(tenant_id)
    with tenant_session(tenant_id) as s:
        uoms = {code: create_uom(s, code, name).id
                for code, name in (("BAG", "Bag"), ("PCS", "Pieces"), ("KG", "Kilogram"))}
        vat = create_tax_code(s, "VAT16", "Standard VAT", Decimal("16"), "B").id
        for sku, name, uom, kind, reorder in PRODUCTS:
            create_product(s, company_id=company_id, sku=sku, name=name, base_uom_id=uoms[uom],
                           tax_code_id=vat, product_type=kind, reorder_level=reorder)

    add_stock(tenant_id)
    STATE.write_text(str(tenant_id))
    print(tenant_id)


if __name__ == "__main__":
    sys.exit(main())
