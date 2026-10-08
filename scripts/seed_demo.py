"""Create a demo tenant with sample products (development only).

Prints the tenant ID. Safe to run more than once: reuses the tenant stored in .demo_tenant.
"""

import sys
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from ziira.kernel.context import RequestContext, set_context
from ziira.kernel.db import admin_session, tenant_session
from ziira.kernel.registry import Registry, load_event_handlers
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

    tenant_id, company_id, branch_id = uuid4(), uuid4(), uuid4()
    with admin_session() as s:
        s.execute(text("insert into kernel.tenant (id, name) values (:i, 'Demo Hardware')"), {"i": str(tenant_id)})
    with tenant_session(tenant_id, admin=True) as s:
        s.execute(text("insert into kernel.company (id, tenant_id, name, vat_registered) "
                       "values (:i, :t, 'Demo Hardware Ltd', true)"), {"i": str(company_id), "t": str(tenant_id)})
        s.execute(text("insert into kernel.branch (id, tenant_id, company_id, code, name) "
                       "values (:i, :t, :c, 'THK', 'Thika')"),
                  {"i": str(branch_id), "t": str(tenant_id), "c": str(company_id)})

    Registry().enable(tenant_id, "pos")             # also enables products, inventory, payments
    Registry().enable(tenant_id, "catalog_stats")

    set_context(RequestContext(tenant_id=tenant_id, channel="system"))
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
