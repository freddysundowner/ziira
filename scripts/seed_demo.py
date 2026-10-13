"""Create a demo tenant with sample products (development only).

Workspace code: demo-hardware · owner: owner@demo-hardware.test · password: demo-pass-123

Prints the tenant ID. Safe to run more than once: reuses the tenant stored in .demo_tenant.
"""

import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from ziira.kernel.context import system_context
from ziira.kernel.db import admin_session, tenant_session
from ziira.kernel.registry import Registry, load_event_handlers
from ziira.kernel.tenants import create_tenant
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


def main() -> None:
    load_event_handlers()
    if STATE.exists():
        tenant_id = UUID(STATE.read_text().strip())
        with admin_session() as s:
            found = s.execute(text("select 1 from kernel.tenant where id = :t"), {"t": str(tenant_id)}).first()
        if found:
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

    STATE.write_text(str(tenant_id))
    print(tenant_id)


if __name__ == "__main__":
    sys.exit(main())
