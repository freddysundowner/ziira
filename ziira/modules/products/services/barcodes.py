"""Use case: the barcodes of a product (several per product; a code belongs to one product in a company)."""

from uuid import UUID

from ziira.modules.products.domain import rules
from ziira.modules.products.permissions import PRODUCTS_MANAGE
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Product
from ziira.modules.products.services.find_products import get_product
from ziira.sdk import Conflict, Session, audit_record, current_context


def list_barcodes(session: Session, product_id: UUID) -> list[str]:
    """The product's barcodes. Needs 'products.view' for its company."""
    product = get_product(session, product_id)
    return products_repo.barcodes_of(session, {product.id}).get(product.id, [])


def set_barcodes(session: Session, product_id: UUID, codes: list[str]) -> Product:
    """Replace the product's barcodes with `codes`. A code already on another product of the company is refused
    (naming that product). Needs 'products.manage'."""
    product = get_product(session, product_id)
    ctx = current_context()
    ctx.require(PRODUCTS_MANAGE, company_id=product.company_id)
    wanted = rules.clean_barcodes(codes)
    for code in wanted:
        owner = products_repo.barcode_owner(session, product.company_id, code)
        if owner is not None and owner != product.id:
            other = products_repo.get_product(session, owner)
            raise Conflict(f"Barcode {code} is already used by {other.sku if other else 'another product'}")
    before = products_repo.barcodes_of(session, {product.id}).get(product.id, [])
    products_repo.replace_barcodes(session, product, [c for c in wanted if c not in before],
                                   [c for c in before if c not in wanted], ctx.tenant_id, ctx.user_id)
    audit_record(session, "update", "products.product", product.id, {"barcodes": wanted, "was": before})
    return product


def add_barcodes(session: Session, product: Product, codes: list[str]) -> None:
    """Add codes to a product just made (file imports). The caller has checked the permission."""
    ctx = current_context()
    wanted = rules.clean_barcodes(codes)
    for code in wanted:
        if products_repo.barcode_owner(session, product.company_id, code) is not None:
            raise Conflict(f"Barcode {code} is already used by another product")
    products_repo.replace_barcodes(session, product, wanted, [], ctx.tenant_id, ctx.user_id)

