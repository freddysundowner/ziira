"""Public interface of the Products module.

Other units (for example POS or Inventory) may import only from this file. It also defines the
sockets Products offers (declared in hooks.py and in manifest.toml):

- Validation hook PRODUCT_BEFORE_CREATE: runs before a product is saved, with a ProductDraft.
  Raise ValidationFailed to block it.
- Extension point SKU_SUGGESTER: implement SkuSuggester to suggest SKUs for a new product name.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ziira.modules.products.repository import products_repo
from ziira.sdk import Session

PRODUCT_BEFORE_CREATE = "products.product.before_create"
SKU_SUGGESTER = "products.sku_suggester"


@dataclass(frozen=True)
class ProductDraft:
    """A product about to be created, as validators of PRODUCT_BEFORE_CREATE see it."""

    company_id: UUID
    sku: str
    name: str
    product_type: str
    base_uom_id: UUID
    tax_code_id: UUID


class SkuSuggester(ABC):
    """Contract for the SKU_SUGGESTER extension point."""

    @abstractmethod
    def suggest(self, session: Session, company_id: UUID, name: str) -> list[str]:
        """Return candidate SKUs for a product called `name` (may be empty)."""


def product_name_exists(session: Session, company_id: UUID, name: str) -> bool:
    """True if the company already has a product with this name (ignoring case and spaces)."""
    return products_repo.name_exists(session, company_id, name)


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
