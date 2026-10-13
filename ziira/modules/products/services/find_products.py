"""Use cases: read products."""

from uuid import UUID

from ziira.modules.products.permissions import PRODUCTS_VIEW
from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Product
from ziira.sdk import NotFound, Session, current_context


def get_product(session: Session, product_id: UUID) -> Product:
    """Return one product or raise NotFound (also for other tenants' and out-of-scope products)."""
    product = products_repo.get_product(session, product_id)
    companies = current_context().companies_with(PRODUCTS_VIEW)
    if product is None or (companies is not None and product.company_id not in companies):
        raise NotFound("Product not found")
    return product


def list_products(session: Session, search: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[Product]:
    """List products by name, optionally filtered by name or SKU, in the companies the user may see."""
    companies = current_context().companies_with(PRODUCTS_VIEW)
    return products_repo.list_products(session, search, min(limit, 200), offset, companies)
