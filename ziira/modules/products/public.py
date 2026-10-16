"""Public interface of the Products module.

Other units (for example POS or Inventory) may import only from this file. It also defines the
sockets Products offers (declared in hooks.py and in manifest.toml):

- Validation hook PRODUCT_BEFORE_CREATE: runs before a product is saved, with a ProductDraft.
  Raise ValidationFailed to block it.
- Extension point SKU_SUGGESTER: implement SkuSuggester to suggest SKUs for a new product name.
- Extension point TAX_CODE_SEED: a country pack implements TaxCodeSeed to supply its tax codes (data), which are added
  to a business that switches the pack on. Products has no tax codes of its own: the international pack supplies a
  minimal set.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from ziira.modules.products.repository import products_repo
from ziira.sdk import Session, ValidationFailed

PRODUCT_BEFORE_CREATE = "products.product.before_create"
SKU_SUGGESTER = "products.sku_suggester"
TAX_CODE_SEED = "products.tax_code_seed"


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


@dataclass(frozen=True)
class TaxCodeRow:
    """A tax code a country pack supplies. `vat_rate` is a percentage; `authority_code` is the tax authority's name."""

    code: str
    name: str
    vat_rate: Decimal
    authority_code: str | None = None


def check_tax_codes(rows: list[TaxCodeRow]) -> None:
    """For a pack's own tests: ValidationFailed on the first tax code Products would refuse, ValueError on a repeat."""
    from ziira.modules.products.domain import rules

    seen: set[str] = set()
    for row in rows:
        code = rules.check_tax_code(row.code)
        rules.check_name(row.name)
        rules.check_vat_rate(row.vat_rate)
        rules.check_authority_code(row.authority_code)
        if code in seen:
            raise ValueError(f"{code} appears twice")
        seen.add(code)


class TaxCodeSeed(ABC):
    """Contract for the TAX_CODE_SEED extension point. `countries` are ISO codes the data is for (empty: worldwide)."""

    countries: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def tax_codes(self) -> list[TaxCodeRow]:
        """The codes to add (those the business already has are left alone)."""


def product_name_exists(session: Session, company_id: UUID, name: str) -> bool:
    """True if the company already has a product with this name (ignoring case and spaces)."""
    return products_repo.name_exists(session, company_id, name)


@dataclass(frozen=True)
class ProductView:
    """What other modules need to know about a product."""

    id: UUID
    company_id: UUID
    sku: str
    name: str
    product_type: str
    base_uom_id: UUID
    tax_code_id: UUID
    vat_rate: Decimal
    is_batch_tracked: bool
    is_active: bool
    reorder_level: Decimal | None
    barcodes: tuple[str, ...] = ()


def find_product(session: Session, product_id: UUID) -> ProductView | None:
    """Return a product with its VAT rate, or None if it does not exist for this tenant."""
    p = products_repo.get_product(session, product_id)
    if p is None:
        return None
    tax = products_repo.get_tax_code(session, p.tax_code_id)
    return ProductView(id=p.id, company_id=p.company_id, sku=p.sku, name=p.name, product_type=p.product_type,
                       base_uom_id=p.base_uom_id, tax_code_id=p.tax_code_id,
                       vat_rate=tax.vat_rate if tax else Decimal("0"),
                       is_batch_tracked=p.is_batch_tracked, is_active=p.is_active,
                       reorder_level=p.reorder_level)


def find_product_by_sku(session: Session, company_id: UUID, sku: str) -> ProductView | None:
    """The company's product with this SKU (case and spaces ignored), or None. Used by file imports."""
    from sqlalchemy import select

    from ziira.modules.products.repository.models import Product

    found = session.scalar(select(Product.id).where(Product.company_id == company_id,
                                                      Product.sku == sku.strip().upper()))
    return find_product(session, found) if found is not None else None


def product_labels(session: Session, product_ids: set[UUID]) -> dict[UUID, tuple[str, str]]:
    """(sku, name) for each existing product id: for screens that list other units' records."""
    return {p.id: (p.sku, p.name) for p in products_repo.get_products(session, product_ids)}


def selling_prices(session: Session, company_id: UUID, branch_id: UUID | None, product_ids: set[UUID],
                   day: date | None = None, customer_group: str | None = None) -> dict[UUID, Decimal]:
    """The tax-inclusive selling price of each product that has one on `day` (default today) at the branch, from a
    list for the customer's group where there is one. Products without a price are absent."""
    from ziira.modules.products.services.pricing import current_prices

    return current_prices(session, company_id, branch_id, product_ids, day, customer_group)


def sellable_products(session: Session, company_id: UUID, search: str | None = None, limit: int = 100,
                      offset: int = 0, barcode: str | None = None) -> list[ProductView]:
    """The company's active products by name (a till's catalog), with their VAT rates and barcodes; `barcode` keeps
    only the product with that code."""
    rates = {t.id: t.vat_rate for t in products_repo.list_tax_codes(session)}
    found = products_repo.list_products(session, search, min(limit, 1000), offset, {company_id}, only_active=True,
                                        barcode=barcode)
    codes = products_repo.barcodes_of(session, {p.id for p in found})
    return [ProductView(
        id=p.id, company_id=p.company_id, sku=p.sku, name=p.name, product_type=p.product_type,
        base_uom_id=p.base_uom_id, tax_code_id=p.tax_code_id, vat_rate=rates.get(p.tax_code_id, Decimal(0)),
        is_batch_tracked=p.is_batch_tracked, is_active=p.is_active, reorder_level=p.reorder_level,
        barcodes=tuple(codes.get(p.id, ())))
        for p in found]


def tax_code_rate(session: Session, tax_code_id: UUID) -> Decimal | None:
    """The VAT rate (percent) of an active tax code, or None when it does not exist or is not in use."""
    tax = products_repo.get_tax_code(session, tax_code_id)
    return tax.vat_rate if tax is not None and tax.is_active else None


def set_selling_price(session: Session, company_id: UUID, product_id: UUID, price: Decimal,
                      valid_from: date | None = None) -> UUID:
    """Set a product's tax-inclusive selling price on the company's default price list from a date (today by
    default), through the price service: the caller needs 'prices.manage', the old price ends the day before and the
    change is audited and announced. Returns the id of the new price. Raises if the company has no default list."""
    from ziira.modules.products.services import pricing

    lists = [x for x in products_repo.lists_for_branch(session, company_id, None) if x.is_default]
    if not lists:
        raise ValidationFailed("The company has no default price list to put the price on")
    item = pricing.set_price(session, lists[0].id, product_id=product_id, price=price, valid_from=valid_from)
    return item.id
