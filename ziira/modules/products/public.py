"""Public interface of the Products module.

Other units (for example POS or Inventory) may import only from this file.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.products.repository import products_repo
from ziira.sdk import Session


@dataclass(frozen=True)
class ProductView:
    """What other modules need to know about a product."""

    id: UUID
    sku: str
    name: str
    product_type: str
    base_uom_id: UUID
    tax_code_id: UUID
    vat_rate: Decimal
    is_batch_tracked: bool


def find_product(session: Session, product_id: UUID) -> ProductView | None:
    """Return a product with its VAT rate, or None if it does not exist for this tenant."""
    p = products_repo.get_product(session, product_id)
    if p is None:
        return None
    tax = products_repo.get_tax_code(session, p.tax_code_id)
    return ProductView(id=p.id, sku=p.sku, name=p.name, product_type=p.product_type,
                       base_uom_id=p.base_uom_id, tax_code_id=p.tax_code_id,
                       vat_rate=tax.vat_rate if tax else Decimal("0"),
                       is_batch_tracked=p.is_batch_tracked)
