"""Use cases: read products."""

from uuid import UUID

from ziira.modules.products.repository import products_repo
from ziira.modules.products.repository.models import Product
from ziira.sdk import NotFound, Session


def get_product(session: Session, product_id: UUID) -> Product:
    """Return one product or raise NotFound (also for other tenants' products)."""
    product = products_repo.get_product(session, product_id)
    if product is None:
        raise NotFound("Product not found")
    return product


def list_products(session: Session, search: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[Product]:
    """List products by name, optionally filtered by name or SKU."""
    return products_repo.list_products(session, search, min(limit, 200), offset)
